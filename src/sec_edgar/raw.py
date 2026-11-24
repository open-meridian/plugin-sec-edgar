"""What SEC answered, kept as received, in the plugin's own storage.

A data plugin keeps its source's raw records in the storage the deployment
grants an edge plugin (`meridian.edge.storage_dir()`), and every row it
records names the one it was converted from (`ObservationMeta.raw`). Here
that is each answer of SEC's -- a company's submissions, an older page of
them, the ticker map -- with its address, status, when it was received, and
the JSON itself, one gzipped file each, kept before anything is read from
it. The User-Agent sent is never kept.

One kind of raw record, `responses` (declared.py), in units of a month of
receipt: `responses/<YYYY-MM>/`, each file `<received>-<what>.json.gz`, its
key that path. A month's unit is written to only in that month, so once its
last record is past the kind's window it is moved whole, as the SDK's
`responses_past_window` setting says: archived (`plugin.archive_unit`),
deleted (`plugin.delete_unit`, which a deployment's hold refuses, keeping
it) or kept.

**Where a filing was first read.** A filing read again -- the next check, a
restart, a reader's want -- names the answer it was first read from, never
the newest copy: the lake compares a row's raw record too, so a new
reference would restate every filing unchanged. Which answer first held each
filing, by its accession number, is noted under `firsts/<YYYY-MM>.json` at
the storage's root, a file per month of the filings' dates.

Where no storage is granted -- a test, a preview -- the store keeps its
records in a directory of its own and moves nothing.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import meridian
from meridian import edge

from .edgar import Fetched

log = logging.getLogger("sec_edgar")

#: The kind of raw record, and its default window: ten years.
RESPONSES = "responses"
DEFAULT_WINDOW_DAYS = 3650
#: The longest a window may be set to, which the storage declaration states.
MOST_WINDOW_DAYS = 36500
#: Where each filing's first answer is noted, at the storage's root.
FIRSTS = "firsts"


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


def name_of(path: str) -> str:
    """A short name for what an address asks: `CIK0000320193`,
    `CIK0000320193-submissions-001` or `company-tickers`."""
    leaf = path.rsplit("/", 1)[-1].removesuffix(".json")
    return re.sub(r"[^A-Za-z0-9-]", "-", leaf.replace("_", "-"))[:60] or "answer"


@dataclass(frozen=True)
class Unit:
    """A month of answers: its path in storage, and what it holds."""

    unit: str
    records: int
    first_ns: int
    last_ns: int


class RawStore:
    """Answers kept under `root`: the granted storage, or a directory of the
    store's own where none is granted (`granted` False)."""

    def __init__(self, root: Path | None = None) -> None:
        self._given = root
        self._root: Path | None = None
        self._granted = False
        self._firsts: dict[str, dict[str, Any]] = {}

    def open(self) -> Path:
        """Where the answers are kept, read once: from the class's `on_start`,
        once the plugin has registered, since on an instance run as shards or
        with a standby pod its storage is the shard's own folder."""
        if self._root is None:
            granted = self._given if self._given is not None else edge.storage_dir()
            self._granted = granted is not None
            self._root = (
                Path(granted) if granted is not None else Path(tempfile.mkdtemp(prefix="edgar-"))
            )
            self._firsts = {}
        return self._root

    def close(self) -> None:
        """Forget where the answers are kept, as the plugin stops."""
        self._root = None

    @property
    def root(self) -> Path:
        return self.open()

    @property
    def granted(self) -> bool:
        self.open()
        return self._granted

    def keep(self, fetched: Fetched) -> str:
        """Keep an answer before anything is read from it; its key."""
        at = fetched.fetched_at.astimezone(UTC)
        unit = f"{RESPONSES}/{at:%Y-%m}"
        key = f"{unit}/{at:%Y%m%dT%H%M%S%fZ}-{name_of(fetched.path)}.json.gz"
        document = {
            "url": fetched.url,
            "status": fetched.status,
            "received_at": at.isoformat(),
            "body": fetched.text,
        }
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".partial")
        partial.write_bytes(gzip.compress(json.dumps(document).encode(), mtime=0))
        partial.replace(target)
        return key

    # ── Where each filing was first read ────────────────────────────────

    def first(self, accession: str, month: str, key: str) -> tuple[str, bool]:
        """The key of the answer `accession` was first read from, noting `key`
        if none is noted or storage no longer holds it; and whether it was
        noted now. `month` is the filing's, `YYYY-MM`."""
        noted = self._month(month)
        held = noted.get(accession)
        if isinstance(held, str) and (not held or (self.root / held).is_file()):
            return held, False
        noted[accession] = key
        return key, True

    def save_firsts(self) -> None:
        """Write the months noted since the last save."""
        for month, noted in self._firsts.items():
            target = self.root / FIRSTS / f"{month}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_suffix(".partial")
            partial.write_text(json.dumps(noted, sort_keys=True, indent=0))
            partial.replace(target)

    def _month(self, month: str) -> dict[str, Any]:
        held = self._firsts.get(month)
        if held is None:
            try:
                held = json.loads((self.root / FIRSTS / f"{month}.json").read_text())
            except (OSError, ValueError):
                held = {}
            if not isinstance(held, dict):
                held = {}
            self._firsts[month] = held
        return held

    # ── Reading back and moving ─────────────────────────────────────────

    def read(self, key: str) -> dict[str, Any] | None:
        """A kept answer by its key, or None where storage no longer holds it."""
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            return None
        document: dict[str, Any] = json.loads(gzip.decompress(path.read_bytes()))
        return document

    def keys(self) -> list[str]:
        """Every kept answer's key, oldest first."""
        held = self.root / RESPONSES
        if not held.is_dir():
            return []
        return sorted(str(p.relative_to(self.root)) for p in held.glob("*/*.json.gz"))

    def units(self) -> Iterator[Unit]:
        """Each month of answers in storage, oldest first."""
        held = self.root / RESPONSES
        if not held.is_dir():
            return
        for month in sorted(p for p in held.iterdir() if p.is_dir()):
            read = (_received(p.name) for p in month.glob("*.json.gz"))
            stamps = sorted(s for s in read if s is not None)
            if stamps:
                yield Unit(
                    str(month.relative_to(self.root)), len(stamps), _ns(stamps[0]), _ns(stamps[-1])
                )

    async def tend(
        self, plugin: meridian.Plugin, window_days: int, past_window: str, now: datetime
    ) -> dict[str, int]:
        """Move each month past the window as `past_window` says, and say on
        the heartbeat what storage holds; what it came to."""
        done = {"archived": 0, "deleted": 0, "kept": 0, "refused": 0}
        if not self.granted:
            return done
        cut = _ns(now - timedelta(days=window_days))
        this_month = f"{RESPONSES}/{now.astimezone(UTC):%Y-%m}"
        for unit in list(self.units()):
            if unit.last_ns >= cut or unit.unit == this_month:
                continue
            if past_window not in ("archived", "deleted"):
                done["kept"] += 1
                continue
            move = plugin.archive_unit if past_window == "archived" else plugin.delete_unit
            try:
                await move(
                    RESPONSES,
                    unit.unit,
                    record_count=unit.records,
                    first_received_ns=unit.first_ns,
                    last_received_ns=unit.last_ns,
                )
                done[past_window] += 1
            except meridian.MeridianError as refused:
                log.warning("%s: %s refused, kept: %s", unit.unit, past_window, refused)
                done["refused"] += 1
        plugin.stored = [self.span()]
        return done

    def span(self) -> Any:
        """What storage holds of the kind, for the heartbeat."""
        from meridian.v1 import sidecar_pb2

        units = list(self.units())
        return sidecar_pb2.StoredSpan(
            record_kind=RESPONSES,
            record_count=sum(u.records for u in units),
            first_received_ns=units[0].first_ns if units else 0,
            last_received_ns=units[-1].last_ns if units else 0,
        )


def _received(name: str) -> datetime | None:
    try:
        return datetime.strptime(name.split("-", 1)[0], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
    except ValueError:
        return None

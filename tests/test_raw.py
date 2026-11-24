"""SEC's answers kept as received, each filing naming the answer it was
first read from, and months moved past their window through the SDK."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sec_edgar.edgar import DATA, Fetched
from sec_edgar.raw import RawStore, name_of

from conftest import AT, USER_AGENT


def test_an_answer_is_kept_as_received(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    url = f"{DATA}/submissions/CIK0900000001.json"
    key = store.keep(Fetched(url, 200, b'{"name": "Northwind"}', AT, {"x": USER_AGENT}))
    assert key == "responses/2026-11/20261124T150000000000Z-CIK0900000001.json.gz"
    kept = store.read(key)
    assert kept is not None and kept["url"] == url and kept["status"] == 200
    assert kept["body"] == '{"name": "Northwind"}'
    # Who asked is never kept with what SEC answered.
    assert USER_AGENT not in str(kept)
    assert store.read("../outside.json.gz") is None
    assert name_of("/files/company_tickers.json") == "company-tickers"


def test_a_filing_names_the_answer_it_was_first_read_from(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    first = store.keep(Fetched(f"{DATA}/submissions/CIK0900000002.json", 200, b"{}", AT))
    later = store.keep(
        Fetched(f"{DATA}/submissions/CIK0900000002.json", 200, b"{}", AT + timedelta(hours=1))
    )
    assert store.first("0001193125-26-301122", "2026-11", first) == (first, True)
    assert store.first("0001193125-26-301122", "2026-11", later) == (first, False)
    store.save_firsts()
    again = RawStore(tmp_path)
    assert again.first("0001193125-26-301122", "2026-11", later) == (first, False)


class Plugin:
    def __init__(self) -> None:
        self.moved: list[tuple[str, str]] = []
        self.stored: list[Any] = []

    async def archive_unit(self, kind: str, unit: str, **_: Any) -> None:
        self.moved.append(("archived", unit))

    async def delete_unit(self, kind: str, unit: str, **_: Any) -> None:
        self.moved.append(("deleted", unit))


async def test_months_past_the_window_are_moved(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store._given, store._root, store._granted = tmp_path, tmp_path, True
    old = datetime(2025, 1, 5, tzinfo=UTC)
    store.keep(Fetched(f"{DATA}/submissions/CIK0900000002.json", 200, b"{}", old))
    store.keep(Fetched(f"{DATA}/submissions/CIK0900000002.json", 200, b"{}", AT))
    plugin = Plugin()
    done = await store.tend(plugin, 30, "archived", AT)  # type: ignore[arg-type]
    assert done["archived"] == 1 and plugin.moved == [("archived", "responses/2025-01")]
    assert plugin.stored[0].record_count == 2
    kept = await store.tend(Plugin(), 30, "kept", AT)  # type: ignore[arg-type]
    assert kept["kept"] == 1

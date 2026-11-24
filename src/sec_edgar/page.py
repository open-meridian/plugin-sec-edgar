"""The plugin's pages, under Manage alone: the data role's common pages,
Connection and Datasets, each also a read tool for agents on the
deployment's MCP under the role's names (`read_connection`,
`read_datasets`). Each record is the role's (`meridian.roles.data`),
extended with EDGAR's fields; each template is the role's, with EDGAR's
nuance at its blocks or, for the Datasets tabs, its sections in its order.

A data plugin shows its connectivity, its datasets and how its subjects
resolve, and no data:

- **Connection** (`/`): "Key" -- the mode (Live, Sample data or No key while
  the User-Agent is missing or malformed), whether the User-Agent is set
  (the setting named, its value never shown), and **Sources**, one line per
  EDGAR source read (state, latest filing, calls, last error); "Limits and
  use" -- SEC's 10 requests a second, the pace kept and SEC's refusals;
  "Stream": it does not stream.
- **Datasets** (`/datasets`): the role's sections and EDGAR's as tabs, one
  shown at a time (`?view=`): "Served" (with **Lag** as a column) and
  "Subjects", "Wants", **Filers** (each company read, by CIK, with its
  former names and the deployment's record or why none, searched) and
  **Terms**.

Neither shows a filing. Settings change through core's tools; the pages
hold no actions.
"""

from __future__ import annotations

import statistics
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import meridian
from meridian.roles import data

from . import records
from .declared import CATALOGUE, FILINGS, TERMS
from .edgar import DATA, TICKERS, WWW
from .feed import Feed, Status
from .limits import SEC_MOST_PER_SECOND
from .settings import USER_AGENT

TITLE = "SEC EDGAR"
#: The kit these pages are built on.
KIT = "0.13.0"

pages = meridian.Pages(TITLE, templates=Path(__file__).parent / "templates", kit=KIT)

CONNECTION = "/"
DATASETS = "/datasets"

#: The longest search the Filers tab reads.
MOST_QUERY = 100
#: The Datasets page's tabs, one shown at a time (`?view=`), the first by default.
VIEWS = ("served", "wants", "filers", "terms")
#: How many wants the Datasets tab lists; read_datasets answers every one held.
SHOWN_WANTS = 3

_held: dict[str, Feed] = {}


def hold(feed: Feed) -> None:
    """The feed the pages read, once the plugin has registered."""
    _held["feed"] = feed


def _status() -> tuple[Status, Feed | None]:
    feed = _held.get("feed")
    return (feed.status if feed is not None else Status(waiting="is not set"), feed)


def _iso(moment: datetime | None) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds") if moment else ""


def _waiting(status: Status) -> str:
    return "" if status.mode == "synthetic" else status.waiting


def _mode(status: Status) -> str:
    if status.mode == "synthetic":
        return "Sample data"
    return "No key" if status.waiting else "Live"


def _state(status: Status, feed: Feed | None) -> tuple[str, str, str]:
    """The head's status: its state, what it means, and its detail."""
    waiting = _waiting(status)
    if waiting:
        return "warn", f"Waiting for {USER_AGENT}", f"{USER_AGENT} {waiting}"
    misses = sorted(f.cik for f in status.filers.values() if f.miss)
    if status.error and status.read_at is None:
        return "error", "Not answering", status.error
    if status.error:
        return "warn", "Answering", status.error
    if feed is not None and not feed.watchlist and not feed.standing:
        return "ok", "Nothing kept current", "Filings are fetched when wanted"
    if status.read_at is None:
        return "busy", "Checking EDGAR", ""
    if misses:
        plural = "filer" if len(misses) == 1 else "filers"
        return "warn", f"{len(misses)} {plural} not held", ", ".join(misses)
    if status.unread:
        said = "entry names" if len(status.unread) == 1 else "entries name"
        return (
            "warn",
            f"{len(status.unread)} watchlist {said} no company",
            ", ".join(f"{entry}: {why}" for entry, why in sorted(status.unread.items())),
        )
    return "ok", "Sample data" if status.mode == "synthetic" else "Answering", ""


def _sources(status: Status) -> list[records.SourceRead]:
    seen = list(status.filers.values())
    latest = max((f.latest_filed for f in seen if f.latest_filed), default=None)
    errors = [f.error for f in seen if f.error]
    return [
        records.SourceRead(
            source="Company submissions",
            address=f"{DATA}/submissions/",
            state="Not read yet" if not seen else ("Failing" if errors else "Answering"),
            last_release=latest.isoformat() if latest else "",
            calls=sum(f.calls for f in seen),
            last_error=errors[0] if errors else "",
        ),
        records.SourceRead(
            source="Ticker map",
            address=f"{WWW}{TICKERS}",
            state=(
                "Not read yet"
                if not status.ticker_calls
                else ("Failing" if status.ticker_error else "Answering")
            ),
            calls=status.ticker_calls,
            last_error=status.ticker_error,
        ),
    ]


def connection_read(status: Status, feed: Feed | None) -> records.ConnectionRead:
    state, said, _ = _state(status, feed)
    kept = feed.raw.keys() if feed is not None else []
    window = ""
    if feed is not None and feed.raw.granted:
        window = "in the storage the deployment grants, as its responses settings say"
    elif feed is not None:
        window = "in a directory of the plugin's own: this deployment grants no storage"
    rate = feed.api.limiter.rate if feed is not None else 0
    return records.ConnectionRead(
        mode=_mode(status),
        credentials=[data.Credential("User-Agent", status.waiting != "is not set")],
        entitled_at_vendor="" if _waiting(status) else "Every company's filings on EDGAR",
        limit=(
            f"SEC's {SEC_MOST_PER_SECOND} requests a second for one client; this plugin asks "
            f"one at a time, at most {rate} a second, and pauses after a refusal"
        ),
        calls=status.fetches,
        rate_limited=feed.api.limiter.refused if feed is not None else 0,
        last_call_at=_iso(status.checked_at),
        last_error=status.error,
        sessions=None,
        state=state,
        said=said,
        source=(
            "The responses committed with the plugin"
            if status.mode == "synthetic"
            else f"{DATA}, each company's submissions"
        ),
        checked_at=_iso(status.checked_at),
        waiting=f"{USER_AGENT} {_waiting(status)}" if _waiting(status) else "",
        per_second=rate,
        kept_current=len(feed.watchlist) + len(feed.standing) if feed is not None else 0,
        sources=_sources(status),
        responses_kept=len(kept),
        kept_for=window,
    )


def _duration(seconds: int) -> str:
    minutes, rest = divmod(max(seconds, 0), 60)
    return f"{minutes} m {rest:02d} s"


def lag_read(status: Status, dataset: str) -> records.LagRead:
    lags = status.lags
    if not lags:
        return records.LagRead(dataset=dataset, said="No filing has arrived since the start")
    median, longest = int(statistics.median(lags)), max(lags)
    return records.LagRead(
        dataset=dataset,
        filings=len(lags),
        median_seconds=median,
        longest_seconds=longest,
        median=f"{_duration(median)} median",
        said=f"{_duration(median)} median, {_duration(longest)} longest, of {len(lags)} filings",
    )


def _filer_read(feed: Feed | None, held: Any) -> records.FilerRead:
    kept = feed is not None and (bool(held.entry) or held.cik in feed.standing.values())
    return records.FilerRead(
        cik=held.cik,
        name=held.name,
        entry=held.entry,
        tickers=list(held.tickers),
        former_names=list(held.former_names),
        kept_current=kept,
        company_id=held.company_id,
        miss=held.miss,
        latest_form=held.latest_form,
        latest_filed=held.latest_filed.isoformat() if held.latest_filed else "",
        sent=held.sent,
        last_error=held.error,
    )


def datasets_read(status: Status, feed: Feed | None) -> records.DatasetsRead:
    instance = feed.plugin.identity.instance_id if feed is not None else "sec-edgar"
    entitled = (
        f"No: {USER_AGENT} {_waiting(status)}"
        if _waiting(status)
        else "Yes: every company's filings on EDGAR"
    )
    return records.DatasetsRead(
        served=data.served(CATALOGUE, instance, feed.wants if feed is not None else None, entitled),
        wants=list(data.want_rows(feed.wants)) if feed is not None else [],
        reads_instruments=True,
        terms=TERMS,
        filers=[_filer_read(feed, f) for _, f in sorted(status.filers.items())],
        lag=[lag_read(status, f"{instance}:{FILINGS}")],
        unread=[f"{entry}: {why}" for entry, why in sorted(status.unread.items())],
    )


def figures(status: Status, feed: Feed | None) -> list[meridian.Figure]:
    """The data role's figures, in its order (`meridian.roles.data`)."""
    state, said, why = _state(status, feed)
    if status.mode == "synthetic" and state == "ok":
        connection: Any = "Sample data"
    elif _waiting(status) or said == "Not answering":
        connection = meridian.Figure(
            "", said, state="error" if state == "error" else "warn", why=why[:200]
        )
    else:
        connection = meridian.Figure(
            "", "Answering", state="warn" if status.error else None, why=status.error[:200]
        )
    last = feed.wants.counts.last_ns if feed is not None else 0
    rate = feed.api.limiter.rate if feed is not None else 0
    return data.figures(
        connection=connection,
        entitled_at_vendor=(
            f"0 of 1 datasets: {USER_AGENT} {_waiting(status)}"
            if _waiting(status)
            else "1 of 1 datasets"
        ),
        stream="Does not stream",
        last_recorded=(datetime.fromtimestamp(last / 10**9, UTC) if last else None),
        rate_use=f"at most {rate} of {SEC_MOST_PER_SECOND} a second",
    )


def _moment(value: str) -> str:
    """An ISO moment as a person reads it, to the minute in UTC."""
    if not value:
        return ""
    if len(value) == 10:
        return value
    return datetime.fromisoformat(value).astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _weekday(value: str) -> str:
    return date.fromisoformat(value).strftime("%a %d %b %Y") if value else ""


def matching(query: str, *texts: str) -> bool:
    """Whether every word of a search is in one of `texts`, case aside."""
    words = query.lower().split()
    held = " ".join(texts).lower()
    return all(word in held for word in words)


pages.environment.filters["moment"] = _moment
pages.environment.filters["day"] = _weekday


@pages.page(
    CONNECTION,
    "Connection",
    levels="admin",
    answers=records.ConnectionRead,
    name="read_connection",
    description=(
        "How this plugin reaches SEC EDGAR, as every data plugin's Connection answers it: the "
        "mode (Live, Sample data, or No key while the User-Agent setting is missing or "
        "malformed, naming edgar_user_agent and why), whether the User-Agent is set (never its "
        "value), what EDGAR serves, SEC's limit of 10 requests a second and the pace kept, the "
        "requests made and SEC's refusals, the last call and why it failed if it did; it does "
        "not stream. Then EDGAR's own: each source -- companies' submissions and the ticker "
        "map -- with its state, latest filing, calls and last error; how many companies are "
        "kept current; and how many answers are kept. No filing."
    ),
)
async def connection(request: meridian.Request) -> meridian.Response:
    status, feed = _status()
    read = connection_read(status, feed)
    return pages.answer("connection.html", read, detail=_state(status, feed)[2])


@pages.page(
    DATASETS,
    "Datasets",
    levels="admin",
    answers=records.DatasetsRead,
    name="read_datasets",
    description=(
        "What this plugin serves the lake, as every data plugin's Datasets answers it: "
        "edgar_filings as the catalogue declares it (each company's filings on EDGAR, pushed "
        "for the watchlist and pulled when wanted; New York's day; no calendar), whether a "
        "deployment admin has licensed it, what it recorded and declined; the standing wants "
        "it keeps current and the wants it answered. Then EDGAR's own: SEC's terms in words, "
        "the lag from SEC's acceptance to recording, each company it reads by CIK with its "
        "tickers, former names and the deployment's company record or why there is none, and "
        "each watchlist entry that names no company. No filing."
    ),
)
async def datasets(request: meridian.Request) -> meridian.Response:
    status, feed = _status()
    read = datasets_read(status, feed)
    # A browser's search narrows the filers drawn, and it is drawn the latest
    # wants; a tool answers them all.
    query = request.query.get("q", "").strip()[:MOST_QUERY]
    asked = request.query.get("view", "")
    view = "filers" if query else asked if asked in VIEWS else VIEWS[0]
    shown = [
        f
        for f in read.filers
        if matching(query, f.cik, f.name, f.entry, " ".join(f.tickers), " ".join(f.former_names))
    ]
    drawn = read if request.tool_name else replace(read, wants=read.wants[:SHOWN_WANTS])
    return pages.answer(
        "datasets.html",
        drawn,
        query=query,
        view=view,
        shown=shown,
        state=_state(status, feed),
        checked_at=_iso(status.checked_at),
        wants=len(read.wants),
    )

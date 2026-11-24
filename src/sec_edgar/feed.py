"""SEC EDGAR's filings into the lake: the watchlist's companies' filings
recorded as they arrive, and any company's recorded when the lake wants
them, through the SDK's filings helpers
(`meridian.roles.data.filings`, contract v28).

**Push.** At start and every few minutes, each company kept current -- the
`edgar_watchlist` setting's, by CIK or by the ticker SEC maps to one, and a
standing want's -- has its submissions read, and each filing not yet sent in
this process is recorded. The lake answers a filing it holds unchanged, so
nothing is kept between starts but the answers in storage: a restart sends
the recent filings again, each naming the answer it was first read from, and
the lake changes nothing.

**A filing.** One `Filing` row under its filer, keyed by its accession
number: the form as EDGAR states it, a kind from the platform's short list
(`kind_of`), an 8-K's items, the period it reports on, the date it was
filed, and SEC's acceptance as both its valid and its published time. EDGAR
states the acceptance with a trailing `Z`, but in Eastern time, the hours
EDGAR accepts filings (6:00 to 22:00), so it is read as New York's.

**The filer.** A company is named by its CIK, ten digits, and resolved to
the deployment's company record (`ENT-`) by that CIK, once per process; a
ticker only helps find the CIK. A filer the deployment does not hold is
reported missing, as any miss is, kept as reported on the row (its CIK and
name), and its filings recorded all the same. EDGAR's former names are shown on the Filers tab; the
platform's company record keeps them as dated changes.

**Wants.** The lake asks `edgar_filings` for companies: filings on a
business date, over a range of time, or the latest. Each company whose
record carries a CIK is answered from EDGAR, reading the older pages of its
submissions only where the range reaches back past the recent ones;
declined `not_covered` where no CIK, `beyond_history` before its first
filing on EDGAR, `source_silent` where it filed nothing then, and every
company `not_entitled` while the User-Agent is missing or malformed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import meridian
from meridian.errors import CallFailed
from meridian.operations import Filing
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles import Latency, data
from meridian.roles.data import filings

from . import edgar
from .declared import DAY_TIME_ZONE, FILING, FILINGS, KEYS
from .raw import RawStore

log = logging.getLogger("sec_edgar")

NEW_YORK = ZoneInfo(DAY_TIME_ZONE)
#: The source this plugin names on what it reports missing.
SOURCE = "sec-edgar"
#: The day EDGAR's electronic filings begin: nothing is asked before it.
FIRST_DAY = date(1994, 1, 1)
#: How many arrival lags are kept for the Lag tab.
LAGS = 2000
#: The most filings one want is answered with.
MOST_FILINGS = 5000
#: How long the ticker map is kept before it is read again, in seconds.
TICKERS_SECONDS = 86_400


def _ns(moment: datetime) -> int:
    return int(moment.timestamp() * 1_000_000) * 1000


def accepted_ns(text: str) -> int:
    """EDGAR's acceptance (`2026-10-30T16:30:12.000Z`), in Eastern time
    despite its `Z`, in nanoseconds; 0 where it does not read."""
    try:
        moment = datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0
    return _ns(moment.replace(tzinfo=NEW_YORK))


#: Each kind on the platform's short list, by the forms that are it; an
#: amendment (`/A`) is its form's kind.
_KINDS: dict[str, tuple[str, ...]] = {
    "FILING_KIND_ANNUAL_REPORT": ("10-K", "10-K405", "10-KT", "20-F", "40-F", "10-KSB"),
    "FILING_KIND_QUARTERLY_REPORT": ("10-Q", "10-QT", "10-QSB"),
    "FILING_KIND_CURRENT_REPORT": ("8-K", "6-K", "8-K12B", "8-K12G3"),
    "FILING_KIND_PROXY": ("DEF 14A", "DEFA14A", "DEFM14A", "PRE 14A", "PREM14A", "DEF 14C"),
    "FILING_KIND_OWNERSHIP": ("3", "4", "5"),
    "FILING_KIND_HOLDINGS_REPORT": ("13F-HR", "13F-NT"),
    "FILING_KIND_BENEFICIAL_OWNERSHIP": (
        "SC 13D", "SC 13G", "SCHEDULE 13D", "SCHEDULE 13G",
    ),
}  # fmt: skip
_REGISTRATION = ("S-1", "S-3", "S-4", "S-8", "S-11", "F-1", "F-3", "F-4", "424B")


def kind_of(form: str) -> str:
    """The platform's kind for an EDGAR form, by its name,
    `FILING_KIND_OTHER` for one not on the short list."""
    base = form.strip().upper().removesuffix("/A")
    for kind, forms in _KINDS.items():
        if base in forms:
            return kind
    if base.startswith(_REGISTRATION):
        return "FILING_KIND_REGISTRATION"
    return "FILING_KIND_OTHER"


@dataclass(frozen=True)
class Stated:
    """One filing as EDGAR states it in a company's submissions."""

    accession: str
    form: str
    filed: date
    report: str
    accepted_ns: int
    items: tuple[str, ...]


@dataclass(frozen=True)
class Page:
    """One older page of a company's submissions, as `filings.files` names it."""

    name: str
    count: int
    first: date
    last: date


@dataclass(frozen=True)
class Submissions:
    """A company's submissions: who it is, its recent filings, its older pages."""

    cik: str
    name: str
    tickers: tuple[str, ...]
    former_names: tuple[str, ...]
    filings: tuple[Stated, ...]
    pages: tuple[Page, ...]


def _day(text: object) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def stated_in(table: Mapping[str, Any]) -> list[Stated]:
    """The filings of one of EDGAR's column tables (`filings.recent`, or an
    older page), newest first, a row that does not read left out."""
    numbers = table.get("accessionNumber") or []
    held: list[Stated] = []
    for i, number in enumerate(numbers):

        def cell(column: str, i: int = i) -> str:
            values = table.get(column) or []
            return str(values[i]) if i < len(values) and values[i] is not None else ""

        filed = _day(cell("filingDate"))
        if not number or filed is None:
            continue
        items = tuple(x.strip() for x in cell("items").split(",") if x.strip())
        held.append(
            Stated(
                accession=str(number),
                form=cell("form"),
                filed=filed,
                report=cell("reportDate")[:10],
                accepted_ns=accepted_ns(cell("acceptanceDateTime")),
                items=items,
            )
        )
    return held


def _former(answer: Mapping[str, Any]) -> tuple[str, ...]:
    said = []
    for former in answer.get("formerNames") or []:
        name = str(former.get("name", "")).strip()
        since, until = str(former.get("from", ""))[:10], str(former.get("to", ""))[:10]
        if name:
            said.append(f"{name} ({since or '?'} to {until or '?'})")
    return tuple(said)


def submissions_of(cik: str, answer: Mapping[str, Any]) -> Submissions:
    stated = answer.get("filings") or {}
    pages = []
    for page in stated.get("files") or []:
        first, last = _day(page.get("filingFrom")), _day(page.get("filingTo"))
        if first and last and page.get("name"):
            pages.append(Page(str(page["name"]), int(page.get("filingCount", 0)), first, last))
    return Submissions(
        cik=cik,
        name=str(answer.get("name", "")),
        tickers=tuple(str(t) for t in answer.get("tickers") or []),
        former_names=_former(answer),
        filings=tuple(stated_in(stated.get("recent") or {})),
        pages=tuple(pages),
    )


@dataclass
class FilerState:
    """One company as the plugin last saw it, for the Filers tab."""

    cik: str
    entry: str = ""
    name: str = ""
    tickers: tuple[str, ...] = ()
    former_names: tuple[str, ...] = ()
    #: The deployment's company record for it, or why there is none.
    company_id: str = ""
    miss: str = ""
    latest_form: str = ""
    latest_filed: date | None = None
    sent: int = 0
    calls: int = 0
    error: str = ""


@dataclass(frozen=True)
class Outcome:
    recorded: int = 0
    restated: int = 0
    unchanged: int = 0


@dataclass
class Status:
    """What the plugin last did, for its pages; held in memory, lost on a
    restart and read again by the first check."""

    mode: str = "live"
    #: Why the User-Agent will not do, while it will not; empty once it will.
    waiting: str = ""
    started_at: datetime | None = None
    checked_at: datetime | None = None
    read_at: datetime | None = None
    error: str = ""
    fetches: int = 0
    ticker_calls: int = 0
    ticker_error: str = ""
    #: Each company seen, by CIK.
    filers: dict[str, FilerState] = field(default_factory=dict)
    #: Each watchlist entry that names no company, with why.
    unread: dict[str, str] = field(default_factory=dict)
    #: Seconds from SEC's acceptance to the plugin's recording, for filings
    #: that arrived while it ran.
    lags: list[int] = field(default_factory=list)


class Failed(Exception):  # noqa: N818 - what an answer was
    """SEC refused or did not answer; its words."""


class Feed(data.Role):
    """The plugin's data role class, its acts made on itself -- registered
    with `meridian.run`, or bound to the suite's `Recorder` in its tests --
    reading EDGAR, resolving filers, recording filings, answering wants."""

    def __init__(
        self,
        api: edgar.Api,
        raw: RawStore,
        now: Callable[[], datetime] = edgar.utc_now,
        watchlist: Sequence[str] = (),
        waiting: str = "",
    ) -> None:
        self.api = api
        self.raw = raw
        self.now = now
        self.watchlist = tuple(watchlist)
        clock = lambda: _ns(self.now())  # noqa: E731 - one clock for all
        self.wants = data.Wants(self, KEYS, clock_ns=clock)
        # Each filing recorded unasked or for a standing want has its age at
        # the edge recorded, by its acceptance, and reported (`__main__`).
        self.latency = Latency(self, clock_ns=clock)
        self.wants.latency = self.latency
        self.status = Status(mode=api.mode, waiting=waiting, started_at=now())
        #: Each filing sent in this process, by accession number.
        self.sent: set[str] = set()
        #: A standing want's companies, by record, with their CIKs.
        self.standing: dict[str, str] = {}
        self._ciks: dict[str, str] = {}
        self._filers: dict[str, str] = {}
        self._tickers: dict[str, str] = {}
        self._tickers_at: datetime | None = None

    def use(self, api: edgar.Api, watchlist: Sequence[str], waiting: str) -> None:
        """Read from `api` from now on, keeping `watchlist` current: the
        settings changed."""
        if api.mode != self.api.mode:
            self.sent.clear()
        self.api = api
        self.watchlist = tuple(watchlist)
        self.status.mode = api.mode
        self.status.waiting = waiting

    @property
    def waiting(self) -> str:
        """Why SEC is not asked: the User-Agent's problem, live; empty where
        it may be asked."""
        return "" if self.api.mode == "synthetic" else self.status.waiting

    def filer(self, cik: str) -> FilerState:
        return self.status.filers.setdefault(cik, FilerState(cik))

    # ── Asking EDGAR ────────────────────────────────────────────────────

    async def ask(self, url: str, cik: str = "") -> tuple[dict[str, Any], str]:
        """One answer's JSON and its key in storage; Failed where SEC refused
        or did not answer."""
        held = self.filer(cik) if cik else None
        try:
            fetched = await self.api.get(url)
        except edgar.Unreachable as failed:
            if held is not None:
                held.error = str(failed)
            raise Failed(str(failed)) from failed
        self.status.fetches += 1
        if held is not None:
            held.calls += 1
        key = self.raw.keep(fetched)
        if fetched.status != 200:
            if held is not None:
                held.error = fetched.error
            raise Failed(fetched.error)
        if held is not None:
            held.error = ""
        return fetched.json(), key

    async def tickers(self) -> dict[str, str]:
        """SEC's tickers, each to its CIK, read once a day."""
        now = self.now()
        if self._tickers_at and (now - self._tickers_at).total_seconds() < TICKERS_SECONDS:
            return self._tickers
        self.status.ticker_calls += 1
        try:
            answer, _ = await self.ask(edgar.WWW + edgar.TICKERS)
        except Failed as failed:
            self.status.ticker_error = str(failed)
            return self._tickers
        self.status.ticker_error = ""
        held: dict[str, str] = {}
        for row in answer.values():
            if isinstance(row, Mapping) and row.get("ticker") and row.get("cik_str") is not None:
                try:
                    held[str(row["ticker"]).upper()] = filings.cik(row["cik_str"])
                except ValueError:
                    continue
        self._tickers, self._tickers_at = held, now
        return held

    async def cik_of_entry(self, entry: str) -> str:
        """The CIK a watchlist entry names -- a CIK as given, or a ticker's --
        or empty, the reason noted."""
        digits = entry.upper().removeprefix("CIK")
        if digits.isdigit():
            try:
                found = filings.cik(digits)
            except ValueError:
                self.status.unread[entry] = "not a CIK: more than ten digits"
                return ""
            self.status.unread.pop(entry, None)
            return found
        mapped = (await self.tickers()).get(entry.upper(), "")
        if mapped:
            self.status.unread.pop(entry, None)
        else:
            self.status.unread[entry] = "no ticker SEC maps to a CIK"
        return mapped

    async def submissions(self, cik: str) -> tuple[Submissions, str]:
        """A company's submissions, and the answer's key in storage."""
        answer, key = await self.ask(edgar.DATA + edgar.submissions_path(cik), cik)
        read = submissions_of(cik, answer)
        held = self.filer(cik)
        held.name, held.tickers, held.former_names = read.name, read.tickers, read.former_names
        if read.filings:
            held.latest_form, held.latest_filed = read.filings[0].form, read.filings[0].filed
        return read, key

    async def older(self, cik: str, page: Page) -> tuple[list[Stated], str]:
        answer, key = await self.ask(edgar.DATA + edgar.page_path(page.name), cik)
        return stated_in(answer), key

    # ── Resolving and converting ────────────────────────────────────────

    async def filer_id(self, read: Submissions) -> str:
        """The deployment's company record for a filer, by its CIK, asked once
        per process; empty where none is held, reported missing as any miss
        is -- not found, or ambiguous where its CIK meets two records."""
        held = self.filer(read.cik)
        if read.cik in self._filers:
            return self._filers[read.cik]
        cik = ops.Identifier(scheme=filings.CIK, value=read.cik)
        found, reason = "", ops.MISS_REASON_NOT_FOUND
        try:
            found = (await self.resolve_company(identifiers=[cik])).company_id
        except CallFailed as failed:
            if "ambiguous" in f"{failed.kind} {failed.detail}".lower():
                reason = ops.MISS_REASON_AMBIGUOUS
        if not found:
            await self.report_missing_instrument(
                source=SOURCE, identifiers=[cik], as_of_ns=_ns(self.now()), reason=reason
            )
            log.info("filer CIK %s is not held", read.cik)
        self._filers[read.cik] = found
        held.company_id = found
        held.miss = (
            "" if found else "two records hold its CIK" if reason == ops.MISS_REASON_AMBIGUOUS
            else "not held"
        )  # fmt: skip
        return found

    async def convert(self, read: Submissions, stated: Sequence[Stated], key: str) -> list[Filing]:
        """`stated` as rows of `edgar_filings`, each naming the answer it was
        first read from, the filer as its record or, where none is held, as
        reported."""
        if not stated:
            return []
        company = await self.filer_id(read)
        unconverted = (
            [] if company else [ops.AsReported(scheme=filings.CIK, code=read.cik, text=read.name)]
        )
        rows = []
        for each in stated:
            first, _ = self.raw.first(each.accession, f"{each.filed:%Y-%m}", key)
            rows.append(
                filings.filing(
                    company,
                    each.accession,
                    each.form,
                    kind_of(each.form),
                    each.filed,
                    dataset=self.wants.dataset(FILINGS),
                    items=each.items,
                    period_of_report=each.report,
                    valid_from_ns=each.accepted_ns,
                    published_ns=each.accepted_ns,
                    raw=self.plugin.raw_record(first) if first else None,
                    unconverted=unconverted,
                )
            )
        self.raw.save_firsts()
        return rows

    async def record(self, rows: Sequence[Filing], want_id: str = "") -> Outcome:
        counts = self.wants.counts
        before = (counts.recorded, counts.restated, counts.unchanged)
        if rows:
            await self.wants.record("filings", rows, FILINGS, want_id)
        return Outcome(
            counts.recorded - before[0], counts.restated - before[1], counts.unchanged - before[2]
        )

    # ── Keeping the watchlist current ───────────────────────────────────

    async def current(self) -> list[str]:
        """The CIKs kept current: the watchlist's, then each standing want's."""
        held: list[str] = []
        for entry in self.watchlist:
            found = await self.cik_of_entry(entry)
            if found and found not in held:
                held.append(found)
                self.filer(found).entry = entry
        for found in self.standing.values():
            if found not in held:
                held.append(found)
        return held

    async def check(self) -> Outcome:
        """Read every company kept current, recording each filing not yet
        sent in this process."""
        self.status.checked_at = self.now()
        if self.waiting:
            self.status.error = ""
            return Outcome()
        done = Outcome()
        errors: list[str] = []
        kept = await self.current()
        started = _ns(self.status.started_at) if self.status.started_at else 0
        for found in kept:
            try:
                read, key = await self.submissions(found)
            except Failed as failed:
                errors.append(f"CIK {found}: {failed}")
                continue
            fresh = [f for f in read.filings if f.accession not in self.sent]
            rows = await self.convert(read, fresh, key)
            try:
                outcome = await self.record(rows)
            except meridian.MeridianError as refused:
                errors.append(f"CIK {found}: the deployment refused a recording: {refused}")
                continue
            self.sent.update(f.accession for f in fresh)
            self.filer(found).sent += len(fresh)
            now = _ns(self.now())
            arrived = [f for f in fresh if f.accepted_ns and f.accepted_ns >= started]
            self.status.lags[:] = [
                *self.status.lags,
                *((now - f.accepted_ns) // 10**9 for f in arrived),
            ][-LAGS:]
            done = Outcome(
                done.recorded + outcome.recorded,
                done.restated + outcome.restated,
                done.unchanged + outcome.unchanged,
            )
        self.status.error = errors[0] if errors else ""
        if kept and len(errors) < len(kept):
            self.status.read_at = self.now()
        if done.recorded or done.restated:
            log.info("%d filings recorded, %d restated", done.recorded, done.restated)
        return done

    # ── Wants ───────────────────────────────────────────────────────────

    async def on_observations_wanted(
        self, heard: meridian.Heard[ops.ObservationsWantedEvent]
    ) -> None:
        """Record what the lake wants of `edgar_filings`, or decline it (the
        SDK's `Wants.hear`, answered by `answer`)."""
        await self.wants.hear(heard, self.answer)

    async def on_want_withdrawn(self, heard: meridian.Heard[ops.WantWithdrawnEvent]) -> None:
        """A standing want withdrawn: its companies no longer kept current for it."""
        held = self.wants.withdraw(heard.message.want_id)
        if held is not None:
            still = {s for w in self.wants.standing.values() for s in w.subjects}
            for subject in held.subjects:
                if subject not in still:
                    self.standing.pop(subject, None)
        log.info("standing want %s withdrawn", heard.message.want_id)

    async def cik_of(self, company_id: str) -> str:
        """The CIK the deployment's company record carries, or empty."""
        if company_id not in self._ciks:
            found = ""
            try:
                record = await self.resolve_company(company_id=company_id)
            except CallFailed:
                record = None
            for identifier in record.identifiers if record is not None else ():
                if identifier.scheme == filings.CIK and identifier.value:
                    try:
                        found = filings.cik(identifier.value)
                    except ValueError:
                        continue
                    break
            self._ciks[company_id] = found
        return self._ciks[company_id]

    async def answer(
        self,
        want: ops.ObservationsWantedEvent,
        key: str,
        subjects: list[str],
        kinds: tuple[int, ...],
    ) -> dict[str, str]:
        """One want answered from EDGAR: its filings recorded against it, and
        each company declined, with why."""
        if key not in KEYS or want.data_type not in ("", FILING):
            return {s: "not_covered" for s in subjects}
        if self.waiting:
            return {s: "not_entitled" for s in subjects}
        declined: dict[str, str] = {}
        for subject in subjects:
            found = await self.cik_of(subject)
            if not found:
                declined[subject] = "not_covered"
                continue
            reason = await self._record_company(want, found)
            if reason:
                declined[subject] = reason
            elif want.standing:
                self.wants.stand(want, [subject], kinds)
                self.standing[subject] = found
        return declined

    def _window(self, want: ops.ObservationsWantedEvent) -> tuple[date, date] | None:
        """The days a want asks for, New York's; None for the latest."""
        if want.business_date:
            day = date.fromisoformat(want.business_date)
            return day, day
        if want.valid_from_ns or want.valid_until_ns:
            start = datetime.fromtimestamp(want.valid_from_ns / 1e9, NEW_YORK).date()
            until = want.valid_until_ns - 1 if want.valid_until_ns else _ns(self.now())
            return start, datetime.fromtimestamp(until / 1e9, NEW_YORK).date()
        return None

    @staticmethod
    def _asked(want: ops.ObservationsWantedEvent, each: Stated) -> bool:
        if want.business_date:
            return each.filed.isoformat() == want.business_date
        if want.valid_from_ns and each.accepted_ns < want.valid_from_ns:
            return False
        return not (want.valid_until_ns and each.accepted_ns >= want.valid_until_ns)

    async def _record_company(self, want: ops.ObservationsWantedEvent, cik: str) -> str:
        """Record a company's filings that a want asks for, against it; the
        reason it is declined, or empty where a filing was recorded."""
        try:
            read, key = await self.submissions(cik)
        except Failed as failed:
            log.warning("want %s: CIK %s not read: %s", want.want_id, cik, failed)
            return "source_silent"
        window = self._window(want)
        if window is None:
            chosen = [(read.filings[0], key)] if read.filings else []
        else:
            start, end = window
            if end < FIRST_DAY:
                return "beyond_history"
            chosen = [(f, key) for f in read.filings if self._asked(want, f)]
            oldest_recent = read.filings[-1].filed if read.filings else date.max
            if start < oldest_recent:
                for page in read.pages:
                    if page.last < start or page.first > end:
                        continue
                    try:
                        stated, page_key = await self.older(cik, page)
                    except Failed as failed:
                        log.warning("want %s: %s not read: %s", want.want_id, page.name, failed)
                        continue
                    chosen.extend((f, page_key) for f in stated if self._asked(want, f))
        if not chosen:
            first = min([p.first for p in read.pages] + [f.filed for f in read.filings[-1:]],
                        default=None)  # fmt: skip
            if window is not None and first is not None and window[1] < first:
                return "beyond_history"
            return "source_silent"
        rows: list[Filing] = []
        by_key: dict[str, list[Stated]] = {}
        for each, held in chosen[:MOST_FILINGS]:
            by_key.setdefault(held, []).append(each)
        for held, stated in by_key.items():
            rows.extend(await self.convert(read, stated, held))
        await self.record(rows, want.want_id)
        return ""

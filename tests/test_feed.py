"""The filings: the watchlist's pushed as they arrive, recorded once; any
company's pulled when wanted; each filer named by its CIK; and what is
declined, and why."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard

from sec_edgar.edgar import DATA, WWW, SyntheticApi, submissions_path
from sec_edgar.feed import NEW_YORK, accepted_ns, kind_of

from conftest import (
    ARRIVING,
    AT,
    CONTOSO,
    FABRIKAM,
    FILINGS,
    NORTHWIND,
    Arriving,
    feed,
    lake,
    sent,
    want,
)


def _ns(moment: datetime) -> int:
    return int(moment.timestamp()) * 10**9


async def test_a_watchlist_companys_new_filing_is_recorded_once(tmp_path: Path) -> None:
    recorder = lake()
    api = Arriving()
    started = AT - timedelta(hours=3)
    work = feed(tmp_path, recorder, watchlist=[CONTOSO], api=api, at=started)
    first = await work.check()
    assert first.recorded == 3 and not first.restated
    # Contoso files an 8-K at 08:30 New York time; the next check sends it alone.
    api.arrived = True
    work.now = lambda: AT
    second = await work.check()
    assert (second.recorded, second.restated, second.unchanged) == (1, 0, 0)
    assert sent(recorder)[-1].filing.accession_number == ARRIVING
    # Read again, nothing is sent: the lake already holds it.
    before = len(sent(recorder))
    third = await work.check()
    assert (third.recorded, third.restated, third.unchanged) == (0, 0, 0)
    assert len(sent(recorder)) == before
    # Its arrival is the Lag tab's: accepted 13:30 UTC, recorded 15:00.
    assert work.status.lags == [90 * 60]


async def test_a_restart_reads_again_and_changes_nothing(tmp_path: Path) -> None:
    recorder = lake()
    await feed(tmp_path, recorder, watchlist=[NORTHWIND, CONTOSO]).check()
    # A new process, the same storage: each filing names the answer it was
    # first read from, so the lake answers every one unchanged.
    later = feed(tmp_path, recorder, watchlist=[NORTHWIND, CONTOSO], at=AT + timedelta(hours=1))
    again = await later.check()
    assert again.unchanged == 10 and not again.recorded and not again.restated


async def test_a_filing_as_recorded(tmp_path: Path) -> None:
    recorder = lake()
    await feed(tmp_path, recorder, watchlist=[NORTHWIND]).check()
    rows = {f.filing.accession_number: f for f in sent(recorder)}
    assert len(rows) == 7, "the recent filings: the older page is read only when wanted"
    eight_k = rows["0000900000-26-000041"]
    assert eight_k.filing.form == "8-K" and eight_k.kind == ops.FILING_KIND_CURRENT_REPORT
    assert list(eight_k.items) == ["2.02", "9.01"]
    assert eight_k.filed_date == "2026-11-20" and eight_k.period_of_report == "2026-11-19"
    meta = eight_k.meta
    assert meta.row_key == "0000900000-26-000041"
    assert meta.source.dataset == FILINGS
    assert [(s.entity_id, s.role) for s in meta.subjects] == [
        ("ENT-NORTHWIND", ops.SUBJECT_ROLE_FILER)
    ]
    # SEC accepted it at 16:05:31 New York time, its valid and published time.
    accepted = _ns(datetime(2026, 11, 20, 16, 5, 31, tzinfo=NEW_YORK))
    assert meta.valid_from_ns == accepted
    assert [(t.kind, t.at_ns) for t in meta.source_times] == [
        (ops.SOURCE_TIME_KIND_PUBLISHED, accepted)
    ]
    assert meta.raw.instance_id == "sec-edgar" and meta.raw.key.startswith("responses/2026-11/")
    assert meta.raw.key.endswith("-CIK0900000001.json.gz")
    assert work_kinds(rows) == {
        "10-Q": ops.FILING_KIND_QUARTERLY_REPORT,
        "4": ops.FILING_KIND_OWNERSHIP,
        "DEF 14A": ops.FILING_KIND_PROXY,
        "10-K": ops.FILING_KIND_ANNUAL_REPORT,
        "SC 13G/A": ops.FILING_KIND_BENEFICIAL_OWNERSHIP,
        "8-K": ops.FILING_KIND_CURRENT_REPORT,
    }
    # No 13G states a period, and none is made up.
    assert rows["0000950103-26-002210"].period_of_report == ""


def work_kinds(rows: dict[str, ops.Filing]) -> dict[str, int]:
    return {f.filing.form: f.kind for f in rows.values()}


async def test_a_filer_is_named_by_its_cik_and_its_former_names_kept(tmp_path: Path) -> None:
    recorder = lake()
    work = feed(tmp_path, recorder, watchlist=["ZZNW"])
    await work.check()
    asked = recorder.on("ResolveCompany")
    assert [(i.scheme, i.value) for i in asked[0].identifiers] == [("cik", NORTHWIND)]
    held = work.status.filers[NORTHWIND]
    assert held.entry == "ZZNW" and held.company_id == "ENT-NORTHWIND"
    assert held.name == "Northwind Instruments Corp" and held.tickers == ("ZZNW",)
    assert held.former_names == (
        "NORTHWIND LABS INC (2004-06-01 to 2019-03-14)",
        "NORTHWIND LABORATORIES INC (1996-02-12 to 2004-05-28)",
    )
    assert WWW + "/files/company_tickers.json" in work.api.asked  # type: ignore[attr-defined]


async def test_a_filer_not_held_is_kept_as_reported(tmp_path: Path) -> None:
    recorder = lake(held={CONTOSO: "ENT-CONTOSO"})
    work = feed(tmp_path, recorder, watchlist=[NORTHWIND])
    done = await work.check()
    assert done.recorded == 7, "recorded all the same"
    row = sent(recorder)[0]
    assert not row.meta.subjects
    assert [(u.scheme, u.code, u.text) for u in row.meta.unconverted] == [
        ("cik", NORTHWIND, "Northwind Instruments Corp")
    ]
    assert work.status.filers[NORTHWIND].miss == "not held"
    # Reported missing, as any miss is, once.
    (missed,) = recorder.on("ReportMissingInstrument")
    assert [(i.scheme, i.value) for i in missed.identifiers] == [("cik", NORTHWIND)]
    assert missed.reason == ops.MISS_REASON_NOT_FOUND and missed.source == "sec-edgar"
    await work.check()
    assert len(recorder.on("ReportMissingInstrument")) == 1


async def test_an_entry_naming_no_company_is_said_and_skipped(tmp_path: Path) -> None:
    recorder = lake()
    work = feed(tmp_path, recorder, watchlist=["NOPE", "12345678901", CONTOSO])
    done = await work.check()
    assert done.recorded == 3
    assert work.status.unread == {
        "NOPE": "no ticker SEC maps to a CIK",
        "12345678901": "not a CIK: more than ten digits",
    }


async def test_a_non_watchlist_company_is_fetched_when_wanted(tmp_path: Path) -> None:
    recorder = lake()
    work = feed(tmp_path, recorder, watchlist=[CONTOSO])
    await work.on_observations_wanted(want("w-day", ["ENT-FABRIKAM"], day="2026-11-12"))
    rows = sent(recorder)
    assert [r.filing.accession_number for r in rows] == ["0001628280-26-071510"]
    assert recorder.on("RecordFilings")[0].want_id == "w-day"
    assert DATA + submissions_path(FABRIKAM) in work.api.asked  # type: ignore[attr-defined]
    assert work.wants.sent_to("edgar_filings").recorded == 1
    # Its latest, asked with no date.
    await work.on_observations_wanted(want("w-latest", ["ENT-FABRIKAM"]))
    assert sent(recorder)[-1].filing.accession_number == "0001628280-26-071510"


async def test_a_range_reaching_back_reads_the_older_page(tmp_path: Path) -> None:
    recorder = lake()
    work = feed(tmp_path, recorder)
    since = _ns(datetime(2019, 1, 1, tzinfo=NEW_YORK))
    until = _ns(datetime(2026, 1, 1, tzinfo=NEW_YORK))
    await work.on_observations_wanted(
        want("w-range", ["ENT-NORTHWIND"], valid_from_ns=since, valid_until_ns=until)
    )
    rows = sent(recorder)
    assert [r.filing.accession_number for r in rows] == [
        "0000900000-25-000044",
        "0000900000-19-000009",
    ]
    assert all("submissions-001" in r.meta.raw.key for r in rows)
    assert rows[1].items == ["5.03", "9.01"]


async def test_what_is_declined_and_why(tmp_path: Path) -> None:
    recorder = lake()
    work = feed(tmp_path, recorder)
    await work.on_observations_wanted(
        want("w-1", ["ENT-UNKNOWN", "ENT-FABRIKAM", "ENT-CONTOSO"], day="2026-11-01")
    )
    await work.on_observations_wanted(want("w-2", ["ENT-NORTHWIND"], day="1995-06-01"))
    await work.on_observations_wanted(want("w-3", ["ENT-NORTHWIND"], day="1990-06-01"))
    await work.on_observations_wanted(
        want("w-4", ["ENT-CONTOSO"], data_type="meridian.v1.Price", day="2026-11-18")
    )
    declined = {
        (d.want_id, s.entity_id): d.reason for d in recorder.on("DeclineWant") for s in d.subjects
    }
    assert declined == {
        ("w-1", "ENT-UNKNOWN"): ops.UNANSWERED_REASON_NOT_COVERED,
        ("w-1", "ENT-FABRIKAM"): ops.UNANSWERED_REASON_SOURCE_SILENT,
        ("w-1", "ENT-CONTOSO"): ops.UNANSWERED_REASON_SOURCE_SILENT,
        ("w-2", "ENT-NORTHWIND"): ops.UNANSWERED_REASON_BEYOND_HISTORY,
        ("w-3", "ENT-NORTHWIND"): ops.UNANSWERED_REASON_BEYOND_HISTORY,
        ("w-4", "ENT-CONTOSO"): ops.UNANSWERED_REASON_NOT_COVERED,
    }
    assert not sent(recorder)


async def test_a_standing_want_keeps_a_company_current(tmp_path: Path) -> None:
    recorder = lake()
    api = Arriving()
    work = feed(tmp_path, recorder, api=api)
    await work.on_observations_wanted(want("w-standing", ["ENT-CONTOSO"], standing=True))
    assert work.standing == {"ENT-CONTOSO": CONTOSO}
    api.arrived = True
    done = await work.check()
    assert ARRIVING in {r.filing.accession_number for r in sent(recorder)}
    assert done.recorded >= 1
    # The lake withdraws it: Contoso is no longer kept current.
    await work.on_want_withdrawn(
        Heard(row="WantWithdrawn", message=ops.WantWithdrawnEvent(want_id="w-standing"))
    )
    assert work.standing == {} and await work.current() == []


async def test_a_missing_or_malformed_user_agent_asks_nothing(tmp_path: Path) -> None:
    for problem in ("is not set", "names no contact email address"):
        recorder = lake()
        api = SyntheticApi(lambda: AT)
        api.mode = "live"
        work = feed(tmp_path, recorder, watchlist=[CONTOSO], api=api, waiting=problem)
        assert (await work.check()).recorded == 0
        await work.on_observations_wanted(want("w-1", ["ENT-CONTOSO"], day="2026-11-18"))
        assert api.asked == [] and not sent(recorder)
        (declined,) = recorder.on("DeclineWant")
        assert declined.reason == ops.UNANSWERED_REASON_NOT_ENTITLED
        assert work.waiting == problem


def test_forms_kinds_and_acceptance() -> None:
    assert kind_of("10-K/A") == "FILING_KIND_ANNUAL_REPORT"
    assert kind_of("20-F") == "FILING_KIND_ANNUAL_REPORT"
    assert kind_of("6-K") == "FILING_KIND_CURRENT_REPORT"
    assert kind_of("424B2") == "FILING_KIND_REGISTRATION"
    assert kind_of("S-1/A") == "FILING_KIND_REGISTRATION"
    assert kind_of("13F-HR") == "FILING_KIND_HOLDINGS_REPORT"
    assert kind_of("SCHEDULE 13D/A") == "FILING_KIND_BENEFICIAL_OWNERSHIP"
    assert kind_of("CORRESP") == "FILING_KIND_OTHER"
    # EDGAR's acceptance is Eastern time, whatever its Z says.
    assert accepted_ns("2026-11-20T16:05:31.000Z") == _ns(
        datetime(2026, 11, 20, 16, 5, 31, tzinfo=NEW_YORK)
    )
    assert accepted_ns("") == 0

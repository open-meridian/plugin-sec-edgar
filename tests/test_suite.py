"""The data suite (meridian.suites), each case EDGAR's filings present
mapped to the plugin's own conversion of the responses committed with it:
the filings slice's cases for a filing and its filer, and the role's cases
every data plugin presents -- a filer whose CIK meets two records reported
missing, a subject declined, a standing want withdrawn,
its datasets' licences read, and its feed delay.

A filing is not a price, a rate, a trade, a quote or an outcome: every case
about one is the SDK's list for a plugin that records
none (`RATES_NOT_PRESENTED`, but for the filings this version presents), or
the rates cases, each with why. The filings slice's other kinds -- reported
facts, holdings, dividends, ratings -- come with their own datasets in later
versions, so their cases are named here, with why.

The cases every suite holds that the SDK answers (a replacement, the
template catalogue, an event group heard) are the SDK's.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from meridian.errors import CallFailed
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.roles.data.testing import RATES_CASES, RATES_NOT_PRESENTED, feed_delay
from meridian.suites import ANSWERED_BY_SDK, Recorder, run

from conftest import CONTOSO, FILINGS, companies, feed, want

PRESENTED = (
    "a-filing-recorded",
    "an-asset-that-does-not-resolve",
    "resolves-a-filer",
    "a-subject-declined",
    "a-standing-want-withdrawn",
    "reads-its-datasets-licences",
    "reports-its-feed-delay",
)
#: The filings slice's kinds a later version brings, each its own dataset.
LATER = {
    "a-fact-restated": "reported facts come with edgar_facts, a later version",
    "a-fact-confirmed": "reported facts come with edgar_facts, a later version",
    "a-complete-holdings-report": "13F holdings come with edgar_13f, a later version",
    "a-cusip-used-as-key": "13F holdings come with edgar_13f, a later version",
    "a-stake-crossed": "Schedules 13D and 13G come with edgar_13dg, a later version",
    "a-dividend-declared": "declared dividends come with edgar_dividends, a later version",
    "a-rating-action": "rating actions are another publisher's: each agency's own files",
}
NOT_PRESENTED = {
    **{c: why for c, why in RATES_NOT_PRESENTED.items() if c not in PRESENTED},
    **{c: "it records filings, never rates" for c in RATES_CASES},
    **LATER,
    "records-a-datasets-liveness": "it polls EDGAR every few minutes and streams nothing",
    "reads-a-calendar": "its dataset declares no calendar: filings arrive when companies file",
    "asks-for-a-settlement-date": "a filing settles nothing",
    "records-a-derived-series": "EDGAR publishes no figure of its own in this version",
}


def producers(tmp: Path) -> dict[str, Callable[[Recorder], Awaitable[None]]]:
    async def eight_k(recorder: Recorder) -> None:
        # Contoso, kept current, files an 8-K: recorded under its filer,
        # resolved by its CIK.
        companies(recorder)
        await feed(tmp, recorder, watchlist=[CONTOSO]).check()
        sent = [f for p in recorder.on("RecordFilings") for f in p.filings]
        assert any(f.filing.form == "8-K" for f in sent)

    async def two_records(recorder: Recorder) -> None:
        # Contoso's CIK meets two of the deployment's company records.
        def ambiguous(_: object) -> None:
            raise CallFailed("ResolveCompany", "ambiguous", "two companies hold the CIK")

        recorder.answer("ResolveCompany", ambiguous)
        await feed(tmp, recorder, watchlist=[CONTOSO]).check()

    async def delayed(recorder: Recorder, latency: object) -> None:
        # Each filing recorded unasked has its age at the edge recorded, by
        # SEC's acceptance, then reported.
        companies(recorder)
        work = feed(tmp, recorder, watchlist=[CONTOSO])
        work.wants.latency = latency
        await work.check()

    async def declined(recorder: Recorder) -> None:
        companies(recorder)
        work = feed(tmp, recorder)
        asked = want("w-2", ["ENT-NOT-A-FILER"], day="2026-11-12").message
        recorder.answer("ObservationsWanted", lambda _: asked)
        await recorder.hear(work, "ObservationsWanted")

    async def withdrawn(recorder: Recorder) -> None:
        companies(recorder)
        work = feed(tmp, recorder)
        recorder.answer(
            "WantWithdrawn",
            lambda _: ops.WantWithdrawnEvent(want_id="w-standing", dataset=FILINGS),
        )
        await recorder.hear(work, "WantWithdrawn")

    async def licences(recorder: Recorder) -> None:
        recorder.answer(
            "ListDatasets",
            lambda _: ops.ListDatasetsResult(licences=[ops.DatasetLicence(dataset=FILINGS)]),
        )
        work = feed(tmp, recorder)
        await work.wants.read_licences()
        assert work.wants.licensed == {FILINGS}

    return {
        "a-filing-recorded": eight_k,
        "resolves-a-filer": eight_k,
        "an-asset-that-does-not-resolve": two_records,
        "reports-its-feed-delay": feed_delay(delayed),
        "a-subject-declined": declined,
        "a-standing-want-withdrawn": withdrawn,
        "reads-its-datasets-licences": licences,
    }


def test_the_data_suite_passes(tmp_path: Path) -> None:
    report = run("data", producers(tmp_path), not_presented=NOT_PRESENTED, instance_id="sec-edgar")
    assert report.passed, report.failures
    assert sorted(report.not_presented) == sorted(NOT_PRESENTED)
    assert sorted(report.passed_cases) == sorted([*PRESENTED, *ANSWERED_BY_SDK])
    assert report.answered_by_sdk == list(ANSWERED_BY_SDK)

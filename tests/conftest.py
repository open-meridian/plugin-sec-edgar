"""Shared stand-ins: EDGAR's responses committed with the plugin, a fixed
clock, the deployment's company records, and the lake as the sidecar answers
it."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from meridian.errors import CallFailed
from meridian.plugin.v1 import operations_pb2 as ops
from meridian.receive import Heard
from meridian.roles.data.testing import Lake
from meridian.suites import Recorder

from sec_edgar.edgar import DATA, Fetched, SyntheticApi, submissions_path
from sec_edgar.feed import Feed
from sec_edgar.raw import RawStore

#: 15:00 UTC on Tuesday 24 November 2026, 10:00 in New York.
AT = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
INSTANCE = "sec-edgar"
FILINGS = f"{INSTANCE}:edgar_filings"
FILING = "meridian.v1.Filing"
#: The User-Agent the tests declare: a placeholder, never a person's address.
USER_AGENT = "Example Co admin@example.com"

#: The three fictitious companies the committed responses hold.
NORTHWIND = "0900000001"  # renamed twice; an older page of submissions
CONTOSO = "0900000002"
FABRIKAM = "0900000003"  # on no watchlist: fetched when wanted
#: The deployment's company record for each, by CIK.
COMPANIES = {NORTHWIND: "ENT-NORTHWIND", CONTOSO: "ENT-CONTOSO", FABRIKAM: "ENT-FABRIKAM"}

#: A filing Contoso makes while the plugin runs.
ARRIVING = "0001193125-26-305500"


def companies(recorder: Recorder, held: dict[str, str] | None = None) -> dict[str, str]:
    """The deployment's company records, answering ResolveCompany by CIK or
    by record, as the platform does; a CIK it does not hold refused."""
    records = dict(COMPANIES if held is None else held)

    def resolve(params: ops.ResolveCompanyParams) -> ops.ResolveCompanyResult:
        if params.company_id:
            for cik, company in records.items():
                if company == params.company_id:
                    return ops.ResolveCompanyResult(
                        company_id=company,
                        identifiers=[ops.Identifier(scheme="cik", value=cik)],
                        version=1,
                    )
            raise CallFailed("ResolveCompany", "not_found", params.company_id)
        for identifier in params.identifiers:
            if identifier.scheme == "cik" and identifier.value in records:
                return ops.ResolveCompanyResult(company_id=records[identifier.value], version=1)
        raise CallFailed("ResolveCompany", "not_found", "no company holds the identifiers")

    recorder.answer("ResolveCompany", resolve)
    return records


def lake(held: dict[str, str] | None = None) -> Lake:
    """The lake as a test stands it in, holding the companies, and answering
    a batch of filings as it answers any row: a row key new recorded, the
    same row again unchanged, a changed one restated."""
    recorder = Lake(INSTANCE)
    companies(recorder, held)
    versions: dict[str, tuple[Any, ...]] = {}

    def recorded(params: ops.RecordFilingsParams) -> ops.RecordFilingsResult:
        done = ops.RecordFilingsResult()
        for filing in params.filings:
            stated = (
                filing.filing.SerializeToString(),
                filing.kind,
                tuple(filing.items),
                filing.filed_date,
                filing.period_of_report,
                filing.meta.raw.key,
                tuple((t.kind, t.at_ns) for t in filing.meta.source_times),
            )
            was = versions.get(filing.meta.row_key)
            if was is None:
                done.recorded += 1
            elif was == stated:
                done.unchanged += 1
            else:
                done.restated += 1
            versions[filing.meta.row_key] = stated
        return done

    recorder.answer("RecordFilings", recorded)
    return recorder


def sent(recorder: Recorder) -> list[ops.Filing]:
    """Every filing sent, in the order sent."""
    return [f for params in recorder.on("RecordFilings") for f in params.filings]


class Arriving(SyntheticApi):
    """EDGAR, Contoso's 8-K of 24 November among its submissions once
    `arrived` is set, as a filing accepted while the plugin runs shows."""

    def __init__(self) -> None:
        super().__init__(lambda: AT)
        self.arrived = False

    async def get(self, url: str) -> Fetched:
        got = await super().get(url)
        if not self.arrived or url != DATA + submissions_path(CONTOSO):
            return got
        answer = json.loads(got.body)
        recent = answer["filings"]["recent"]
        new = {
            "accessionNumber": ARRIVING, "filingDate": "2026-11-24", "reportDate": "2026-11-23",
            "acceptanceDateTime": "2026-11-24T08:30:00.000Z", "act": "34", "form": "8-K",
            "fileNumber": "001-10002", "filmNumber": "26999999", "items": "7.01,9.01",
            "core_type": "8-K", "size": 120000, "isXBRL": 1, "isInlineXBRL": 1,
            "primaryDocument": "ctso-20261123.htm", "primaryDocDescription": "8-K",
        }  # fmt: skip
        for column, value in new.items():
            recent[column].insert(0, value)
        return Fetched(url, 200, json.dumps(answer).encode(), got.fetched_at)


def feed(
    tmp: Path,
    recorder: Recorder | None = None,
    *,
    watchlist: Sequence[str] = (),
    api: Any = None,
    at: datetime = AT,
    waiting: str = "",
) -> Feed:
    """The plugin's work on the lake and EDGAR's committed responses, at
    `at`: its data role class bound to the lake."""
    held = recorder if recorder is not None else lake()
    return held.bind(
        Feed(
            api or SyntheticApi(lambda: at),
            RawStore(tmp),
            now=lambda: at,
            watchlist=watchlist,
            waiting=waiting,
        )
    )


def want(
    want_id: str,
    subjects: list[str],
    *,
    day: str = "",
    standing: bool = False,
    dataset: str = FILINGS,
    data_type: str = FILING,
    valid_from_ns: int = 0,
    valid_until_ns: int = 0,
) -> Heard:  # type: ignore[type-arg]
    return Heard(
        row="ObservationsWanted",
        message=ops.ObservationsWantedEvent(
            want_id=want_id,
            dataset=dataset,
            data_type=data_type,
            subjects=[ops.SubjectRef(entity_id=s) for s in subjects],
            business_date=day,
            standing=standing,
            valid_from_ns=valid_from_ns,
            valid_until_ns=valid_until_ns,
        ),
    )

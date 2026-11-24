"""The catalogue, from code, as the deployment approves it."""

from __future__ import annotations

from meridian.plugin.v1 import operations_pb2 as ops

from sec_edgar.declaration import DECLARATION
from sec_edgar.declared import TERMS


def test_one_dataset_of_filings() -> None:
    (filings,) = DECLARATION.catalogue
    assert filings.key == "edgar_filings"
    assert list(filings.data_types) == ["meridian.v1.Filing"]
    assert filings.vendor == "U.S. Securities and Exchange Commission (EDGAR)"
    assert [ops.ObservationMode.Name(m) for m in filings.modes] == [
        "OBSERVATION_MODE_PUSH", "OBSERVATION_MODE_PULL"
    ]  # fmt: skip
    # Event-driven: silence is no fault. From 1994, and New York's day.
    assert filings.cadence == 0 and filings.history > 11_000
    assert filings.day_time_zone == "America/New_York" and not filings.calendar_id
    assert not filings.venue_id and filings.gap_recovery == "backfill"


def test_secs_terms_in_words_and_no_licence() -> None:
    (filings,) = DECLARATION.catalogue
    assert filings.terms_and_pricing == TERMS and len(TERMS) <= 2000
    assert "User-Agent" in TERMS and "10 requests a second" in TERMS
    assert "seal" in TERMS


def test_the_answers_are_kept_in_storage() -> None:
    assert DECLARATION.storage is not None
    assert [k.name for k in DECLARATION.storage.kinds] == ["responses"]

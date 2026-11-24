"""What this version declares beside its role, `data`, built from code and
used twice: `__main__` registers with it, and `meridian plugin upload` reads
it from the built image (pyproject.toml's `[tool.meridian] declaration`).

**The catalogue: one dataset in this version, `edgar_filings`.** Each filing
a company makes on EDGAR, recorded as a `Filing` row under its filer:

- `vendor` the SEC, through EDGAR; no aggregator;
- `modes`: pushed (the watchlist's companies, checked every few minutes) and
  pulled (any company's, when a reader wants it);
- `cadence` 0: filings arrive when companies file, and silence is no fault;
- `history` from 1994, when EDGAR's electronic filings begin, in days to
  this version's release;
- its day New York's: a filing's date is EDGAR's, in Eastern time; no
  calendar;
- no venue;
- its terms in plain words (`TERMS`), and no licence declared: a
  deployment admin sets the licence on the Data sources page;
- a gap asked again (`gap_recovery` `backfill`): EDGAR serves each company's
  whole history.

The facts, 13F holdings, Schedules 13D and 13G and dividend datasets come in
later versions, each its own dataset.

**Storage:** SEC's answers (raw.py), archivable, ten years by default.
"""

from __future__ import annotations

from datetime import date

from meridian import DatasetDeclaration
from meridian.declaration import RecordKind

from .raw import DEFAULT_WINDOW_DAYS, RESPONSES

FILINGS = "edgar_filings"
KEYS = (FILINGS,)

VENDOR = "U.S. Securities and Exchange Commission (EDGAR)"
FILING = "meridian.v1.Filing"
#: Event-driven: a filing arrives when a company files.
CADENCE = 0
#: EDGAR's electronic filings, from 1994, to this version's release.
HISTORY = (date(2026, 11, 24) - date(1994, 1, 1)).days
DAY_TIME_ZONE = "America/New_York"

#: SEC's terms, in plain words, as docs/terms.md summarises them.
TERMS = (
    "SEC EDGAR's filings: public, free, no key. SEC's fair-access policy asks every automated "
    "client to declare a User-Agent naming its company and a contact address, and to make at "
    "most 10 requests a second; a client that does not is refused for a while. Filings are "
    "public records and may be reused; the SEC's seal may not be used, and nothing here is "
    "endorsed by the SEC."
)

CATALOGUE = [
    DatasetDeclaration(
        key=FILINGS,
        vendor=VENDOR,
        data_types=[FILING],
        modes=["push", "pull"],
        cadence=CADENCE,
        history=HISTORY,
        terms_and_pricing=TERMS,
        gap_recovery="backfill",
        day_time_zone=DAY_TIME_ZONE,
    )
]

RESPONSES_KIND = RecordKind(RESPONSES, "Raw responses", window_days=DEFAULT_WINDOW_DAYS)

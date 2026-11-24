"""The typed records the pages answer, for a person's page and an agent's
tool alike: the data role's common records (`meridian.roles.data`), each
extended with EDGAR's own fields -- Connection's **Sources**, and Datasets'
**Filers** and **Lag**. The Connection tab is `read_connection`, the
Datasets tab `read_datasets`, each answering what its page shows.

A data plugin's pages show its connection and its datasets, never the data:
filings are the reading roles' to show. So neither record holds a filing;
each says how EDGAR was reached and what the plugin serves of it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from meridian.roles import data


@dataclass(frozen=True)
class SourceRead:
    """One of EDGAR's sources the plugin reads, as "Sources" lists it: its
    state, the latest filing read from it, the next expected (none: filings
    arrive when companies file), the calls made, and the last error."""

    source: str
    address: str
    state: str
    last_release: str = ""
    next_expected: str = ""
    calls: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class ConnectionRead(data.ConnectionRead):
    """Connection's common fields, then EDGAR's: the head's status and what
    it means, where it reads, the last check, why it waits (the User-Agent's
    problem, naming the setting), the pace kept and SEC's refusals, each
    source, how many companies are kept current, and the answers kept."""

    state: str = ""
    said: str = ""
    source: str = ""
    checked_at: str = ""
    waiting: str = ""
    per_second: int = 0
    kept_current: int = 0
    sources: list[SourceRead] = field(default_factory=list)
    responses_kept: int = 0
    kept_for: str = ""


@dataclass(frozen=True)
class FilerRead:
    """One company the plugin reads, as "Filers" lists it: its CIK, EDGAR's
    name, tickers and former names, the watchlist entry naming it, whether
    it is kept current, the deployment's company record or why there is
    none, its latest filing's form and date, the filings sent since start,
    and the last error."""

    cik: str
    name: str = ""
    entry: str = ""
    tickers: list[str] = field(default_factory=list)
    former_names: list[str] = field(default_factory=list)
    kept_current: bool = False
    company_id: str = ""
    miss: str = ""
    latest_form: str = ""
    latest_filed: str = ""
    sent: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class LagRead:
    """A dataset's lag: how long after SEC accepted a filing the plugin
    recorded it, for filings that arrived while it ran -- the median and the
    longest, in seconds and in words -- and how many."""

    dataset: str
    filings: int = 0
    median_seconds: int = 0
    longest_seconds: int = 0
    median: str = ""
    said: str = ""


@dataclass(frozen=True)
class DatasetsRead(data.DatasetsRead):
    """Datasets' common fields, then EDGAR's: its terms in words, each
    company it reads ("Filers"), the lag ("Lag"), and each watchlist entry
    that names no company, with why."""

    served: list[data.Served] = field(default_factory=list)
    wants: list[data.WantHeard] = field(default_factory=list)  # type: ignore[assignment]
    terms: str = ""
    filers: list[FilerRead] = field(default_factory=list)
    lag: list[LagRead] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)

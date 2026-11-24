"""The plugin's settings, declared to the SDK, and what it makes of them.

In the data role's order: no `environment` (EDGAR has one site); the
plugin's own; then the role's sample data.

- `edgar_user_agent` -- the company name and contact address SEC's
  fair-access policy asks every automated client to declare, as
  `Example Co admin@example.com`. Required: while it is missing the sidecar
  names it, and while it is missing or malformed (`check_user_agent`) the
  plugin asks SEC nothing and its status names the setting. Each deployment
  enters its own.
- `edgar_requests_per_second` -- the plugin's share of SEC's limit of 10
  requests a second: 1 to 10, 5 by default.
- `edgar_watchlist` -- the companies whose filings are pushed as they
  arrive, a typed table of one column, each a CIK or a ticker; any other
  company's filings are fetched when a reader wants them. The plugin never
  reads positions to choose.
- `sample_data` -- a developer's setting: the responses committed under
  responses/ in place of SEC, for trying the plugin offline.

The SDK declares the storage's two settings from the declaration's kind:
`responses_window_days` and `responses_past_window`. Their names are the
SDK's, and read here only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import meridian

from .edgar import check_user_agent
from .limits import DEFAULT_PER_SECOND, SEC_MOST_PER_SECOND, per_second
from .raw import DEFAULT_WINDOW_DAYS, RESPONSES

USER_AGENT = "edgar_user_agent"
PER_SECOND = "edgar_requests_per_second"
WATCHLIST = "edgar_watchlist"
#: The table's one column: a CIK or a ticker.
COMPANY = "company"
SAMPLE_DATA = "sample_data"
WINDOW = f"{RESPONSES}_window_days"
PAST_WINDOW = f"{RESPONSES}_past_window"
#: The most companies the watchlist holds.
MOST_WATCHED = 500


@meridian.settings
class Declared:
    """The settings as declared, in the data role's order."""

    edgar_user_agent: str = meridian.setting(
        "User-Agent",
        required=True,
        description=(
            "Your company's name and a contact email address, as Example Co admin@example.com. "
            "SEC asks every automated client to declare one, and refuses those that do not."
        ),
    )
    edgar_requests_per_second: int = meridian.setting(
        "Requests a second",
        default=DEFAULT_PER_SECOND,
        at_least=1,
        at_most=SEC_MOST_PER_SECOND,
        unit="requests a second",
        description=(
            "This plugin's share of SEC's limit of 10 requests a second, 1 to 10. Lower it "
            "where other tools at your firm call SEC too."
        ),
    )
    edgar_watchlist: list = meridian.setting(  # type: ignore[type-arg]
        "Watchlist",
        description=(
            "The companies whose filings are recorded as they arrive. Any other company's "
            "filings are fetched when a reader wants them."
        ),
        columns=[
            meridian.Column(
                COMPANY,
                kind="text",
                label="CIK or ticker",
                required=True,
                description="The company's SEC Central Index Key, or a ticker SEC maps to one",
            )
        ],
        most_rows=MOST_WATCHED,
    )
    sample_data: bool = meridian.sample_data(
        description=(
            "Serve the responses committed with the plugin instead of asking SEC: three "
            "fictitious companies' submissions in EDGAR's layout. Runs without a User-Agent. "
            "Development deployments only."
        )
    )


DECLARED = Declared


@dataclass(frozen=True)
class Config:
    user_agent: str = ""
    #: Why the User-Agent will not do; empty where it will.
    user_agent_problem: str = "is not set"
    per_second: int = DEFAULT_PER_SECOND
    watchlist: tuple[str, ...] = ()
    sample_data: bool = False
    window_days: int = DEFAULT_WINDOW_DAYS
    past_window: str = "kept"


def _watchlist(rows: object) -> tuple[str, ...]:
    """The table's entries, trimmed, once each, in the table's order."""
    held: list[str] = []
    if not isinstance(rows, Sequence) or isinstance(rows, str):
        return ()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        entry = str(row.get(COMPANY, "")).strip().upper()
        if entry and entry not in held:
            held.append(entry)
    return tuple(held[:MOST_WATCHED])


def config_from(values: Mapping[str, object]) -> Config:
    """The configuration a delivery of the settings says."""
    agent = values.get(USER_AGENT)
    rate = values.get(PER_SECOND)
    window = values.get(WINDOW)
    past = values.get(PAST_WINDOW)
    said = agent.strip() if isinstance(agent, str) else ""
    return Config(
        user_agent=said,
        user_agent_problem=check_user_agent(said),
        per_second=per_second(rate) if isinstance(rate, int) else DEFAULT_PER_SECOND,
        watchlist=_watchlist(values.get(WATCHLIST)),
        sample_data=values.get(SAMPLE_DATA) is True,
        window_days=window if isinstance(window, int) and window > 0 else DEFAULT_WINDOW_DAYS,
        past_window=past if isinstance(past, str) and past else "kept",
    )

"""The settings as declared, in the data role's order, and read back."""

from __future__ import annotations

from meridian._settings import declared_by

from sec_edgar.settings import DECLARED, config_from

from conftest import USER_AGENT


def test_declared_in_the_roles_order() -> None:
    declared = declared_by(DECLARED)
    assert [s.name for s in declared] == [
        "edgar_user_agent",
        "edgar_requests_per_second",
        "edgar_watchlist",
        "sample_data",
    ]
    agent, rate, watchlist, sample = declared
    # SEC asks for it, so setup does: required, and no secret.
    assert agent.required and not agent.secret and agent.kind is str
    assert rate.kind is int and rate.default == 5
    assert watchlist.kind is list and [c.name for c in watchlist.columns] == ["company"]
    assert watchlist.columns[0].required and watchlist.columns[0].kind == "text"
    assert sample.developer


def test_read_back() -> None:
    config = config_from(
        {
            "edgar_user_agent": f"  {USER_AGENT} ",
            "edgar_requests_per_second": 8,
            "edgar_watchlist": [{"company": " zznw "}, {"company": "0900000002"},
                                {"company": "ZZNW"}, {"other": "x"}],
            "responses_window_days": 30,
            "responses_past_window": "archived",
        }
    )  # fmt: skip
    assert config.user_agent == USER_AGENT and config.user_agent_problem == ""
    assert config.per_second == 8 and config.watchlist == ("ZZNW", "0900000002")
    assert config.window_days == 30 and config.past_window == "archived"
    assert not config.sample_data


def test_a_missing_or_malformed_user_agent_is_said() -> None:
    assert config_from({}).user_agent_problem == "is not set"
    assert config_from({"edgar_user_agent": "Example Co"}).user_agent_problem == (
        "names no contact email address"
    )
    # Held to SEC's 10, and to at least 1.
    assert config_from({"edgar_requests_per_second": 40}).per_second == 10
    assert config_from({"edgar_requests_per_second": 0}).per_second == 1
    assert config_from({}).per_second == 5

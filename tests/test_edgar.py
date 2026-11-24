"""EDGAR's addresses, the User-Agent's check, the live client's pace and
the committed responses."""

from __future__ import annotations

import pytest

from sec_edgar import edgar
from sec_edgar.edgar import (
    DATA,
    Fetched,
    LiveApi,
    SyntheticApi,
    check_user_agent,
    page_path,
    submissions_path,
)
from sec_edgar.limits import Limiter

from conftest import AT, NORTHWIND, USER_AGENT


def test_the_user_agent_is_checked() -> None:
    assert check_user_agent(USER_AGENT) == ""
    assert check_user_agent("Jane Doe jane.doe@example.org") == ""
    assert check_user_agent("") == "is not set"
    assert check_user_agent("   ") == "is not set"
    assert check_user_agent("Example Co") == "names no contact email address"
    assert check_user_agent("admin@example.com") == "names no company or person beside the address"
    assert check_user_agent("Exämple Co admin@example.com") == (
        "holds characters other than plain ASCII"
    )
    assert check_user_agent("Example Co\nadmin@example.com") == (
        "holds characters other than plain ASCII"
    )
    assert check_user_agent("X" * 190 + " a@example.com") == "is longer than 200 characters"


def test_the_addresses() -> None:
    assert submissions_path(NORTHWIND) == "/submissions/CIK0900000001.json"
    assert page_path("CIK0900000001-submissions-001.json") == (
        "/submissions/CIK0900000001-submissions-001.json"
    )
    with pytest.raises(ValueError):
        page_path("../../etc/passwd")


async def test_the_committed_responses() -> None:
    api = SyntheticApi(lambda: AT)
    got = await api.get(DATA + submissions_path(NORTHWIND))
    assert got.status == 200 and got.json()["name"] == "Northwind Instruments Corp"
    missing = await api.get(DATA + submissions_path("0900000099"))
    assert missing.status == 404 and missing.json() == {}


async def test_the_live_client_paces_and_backs_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """No call leaves the test: the client's request is replaced, and the
    limiter's clock and sleep are the test's."""
    now = [0]
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += int(seconds * 1e9)

    limiter = Limiter(5, clock=lambda: now[0], sleep=sleep)
    client = LiveApi(USER_AGENT, limiter, now=lambda: AT)
    answers = iter([429, 200, 200])
    headers: list[str] = []

    def answer(url: str) -> Fetched:
        headers.append(client._user_agent)
        return Fetched(url, next(answers), b"{}", AT)

    monkeypatch.setattr(client, "_get", answer)
    refused = await client.get(DATA + submissions_path(NORTHWIND))
    assert refused.status == 429 and "429" in refused.error and limiter.refused == 1
    await client.get(DATA + submissions_path(NORTHWIND))
    assert slept and slept[-1] >= 10, "paused after the 429"
    await client.get(DATA + submissions_path(NORTHWIND))
    assert headers == [USER_AGENT] * 3


def test_a_403_says_what_to_check() -> None:
    said = Fetched(DATA + "/submissions/CIK0900000001.json", 403, b"", AT).error
    assert "edgar_user_agent" in said and "edgar_requests_per_second" in said
    assert edgar.MOST_USER_AGENT == 200

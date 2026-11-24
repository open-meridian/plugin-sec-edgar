"""The two pages under Manage, and their read tools: what each shows, to
whom, that a tool answers what its page shows, that a missing User-Agent is
named, and that no filing is shown."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from meridian.testing import PageClient

from sec_edgar import page as page_module
from sec_edgar.edgar import SyntheticApi
from sec_edgar.page import CONNECTION, DATASETS, figures, hold, pages

from conftest import AT, CONTOSO, FABRIKAM, FILINGS, NORTHWIND, USER_AGENT, feed, lake, want

#: Filings the committed responses hold, none of which a page may show.
ACCESSIONS = ("0000900000-26-000041", "0001193125-26-301122", "0001628280-26-071510")


@pytest.fixture
def client(tmp_path: Path) -> PageClient:
    work = feed(tmp_path, watchlist=["ZZNW", CONTOSO, "NOPE"])

    async def run() -> None:
        await work.check()
        await work.on_observations_wanted(want("w-day", ["ENT-FABRIKAM"], day="2026-11-12"))
        await work.on_observations_wanted(want("w-standing", ["ENT-FABRIKAM"], standing=True))

    asyncio.run(run())
    hold(work)
    return PageClient(pages)


def test_each_page_is_managed_alone(client: PageClient) -> None:
    served = {(r.page.path, r.level): r.response.status for r in client.every_page()}
    assert served == {
        (CONNECTION, "admin"): 200,
        (CONNECTION, "write"): 403,
        (CONNECTION, "read"): 403,
        (DATASETS, "admin"): 200,
        (DATASETS, "write"): 403,
        (DATASETS, "read"): 403,
    }
    # No filing on any page: filings are the reading roles' to show.
    client.assert_no_account_data(*ACCESSIONS)


def test_connection_says_how_edgar_is_reached(client: PageClient) -> None:
    text = client.get(CONNECTION, "admin").text
    assert text.index("<h2>Key</h2>") < text.index("<tr data-sources>") < text.index("<h2>Limits")
    assert "<h2>Sessions</h2>" not in text
    assert 'state="warn"' in text  # the entry that names no company
    assert "Company submissions answering" in text and "Ticker map answering" in text
    assert "Fri 20 Nov 2026" in text  # the latest filing read
    assert "Kept current: 4 companies" in text  # three entries, one standing want
    assert "<tr data-pace>" in text and "5 requests a second at most" in text
    assert "Does not stream" in text and 'href="/.meridian/ui/0.13.0/meridian.css"' in text


def test_datasets_lists_the_dataset_and_its_filers(client: PageClient) -> None:
    text = client.get(DATASETS, "admin").text
    tabs = ["Served <span", "Wants <span", "Filers <span", ">Terms</a>"]
    assert [text.index(t) for t in tabs] == sorted(text.index(t) for t in tabs)
    assert FILINGS in text and "<h2>Subjects</h2>" in text
    assert "NOPE: no ticker SEC maps to a CIK" in text
    filers = client.get(DATASETS, "admin", view="filers").text
    assert filers.count("<tr data-filer=") == 3
    assert "NORTHWIND LABS INC (2004-06-01 to 2019-03-14)" in filers
    assert "renamed" in filers and "ENT-NORTHWIND" in filers
    terms = client.get(DATASETS, "admin", view="terms").text
    assert "fair-access policy" in terms and "seal" in terms


def test_the_filers_are_searched(client: PageClient) -> None:
    text = client.get(DATASETS, "admin", q="laboratories").text
    assert f'data-filer="{NORTHWIND}"' in text and f'data-filer="{CONTOSO}"' not in text
    assert "No filer matches" in client.get(DATASETS, "admin", q="drachma").text
    assert len(client.call_tool("read_datasets").data["filers"]) == 3


def test_the_tools_answer_what_the_pages_show(client: PageClient) -> None:
    assert {t.name for t in pages.tools} == {"read_connection", "read_datasets"}
    data = client.call_tool("read_connection").data
    assert data["mode"] == "Sample data" and data["sessions"] is None
    assert data["kept_current"] == 4 and data["per_second"] == 5
    sources = {s["source"]: s for s in data["sources"]}
    assert sources["Company submissions"]["last_release"] == "2026-11-20"
    assert sources["Ticker map"]["calls"] == 1
    read = client.call_tool("read_datasets").data
    assert [s["dataset"] for s in read["served"]] == [FILINGS]
    assert read["served"][0]["recorded"] == 11  # ten pushed, one wanted
    filers = {f["cik"]: f for f in read["filers"]}
    assert filers[NORTHWIND]["entry"] == "ZZNW" and filers[NORTHWIND]["kept_current"]
    assert filers[FABRIKAM]["entry"] == "" and filers[FABRIKAM]["kept_current"]
    assert filers[CONTOSO]["latest_form"] == "8-K"
    assert read["wants"][0]["want_id"] == "w-standing"
    page = client.get(DATASETS, "admin", view="filers").text
    assert all(f["company_id"] in page for f in read["filers"])


def test_a_missing_or_malformed_user_agent_is_named(tmp_path: Path) -> None:
    api = SyntheticApi(lambda: AT)
    api.mode = "live"
    work = feed(tmp_path, lake(), api=api, waiting="names no contact email address")
    hold(work)
    client = PageClient(pages)
    text = client.get(CONNECTION, "admin").text
    assert "Waiting: edgar_user_agent names no contact email address" in text
    assert "Waiting for edgar_user_agent" in text
    data = client.call_tool("read_connection").data
    assert data["mode"] == "No key"
    assert data["waiting"] == "edgar_user_agent names no contact email address"
    assert data["credentials"] == [{"label": "User-Agent", "set": True}]
    said = figures(work.status, work)
    assert said[0].value == "Waiting for edgar_user_agent" and said[0].state == "warn"
    assert said[0].why == "edgar_user_agent names no contact email address"
    assert said[1].value == "0 of 1 datasets: edgar_user_agent names no contact email address"
    unset = feed(tmp_path, lake(), api=api, waiting="is not set")
    hold(unset)
    data = PageClient(pages).call_tool("read_connection").data
    assert data["credentials"] == [{"label": "User-Agent", "set": False}]


def test_the_user_agent_is_never_shown(tmp_path: Path) -> None:
    work = feed(tmp_path, watchlist=[CONTOSO])
    asyncio.run(work.check())
    hold(work)
    client = PageClient(pages)
    for path in (CONNECTION, DATASETS):
        assert USER_AGENT not in client.get(path, "admin").text
    assert USER_AGENT not in str(client.call_tool("read_connection").json)


def test_before_the_first_check() -> None:
    page_module._held.clear()
    client = PageClient(pages)
    assert "Waiting for edgar_user_agent" in client.get(CONNECTION, "admin").text
    assert "No filer read yet" in client.get(DATASETS, "admin", view="filers").text
    assert "No wants yet" in client.get(DATASETS, "admin").text


def test_the_figures_are_the_data_roles_in_its_order(client: PageClient) -> None:
    work = page_module._held["feed"]
    said = figures(work.status, work)
    assert [f.label for f in said] == [
        "Connection",
        "Entitled at the vendor",
        "Stream",
        "Last recorded",
        "Rate use",
    ]
    assert said[1].value == "1 of 1 datasets" and said[2].value == "Does not stream"
    assert said[4].value == "at most 5 of 10 a second"

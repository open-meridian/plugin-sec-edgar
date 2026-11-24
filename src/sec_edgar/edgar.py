"""SEC EDGAR's public JSON, and its stand-in.

Three kinds of request are made, and nothing else, each as JSON:

- `https://data.sec.gov/submissions/CIK##########.json` -- a company's
  submissions: its name, tickers and former names, and its most recent
  filings (about a year's, or the last thousand), each with its accession
  number, form, filing date, report date, acceptance time and items;
- `https://data.sec.gov/submissions/<name>.json` -- one of the older pages
  that answer names under `filings.files`, each with the filings between two
  dates, read only when a reader asks for days before the recent ones;
- `https://www.sec.gov/files/company_tickers.json` -- the tickers SEC maps to
  CIKs, read when the watchlist names a ticker, once a day.

**Who is asking.** SEC asks every automated client to declare a User-Agent
naming its company and a contact address. The plugin sends the
`edgar_user_agent` setting as it is, and asks nothing while it is missing or
malformed (`check_user_agent`). It is a deployment's own contact, so it is
never logged or kept with an answer.

**How fast.** Every request waits for its slot (limits.py): at most the
setting's rate, never more than SEC's 10 a second, and paused after a 429 or
a 403.

`SyntheticApi` answers from the responses committed under responses/
(responses/index.json): three fictitious companies' submissions and the
ticker map, in EDGAR's own layout, so the tests and sample data run offline
and the same on any day.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources
from typing import Any, Protocol

from .limits import Limiter, retry_after

DATA = "https://data.sec.gov"
WWW = "https://www.sec.gov"
TICKERS = "/files/company_tickers.json"
TIMEOUT = 60.0
#: The most of an answer read: a large filer's submissions run to a few MB.
MOST_BYTES = 32 * 1024 * 1024
#: The longest User-Agent sent.
MOST_USER_AGENT = 200

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def submissions_path(cik: str) -> str:
    return f"/submissions/CIK{cik}.json"


def page_path(name: str) -> str:
    """One older page of a company's submissions, by the name EDGAR gives it."""
    if not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", name):
        raise ValueError(f"{name!r} is not a submissions page")
    return f"/submissions/{name}"


def check_user_agent(text: str) -> str:
    """Why a User-Agent will not do, or empty where it will: SEC asks for a
    company or person's name and a contact address, as
    `Example Co admin@example.com`, in plain ASCII."""
    said = text.strip()
    if not said:
        return "is not set"
    if len(said) > MOST_USER_AGENT:
        return f"is longer than {MOST_USER_AGENT} characters"
    if any(not (" " <= c <= "~") for c in said):
        return "holds characters other than plain ASCII"
    email = _EMAIL.search(said)
    if email is None:
        return "names no contact email address"
    named = (said[: email.start()] + said[email.end() :]).strip()
    if not re.search(r"[A-Za-z]", named):
        return "names no company or person beside the address"
    return ""


class Unreachable(Exception):  # noqa: N818 - what SEC was
    """SEC could not be asked: no answer, or not in time."""


@dataclass(frozen=True)
class Fetched:
    """One answer of SEC's, as received."""

    url: str
    status: int
    body: bytes
    fetched_at: datetime
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def path(self) -> str:
        return self.url.removeprefix(DATA).removeprefix(WWW)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        """The answer's JSON object; empty where it holds none."""
        try:
            read = json.loads(self.body)
        except ValueError:
            return {}
        return read if isinstance(read, dict) else {}

    @property
    def error(self) -> str:
        if self.status == 403:
            return (
                f"{self.url} answered 403: SEC refuses an undeclared or over-eager client; "
                "check edgar_user_agent and edgar_requests_per_second"
            )
        if self.status == 429:
            return f"{self.url} answered 429: too many requests; paused"
        return f"{self.url} answered {self.status}"


class Api(Protocol):
    mode: str
    limiter: Limiter

    async def get(self, url: str) -> Fetched: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


class LiveApi:
    """SEC itself, asked as `user_agent`, paced by `limiter`."""

    mode = "live"

    def __init__(
        self, user_agent: str, limiter: Limiter, now: Callable[[], datetime] = utc_now
    ) -> None:
        self._user_agent = user_agent.strip()
        self.limiter = limiter
        self._now = now

    async def get(self, url: str) -> Fetched:
        await self.limiter.wait()
        got = await asyncio.to_thread(self._get, url)
        self.limiter.answered(got.status, retry_after(got.headers.get("retry-after")))
        return got

    def _get(self, url: str) -> Fetched:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310 - SEC's https addresses
                body = answer.read(MOST_BYTES + 1)
                status = answer.status
                headers = {k.lower(): v for k, v in answer.headers.items()}
        except urllib.error.HTTPError as refused:
            body = refused.read(MOST_BYTES + 1) if refused.fp else b""
            status = refused.code
            headers = {k.lower(): v for k, v in (refused.headers or {}).items()}
        except (urllib.error.URLError, TimeoutError, OSError) as failed:
            reason = getattr(failed, "reason", failed)
            raise Unreachable(f"{url}: {type(reason).__name__}") from failed
        if len(body) > MOST_BYTES:
            raise Unreachable(f"{url}: answered more than {MOST_BYTES} bytes")
        if headers.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        return Fetched(url, status, body, self._now(), headers)


class SyntheticApi:
    """The responses committed under responses/: each address answered as
    its file says, anything else 404 as EDGAR answers a CIK it does not hold."""

    mode = "synthetic"

    def __init__(self, now: Callable[[], datetime] = utc_now) -> None:
        self._now = now
        self.limiter = Limiter()
        held = resources.files(__package__).joinpath("responses")
        index = json.loads(held.joinpath("index.json").read_text(encoding="utf-8"))
        self.answers: dict[str, Any] = {
            url: json.loads(held.joinpath(name).read_text(encoding="utf-8"))
            for url, name in index["answers"].items()
        }
        self.asked: list[str] = []

    async def get(self, url: str) -> Fetched:
        self.asked.append(url)
        at = self._now()
        if url not in self.answers:
            return Fetched(url, 404, b"<Error><Code>NoSuchKey</Code></Error>", at)
        return Fetched(url, 200, json.dumps(self.answers[url]).encode(), at)


def api(
    synthetic: bool, user_agent: str, limiter: Limiter, now: Callable[[], datetime] = utc_now
) -> Api:
    return SyntheticApi(now) if synthetic else LiveApi(user_agent, limiter, now)

"""Record real EDGAR responses to replace or add to the committed ones.

Run by hand, on a machine that reaches SEC, never in CI:

    python tools/record.py "Your Co you@your.co" 0000320193 0000789019

with the User-Agent SEC asks for (yours, not a colleague's) and the CIKs to
record. It writes each company's submissions, and the ticker map, to
src/sec_edgar/responses/, one request a second, and prints the lines to add
to responses/index.json's "answers". Read what it wrote before committing:
the tests assert on the committed companies' filings, so a new recording
means new expectations.
"""

from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.request
from pathlib import Path

DATA = "https://data.sec.gov"
WWW = "https://www.sec.gov"
OUT = Path(__file__).resolve().parent.parent / "src" / "sec_edgar" / "responses"


def get(url: str, agent: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - SEC's https addresses
        body = answer.read()
        if answer.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    time.sleep(1.0)
    return json.loads(body)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or "@" not in argv[0]:
        print(__doc__, file=sys.stderr)
        return 2
    agent, ciks = argv[0], [c.zfill(10) for c in argv[1:]]
    answers: dict[str, str] = {}
    for cik in ciks:
        name = f"CIK{cik}.json"
        url = f"{DATA}/submissions/{name}"
        (OUT / name).write_text(json.dumps(get(url, agent), indent=1) + "\n")
        answers[url] = name
    tickers = get(f"{WWW}/files/company_tickers.json", agent)
    (OUT / "company_tickers.json").write_text(json.dumps(tickers) + "\n")
    answers[f"{WWW}/files/company_tickers.json"] = "company_tickers.json"
    print(json.dumps(answers, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

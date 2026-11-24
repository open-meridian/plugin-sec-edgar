# SEC EDGAR plugin

An [Open Meridian](https://github.com/open-meridian) data plugin that records
the filings companies make with the U.S. Securities and Exchange Commission
into a deployment's lake, read from EDGAR's public JSON.

- **One dataset, `edgar_filings`:** each filing's accession number, form,
  kind of report, filing date, period, 8-K items and acceptance time, against
  the company it names, found by its CIK.
- **A watchlist** of CIKs or tickers whose filings are recorded as they
  arrive; any other company's are fetched when a reader asks.
- **Polite to SEC:** it sends the User-Agent you set and asks nothing
  without one, keeps to the rate you set (never above SEC's 10 requests a
  second), and pauses when SEC refuses.
- **Traceable:** every row names the EDGAR response it was read from, kept
  in the plugin's storage.

It shows no filing on its own pages, which show its connection and its
dataset. What it may publish and read comes from the role `pyproject.toml`
declares, `data`, once a deployment admin approves it.

## Use it

    meridian plugin upload
    meridian plugin launch sec-edgar 0.1.0 --instance sec-edgar

Then, in the dashboard: set **User-Agent** (`Example Co admin@example.com`,
your own), optionally the rate and the watchlist; license
`sec-edgar:edgar_filings` on **Data sources**; and entitle the plugins that
read it. [docs/setup.md](docs/setup.md) walks through each step.

## Develop it

    pip install -e '.[dev]'
    python -m pytest
    meridian plugin check --verified --run-tests

The tests run offline against EDGAR responses committed under
`src/sec_edgar/responses/`; nothing in the tests or CI calls SEC. With the
**Sample data** setting on, a development deployment runs on the same
responses. `make ci-local` runs lint, the tests, the plugin check and the
image in containers.

| Module | What it does |
|---|---|
| `edgar.py` | EDGAR's three requests, and the committed stand-in |
| `limits.py` | the request pace and the pause after a refusal |
| `feed.py` | turns submissions into filings, the watchlist, readers' wants |
| `raw.py` | EDGAR's answers as received, and their window |
| `settings.py`, `declared.py` | the settings and the dataset's declaration |
| `page.py`, `records.py`, `templates/` | the Connection and Datasets pages, and their tools |

`AGENTS.md` is for coding agents working on the plugin.

## Licence

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). Not affiliated with
or endorsed by the U.S. Securities and Exchange Commission.

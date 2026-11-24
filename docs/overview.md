# Overview

This plugin records the filings companies make with the U.S. Securities and
Exchange Commission into your deployment's lake, read from EDGAR's public
JSON. It is for anyone at your firm who reads filings: a research page, a
calendar of reports, an agent following a company's disclosures.

## What it records

One dataset, `edgar_filings`. Each row is one filing, as EDGAR lists it:

- the company that filed it, found in your deployment by its Central Index
  Key (CIK), SEC's number for every filer;
- its accession number, EDGAR's own identifier, which is also the row's key;
- its form as filed (10-K, 10-Q, 8-K, DEF 14A, S-1 and the rest), and the
  kind of report the form is: annual, quarterly, current, proxy,
  registration, ownership, holdings, beneficial ownership, or other;
- the date it was filed, the period it reports on, and an 8-K's items;
- when EDGAR accepted it, as the time it was published.

Each row names the response from EDGAR it was read from, kept in the
plugin's storage, so any filing can be traced to what SEC answered.

## How it decides what to read

- **Your watchlist** (a setting): those companies' filings are checked every
  five minutes and recorded as they arrive. A filing already recorded is not
  sent again.
- **Anything else** is fetched when a reader asks the lake for a company's
  filings. A reader asking to keep a company current is checked the same way
  as the watchlist until it stops asking.
- History reaches back to 1994, EDGAR's first year. Older pages of a
  company's filings are read only when a reader asks for those dates.

The plugin never reads your positions or accounts to choose what to follow.

## Companies, not tickers

A company is identified by its CIK. A ticker in the watchlist is turned into
a CIK with SEC's own ticker list, and only as an aid: tickers move, CIKs do
not. A company that changed its name keeps its CIK, and its former names are
shown beside the current one.

## What it does not do

- It reads filings' index entries, not the documents themselves, and no
  financial statement figures, holdings reports or dividends yet.
- It shows no filing on its own pages: those show the connection and the
  dataset. Filings are for the pages and agents that read the lake.
- It makes nothing up: a company your deployment does not hold is reported
  as a miss, and its filings are recorded without a company until it is
  added.
- It does not judge or rank filings, and generates no trading signal.

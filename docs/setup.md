# Setup

## Before launching

SEC asks every automated client to say who it is: a company or person's name
and a contact email address, sent with every request. Decide which address
SEC should write to if your deployment's requests cause a problem, such as a
shared operations inbox.

Launch the plugin and approve its one role, `data` (a data plugin).

## Settings

In the dashboard's Settings form:

- **User-Agent**, required: your name and contact address, as
  `Example Co admin@example.com`, in plain ASCII. While it is missing or
  malformed the plugin asks SEC nothing, Connection says **No key**, and the
  plugin's status names the setting and what is wrong with it.
- **Requests a second**: this plugin's share of SEC's limit of 10 requests a
  second, from 1 to 10, 5 by default. Lower it where other tools at your firm
  call SEC from the same network: SEC counts them together.
- **Watchlist**: the companies whose filings are recorded as they arrive, one
  per row, each a CIK or a ticker. Up to 500. Empty by default: any
  company's filings are still fetched when a reader asks.
- **Raw responses window** and **past the window**: how long EDGAR's answers
  are kept in the plugin's storage, ten years by default, and whether they
  are then archived, kept or deleted.
- **Sample data**, on a deployment installed for development only: a few
  fictitious companies' filings, committed with the plugin, in place of SEC.
  Runs without a User-Agent.

## Its dataset

On the deployment's **Data sources** page (deployment admins):

1. **License** `<instance>:edgar_filings`. It describes SEC's terms in words
   (see Terms) and declares no licence of its own: set one, with a note
   saying why. Until it is set, the lake keeps the rows and reads every use
   restrictively.
2. **Entitle** each plugin that reads filings.

## The companies

Each filing is recorded against the company your deployment holds under its
CIK. The Datasets page's **Filers** tab shows each company read, its CIK,
its former names and the record it resolved to, or **not held** where your
deployment does not have it yet. Add the company, and the next check
records its filings against it.

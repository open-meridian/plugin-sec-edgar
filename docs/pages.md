# Pages

Both pages are the data role's, the same on every data plugin, under
**Manage**, for the plugin's admins. Neither shows a filing. Each is also a
read tool on the deployment's MCP, answering what the page shows, under the
same names on every data plugin.

## Connection (`read_connection`)

How the plugin reaches EDGAR, and how the last check went:

- the head's status: answering, checking, waiting for the User-Agent, not
  answering, companies not held, or watchlist entries that name no company;
- **Key:** the mode (Live, Sample data or No key), whether the User-Agent is
  set (never its value), and **Sources**, one line each for company filings
  and the ticker list, with the calls made and the last error;
- **Limits and use:** SEC's limit of 10 requests a second, the rate the
  plugin keeps, how many requests SEC refused, and when the plugin is paused
  after a refusal.

## Datasets (`read_datasets`)

What the plugin serves, in tabs, one at a time:

- **Served:** `edgar_filings` as the catalogue lists it, whether a deployment
  admin has licensed it, rows recorded and wants answered, and the lag
  between EDGAR accepting a filing and the plugin recording it;
- **Wants:** what readers have asked the lake for, and how each was
  answered;
- **Filers:** each company read, searchable by CIK, name, ticker or former
  name, with its latest filing and the record it resolved to;
- **Terms:** SEC's terms, as the dataset declares them.

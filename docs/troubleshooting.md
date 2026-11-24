# Troubleshooting

## Waiting for edgar_user_agent

The User-Agent setting is missing or malformed, so the plugin asks SEC
nothing. The status says what is wrong: not set, no contact email address,
no name beside the address, characters other than plain ASCII, or too long.
Set it in the Settings form as `Example Co admin@example.com`.

## Not answering

SEC could not be reached, or answered with an error. A 403 means SEC refused
the client: check that the User-Agent names a real contact, and lower
**Requests a second** if other tools at your firm call SEC too. A 429 means
too many requests: the plugin pauses on its own, longer each time, and
carries on when SEC lets it.

## N filers not held

Your deployment holds no company under those CIKs. Their filings are
recorded without a company until it does. The Datasets page's **Filers** tab
names each one. Add the company, and the next check records against it.

## N watchlist entries name no company

A watchlist row is not a CIK, and SEC's ticker list maps it to no company.
Correct the row, or use the company's CIK, which EDGAR shows on every
company page.

## A filing appears later than expected

EDGAR publishes a filing once it is accepted. The plugin checks the watchlist
every five minutes, so a filing can take up to that long, plus EDGAR's own
delay, to appear. The **Served** tab's lag shows how long the last ones took.

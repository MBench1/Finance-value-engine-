# Intrinsic Value Engine — full deployment

One static page + one nightly robot = a DCF workstation covering **every US-listed company** (~8,000 filers), refreshed automatically, hosted free.

## What's in this folder

```
index.html                          the complete valuation app (copy from the outputs folder)
scripts/build_data.py               turns SEC's bulk companyfacts.zip into per-ticker JSONs
.github/workflows/refresh-data.yml  runs the script nightly on GitHub's servers
data/                               (created by the workflow) AAPL.json, MSFT.json, ... + _index.json
```

## How the site decides where data comes from

When you type a ticker and click Autofill, the page tries, in order:

1. `data/TICKER.json` — the nightly pipeline output (same origin, can never be blocked)
2. The built-in 30-company snapshot library (works offline, embedded in index.html)
3. Live SEC EDGAR via probed transports (direct → your proxy → public proxies)
4. The open + paste path (always works, manual)

Deploying this repo activates path 1 for every US filer. Until then the site
still works fine on paths 2–4.

## Deploy in 5 steps (~5 minutes)

1. Create a new GitHub repository (public, so Pages is free).
2. Copy `index.html`, `scripts/`, and `.github/` into it and push.
3. **Edit one line:** in `.github/workflows/refresh-data.yml`, replace
   `your-email@example.com` with your real email (the SEC requires it as
   identification on bulk downloads — it is not an account or key).
4. Repo Settings → Pages → deploy from branch `main`, folder `/ (root)`.
5. Actions tab → "Refresh EDGAR company data" → Run workflow. First run takes
   ~10–15 minutes (the bulk file is ~1 GB; it is streamed, never extracted).
   After it commits `data/`, your site autocompletes any US ticker instantly.

From then on it refreshes itself every night at 05:30 UTC. GitHub's free tier
covers this comfortably (one ~15 minute job per day).

## What the pipeline can and cannot give you

Covered automatically: revenue, EBIT, debt, cash, shares, interest expense,
effective tax, R&D, SBC — latest fiscal year, from official XBRL filings,
with a staleness guard so discontinued tags from old years are never mixed in.

Not on EDGAR, by nature:
- **Share price** — type it, or wire a free quote API (Finnhub/Twelve Data).
- **52-week range / analyst targets** — optional inputs for the football field.
- **Industry classification** — pick it in Stage 1 (it seeds beta, target
  margin, sales-to-capital, and comps bands).

Known rough edges (by design they fail loud, not wrong): ~10–20% of filers use
custom XBRL tags or are structurally odd (banks, insurers, REITs) — those
tickers may come back partial or missing, and the site falls through to live
EDGAR or paste. Anomalous tax years are clamped and flagged in a note.

## Keeping parsers in sync

`scripts/build_data.py` is a line-for-line port of the parser inside
`index.html` (`XBRL_TAGS`, `pickAnnualDuration`, `pickLatestInstant`,
staleness guard). If you change the logic in one, change the other.

## Legal

SEC EDGAR data is public domain. The SEC asks bulk users to identify
themselves via User-Agent and stay under 10 requests/second — this pipeline
makes 2 requests per day. Reference tables inside index.html (betas, ERPs,
spreads, multiples) are labeled snapshots in the style of public Damodaran
datasets; refresh them periodically. Educational tool, not investment advice.

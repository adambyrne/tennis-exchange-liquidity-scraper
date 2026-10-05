# Tennis Betting Slip Calculator

A dependency-free, typed Python CLI for modelling tennis betting slips. It is a calculator and slip manager, not a bookmaker and it does not provide live odds.

## Features

- `Decimal`-based odds, stakes, returns, implied probability, and bookmaker margin
- Singles, accumulators, and system bets
- Validation for invalid, duplicate, and conflicting match selections
- Remove individual selections and clear slips
- Named JSON slips and CSV export
- Static odds provider with UTC update timestamps and stale-odds checks
- Deterministic win-probability simulation with an optional seed
- Optional user probability/value-bet indicator
- Extensible `OddsProvider` protocol for future integrations
- Responsible-gambling notice and optional spending/session-limit fields

## Usage

The simple interactive mode remains available:

```bash
python main.py
```

Command-oriented examples:

```bash
python main.py matches
python main.py save slip.json "Novak Djokovic" "Carlos Alcaraz" 1.80
python main.py calculate slip.json 10
```

`calculate` also writes a CSV beside the JSON file. JSON files can be loaded with
`tennis_betting.storage.load_slip`; the Python modules are intentionally
dependency-free and suitable for embedding.

## Exchange liquidity scraper

The scraper collects live public tennis match markets from Polymarket and
Kalshi without accounts or credentials:

```bash
python main.py scrape --once --db liquidity.sqlite3
python main.py export-liquidity --db liquidity.sqlite3 liquidity.csv
python main.py compare-liquidity --db liquidity.sqlite3 tennis-comparison.csv
python main.py ui --db liquidity.sqlite3
```

The default `all` provider collects from both venues. Select one explicitly
with `--provider polymarket` or `--provider kalshi`; use `--max-events N` to
cap a collection run while testing. Polymarket pages active tennis events and
reads one match-winner outcome book, which supplies the normalized two-sided
liquidity without a redundant fetch of its complementary outcome. Kalshi discovers open tennis match series and reads the public YES/NO order book for each event's canonical player-winner
market. Kalshi matched notional
is calculated from every public trade page for both player-winner markets,
summing executed contract count multiplied by the trade price for the traded
outcome. This produces an actual USD notional rather than estimating from the
latest price. The Kalshi public market-data endpoints used here do not require
API credentials. Neither adapter places orders. Each snapshot preserves
provider/event/market IDs, competitors, start and observation timestamps,
automated competition grade, pre-match/in-play phase, visible liquidity,
matched volume, currency, and raw provenance. SQLite is the local-first
queryable database. Parquet is available when the optional `pyarrow` package is
installed:

```bash
python main.py export-liquidity --format parquet --db liquidity.sqlite3 liquidity.parquet
```

The normal collection cadence is ten minutes:

```bash
python main.py scrape --db liquidity.sqlite3
```

`--live` remains accepted for backwards compatibility but is no longer needed.
Previous built-in fixture data has been removed; when the database is opened,
old rows marked `fixture://sample` are automatically deleted. Betfair live
transport is not enabled:

```bash
python main.py scrape --provider kalshi --once --db liquidity.sqlite3
python main.py compare-liquidity --db liquidity.sqlite3 tennis-comparison.csv
```

Each successful scrape atomically replaces the previous snapshot set in
`liquidity.sqlite3`; it does not append old runs. CSV export reads that current
set and overwrites the destination CSV file. A failed provider request leaves
the last complete set in place. The one-shot scrape summary reports separate
Polymarket and Kalshi counts so a venue returning no events is visible. Provider
discovery runs concurrently, and independent order-book requests use up to
eight workers per venue to reduce collection time. Kalshi discovery concurrency
is capped at four, and transient rate limits are retried.

`compare-liquidity` compares the latest stored snapshot for each market and
exports only one-to-one, unambiguous cross-venue matches. Matching uses both
competitors (order-independent) and a 36-hour start-time window; similar names
or ambiguous duplicate fixtures are left out rather than guessed. The UI and
CSV compare matched notional in USD on both venues. Polymarket supplies
provider-reported market volume in USD; Kalshi notional is derived from the
complete paginated public trade history for the two player-winner markets.
Older locally stored Kalshi snapshots remain in SQLite but are excluded from
comparisons until the next scrape, because their stored contract counts cannot
be safely converted into historical dollar notional.
Expandable UI rows separately show current order-book depth:
Polymarket bids plus asks from outcome books and Kalshi YES/NO bid levels
(price multiplied by contract quantity). This is resting depth, not traded
volume, executable profit, or a guarantee that liquidity is available at one
price.

The `ui` command starts a small dependency-free local dashboard at
`http://127.0.0.1:8000`. Open that address in a browser and use **Refresh data**
to run both providers and refresh the comparison table. The dashboard shows
the last update time, match count, and a colored leader indicator. Switch
between **Matched Amount** and **Order Book Depth** without losing the current
filters or sort. Matched amount compares USD notional on both venues. Order-book
depth uses displayed USD notional on both venues. Filter by tournament type
and match status (pre-match, in-play, or both); both summary tables and the
results update together. The tournament summary shows leader percentages by
type and an aggregate total. The liquidity-range summary groups matches by combined
amount in the active view (<5k, 5k-25k, 25k-100k, and 100k+) and shows counts
and leader percentages. Zero Liquidity % counts matches where either platform
has no liquidity; positive-liquidity ties are split evenly between platform
shares. Expand a liquidity range to see its grade-level match counts and
platform percentages. The tournament summary includes the average combined
Polymarket and Kalshi amount per match, formatted in USD, with the Total row
calculated across all filtered matches. Expanded market
rows also switch between matched
market amounts and order-book depth; Polymarket matched volume is the market
total shared across its outcome tokens. Older snapshots without per-market
detail show their stored aggregate depth as a fallback.
The view switch includes a short description of each data mode and sits beside
**Refresh data**; tournament and status controls
are grouped with a reset action, followed by the two summary cards. Match rows
show tournament/status badges and can be expanded to compare venue-specific
market details. Refreshing uses skeleton rows and a completion indicator.
Doubles teams are matched as pairs, including abbreviated
Polymarket names, and Kalshi ATP Challenger series are included even when the
series title omits the word "match". Use `--host` or `--port` if needed.
Stop it with `Ctrl+C`.

### Public dashboard hosting

The repository includes a GitHub Actions workflow that scrapes both public
providers, builds a static dashboard, and deploys it to GitHub Pages when
manually started from the dashboard or repository's Actions tab. The hosted
page is public and requires no local Python process. To enable direct refresh
from the page, deploy the authenticated Cloudflare Worker in `refresh_worker/`
and set the repository Actions variable `DASHBOARD_REFRESH_API_URL` to its
`workers.dev` URL. The one-time setup requires a Cloudflare account, a KV
namespace, and a GitHub App installed on this repository with **Actions: Read
and write** permission. Create the KV namespace and deploy the Worker:

```bash
npx wrangler kv namespace create SESSIONS --config refresh_worker/wrangler.toml
# Copy the returned namespace ID into refresh_worker/wrangler.toml.
npx wrangler deploy --config refresh_worker/wrangler.toml
```

Set the GitHub App's OAuth callback URL to `https://<worker-host>/auth/callback`,
then save the App's client ID and client secret as Worker secrets:

```bash
npx wrangler secret put GITHUB_APP_CLIENT_ID --config refresh_worker/wrangler.toml
npx wrangler secret put GITHUB_APP_CLIENT_SECRET --config refresh_worker/wrangler.toml
```

Add the Worker URL under repository **Settings > Secrets and variables >
Actions > Variables** as `DASHBOARD_REFRESH_API_URL`, then run the publishing
workflow once to publish the configured UI. **Refresh data** opens a GitHub
sign-in popup, starts the scrape directly, shows progress while GitHub Actions
runs, and reloads results/history after successful deployment. Each person
triggering a scrape must sign in with a GitHub account that has write access to
this repository. The GitHub token stays in the Worker and is never sent to the
browser; the browser receives only a short-lived opaque session token. Do not
put GitHub credentials or tokens in Pages files or repository variables.
Without the Worker URL configured, the button falls back to opening the Actions
workflow page. No periodic scrape or automatic browser polling is configured,
so data remains at the latest successful refresh until a user triggers another
run.
The **Historical Data** tab contains the **Performance History** and
**Betting Activity by Time Window** tables. Performance History stores the last
100 successful refreshes in the published site. Each record retains its full
matched-result snapshot and separate Matched Amount and Order Book Depth
tournament and liquidity-range breakdowns, including platform leader
percentages and match counts. History rows also show overall and per-grade
average combined liquidity in USD for each view. Older snapshots are upgraded from their saved results
when the next history record is published. Switch the active data view to
inspect that view's history; sort by
refresh number, timestamp, leader share, or match count, and expand a row to
review its tournament and range details. Platform percentages are the share of
matches led by that venue; ties remain in the denominator but count as a win
for neither platform. A highlighted Total row reports the number of refreshes
and the average platform leader shares and match count, plus match-weighted
overall and per-grade liquidity averages for the active view.
The **Historical Liquidity Range** table records each refresh's match counts
and Polymarket, Kalshi, and zero-liquidity shares across the four liquidity
ranges. Expand a refresh or the Total row to inspect its range breakdown;
the Total pools match snapshots across retained refreshes. Matches with zero
liquidity on either platform count as zero-liquidity, while positive ties are
split evenly between Polymarket and Kalshi. The table follows the active
Matched Amount or Order Book Depth view.
The **Historical Grade Liquidity Comparison** table reports per-refresh
average Polymarket and Kalshi liquidity for each competition grade, along
with their difference and leader. It follows the selected Matched Amount or
Order Book Depth view; its Total row is match-weighted across all grade and
refresh observations. Grade averages are derived from the saved result
snapshots so the history can be rebuilt when the dashboard is published.
**Betting Activity by Time Window** tracks positive increases in
provider-reported matched volume between successive successful refreshes,
grouped by competition grade and time remaining until scheduled start. The scheduled start time is the
classification source: the "In-Play" bucket means that scheduled start has
passed, not that a live score/status was independently verified. This avoids
assigning a future match to In-Play merely because one exchange reports a live
phase inconsistent with the other exchange's schedule. The first observation
of each match establishes a baseline; it is not treated as new
activity because its cumulative volume may have accrued before tracking began.
Each increment is assigned to the bucket at the later observation, so long gaps
between refreshes can blur the exact timing of activity. Records without a
scheduled start time and volume decreases are excluded. The table aggregates
activity in retained history, while each history row's Details shows that
refresh's grade-by-period USD increments.
Pushes that change the workflow or scraper code also run the publishing
workflow. GitHub Pages is enabled by the workflow when repository policy
permits; if Pages is restricted, an administrator must allow Pages
deployments from GitHub Actions. The public URL appears in the workflow's
`github-pages` deployment environment.

The hosted site displays the most recent successful scrape. A failed scrape
does not publish an empty replacement site. Public access to market data is
subject to Polymarket and Kalshi availability and rate limits.

If Python reports a local certificate verification error on Windows, update the
certificate bundle used by the adapter:

```bash
python -m pip install --upgrade certifi
```

Because each successful scrape replaces the previous snapshot set, this mode
does not build a historical time series. Kalshi market availability, API rate
limits, and service access can vary by location and exchange policy. Betfair's
Exchange API requires an authenticated client and is not enabled.

Polymarket `grade` uses the event's official sport/series metadata, with
tournament-name rules for ITF circuit codes such as `M25` and `W50`.
`market_name` describes the selected market type (`Match Winner`), not the CLOB
API used to retrieve its order book. On database open, existing Polymarket rows
with the old generic market label are updated, as are unknown grades that can
be inferred from the stored tournament name. Rows that lack enough stored
metadata are corrected as new snapshots are collected.

Classification uses provider/event-name rules for Grand Slam, ATP, WTA, ATP
Challenger, ITF, and UTR. The `classification_overrides` table is the manual
exception point. Matching is deterministic and conservative: mismatched times,
low confidence, or ambiguous competitor matches remain unlinked. A future
backfill client should implement the same provider interface over each venue's
historical endpoint, page by time window, and insert observations through the
same SQLite writer; this version does not fabricate or backfill history.

## Tests

Run:

```bash
python -m unittest discover -v
```

Please gamble responsibly: never bet more than you can afford to lose.

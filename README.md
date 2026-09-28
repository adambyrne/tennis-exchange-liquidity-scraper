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
liquidity without a redundant fetch of its complementary outcome. Kalshi
discovers open tennis match series and reads the public YES/NO order book for
each event's canonical player-winner market. The Kalshi public market-data
endpoints used here do not require API credentials. Neither adapter places
orders. Each snapshot preserves
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
CSV compare provider-reported matched volume. Polymarket reports
market volume in USD, while Kalshi reports volume in contracts; these native
units are not directly comparable, so relative leaders and win percentages are
indicative only. Expandable UI rows separately show current order-book depth:
Polymarket bids plus asks from outcome books and Kalshi YES/NO bid levels
(price multiplied by contract quantity). This is resting depth, not traded
volume, executable profit, or a guarantee that liquidity is available at one
price.

The `ui` command starts a small dependency-free local dashboard at
`http://127.0.0.1:8000`. Open that address in a browser and use **Refresh data**
to run both providers and refresh the comparison table. The dashboard shows
the last update time, match count, provider-reported matched volume, and a
colored leader indicator. Since the venues report different units (USD versus
contracts), volume comparisons are indicative rather than currency-normalized.
Results default to highest Polymarket-reported volume; sortable columns can be
changed by clicking their headers. Filter by tournament type and match status
(pre-match, in-play, or both); the summary table and results update together.
The summary breaks out reported-volume leaders by tournament type and includes
an aggregate total row with visual progress bars. Expand a match row to compare
current Polymarket outcome-book and Kalshi player-winner order-book depth.
Older snapshots without per-market detail show their stored aggregate depth as
a fallback. Doubles teams are matched as pairs, including abbreviated
Polymarket names, and Kalshi ATP Challenger series are included even when the
series title omits the word "match". Use `--host` or `--port` if needed.
Stop it with `Ctrl+C`.

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

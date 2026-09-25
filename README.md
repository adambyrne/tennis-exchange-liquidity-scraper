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

The scraper collects live public Polymarket tennis match markets without
accounts or credentials:

```bash
python main.py scrape --once --db liquidity.sqlite3
python main.py export-liquidity --db liquidity.sqlite3 liquidity.csv
```

The collector pages through active tennis events and records the match-winner
market for each event, rather than stopping after the first 100 child markets
or collecting futures and side markets. It reads both outcome order books;
active events without an available CLOB order book are skipped. Each snapshot
preserves provider/event/market IDs, competitors, start
and observation timestamps, automated competition grade, pre-match/in-play
phase, available back and unmatched liquidity, matched volume, currency, raw
provenance, and optional cross-venue match metadata. SQLite is the local-first
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
Polymarket market discovery and CLOB order books are public. Previous built-in
fixture data has been removed; when the database is opened, old rows marked
`fixture://sample` are automatically deleted. Betfair and Kalshi live
transport is not enabled:

```bash
python main.py scrape --live --provider polymarket --once --db liquidity.sqlite3
python main.py export-liquidity --db liquidity.sqlite3 polymarket.csv
```

If Python reports a local certificate verification error on Windows, update the
certificate bundle used by the adapter:

```bash
python -m pip install --upgrade certifi
```

The adapter stores each observation locally. Re-running it builds your own
historical series; it does not fabricate past order-book data. Betfair's
Exchange API and Kalshi's Trade
API have different authentication, market semantics, rate limits, and terms; configure credentials
only after reviewing the current provider documentation and terms. The adapters
fail explicitly rather than making an unauthenticated request. The environment
names reserved for future clients are `BETFAIR_APP_KEY` and `KALSHI_API_KEY`.

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

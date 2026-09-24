from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .models import BetType, LiquiditySnapshot, Selection, Slip

SCHEMA = """
CREATE TABLE IF NOT EXISTS liquidity_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, source_event_id TEXT NOT NULL,
 source_market_id TEXT NOT NULL, event_name TEXT NOT NULL, market_name TEXT NOT NULL,
 competitor_names TEXT NOT NULL, start_time TEXT NOT NULL, observed_at TEXT NOT NULL,
 grade TEXT NOT NULL, phase TEXT NOT NULL, available_back NUMERIC NOT NULL,
 available_unmatched NUMERIC NOT NULL, matched_volume NUMERIC NOT NULL, currency TEXT NOT NULL,
 source_url TEXT, match_key TEXT, match_confidence NUMERIC, raw_json TEXT NOT NULL,
 UNIQUE(provider, source_market_id, observed_at)
);
CREATE TABLE IF NOT EXISTS classification_overrides (
 event_key TEXT PRIMARY KEY, grade TEXT NOT NULL, reason TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_liquidity_event_time ON liquidity_snapshots(event_name, observed_at);
CREATE INDEX IF NOT EXISTS idx_liquidity_provider_phase ON liquidity_snapshots(provider, phase, observed_at);
"""


def connect_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def save_snapshots(connection: sqlite3.Connection, snapshots: list[LiquiditySnapshot]) -> int:
    connection.executemany(
        """INSERT OR IGNORE INTO liquidity_snapshots
        (provider, source_event_id, source_market_id, event_name, market_name, competitor_names,
         start_time, observed_at, grade, phase, available_back, available_unmatched, matched_volume,
         currency, source_url, match_key, match_confidence, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(
            item.provider, item.source_event_id, item.source_market_id, item.event_name, item.market_name,
            json.dumps(item.competitor_names), item.start_time.isoformat(), item.observed_at.isoformat(),
            item.grade.value, item.phase.value, str(item.available_back), str(item.available_unmatched),
            str(item.matched_volume), item.currency, item.source_url, item.match_key,
            str(item.match_confidence) if item.match_confidence is not None else None, json.dumps(item.raw),
        ) for item in snapshots],
    )
    connection.commit()
    return connection.execute("SELECT changes()").fetchone()[0]


def export_liquidity_csv(connection: sqlite3.Connection, path: str | Path) -> None:
    cursor = connection.execute("SELECT * FROM liquidity_snapshots ORDER BY observed_at")
    rows = cursor.fetchall()
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([column[0] for column in cursor.description])
        writer.writerows(tuple(row) for row in rows)


def export_liquidity_parquet(connection: sqlite3.Connection, path: str | Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("Parquet export requires optional dependency: pip install pyarrow") from error
    rows = connection.execute("SELECT * FROM liquidity_snapshots ORDER BY observed_at").fetchall()
    table = pa.Table.from_pylist([dict(row) for row in rows])
    pq.write_table(table, path)


def _json(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BetType):
        return value.value
    return value


def save_slip(slip: Slip, path: str | Path) -> None:
    data = asdict(slip)
    Path(path).write_text(json.dumps(data, default=_json, indent=2), encoding="utf-8")


def load_slip(path: str | Path) -> Slip:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["bet_type"] = BetType(data.get("bet_type", "accumulator"))
    data["stake"] = Decimal(data.get("stake", "0"))
    data["selections"] = [Selection(**item) for item in data.get("selections", [])]
    if data.get("spending_limit") is not None:
        data["spending_limit"] = Decimal(data["spending_limit"])
    data.pop("created_at", None)
    return Slip(**data)


def export_csv(slip: Slip, path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["match_id", "player", "opponent", "odds"])
        writer.writeheader()
        writer.writerows({k: str(getattr(s, k)) for k in writer.fieldnames} for s in slip.selections)

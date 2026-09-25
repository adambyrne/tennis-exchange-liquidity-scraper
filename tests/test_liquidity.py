import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from tennis_betting.classification import classify_event
from tennis_betting.matching import link_match
from tennis_betting.models import CompetitionGrade, Phase
from tennis_betting.normalization import normalize_snapshot
from tennis_betting.providers import (
    FixtureLiquidityProvider,
    PolymarketNotFoundError,
    PolymarketPublicLiquidityProvider,
    ProviderError,
)
from tennis_betting.scraper import collect_once
from tennis_betting.storage import connect_database, export_liquidity_csv, save_snapshots


class LiquidityTests(unittest.TestCase):
    def test_classification_and_normalization(self):
        now = datetime.now(timezone.utc)
        item = normalize_snapshot({
            "event_id": "e", "market_id": "m", "event_name": "ATP Challenger Lyon",
            "competitors": ["A", "B"], "start_time": now.isoformat(),
            "available_back": "12.5", "matched_volume": "99",
        }, "betfair", now)
        self.assertEqual(item.grade, CompetitionGrade.ATP_CHALLENGER)
        self.assertEqual(item.phase, Phase.IN_PLAY)
        self.assertEqual(classify_event("The Championships"), CompetitionGrade.UNKNOWN)

    def test_match_link_is_conservative(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = link_match(("Alex Example", "Ben Sample"), start, [
            ("bf-1", ("Alex Example", "Ben Sample"), start),
        ])
        self.assertEqual(result.key, "bf-1")
        self.assertIsNone(link_match(("Alex", "Other"), start, []).key)

    def test_fixture_collection_and_csv_export(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            snapshots = collect_once([FixtureLiquidityProvider("betfair")], connection)
            self.assertEqual(len(snapshots), 2)
            output = Path(directory) / "liquidity.csv"
            export_liquidity_csv(connection, output)
            self.assertIn("source_market_id", output.read_text(encoding="utf-8"))
            connection.close()

    def test_snapshot_raw_metadata_serializes_decimal_values(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "liquidity.sqlite3")
            snapshot = FixtureLiquidityProvider("betfair").snapshots()[0]
            snapshot = replace(snapshot, raw={
                "order_book": {"price": Decimal("0.123456789"), "size": Decimal("12.50")}
            })
            self.assertEqual(save_snapshots(connection, [snapshot]), 1)
            raw_json = connection.execute(
                "SELECT raw_json FROM liquidity_snapshots WHERE source_market_id = ?",
                (snapshot.source_market_id,),
            ).fetchone()[0]
            self.assertIn('"price": "0.123456789"', raw_json)
            self.assertIn('"size": "12.50"', raw_json)
            connection.close()

    def test_live_adapter_requires_credentials(self):
        from tennis_betting.providers import BetfairLiquidityProvider
        with self.assertRaises(ProviderError):
            BetfairLiquidityProvider().snapshots()

    def test_public_polymarket_adapter_normalizes_market_and_book(self):
        provider = PolymarketPublicLiquidityProvider(max_markets=1)
        provider._get_json = lambda url: (
            [{"id": "event-1", "title": "ATP Tennis",
              "markets": [{"id": "market-1", "conditionId": "condition-1",
              "question": "Player A vs Player B", "slug": "tennis-player-a-vs-player-b",
              "startDate": "2026-09-25T12:00:00Z", "clobTokenIds": '["token-1"]',
              "volume": "123.45"}]}]
            if "gamma-api" in url else
            {"bids": [{"price": "0.50", "size": "10"}],
             "asks": [{"price": "0.60", "size": "8"}]}
        )
        snapshots = provider.snapshots(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source_market_id, "market-1")
        self.assertEqual(snapshots[0].available_back, 5)
        self.assertEqual(snapshots[0].available_unmatched, 8)

    def test_public_polymarket_skips_markets_without_order_books(self):
        provider = PolymarketPublicLiquidityProvider(max_markets=2)

        def get_json(url):
            if "gamma-api" in url:
                return [{"id": "event-1", "title": "Tennis",
                         "markets": [
                             {"id": "no-book", "question": "Tennis: unavailable", "clobTokenIds": '["missing"]'},
                             {"id": "has-book", "question": "Tennis: available", "clobTokenIds": '["available"]'},
                         ]}]
            if "token_id=missing" in url:
                raise PolymarketNotFoundError("no order book")
            return {"bids": [{"price": "0.50", "size": "10"}],
                    "asks": [{"price": "0.60", "size": "8"}]}

        provider._get_json = get_json
        snapshots = provider.snapshots(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source_market_id, "has-book")


if __name__ == "__main__":
    unittest.main()

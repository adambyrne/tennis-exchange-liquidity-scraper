import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tennis_betting.classification import classify_event
from tennis_betting.matching import link_match
from tennis_betting.models import CompetitionGrade, Phase
from tennis_betting.normalization import normalize_snapshot
from tennis_betting.providers import FixtureLiquidityProvider, ProviderError
from tennis_betting.scraper import collect_once
from tennis_betting.storage import connect_database, export_liquidity_csv


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

    def test_live_adapter_requires_credentials(self):
        from tennis_betting.providers import BetfairLiquidityProvider
        with self.assertRaises(ProviderError):
            BetfairLiquidityProvider().snapshots()


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from tennis_betting.cli import build_parser, main
from tennis_betting.classification import classify_event
from tennis_betting.matching import link_match
from tennis_betting.models import CompetitionGrade, Phase
from tennis_betting.normalization import normalize_snapshot
from tennis_betting.providers import (
    PolymarketNotFoundError,
    PolymarketPublicLiquidityProvider,
    ProviderError,
)
from tennis_betting.scraper import collect_once
from tennis_betting.storage import connect_database, export_liquidity_csv, save_snapshots


def test_snapshot(source_market_id="test-market", source_url=None):
    now = datetime.now(timezone.utc)
    return normalize_snapshot({
        "event_id": "test-event",
        "market_id": source_market_id,
        "event_name": "ATP test match",
        "competitors": ["Player One", "Player Two"],
        "start_time": now.isoformat(),
        "source_url": source_url,
    }, "test-provider", now)


class TestSnapshotProvider:
    name = "test-provider"

    def snapshots(self, observed_at=None):
        return [test_snapshot()]


class LiquidityTests(unittest.TestCase):
    def test_scrape_defaults_to_live_polymarket_without_sample_mode(self):
        args = build_parser().parse_args(["scrape", "--once"])
        self.assertEqual(args.provider, "polymarket")

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
        self.assertEqual(classify_event("M25 Sharm ElSheikh"), CompetitionGrade.ITF)
        self.assertEqual(classify_event("M25 Sharm ElSheikh", "itf"), CompetitionGrade.ITF)
        self.assertEqual(classify_event("Korea Open", "wta"), CompetitionGrade.WTA)
        self.assertEqual(classify_event("Chengdu Open", "atp"), CompetitionGrade.ATP)

    def test_match_link_is_conservative(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = link_match(("Alex Example", "Ben Sample"), start, [
            ("bf-1", ("Alex Example", "Ben Sample"), start),
        ])
        self.assertEqual(result.key, "bf-1")
        self.assertIsNone(link_match(("Alex", "Other"), start, []).key)

    def test_provider_collection_and_csv_export(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            snapshots = collect_once([TestSnapshotProvider()], connection)
            self.assertEqual(len(snapshots), 1)
            output = Path(directory) / "liquidity.csv"
            export_liquidity_csv(connection, output)
            self.assertIn("source_market_id", output.read_text(encoding="utf-8"))
            connection.close()

    def test_cli_reports_csv_export_path_and_row_count(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            save_snapshots(connection, [test_snapshot()])
            connection.close()
            output = Path(directory) / "liquidity.csv"
            captured = StringIO()
            with redirect_stdout(captured):
                main(["export-liquidity", "--db", str(db), str(output)])
            self.assertIn(f"Exported 1 snapshots to {output}", captured.getvalue())
            self.assertTrue(output.exists())

    def test_snapshot_raw_metadata_serializes_decimal_values(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "liquidity.sqlite3")
            snapshot = replace(test_snapshot(), raw={
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

    def test_database_connection_removes_legacy_fixture_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            save_snapshots(connection, [test_snapshot("sample-market", "fixture://sample")])
            save_snapshots(connection, [test_snapshot("real-market", "https://polymarket.com/event/test")])
            connection.close()
            connection = connect_database(db)
            rows = connection.execute(
                "SELECT source_market_id FROM liquidity_snapshots ORDER BY source_market_id"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], ["real-market"])
            connection.close()

    def test_database_connection_repairs_legacy_polymarket_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            snapshot = replace(
                test_snapshot("w15-market", "https://polymarket.com/event/w15"),
                provider="polymarket",
                event_name="W15 Maanshan: Player One vs Player Two",
                grade=CompetitionGrade.UNKNOWN,
                market_name="Polymarket CLOB",
            )
            save_snapshots(connection, [snapshot])
            connection.close()
            connection = connect_database(db)
            row = connection.execute(
                "SELECT grade, market_name FROM liquidity_snapshots WHERE source_market_id = ?",
                ("w15-market",),
            ).fetchone()
            self.assertEqual(row["grade"], CompetitionGrade.ITF.value)
            self.assertEqual(row["market_name"], "Match Winner")
            connection.close()

    def test_live_adapter_requires_credentials(self):
        from tennis_betting.providers import BetfairLiquidityProvider
        with self.assertRaises(ProviderError):
            BetfairLiquidityProvider().snapshots()

    def test_public_polymarket_adapter_normalizes_market_and_book(self):
        provider = PolymarketPublicLiquidityProvider(max_events=1)
        provider._get_json = lambda url: (
            [{"id": "event-1", "title": "ATP Tennis",
              "sport": {"sport": "atp", "name": "ATP Tour"},
              "series": [{"title": "ATP"}],
              "markets": [{"id": "market-1", "conditionId": "condition-1",
              "question": "ATP Tennis", "slug": "tennis-player-a-vs-player-b",
              "startDate": "2026-09-25T12:00:00Z",
              "clobTokenIds": '["token-1","token-2"]', "volume": "123.45"}]}]
            if "gamma-api" in url else
            {"bids": [{"price": "0.50", "size": "10"}],
             "asks": [{"price": "0.60", "size": "8"}]}
        )
        snapshots = provider.snapshots(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source_market_id, "market-1")
        self.assertEqual(snapshots[0].available_back, 10)
        self.assertEqual(snapshots[0].available_unmatched, 16)
        self.assertEqual(len(snapshots[0].raw["order_books"]), 2)
        self.assertEqual(snapshots[0].grade, CompetitionGrade.ATP)
        self.assertEqual(snapshots[0].market_name, "Match Winner")

    def test_public_polymarket_uses_circuit_metadata_for_grade(self):
        cases = (
            ("M25 Sharm ElSheikh: Player A vs Player B", "ITF", CompetitionGrade.ITF),
            ("Korea Open: Player A vs Player B", "WTA Tour", CompetitionGrade.WTA),
            ("Chengdu Open: Player A vs Player B", "ATP Tour", CompetitionGrade.ATP),
        )
        for event_title, sport_name, expected_grade in cases:
            with self.subTest(event_title=event_title):
                provider = PolymarketPublicLiquidityProvider(max_events=1)
                provider._get_json = lambda url, title=event_title, label=sport_name: (
                    [{"id": "event-1", "title": title,
                      "sport": {"name": label, "sport": label.lower().replace(" tour", "")},
                      "series": [{"title": label.replace(" Tour", "")}],
                      "markets": [{"id": "market-1", "question": title,
                                   "clobTokenIds": '["token-1", "token-2"]'}]}]
                    if "gamma-api" in url else
                    {"bids": [{"price": "0.50", "size": "10"}],
                     "asks": [{"price": "0.60", "size": "8"}]}
                )
                snapshot = provider.snapshots(datetime(2026, 9, 25, tzinfo=timezone.utc))[0]
                self.assertEqual(snapshot.grade, expected_grade)

    def test_public_polymarket_paginates_events_and_selects_match_market(self):
        provider = PolymarketPublicLiquidityProvider(max_events=101)
        gamma_calls = []
        book = {"bids": [{"price": "0.50", "size": "10"}],
                "asks": [{"price": "0.60", "size": "8"}]}

        def get_json(url):
            if "gamma-api" not in url:
                return book
            gamma_calls.append(url)
            if "offset=0" in url:
                return [
                    {"id": f"future-{index}", "title": f"Tennis tournament futures {index}",
                     "markets": [{"question": f"Will Player {index} win the tournament?",
                                  "clobTokenIds": '["future-token"]'}]}
                    for index in range(100)
                ]
            return [{"id": "match-event", "title": "ATP Match: Player A vs Player B",
                     "startTime": "2026-09-25T20:00:00Z",
                     "markets": [
                         {"id": "side-market", "question": "Total games over 20.5",
                          "clobTokenIds": '["side-token"]'},
                         {"id": "match-market", "question": "ATP Match: Player A vs Player B",
                          "clobTokenIds": '["yes-token", "no-token"]'},
                     ]}]

        provider._get_json = get_json
        snapshots = provider.snapshots(datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc))
        self.assertEqual(len(gamma_calls), 2)
        self.assertIn("offset=100", gamma_calls[1])
        self.assertEqual([snapshot.source_market_id for snapshot in snapshots], ["match-market"])
        self.assertEqual(snapshots[0].competitor_names, ("ATP Match: Player A", "Player B"))

    def test_public_polymarket_skips_markets_without_order_books(self):
        provider = PolymarketPublicLiquidityProvider(max_events=2)

        def get_json(url):
            if "gamma-api" in url:
                return [
                    {"id": "event-1", "title": "Tennis: unavailable",
                     "markets": [{"id": "no-book", "question": "Tennis: unavailable",
                                  "clobTokenIds": '["missing"]'}]},
                    {"id": "event-2", "title": "Tennis: available",
                     "markets": [{"id": "has-book", "question": "Tennis: available",
                                  "clobTokenIds": '["available"]'}]},
                ]
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

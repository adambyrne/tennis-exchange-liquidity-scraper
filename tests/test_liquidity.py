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
from tennis_betting.matching import compare_liquidity_snapshots, link_match
from tennis_betting.models import CompetitionGrade, Phase
from tennis_betting.normalization import normalize_snapshot
from tennis_betting.providers import (
    KalshiPublicLiquidityProvider,
    PolymarketNotFoundError,
    PolymarketPublicLiquidityProvider,
    ProviderError,
)
from tennis_betting.scraper import collect_once
from tennis_betting.storage import (
    connect_database, export_liquidity_csv, save_snapshots,
)
from tennis_betting.ui import HTML, LiquidityUI


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


class FixedSnapshotProvider:
    name = "test-provider"

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def snapshots(self, observed_at=None):
        return self._snapshots


class LiquidityTests(unittest.TestCase):
    def test_scrape_defaults_to_both_live_providers(self):
        args = build_parser().parse_args(["scrape", "--once"])
        self.assertEqual(args.provider, "all")

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

    def test_scrape_replaces_previous_snapshots_with_the_latest_complete_run(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "liquidity.sqlite3")
            old_snapshot = test_snapshot("old-market")
            new_snapshot = test_snapshot("new-market")
            save_snapshots(connection, [old_snapshot])
            collected = collect_once(
                [FixedSnapshotProvider([new_snapshot, new_snapshot])], connection,
            )
            rows = connection.execute(
                "SELECT source_market_id FROM liquidity_snapshots"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], ["new-market"])
            self.assertEqual(collected, [new_snapshot])
            connection.close()

    def test_failed_scrape_preserves_last_complete_snapshot_set(self):
        class FailingProvider:
            name = "failing-provider"

            def snapshots(self, observed_at=None):
                raise ProviderError("temporary API failure")

        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "liquidity.sqlite3")
            save_snapshots(connection, [test_snapshot("previous-run")])
            with self.assertRaisesRegex(ProviderError, "temporary API failure"):
                collect_once([FailingProvider()], connection)
            rows = connection.execute(
                "SELECT source_market_id FROM liquidity_snapshots"
            ).fetchall()
            self.assertEqual([row[0] for row in rows], ["previous-run"])
            connection.close()

    def test_cli_reports_csv_export_path_and_row_count(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            save_snapshots(connection, [test_snapshot()])
            connection.close()
            output = Path(directory) / "liquidity.csv"
            output.write_text("stale data from an earlier export", encoding="utf-8")
            captured = StringIO()
            with redirect_stdout(captured):
                main(["export-liquidity", "--db", str(db), str(output)])
            self.assertIn(f"Exported 1 snapshots to {output}", captured.getvalue())
            self.assertTrue(output.exists())
            self.assertNotIn("stale data", output.read_text(encoding="utf-8"))

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
              "clobTokenIds": '["token-1","token-2"]',
              "outcomes": '["Player A","Player B"]', "volume": "123.45"}]}]
            if "gamma-api" in url else
            {"bids": [{"price": "0.50", "size": "10"}],
             "asks": [{"price": "0.60", "size": "8"}]}
        )
        snapshots = provider.snapshots(datetime(2026, 9, 25, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].source_market_id, "market-1")
        self.assertEqual(snapshots[0].available_back, Decimal("5.00"))
        self.assertEqual(snapshots[0].available_unmatched, Decimal("4.80"))
        self.assertEqual(snapshots[0].matched_volume, Decimal("123.45"))
        self.assertEqual(len(snapshots[0].raw["order_books"]), 2)
        self.assertEqual(len(snapshots[0].raw["ui_markets"]), 2)
        self.assertEqual(
            [market["selection"] for market in snapshots[0].raw["ui_markets"]],
            ["Player A", "Player B"],
        )
        self.assertEqual(
            [market["liquidity"] for market in snapshots[0].raw["ui_markets"]],
            ["9.80", "9.80"],
        )
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
        self.assertEqual(snapshots[0].competitor_names, ("Player A", "Player B"))

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

    def test_kalshi_public_provider_parses_match_market_orderbook(self):
        provider = KalshiPublicLiquidityProvider(max_events=1)

        def get_json(path, params=None):
            if path == "series":
                return {"series": [
                    {"ticker": "KXTTMATCH", "title": "Table Tennis Match", "tags": ["Table Tennis"]},
                    {"ticker": "KXATPMATCH", "title": "ATP Tennis Match", "tags": ["Tennis"]},
                ]}
            if path == "events":
                return {"events": [{
                    "event_ticker": "KXATPMATCH-26SEP25ONE TWO",
                    "title": "Player One vs Player Two",
                    "markets": [
                        {"ticker": "winner-two", "title": "Player Two wins", "open_time": "2026-09-25T12:00:00Z",
                         "volume_fp": "70"},
                        {"ticker": "winner-one", "title": "Player One wins", "open_time": "2026-09-25T12:00:00Z",
                         "volume_fp": "85"},
                    ],
                }], "cursor": ""}
            return {"orderbook_fp": {
                "yes_dollars": [["0.5000", "10.00"]],
                "no_dollars": [["0.4000", "5.00"]],
            }}

        provider._get_json = get_json
        snapshots = provider.snapshots(datetime(2026, 9, 25, 11, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 1)
        snapshot = snapshots[0]
        self.assertEqual(snapshot.provider, "kalshi")
        self.assertEqual(snapshot.source_market_id, "winner-one")
        self.assertEqual(snapshot.competitor_names, ("Player Two", "Player One"))
        self.assertEqual(snapshot.available_back, Decimal("5.000000"))
        self.assertEqual(snapshot.available_unmatched, Decimal("2.000000"))
        self.assertEqual(snapshot.grade, CompetitionGrade.ATP)
        self.assertEqual(snapshot.matched_volume, Decimal("155"))
        self.assertEqual(snapshot.raw["orderbook"]["yes_dollars"][0], ["0.5000", "10.00"])
        self.assertEqual(len(snapshot.raw["ui_markets"]), 2)
        self.assertEqual(
            [market["selection"] for market in snapshot.raw["ui_markets"]],
            ["Player One wins", "Player Two wins"],
        )

    def test_kalshi_discovers_challenger_series_and_collects_doubles_teams(self):
        provider = KalshiPublicLiquidityProvider(timeout_seconds=1)
        events_by_series = {
            "KXATPCHALLENGERMATCH": [{
                "event_ticker": "challenge-single",
                "title": "Angelini vs Johns",
                "markets": [
                    {"ticker": "angelini", "title": "Lorenzo Angelini wins",
                     "open_time": "2026-09-28T10:00:00Z", "status": "active"},
                    {"ticker": "johns", "title": "Garrett Johns wins",
                     "open_time": "2026-09-28T10:00:00Z", "status": "active"},
                ],
            }],
            "KXATPCHALLENGERDOUBLES": [{
                "event_ticker": "challenge-doubles",
                "title": "Poullain / Reco vs Broady / Hudd",
                "markets": [
                    {"ticker": "team-one", "title": "Lucas Poullain / Alexandre Reco wins",
                     "open_time": "2026-09-28T16:00:00Z", "status": "active"},
                    {"ticker": "team-two", "title": "Liam Broady / Emile Hudd wins",
                     "open_time": "2026-09-28T16:00:00Z", "status": "active"},
                ],
            }],
        }

        def get_json(path, params=None):
            if path == "series":
                return {"series": [
                    {"ticker": "KXATPCHALLENGERMATCH", "title": "Challenger ATP", "tags": ["Tennis"]},
                    {"ticker": "KXATPCHALLENGERDOUBLES", "title": "ATP Challenger Doubles Match",
                     "tags": ["Tennis"]},
                    {"ticker": "KXATPSETMATCH", "title": "ATP Set Winner", "tags": ["Tennis"]},
                ]}
            if path == "events":
                return {
                    "events": events_by_series[params["series_ticker"]],
                    "cursor": "",
                }
            return {"orderbook_fp": {
                "yes_dollars": [["0.50", "20"]],
                "no_dollars": [["0.40", "10"]],
            }}

        provider._get_json = get_json
        snapshots = provider.snapshots(datetime(2026, 9, 28, 9, tzinfo=timezone.utc))
        self.assertEqual(len(snapshots), 2)
        by_id = {snapshot.source_event_id: snapshot for snapshot in snapshots}
        self.assertEqual(by_id["challenge-single"].grade, CompetitionGrade.ATP_CHALLENGER)
        doubles = by_id["challenge-doubles"]
        self.assertEqual(doubles.grade, CompetitionGrade.ATP_CHALLENGER)
        self.assertEqual(doubles.competitor_names, (
            "Lucas Poullain / Alexandre Reco",
            "Liam Broady / Emile Hudd",
        ))
        self.assertEqual(len(doubles.raw["ui_markets"]), 2)

    def test_cross_venue_comparison_uses_conservative_match_and_depth(self):
        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        polymarket = replace(
            normalize_snapshot({
                "event_id": "pm-event", "market_id": "pm-market",
                "event_name": "ATP: Player One vs Player Two",
                "competitors": ["Player One", "Player Two"], "start_time": start,
                "matched_volume": "130",
            }, "polymarket", start),
            raw={"order_books": [{
                "bids": [{"price": "0.50", "size": "10"}],
                "asks": [{"price": "0.60", "size": "8"}],
            }]},
        )
        kalshi = replace(
            normalize_snapshot({
                "event_id": "k-event", "market_id": "k-market",
                "event_name": "Player Two vs Player One",
                "competitors": ["Player Two", "Player One"], "start_time": start,
                "available_back": "5", "available_unmatched": "2",
                "matched_volume": "42",
            }, "kalshi", start),
            raw={"orderbook": {
                "yes_dollars": [["0.50", "10"]],
                "no_dollars": [["0.40", "5"]],
            }},
        )
        comparison, = compare_liquidity_snapshots([polymarket, kalshi])
        self.assertEqual(comparison.polymarket_volume, Decimal("130"))
        self.assertEqual(comparison.kalshi_volume, Decimal("42"))
        self.assertEqual(comparison.volume_leader, "Polymarket")
        self.assertEqual(comparison.confidence, 1.0)
        outside_window = replace(kalshi, start_time=start.replace(day=27))
        self.assertEqual(compare_liquidity_snapshots([polymarket, outside_window]), [])

    def test_cross_venue_matching_supports_abbreviated_doubles_teams(self):
        start = datetime(2026, 9, 28, 16, tzinfo=timezone.utc)
        polymarket = normalize_snapshot({
            "event_id": "pm-doubles", "market_id": "pm-doubles",
            "event_name": "Mouilleron-Le-Captif (Doubles): Poullain/Reco vs Broady/Hudd",
            "competitors": PolymarketPublicLiquidityProvider._competitors(
                "Mouilleron-Le-Captif (Doubles): Poullain/Reco vs Broady/Hudd",
            ),
            "start_time": start,
            "available_back": "50",
        }, "polymarket", start)
        kalshi = normalize_snapshot({
            "event_id": "kalshi-doubles", "market_id": "kalshi-doubles",
            "event_name": "Poullain / Reco vs Broady / Hudd",
            "competitors": [
                "Lucas Poullain / Alexandre Reco",
                "Liam Broady / Emile Hudd",
            ],
            "start_time": start.replace(hour=4),
            "available_back": "30",
            "grade": CompetitionGrade.ATP_CHALLENGER.value,
        }, "kalshi", start)
        comparison, = compare_liquidity_snapshots([polymarket, kalshi])
        self.assertEqual(comparison.confidence, 0.96)

    def test_cross_venue_comparison_rejects_ambiguous_matches(self):
        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        base = normalize_snapshot({
            "event_id": "event", "market_id": "market",
            "event_name": "Player One vs Player Two",
            "competitors": ["Player One", "Player Two"], "start_time": start,
        }, "polymarket", start)
        first = replace(base, raw={})
        second = replace(base, provider="kalshi", source_market_id="kalshi-1")
        duplicate = replace(base, provider="kalshi", source_market_id="kalshi-2")
        self.assertEqual(compare_liquidity_snapshots([first, second, duplicate]), [])

    def test_comparison_command_exports_only_matched_latest_markets(self):
        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        polymarket = replace(
            normalize_snapshot({
                "event_id": "pm-event", "market_id": "pm-market",
                "event_name": "Player One vs Player Two",
                "competitors": ["Player One", "Player Two"], "start_time": start,
                "matched_volume": "130",
            }, "polymarket", start),
            raw={"order_books": [{
                "bids": [{"price": "0.50", "size": "10"}],
                "asks": [{"price": "0.60", "size": "8"}],
            }]},
        )
        kalshi = replace(
            normalize_snapshot({
                "event_id": "k-event", "market_id": "k-market",
                "event_name": "Player Two vs Player One",
                "competitors": ["Player Two", "Player One"], "start_time": start,
                "matched_volume": "42",
            }, "kalshi", start),
            raw={"orderbook": {
                "yes_dollars": [["0.50", "10"]],
                "no_dollars": [["0.40", "5"]],
            }},
        )
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "liquidity.sqlite3")
            save_snapshots(connection, [polymarket, kalshi])
            connection.close()
            output = Path(directory) / "comparison.csv"
            captured = StringIO()
            with redirect_stdout(captured):
                main(["compare-liquidity", "--db", str(Path(directory) / "liquidity.sqlite3"), str(output)])
            self.assertIn(f"Exported 1 matched comparisons to {output}", captured.getvalue())
            text = output.read_text(encoding="utf-8")
            self.assertIn("higher_reported_matched_volume", text)
            self.assertIn("130", text)

    def test_ui_reads_current_comparison_results(self):
        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        polymarket = normalize_snapshot({
            "event_id": "pm-event", "market_id": "pm-market",
            "event_name": "Player One vs Player Two",
            "competitors": ["Player One", "Player Two"], "start_time": start,
            "matched_volume": "130",
        }, "polymarket", start)
        kalshi = normalize_snapshot({
            "event_id": "k-event", "market_id": "k-market",
            "event_name": "Player Two vs Player One",
            "competitors": ["Player Two", "Player One"], "start_time": start,
            "matched_volume": "42",
        }, "kalshi", start)
        polymarket = replace(polymarket, raw={"order_books": [{
            "bids": [{"price": "0.50", "size": "10"}],
            "asks": [{"price": "0.60", "size": "8"}],
        }]})
        kalshi = replace(kalshi, phase=Phase.PRE_MATCH, raw={"orderbook": {
            "yes_dollars": [["0.50", "10"]], "no_dollars": [["0.40", "5"]],
        }})
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "liquidity.sqlite3"
            connection = connect_database(db)
            save_snapshots(connection, [polymarket, kalshi])
            connection.close()
            payload = LiquidityUI(db).results()
            self.assertEqual(len(payload["results"]), 1)
            self.assertEqual(payload["results"][0]["volume_leader"], "Polymarket")
            comparison = payload["results"][0]
            self.assertEqual(comparison["id"], "pm-event|k-event")
            self.assertEqual(comparison["polymarket_volume"], "130")
            self.assertEqual(comparison["kalshi_volume"], "42")
            self.assertEqual(comparison["phase"], "in_play")
            self.assertEqual(comparison["markets"]["polymarket"][0]["liquidity"], "9.80")
            self.assertEqual(comparison["markets"]["kalshi"][0]["liquidity"], "7.00")
            self.assertEqual(payload["distribution"], [{
                "tournament_type": "unknown",
                "polymarket_percent": "100%",
                "kalshi_percent": "0%",
                "total_matches": 1,
            }])

    def test_ui_supports_default_and_clickable_column_sorting(self):
        self.assertIn('sortColumn="polymarket", sortDirection="descending"', HTML)
        self.assertIn('data-sort="match"', HTML)
        self.assertIn('data-sort="polymarket"', HTML)
        self.assertIn('data-sort="kalshi"', HTML)
        self.assertIn('data-sort="leader"', HTML)
        self.assertIn('sortDirection==="ascending"?"descending":"ascending"', HTML)
        self.assertIn('sortDirection==="ascending"?"↑":"↓"', HTML)
        self.assertIn('data-sort="leader"', HTML)
        self.assertIn('id="tournament-filter"', HTML)
        self.assertIn('id="status-filter"', HTML)
        self.assertIn('selectedStatus="both"', HTML)
        self.assertIn("selectedGrade===\"all\"", HTML)
        self.assertIn("selectedStatus===\"both\"", HTML)
        self.assertIn('id="distribution"', HTML)
        self.assertIn("renderDistribution()", HTML)
        self.assertIn("expandedMatches=new Set()", HTML)
        self.assertIn('data-expand="${esc(r.id)}"', HTML)
        self.assertIn("marketPanel(\"Polymarket\"", HTML)
        self.assertIn("marketPanel(\"Kalshi\"", HTML)
        self.assertIn("mini-bar", HTML)
        self.assertIn('rowMarkup("Total",total,true)', HTML)

    def test_ui_liquidity_distribution_counts_ties_in_denominator(self):
        from tennis_betting.ui import _liquidity_distribution

        start = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        def snapshot(provider, market_id, amount, competitors, grade):
            return normalize_snapshot({
                "event_id": market_id, "market_id": market_id,
                "event_name": " vs ".join(competitors),
                "competitors": competitors,
                "start_time": start,
                "available_back": amount,
                "matched_volume": amount,
                "grade": grade.value,
            }, provider, start)

        comparisons = compare_liquidity_snapshots([
            snapshot("polymarket", "pm-win", "20", ["Player One", "Player Two"],
                     CompetitionGrade.ATP_CHALLENGER),
            snapshot("kalshi", "k-pm-win", "10", ["Player Two", "Player One"],
                     CompetitionGrade.ATP_CHALLENGER),
            snapshot("polymarket", "pm-kalshi", "5", ["Player Three", "Player Four"],
                     CompetitionGrade.ITF),
            snapshot("kalshi", "k-win", "15", ["Player Four", "Player Three"],
                     CompetitionGrade.ITF),
            snapshot("polymarket", "pm-tie", "10", ["Player Five", "Player Six"],
                     CompetitionGrade.WTA),
            snapshot("kalshi", "k-tie", "10", ["Player Six", "Player Five"],
                     CompetitionGrade.WTA),
        ])
        self.assertEqual(len(comparisons), 3)
        self.assertEqual(_liquidity_distribution(comparisons), [{
            "tournament_type": "atp_challenger",
            "polymarket_percent": "100%",
            "kalshi_percent": "0%",
            "total_matches": 1,
        }, {
            "tournament_type": "itf",
            "polymarket_percent": "0%",
            "kalshi_percent": "100%",
            "total_matches": 1,
        }, {
            "tournament_type": "wta",
            "polymarket_percent": "0%",
            "kalshi_percent": "0%",
            "total_matches": 1,
        }])


if __name__ == "__main__":
    unittest.main()

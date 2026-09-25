from __future__ import annotations

import argparse
from decimal import Decimal

from .calculations import combined_odds, potential_returns
from .models import Selection, Slip
from .providers import StaticOddsProvider
from .providers import (
    PolymarketPublicLiquidityProvider,
)
from .scraper import collect_once, run_scheduler
from .storage import (
    connect_database, export_csv, export_liquidity_csv, export_liquidity_parquet, load_slip, save_slip,
)

NOTICE = "Gamble responsibly. Never bet more than you can afford to lose."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calculate tennis betting slips.")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("matches", help="list static sample matches")
    add = sub.add_parser("add", help="create a slip from one selection")
    add.add_argument("player")
    add.add_argument("opponent")
    add.add_argument("odds", type=Decimal)
    add.add_argument("--match", default="custom")
    add.add_argument("--name", default="default")
    calc = sub.add_parser("calculate", help="calculate a saved slip")
    calc.add_argument("file")
    calc.add_argument("stake", type=Decimal)
    save = sub.add_parser("save", help="save a simple slip")
    save.add_argument("file")
    save.add_argument("player")
    save.add_argument("opponent")
    save.add_argument("odds", type=Decimal)
    sub.add_parser("interactive", help="open the interactive menu")
    scrape = sub.add_parser("scrape", help="collect exchange liquidity into SQLite")
    scrape.add_argument("--db", default="liquidity.sqlite3")
    scrape.add_argument("--live", action="store_true", help="accepted for compatibility; Polymarket is always live")
    scrape.add_argument("--provider", choices=("polymarket",), default="polymarket",
                        help="live provider to collect")
    scrape.add_argument("--once", action="store_true", help="collect one interval and exit")
    scrape.add_argument("--interval", type=int, default=600)
    export = sub.add_parser("export-liquidity", help="export stored liquidity snapshots")
    export.add_argument("--db", default="liquidity.sqlite3")
    export.add_argument("--format", choices=("csv", "parquet"), default="csv")
    export.add_argument("file")
    return parser


def interactive() -> None:
    slip = Slip()
    provider = StaticOddsProvider()
    print("Tennis Betting Slip Calculator\n" + NOTICE)
    for match in provider.matches():
        print(f"{match.id}: {match.player1} ({match.odds_player1}) vs {match.player2} ({match.odds_player2})")
    while True:
        command = input("\nCommands: add, view, remove, calculate, clear, quit\n> ").strip().lower()
        if command in {"quit", "exit", "0"}:
            return
        try:
            if command == "add":
                match_id = input("Match id: ")
                match = next(m for m in provider.matches() if m.id == match_id)
                side = input("Player (1/2): ")
                player, opponent, odds = ((match.player1, match.player2, match.odds_player1)
                                          if side == "1" else (match.player2, match.player1, match.odds_player2))
                slip.add(Selection(match.id, player, opponent, odds))
                print("Added.")
            elif command == "view":
                print("\n".join(f"{i + 1}. {s.player} @ {s.odds}" for i, s in enumerate(slip.selections)) or "Empty slip")
            elif command == "remove":
                slip.remove(int(input("Selection number: ")) - 1)
            elif command == "clear":
                slip.clear()
            elif command == "calculate":
                stake = Decimal(input("Stake: "))
                print(f"Combined odds: {combined_odds(slip.selections):.2f}")
                print(f"Potential return: {potential_returns(slip, stake)[0]:.2f}")
        except (ValueError, StopIteration) as error:
            print(f"Error: {error}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command in (None, "interactive"):
        interactive()
    elif args.command == "matches":
        for match in StaticOddsProvider().matches():
            print(f"{match.id}: {match.player1} vs {match.player2} ({match.odds_player1}/{match.odds_player2})")
    elif args.command == "add":
        slip = Slip(args.name)
        slip.add(Selection(args.match, args.player, args.opponent, args.odds))
        print(f"{args.player} added to {args.name}")
    elif args.command == "save":
        slip = Slip(args.file)
        slip.add(Selection("custom", args.player, args.opponent, args.odds))
        save_slip(slip, args.file)
    elif args.command == "calculate":
        slip = load_slip(args.file)
        print(f"Combined odds: {combined_odds(slip.selections):.2f}")
        print(f"Potential return: {potential_returns(slip, args.stake)[0]:.2f}")
        export_csv(slip, args.file + ".csv")
    elif args.command == "scrape":
        providers = [PolymarketPublicLiquidityProvider()]
        connection = connect_database(args.db)
        try:
            if args.once:
                print(f"Collected {len(collect_once(providers, connection))} snapshots")
            else:
                run_scheduler(providers, connection, args.interval)
        finally:
            connection.close()
    elif args.command == "export-liquidity":
        connection = connect_database(args.db)
        try:
            if args.format == "csv":
                count = export_liquidity_csv(connection, args.file)
            else:
                count = export_liquidity_parquet(connection, args.file)
        finally:
            connection.close()
        print(f"Exported {count} snapshots to {args.file}")

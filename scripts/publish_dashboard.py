from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from tennis_betting.site import build_static_site
from tennis_betting.ui import LiquidityUI


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape current tennis markets and build the static dashboard."
    )
    parser.add_argument("--output-directory", default="site")
    parser.add_argument("--history-file", default="previous-history.json")
    parser.add_argument("--refresh-api-url", default="")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="tennis-liquidity-") as temporary_directory:
        data = LiquidityUI(f"{temporary_directory}/liquidity.sqlite3").scrape()
    if not data["count"]:
        raise RuntimeError("The scrape returned no snapshots; refusing to publish empty data.")
    history_file = Path(args.history_file)
    history = json.loads(history_file.read_text(encoding="utf-8")) if history_file.exists() else []
    if not isinstance(history, list):
        raise ValueError("history file must contain a JSON array")
    build_static_site(data, args.output_directory, history, args.refresh_api_url)
    print(f"Published {len(data['results'])} matched fixtures to {args.output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

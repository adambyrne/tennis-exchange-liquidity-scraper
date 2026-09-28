from __future__ import annotations

import argparse
import tempfile

from tennis_betting.site import build_static_site
from tennis_betting.ui import LiquidityUI


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape current tennis markets and build the static dashboard."
    )
    parser.add_argument("--output-directory", default="site")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="tennis-liquidity-") as temporary_directory:
        data = LiquidityUI(f"{temporary_directory}/liquidity.sqlite3").scrape()
    if not data["count"]:
        raise RuntimeError("The scrape returned no snapshots; refusing to publish empty data.")
    build_static_site(data, args.output_directory)
    print(f"Published {len(data['results'])} matched fixtures to {args.output_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

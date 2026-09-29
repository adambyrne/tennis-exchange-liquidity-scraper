from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .ui import HTML

HISTORY_LIMIT = 100
LIQUIDITY_BANDS = (
    ("<5k", Decimal("0"), Decimal("5000")),
    ("5k-25k", Decimal("5000"), Decimal("25000")),
    ("25k-100k", Decimal("25000"), Decimal("100000")),
    ("100k+", Decimal("100000"), Decimal("Infinity")),
)


def _leader_percentages(results: list[dict[str, Any]], view: str) -> dict[str, Any]:
    total = len(results)
    polymarket_wins = 0
    kalshi_wins = 0
    for result in results:
        if view == "matched":
            polymarket = Decimal(str(result.get("polymarket_volume", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_volume", 0) or 0))
        else:
            polymarket = Decimal(str(result.get("polymarket_depth", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_depth", 0) or 0))
        polymarket_wins += polymarket > kalshi
        kalshi_wins += kalshi > polymarket
    return {
        "total_matches": total,
        "polymarket_percent": (polymarket_wins / total * 100) if total else 0,
        "kalshi_percent": (kalshi_wins / total * 100) if total else 0,
    }


def _breakdown(results: list[dict[str, Any]], view: str) -> dict[str, list[dict[str, Any]]]:
    tournaments: dict[str, list[dict[str, Any]]] = {}
    ranges: dict[str, list[dict[str, Any]]] = {
        label: [] for label, _, _ in LIQUIDITY_BANDS
    }
    for result in results:
        grade = str(result.get("grade") or "unknown")
        tournaments.setdefault(grade, []).append(result)
        if view == "matched":
            combined = Decimal(str(result.get("polymarket_volume", 0) or 0)) + Decimal(
                str(result.get("kalshi_volume", 0) or 0)
            )
        else:
            combined = Decimal(str(result.get("polymarket_depth", 0) or 0)) + Decimal(
                str(result.get("kalshi_depth", 0) or 0)
            )
        for label, lower, upper in LIQUIDITY_BANDS:
            if lower <= combined < upper:
                ranges[label].append(result)
                break

    def rows(
        groups: dict[str, list[dict[str, Any]]],
        labels: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        output = []
        ordered_labels = labels if labels is not None else sorted(groups)
        for label in ordered_labels:
            group = groups[label]
            output.append({
                "label": label,
                **_leader_percentages(group, view),
            })
        return output

    return {
        "tournaments": rows(tournaments),
        "ranges": rows(ranges, (label for label, _, _ in LIQUIDITY_BANDS)),
    }


def _history_entry(data: dict[str, Any], refresh_number: int) -> dict[str, Any]:
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("scrape data must include a results list")
    views = {}
    for view in ("matched", "depth"):
        views[view] = {
            **_leader_percentages(results, view),
            **_breakdown(results, view),
        }
    return {
        "refresh": refresh_number,
        "timestamp": data.get("updated_at"),
        "results": results,
        "views": views,
    }


def append_history(
    data: dict[str, Any],
    history: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    entries = list(history)
    if any(
        not isinstance(entry, dict) or not isinstance(entry.get("refresh"), int)
        for entry in entries
    ):
        raise ValueError("history entries must have an integer refresh number")
    next_refresh = max((entry["refresh"] for entry in entries), default=0) + 1
    entries.append(_history_entry(data, next_refresh))
    return entries[-HISTORY_LIMIT:]


def build_static_site(
    data: dict[str, Any],
    output_directory: str | Path,
    history: Iterable[dict[str, Any]] = (),
) -> None:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(
        HTML.replace("const STATIC_MODE = false;", "const STATIC_MODE = true;"),
        encoding="utf-8",
    )
    (output / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (output / "history.json").write_text(
        json.dumps(append_history(data, history), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

from __future__ import annotations

import json
from decimal import Decimal
from datetime import datetime
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
ACTIVITY_BUCKETS = (
    ("before_24h", "24h+ Before"),
    ("before_24_12h", "24-12h Before"),
    ("before_12_2h", "12-2h Before"),
    ("before_2_0h", "2-0h Before"),
    ("in_play", "In-Play"),
)


def _leader_percentages(results: list[dict[str, Any]], view: str) -> dict[str, Any]:
    total = len(results)
    polymarket_wins = 0
    kalshi_wins = 0
    polymarket_liquidity = Decimal(0)
    kalshi_liquidity = Decimal(0)
    combined_liquidity = Decimal(0)
    for result in results:
        if view == "matched":
            polymarket = Decimal(str(result.get("polymarket_volume", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_volume", 0) or 0))
        else:
            polymarket = Decimal(str(result.get("polymarket_depth", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_depth", 0) or 0))
        polymarket_wins += polymarket > kalshi
        kalshi_wins += kalshi > polymarket
        polymarket_liquidity += polymarket
        kalshi_liquidity += kalshi
        combined_liquidity += polymarket + kalshi
    return {
        "total_matches": total,
        "polymarket_percent": (polymarket_wins / total * 100) if total else 0,
        "kalshi_percent": (kalshi_wins / total * 100) if total else 0,
        "polymarket_average_liquidity": (
            float(polymarket_liquidity / total) if total else 0
        ),
        "kalshi_average_liquidity": (
            float(kalshi_liquidity / total) if total else 0
        ),
        "average_liquidity": (
            float(combined_liquidity / total) if total else 0
        ),
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
        "liquidity_ranges": _liquidity_range_breakdown(results, view),
    }


def _liquidity_range_breakdown(
    results: list[dict[str, Any]], view: str
) -> list[dict[str, Any]]:
    ranges: dict[str, dict[str, Any]] = {
        label: {"total_matches": 0, "polymarket": 0, "kalshi": 0, "zero": 0}
        for label, _, _ in LIQUIDITY_BANDS
    }
    for result in results:
        if view == "matched":
            polymarket = Decimal(str(result.get("polymarket_volume", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_volume", 0) or 0))
        else:
            polymarket = Decimal(str(result.get("polymarket_depth", 0) or 0))
            kalshi = Decimal(str(result.get("kalshi_depth", 0) or 0))
        combined = polymarket + kalshi
        label = next(
            (
                label
                for label, lower, upper in LIQUIDITY_BANDS
                if lower <= combined < upper
            ),
            None,
        )
        if label is None:
            continue
        row = ranges[label]
        row["total_matches"] += 1
        if polymarket <= 0 or kalshi <= 0:
            row["zero"] += 1
        elif polymarket == kalshi:
            row["polymarket"] += Decimal("0.5")
            row["kalshi"] += Decimal("0.5")
        elif polymarket > kalshi:
            row["polymarket"] += 1
        else:
            row["kalshi"] += 1

    return [
        {
            "label": label,
            "total_matches": row["total_matches"],
            "polymarket_percent": float(row["polymarket"] / row["total_matches"] * 100)
            if row["total_matches"]
            else 0,
            "kalshi_percent": float(row["kalshi"] / row["total_matches"] * 100)
            if row["total_matches"]
            else 0,
            "zero_liquidity_percent": float(row["zero"] / row["total_matches"] * 100)
            if row["total_matches"]
            else 0,
        }
        for label, row in ranges.items()
    ]


def _activity_breakdown(
    results: list[dict[str, Any]],
    previous_results: list[dict[str, Any]],
    observed_at: str | None,
) -> dict[str, Any]:
    """Record matched-volume increases, classified by scheduled start time."""
    activity: dict[str, dict[str, Decimal]] = {}
    if not observed_at:
        return {
            "grades": [],
            "bucket_totals": {key: 0 for key, _ in ACTIVITY_BUCKETS},
            "total_volume": 0,
        }
    try:
        observation_time = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return {
            "grades": [],
            "bucket_totals": {key: 0 for key, _ in ACTIVITY_BUCKETS},
            "total_volume": 0,
        }

    previous_by_id = {
        str(result.get("id")): result
        for result in previous_results
        if result.get("id") is not None
    }
    for result in results:
        result_id = result.get("id")
        previous = previous_by_id.get(str(result_id)) if result_id is not None else None
        if previous is None or not result.get("start_time"):
            continue
        try:
            start_time = datetime.fromisoformat(
                str(result["start_time"]).replace("Z", "+00:00")
            )
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=observation_time.tzinfo)
        except ValueError:
            continue
        if start_time <= observation_time:
            # Provider phase may combine inconsistent venue states; scheduled
            # start time is the stable boundary for all pre-match buckets.
            bucket = "in_play"
        else:
            hours_to_start = (
                Decimal(str((start_time - observation_time).total_seconds()))
                / Decimal(3600)
            )
            if hours_to_start >= 24:
                bucket = "before_24h"
            elif hours_to_start >= 12:
                bucket = "before_24_12h"
            elif hours_to_start >= 2:
                bucket = "before_12_2h"
            else:
                bucket = "before_2_0h"
        volume_increase = Decimal(0)
        for venue in ("polymarket", "kalshi"):
            current = Decimal(str(result.get(f"{venue}_volume", 0) or 0))
            prior = Decimal(str(previous.get(f"{venue}_volume", 0) or 0))
            volume_increase += max(current - prior, Decimal(0))
        if volume_increase <= 0:
            continue
        grade = str(result.get("grade") or "unknown")
        grade_activity = activity.setdefault(
            grade, {key: Decimal(0) for key, _ in ACTIVITY_BUCKETS}
        )
        grade_activity[bucket] += volume_increase

    bucket_totals = {
        key: sum((values[key] for values in activity.values()), Decimal(0))
        for key, _ in ACTIVITY_BUCKETS
    }
    return {
        "grades": [
            {
                "label": grade,
                "buckets": {key: float(amount) for key, amount in values.items()},
                "total_volume": float(sum(values.values(), Decimal(0))),
            }
            for grade, values in sorted(activity.items())
        ],
        "bucket_totals": {key: float(amount) for key, amount in bucket_totals.items()},
        "total_volume": float(sum(bucket_totals.values(), Decimal(0))),
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
        "betting_activity": _activity_breakdown(
            results, data.get("_previous_results", []), data.get("updated_at")
        ),
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
    upgraded_entries = []
    previous_results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if isinstance(entry.get("results"), list):
            upgraded = _history_entry(
                {
                    "updated_at": entry.get("timestamp"),
                    "results": entry["results"],
                    "_previous_results": previous_results,
                },
                entry["refresh"],
            )
            if index == 0 and "betting_activity" in entry:
                upgraded["betting_activity"] = entry["betting_activity"]
            upgraded_entries.append(upgraded)
            previous_results = entry["results"]
        else:
            upgraded_entries.append(entry)
    entries = upgraded_entries
    next_refresh = max((entry["refresh"] for entry in entries), default=0) + 1
    entries.append(_history_entry({
        **data,
        "_previous_results": previous_results,
    }, next_refresh))
    return entries[-HISTORY_LIMIT:]


def build_static_site(
    data: dict[str, Any],
    output_directory: str | Path,
    history: Iterable[dict[str, Any]] = (),
    refresh_api_url: str = "",
) -> None:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    html = HTML.replace("const STATIC_MODE = false;", "const STATIC_MODE = true;")
    html = html.replace(
        'const REFRESH_API_BASE = "";',
        f"const REFRESH_API_BASE = {json.dumps(refresh_api_url.rstrip('/'))};",
    )
    (output / "index.html").write_text(html, encoding="utf-8")
    (output / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (output / "history.json").write_text(
        json.dumps(append_history(data, history), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

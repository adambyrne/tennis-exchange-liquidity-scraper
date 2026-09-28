from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from itertools import permutations
from typing import Iterable

from .models import LiquiditySnapshot


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", value.lower())


@dataclass(frozen=True)
class MatchLink:
    key: str | None
    confidence: float
    ambiguous: bool = False


def link_match(competitors: tuple[str, ...], start_time: object, candidates: list[tuple[str, tuple[str, ...], object]]) -> MatchLink:
    """Conservative deterministic linker; near matches remain explicitly ambiguous."""
    wanted = {_normalise(name) for name in competitors}
    scored: list[tuple[float, str]] = []
    for key, names, candidate_time in candidates:
        if candidate_time != start_time or len(names) != len(competitors):
            continue
        score = sum(max(SequenceMatcher(None, item, _normalise(name)).ratio() for name in names) for item in wanted)
        scored.append((score / len(wanted), key))
    if not scored:
        return MatchLink(None, 0.0)
    scored.sort(reverse=True)
    confidence, key = scored[0]
    ambiguous = len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08
    return MatchLink(None if ambiguous or confidence < 0.78 else key, confidence, ambiguous)


@dataclass(frozen=True)
class LiquidityComparison:
    polymarket: LiquiditySnapshot
    kalshi: LiquiditySnapshot
    confidence: float
    polymarket_volume: Decimal
    kalshi_volume: Decimal

    @property
    def volume_leader(self) -> str:
        if self.polymarket_volume == self.kalshi_volume:
            return "Tie"
        return "Polymarket" if self.polymarket_volume > self.kalshi_volume else "Kalshi"


def displayed_orderbook_depth(snapshot: LiquiditySnapshot) -> Decimal:
    """Calculate gross resting-order depth for expandable UI market details."""
    if snapshot.provider == "polymarket":
        books = snapshot.raw.get("order_books")
        if isinstance(books, list) and books and isinstance(books[0], dict):
            book = books[0]
            return sum(
                (Decimal(str(level["price"])) * Decimal(str(level["size"]))
                 for side in ("bids", "asks")
                 for level in book.get(side, []) if isinstance(level, dict)),
                Decimal("0"),
            )
    elif snapshot.provider == "kalshi":
        orderbook = snapshot.raw.get("orderbook")
        if isinstance(orderbook, dict):
            return sum(
                (Decimal(str(level[0])) * Decimal(str(level[1]))
                 for side in ("yes_dollars", "no_dollars")
                 for level in orderbook.get(side, [])
                 if isinstance(level, (list, tuple)) and len(level) >= 2),
                Decimal("0"),
            )
    return snapshot.available_back + snapshot.available_unmatched


def _name_similarity(left: str, right: str) -> float:
    first, second = _normalise(left), _normalise(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    shorter, longer = sorted((first, second), key=len)
    if len(shorter) >= 4 and longer.endswith(shorter):
        return 0.96
    return SequenceMatcher(None, first, second).ratio()


def _team_similarity(left: str, right: str) -> float:
    left_players = [name.strip() for name in re.split(r"\s*/\s*", left) if name.strip()]
    right_players = [name.strip() for name in re.split(r"\s*/\s*", right) if name.strip()]
    if len(left_players) != len(right_players):
        return 0.0
    return max(
        sum(_name_similarity(first, second) for first, second in zip(left_players, order))
        / len(left_players)
        for order in permutations(right_players)
    )


def _competitor_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    if len(left) != 2 or len(right) != 2:
        return 0.0
    return max(
        sum(_team_similarity(first, second) for first, second in zip(left, order)) / 2
        for order in permutations(right)
    )


def _time_delta_hours(left: datetime, right: datetime) -> float:
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return abs((left - right).total_seconds()) / 3600


def compare_liquidity_snapshots(
    snapshots: Iterable[LiquiditySnapshot],
    max_start_delta: timedelta = timedelta(hours=36),
) -> list[LiquidityComparison]:
    """Match only unambiguous cross-venue fixtures with similar names and start times."""
    polymarket = [item for item in snapshots if item.provider == "polymarket"]
    kalshi = [item for item in snapshots if item.provider == "kalshi"]
    candidates: dict[tuple[int, int], tuple[float, float]] = {}
    max_hours = max_start_delta.total_seconds() / 3600
    for left_index, left in enumerate(polymarket):
        for right_index, right in enumerate(kalshi):
            delta = _time_delta_hours(left.start_time, right.start_time)
            if delta > max_hours:
                continue
            name_score = _competitor_similarity(left.competitor_names, right.competitor_names)
            if name_score < 0.86:
                continue
            # Start-time proximity breaks ties between otherwise similar candidates.
            score = name_score - (delta / max_hours * 0.02 if max_hours else 0)
            candidates[left_index, right_index] = (score, name_score)

    def unique_best(scores: list[tuple[float, int]]) -> int | None:
        if not scores:
            return None
        scores.sort(reverse=True)
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.025:
            return None
        return scores[0][1]

    left_choices = {
        index: unique_best([
            (score, right_index)
            for (left_index, right_index), (score, _) in candidates.items()
            if left_index == index
        ])
        for index in range(len(polymarket))
    }
    right_choices = {
        index: unique_best([
            (score, left_index)
            for (left_index, right_index), (score, _) in candidates.items()
            if right_index == index
        ])
        for index in range(len(kalshi))
    }
    comparisons = []
    for left_index, right_index in left_choices.items():
        if right_index is None or right_choices.get(right_index) != left_index:
            continue
        _, confidence = candidates[left_index, right_index]
        left, right = polymarket[left_index], kalshi[right_index]
        comparisons.append(LiquidityComparison(
            left,
            right,
            confidence,
            left.matched_volume,
            right.matched_volume,
        ))
    return sorted(comparisons, key=lambda item: (item.polymarket.start_time, item.polymarket.event_name))

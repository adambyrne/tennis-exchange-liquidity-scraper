from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


def money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


class BetType(str, Enum):
    SINGLE = "single"
    ACCUMULATOR = "accumulator"
    SYSTEM = "system"


class CompetitionGrade(str, Enum):
    GRAND_SLAM = "grand_slam"
    ATP = "atp"
    WTA = "wta"
    ATP_CHALLENGER = "atp_challenger"
    ITF = "itf"
    UTR = "utr"
    UNKNOWN = "unknown"


class Phase(str, Enum):
    PRE_MATCH = "pre_match"
    IN_PLAY = "in_play"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class LiquiditySnapshot:
    provider: str
    source_event_id: str
    source_market_id: str
    event_name: str
    market_name: str
    competitor_names: tuple[str, ...]
    start_time: datetime
    observed_at: datetime
    grade: CompetitionGrade
    phase: Phase
    available_back: Decimal
    available_unmatched: Decimal
    matched_volume: Decimal
    currency: str
    source_url: str | None = None
    match_key: str | None = None
    match_confidence: Decimal | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("available_back", "available_unmatched", "matched_volume"):
            object.__setattr__(self, name, Decimal(str(getattr(self, name))))
        if self.match_confidence is not None:
            object.__setattr__(self, "match_confidence", Decimal(str(self.match_confidence)))


@dataclass(frozen=True)
class Match:
    id: str
    player1: str
    player2: str
    odds_player1: Decimal
    odds_player2: Decimal
    odds_updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "odds_player1", Decimal(str(self.odds_player1)))
        object.__setattr__(self, "odds_player2", Decimal(str(self.odds_player2)))


@dataclass(frozen=True)
class Selection:
    match_id: str
    player: str
    opponent: str
    odds: Decimal
    user_probability: Optional[Decimal] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "odds", Decimal(str(self.odds)))
        if self.user_probability is not None:
            object.__setattr__(self, "user_probability", Decimal(str(self.user_probability)))


@dataclass
class Slip:
    name: str = "default"
    selections: list[Selection] = field(default_factory=list)
    bet_type: BetType = BetType.ACCUMULATOR
    system_size: int = 2
    stake: Decimal = Decimal("0.00")
    spending_limit: Optional[Decimal] = None
    session_limit_minutes: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add(self, selection: Selection) -> None:
        from .validation import validate_selection_for_slip
        validate_selection_for_slip(self, selection)
        self.selections.append(selection)

    def remove(self, index: int) -> Selection:
        if index < 0 or index >= len(self.selections):
            raise IndexError("selection index out of range")
        return self.selections.pop(index)

    def clear(self) -> None:
        self.selections.clear()

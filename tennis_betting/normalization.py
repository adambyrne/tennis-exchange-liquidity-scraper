from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from .classification import classify_event
from .models import LiquiditySnapshot, Phase


def _date(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_snapshot(raw: dict, provider: str, observed_at: datetime | None = None) -> LiquiditySnapshot:
    """Map a provider-neutral fixture/API payload into the stable schema."""
    start_time = _date(raw["start_time"])
    observed = observed_at or datetime.now(timezone.utc)
    status = str(raw.get("status", "")).lower()
    phase = Phase.IN_PLAY if status in {"in_play", "live", "started"} or start_time <= observed else Phase.PRE_MATCH
    event_name = str(raw["event_name"])
    return LiquiditySnapshot(
        provider=provider,
        source_event_id=str(raw["event_id"]),
        source_market_id=str(raw["market_id"]),
        event_name=event_name,
        market_name=str(raw.get("market_name", "match odds")),
        competitor_names=tuple(str(item) for item in raw["competitors"]),
        start_time=start_time,
        observed_at=observed,
        grade=classify_event(event_name, raw.get("grade")),
        phase=phase,
        available_back=Decimal(str(raw.get("available_back", 0))),
        available_unmatched=Decimal(str(raw.get("available_unmatched", 0))),
        matched_volume=Decimal(str(raw.get("matched_volume", 0))),
        currency=str(raw.get("currency", "USD")),
        source_url=raw.get("source_url"),
        raw=raw,
    )

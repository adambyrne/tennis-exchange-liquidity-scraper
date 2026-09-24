from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import CompetitionGrade, LiquiditySnapshot, Phase


def sample_snapshots(provider: str) -> list[LiquiditySnapshot]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return [
        LiquiditySnapshot(
            provider=provider, source_event_id=f"{provider}-event-1", source_market_id=f"{provider}-market-1",
            event_name="ATP Tokyo", market_name="Match Odds", competitor_names=("Alex Example", "Ben Sample"),
            start_time=now + timedelta(hours=3), observed_at=now, grade=CompetitionGrade.ATP,
            phase=Phase.PRE_MATCH, available_back="1250.00", available_unmatched="1800.00",
            matched_volume="9400.00", currency="USD", source_url="fixture://sample",
        ),
        LiquiditySnapshot(
            provider=provider, source_event_id=f"{provider}-event-2", source_market_id=f"{provider}-market-2",
            event_name="WTA Rome", market_name="Match Odds", competitor_names=("Casey Player", "Dana Tennis"),
            start_time=now - timedelta(minutes=45), observed_at=now, grade=CompetitionGrade.WTA,
            phase=Phase.IN_PLAY, available_back="310.00", available_unmatched="500.00",
            matched_volume="2200.00", currency="USD", source_url="fixture://sample",
        ),
    ]

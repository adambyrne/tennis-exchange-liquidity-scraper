from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Protocol

from .fixtures import sample_snapshots
from .models import LiquiditySnapshot, Match


class ProviderError(RuntimeError):
    pass


class LiquidityProvider(Protocol):
    name: str

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]: ...


class FixtureLiquidityProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        return sample_snapshots(self.name)


class CredentialedLiquidityProvider:
    """Adapter boundary for official/public APIs; live transport is intentionally opt-in."""

    endpoint: str
    credential_env: str

    def __init__(self, name: str, endpoint: str, credential_env: str) -> None:
        self.name, self.endpoint, self.credential_env = name, endpoint, credential_env

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        if not os.getenv(self.credential_env):
            raise ProviderError(
                f"{self.name} live collection requires {self.credential_env}; use --sample without credentials"
            )
        raise ProviderError(
            f"{self.name} transport is not enabled in the sample build. Implement the documented API client "
            f"before making live requests to {self.endpoint}"
        )


class BetfairLiquidityProvider(CredentialedLiquidityProvider):
    def __init__(self) -> None:
        super().__init__("betfair", "https://api.betfair.com/exchange/betting/json-rpc/v1", "BETFAIR_APP_KEY")


class PolymarketLiquidityProvider(CredentialedLiquidityProvider):
    def __init__(self) -> None:
        super().__init__("polymarket", "https://gamma-api.polymarket.com", "POLYMARKET_API_TOKEN")


class KalshiLiquidityProvider(CredentialedLiquidityProvider):
    def __init__(self) -> None:
        super().__init__("kalshi", "https://api.elections.kalshi.com/trade-api/v2", "KALSHI_API_KEY")


class StaticOddsProvider:
    def __init__(self, matches: list[Match] | None = None) -> None:
        self._matches = matches or [
            Match("1", "Novak Djokovic", "Carlos Alcaraz", "1.80", "2.05"),
            Match("2", "Jannik Sinner", "Daniil Medvedev", "1.65", "2.30"),
            Match("3", "Taylor Fritz", "Alexander Zverev", "2.10", "1.72"),
            Match("4", "Stefanos Tsitsipas", "Matteo Berrettini", "1.95", "1.88"),
        ]

    def matches(self) -> list[Match]:
        return list(self._matches)

    def stale(self, match: Match, max_age_seconds: int = 3600) -> bool:
        return (datetime.now(timezone.utc) - match.odds_updated_at).total_seconds() > max_age_seconds

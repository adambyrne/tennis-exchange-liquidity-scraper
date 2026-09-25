from __future__ import annotations

import os
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from .fixtures import sample_snapshots
from .models import LiquiditySnapshot, Match
from .normalization import normalize_snapshot

try:
    import certifi
except ImportError:  # pragma: no cover - depends on the host Python installation
    certifi = None


class ProviderError(RuntimeError):
    pass


class PolymarketNotFoundError(ProviderError):
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


class PolymarketPublicLiquidityProvider:
    """Collect active tennis markets from Polymarket's public APIs.

    Market discovery and CLOB order books are public. This adapter intentionally
    does not place orders and does not require a token or wallet credentials.
    """

    name = "polymarket"
    gamma_endpoint = "https://gamma-api.polymarket.com/events"
    clob_endpoint = "https://clob.polymarket.com/book"

    def __init__(self, max_markets: int = 100, timeout_seconds: float = 15) -> None:
        self.max_markets = max_markets
        self.timeout_seconds = timeout_seconds

    def _get_json(self, url: str) -> object:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "tennis-exchange-liquidity-scraper/1.0",
            },
        )
        try:
            context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
            with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise PolymarketNotFoundError(f"Polymarket resource not found: {url}") from error
            raise ProviderError(f"Polymarket request failed for {url}: HTTP {error.code}") from error
        except (OSError, ValueError) as error:
            raise ProviderError(f"Polymarket request failed for {url}: {error}") from error

    @staticmethod
    def _is_tennis(market: dict) -> bool:
        text = " ".join(
            str(market.get(field, ""))
            for field in ("question", "slug", "description", "category", "tags", "event_name")
        ).lower()
        return any(term in text for term in ("tennis", "atp", "wta", "wimbledon", "roland garros", "us open"))

    @staticmethod
    def _competitors(question: str) -> tuple[str, ...]:
        for separator in (" vs. ", " vs ", " v. ", " v "):
            if separator in question.lower():
                parts = question.lower().split(separator, 1)
                return tuple(part.strip(" ?") for part in parts if part.strip(" ?"))
        return (question.strip(),) if question.strip() else ("Unknown",)

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        observed = observed_at or datetime.now(timezone.utc)
        markets: list[dict] = []
        offset = 0
        while len(markets) < self.max_markets:
            page_limit = min(100, self.max_markets - len(markets))
            query = urllib.parse.urlencode({
                "active": "true", "closed": "false", "limit": page_limit,
                "offset": offset, "tag_slug": "tennis",
            })
            page = self._get_json(f"{self.gamma_endpoint}?{query}")
            if not isinstance(page, list) or not page:
                break
            for event in page:
                if not isinstance(event, dict):
                    continue
                for market in event.get("markets", []):
                    if isinstance(market, dict):
                        enriched = dict(market)
                        enriched.setdefault("event_id", event.get("id"))
                        enriched.setdefault("event_name", event.get("title") or event.get("slug"))
                        markets.append(enriched)
                        if len(markets) >= self.max_markets:
                            break
                if len(markets) >= self.max_markets:
                    break
            if len(page) < page_limit:
                break
            offset += len(page)

        snapshots: list[LiquiditySnapshot] = []
        for market in markets:
            if not self._is_tennis(market):
                continue
            token_ids = market.get("clobTokenIds", "[]")
            try:
                token_ids = json.loads(token_ids) if isinstance(token_ids, str) else token_ids
            except ValueError:
                token_ids = []
            if not token_ids:
                continue
            try:
                book = self._get_json(
                    f"{self.clob_endpoint}?{urllib.parse.urlencode({'token_id': token_ids[0]})}"
                )
            except PolymarketNotFoundError:
                # Active Gamma markets can have outcome tokens without a CLOB book yet.
                continue
            if not isinstance(book, dict):
                continue
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            bid_liquidity = sum(Decimal(str(item["price"])) * Decimal(str(item["size"])) for item in bids)
            ask_liquidity = sum(Decimal(str(item["size"])) for item in asks)
            raw = {"market": market, "order_book": book}
            snapshots.append(normalize_snapshot({
                "event_id": market.get("event_id") or market.get("conditionId") or market.get("id"),
                "market_id": market.get("id") or market.get("conditionId"),
                "event_name": market.get("event_name") or market.get("question") or market.get("slug") or "Tennis market",
                "market_name": "Polymarket CLOB",
                "competitors": self._competitors(str(market.get("question", ""))),
                "start_time": market.get("startDate") or observed.isoformat(),
                "available_back": bid_liquidity,
                "available_unmatched": ask_liquidity,
                "matched_volume": market.get("volume", 0),
                "currency": "USDC",
                "source_url": f"https://polymarket.com/event/{market.get('slug', '')}",
                "raw": raw,
            }, self.name, observed))
        return snapshots


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

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

from .models import LiquiditySnapshot, Match
from .classification import classify_event
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

    def __init__(self, max_events: int | None = None, timeout_seconds: float = 15) -> None:
        self.max_events = max_events
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
    def _competitors(question: str) -> tuple[str, ...]:
        for separator in (" vs. ", " vs ", " v. ", " v "):
            index = question.casefold().find(separator)
            if index >= 0:
                parts = (question[:index], question[index + len(separator):])
                return tuple(part.strip(" ?") for part in parts if part.strip(" ?"))
        return (question.strip(),) if question.strip() else ("Unknown",)

    @staticmethod
    def _is_match_winner_market(market: dict, event_name: str) -> bool:
        question = " ".join(str(market.get("question", "")).split()).casefold()
        title = " ".join(event_name.split()).casefold()
        return bool(question and title and question == title)

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        observed = observed_at or datetime.now(timezone.utc)
        events: list[dict] = []
        offset = 0
        while self.max_events is None or len(events) < self.max_events:
            page_limit = (
                100 if self.max_events is None
                else min(100, self.max_events - len(events))
            )
            query = urllib.parse.urlencode({
                "active": "true", "closed": "false", "limit": page_limit,
                "offset": offset, "tag_slug": "tennis", "order": "endDate", "ascending": "true",
            })
            page = self._get_json(f"{self.gamma_endpoint}?{query}")
            if not isinstance(page, list) or not page:
                break
            events.extend(event for event in page if isinstance(event, dict))
            if len(page) < page_limit:
                break
            offset += len(page)

        snapshots: list[LiquiditySnapshot] = []
        for event in events:
            event_name = str(event.get("title") or event.get("slug") or "")
            if not event_name:
                continue
            market = next((
                market for market in event.get("markets", [])
                if isinstance(market, dict)
                and self._is_match_winner_market(market, event_name)
            ), None)
            if market is None:
                continue
            raw_token_ids = market.get("clobTokenIds", "[]")
            try:
                token_ids = json.loads(raw_token_ids) if isinstance(raw_token_ids, str) else raw_token_ids
            except ValueError:
                token_ids = []
            if not isinstance(token_ids, list) or not token_ids:
                continue
            books: list[dict] = []
            for token_id in token_ids[:2]:
                try:
                    book = self._get_json(
                        f"{self.clob_endpoint}?{urllib.parse.urlencode({'token_id': token_id})}"
                    )
                except PolymarketNotFoundError:
                    continue
                if isinstance(book, dict):
                    books.append(book)
            if not books:
                continue
            bids = [level for book in books for level in book.get("bids", [])]
            asks = [level for book in books for level in book.get("asks", [])]
            bid_liquidity = sum(Decimal(str(item["price"])) * Decimal(str(item["size"])) for item in bids)
            ask_liquidity = sum(Decimal(str(item["size"])) for item in asks)
            market = {
                **market,
                "event_id": event.get("id"),
                "event_name": event_name,
                "event_start_time": event.get("startTime") or event.get("startDate"),
                "event_sport": event.get("sport"),
                "event_series": event.get("series"),
            }
            raw = {"market": market, "order_books": books}
            sport = event.get("sport")
            sport_names = [
                sport.get("name", ""), sport.get("sport", ""),
            ] if isinstance(sport, dict) else [str(sport or "")]
            series_names = [
                str(series.get("title", ""))
                for series in event.get("series", [])
                if isinstance(series, dict)
            ]
            grade = classify_event(event_name)
            if grade.value == "unknown":
                grade = classify_event(" ".join([*sport_names, *series_names]))
            snapshots.append(normalize_snapshot({
                "event_id": market.get("event_id") or market.get("conditionId") or market.get("id"),
                "market_id": market.get("id") or market.get("conditionId"),
                "event_name": event_name,
                "market_name": "Match Winner",
                "competitors": self._competitors(str(market.get("question", ""))),
                "start_time": market.get("event_start_time") or market.get("startTime")
                or market.get("startDate") or observed.isoformat(),
                "available_back": bid_liquidity,
                "available_unmatched": ask_liquidity,
                "matched_volume": market.get("volume", 0),
                "grade": market.get("grade") or grade.value,
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

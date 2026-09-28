from __future__ import annotations

import os
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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

_MAX_CONCURRENT_REQUESTS = 8
_MAX_CONCURRENT_DISCOVERY_REQUESTS = 4
_RATE_LIMIT_RETRIES = 3


def _rate_limit_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After")
    try:
        delay = float(retry_after) if retry_after is not None else float(2 ** attempt)
    except ValueError:
        delay = float(2 ** attempt)
    return min(max(delay, 0.0), 30.0)


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
        context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise PolymarketNotFoundError(f"Polymarket resource not found: {url}") from error
                if error.code == 429 and attempt < _RATE_LIMIT_RETRIES:
                    time.sleep(_rate_limit_delay(error, attempt))
                    continue
                raise ProviderError(f"Polymarket request failed for {url}: HTTP {error.code}") from error
            except (OSError, ValueError) as error:
                raise ProviderError(f"Polymarket request failed for {url}: {error}") from error

    @staticmethod
    def _competitors(question: str) -> tuple[str, ...]:
        for separator in (" vs. ", " vs ", " v. ", " v "):
            index = question.casefold().find(separator)
            if index >= 0:
                parts = (question[:index].rsplit(":", 1)[-1], question[index + len(separator):])
                return tuple(part.strip(" ?") for part in parts if part.strip(" ?"))
        return (question.strip(),) if question.strip() else ("Unknown",)

    @staticmethod
    def _is_match_winner_market(market: dict, event_name: str) -> bool:
        question = " ".join(str(market.get("question", "")).split()).casefold()
        title = " ".join(event_name.split()).casefold()
        return bool(question and title and question == title)

    def _snapshot_for_event(
        self, event: dict, observed: datetime,
    ) -> LiquiditySnapshot | None:
        event_name = str(event.get("title") or event.get("slug") or "")
        if not event_name:
            return None
        market = next((
            item for item in event.get("markets", [])
            if isinstance(item, dict) and self._is_match_winner_market(item, event_name)
        ), None)
        if market is None:
            return None
        raw_token_ids = market.get("clobTokenIds", "[]")
        try:
            token_ids = json.loads(raw_token_ids) if isinstance(raw_token_ids, str) else raw_token_ids
        except ValueError:
            token_ids = []
        if not isinstance(token_ids, list) or not token_ids:
            return None
        books: list[dict] = []
        # The first outcome's bids and asks provide the two-sided view; fetching
        # the complementary outcome's book repeats a network request and isn't
        # used in the normalized liquidity totals.
        for token_id in token_ids[:1]:
            try:
                book = self._get_json(
                    f"{self.clob_endpoint}?{urllib.parse.urlencode({'token_id': token_id})}"
                )
            except PolymarketNotFoundError:
                continue
            if isinstance(book, dict):
                books.append(book)
        if not books:
            return None
        # One binary outcome's bids and asks represent both sides of this market.
        bids = books[0].get("bids", [])
        asks = books[0].get("asks", [])
        bid_liquidity = sum(Decimal(str(item["price"])) * Decimal(str(item["size"])) for item in bids)
        ask_liquidity = sum(Decimal(str(item["price"])) * Decimal(str(item["size"])) for item in asks)
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
        return normalize_snapshot({
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
        }, self.name, observed)

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        observed = observed_at or datetime.now(timezone.utc)
        events: list[dict] = []
        offset = 0
        while self.max_events is None or len(events) < self.max_events:
            page_limit = 100 if self.max_events is None else min(100, self.max_events - len(events))
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

        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_REQUESTS) as executor:
            snapshots = list(executor.map(
                lambda event: self._snapshot_for_event(event, observed), events,
            ))
        return [snapshot for snapshot in snapshots if snapshot is not None]


class KalshiPublicLiquidityProvider:
    """Collect active tennis match-winner markets from Kalshi's public market-data API."""

    name = "kalshi"
    endpoint = "https://api.elections.kalshi.com/trade-api/v2"
    _excluded_series_terms = ("table tennis", "pickleball", "tiebreak", "set", "game", "score", "total")

    def __init__(self, max_events: int | None = None, timeout_seconds: float = 15) -> None:
        self.max_events = max_events
        self.timeout_seconds = timeout_seconds
        self._series_cache: list[tuple[str, str]] | None = None

    def _get_json(self, path: str, params: dict[str, object] | None = None) -> object:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.endpoint}/{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "tennis-exchange-liquidity-scraper/1.0",
            },
        )
        context = ssl.create_default_context(cafile=certifi.where()) if certifi else None
        for attempt in range(_RATE_LIMIT_RETRIES + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                if error.code == 429 and attempt < _RATE_LIMIT_RETRIES:
                    time.sleep(_rate_limit_delay(error, attempt))
                    continue
                raise ProviderError(f"Kalshi request failed for {url}: HTTP {error.code}") from error
            except (OSError, ValueError) as error:
                raise ProviderError(f"Kalshi request failed for {url}: {error}") from error

    def _tennis_match_series(self) -> list[tuple[str, str]]:
        if self._series_cache is not None:
            return self._series_cache
        response = self._get_json("series", {"category": "Sports"})
        if not isinstance(response, dict) or not isinstance(response.get("series"), list):
            raise ProviderError("Kalshi returned an invalid series list")
        series = []
        for item in response["series"]:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "")
            title = str(item.get("title") or "")
            tags = item.get("tags", [])
            tag_names = [
                str(tag.get("name", "")) if isinstance(tag, dict) else str(tag)
                for tag in tags
            ] if isinstance(tags, list) else []
            title_lower = title.casefold()
            if (
                ticker
                and "tennis" in {tag.casefold() for tag in tag_names}
                and "match" in title_lower
                and not any(term in title_lower for term in self._excluded_series_terms)
            ):
                series.append((ticker, title))
        self._series_cache = sorted(series)
        return self._series_cache

    @staticmethod
    def _event_competitors(markets: list[dict]) -> tuple[str, ...]:
        names = []
        for market in markets:
            title = str(market.get("title") or "").strip()
            if title.casefold().endswith(" wins"):
                name = title[:-5].strip()
                if name and name not in names:
                    names.append(name)
        return tuple(names)

    @staticmethod
    def _side_notional(levels: object) -> Decimal:
        if not isinstance(levels, list):
            return Decimal("0")
        total = Decimal("0")
        for level in levels:
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                total += Decimal(str(level[0])) * Decimal(str(level[1]))
        return total

    def _events_for_series(self, series: tuple[str, str]) -> list[tuple[dict, str, str]]:
        series_ticker, series_title = series
        results: list[tuple[dict, str, str]] = []
        cursor: str | None = None
        while True:
            params: dict[str, object] = {
                "status": "open",
                "series_ticker": series_ticker,
                "limit": 200,
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor
            response = self._get_json("events", params)
            if not isinstance(response, dict) or not isinstance(response.get("events"), list):
                raise ProviderError(f"Kalshi returned invalid events for series {series_ticker}")
            events = response["events"]
            results.extend(
                (event, series_ticker, series_title)
                for event in events if isinstance(event, dict)
            )
            cursor = response.get("cursor")
            if not cursor or not events:
                break
        return results

    def _snapshot_for_event(
        self, item: tuple[dict, str, str], observed: datetime,
    ) -> LiquiditySnapshot | None:
        event, series_ticker, series_title = item
        event_ticker = str(event.get("event_ticker") or "")
        markets = event.get("markets")
        if not event_ticker or not isinstance(markets, list):
            return None
        valid_markets = [market for market in markets if isinstance(market, dict)]
        competitors = self._event_competitors(valid_markets)
        if len(competitors) != 2:
            return None
        winner_markets = sorted(
            (market for market in valid_markets
             if str(market.get("title", "")).casefold().endswith(" wins")
             and str(market.get("status") or "active").casefold() in {"active", "open"}),
            key=lambda market: str(market.get("ticker", "")),
        )
        if not winner_markets:
            return None
        market = winner_markets[0]
        market_ticker = str(market.get("ticker") or "")
        if not market_ticker:
            return None
        book_response = self._get_json(
            f"markets/{urllib.parse.quote(market_ticker, safe='')}/orderbook"
        )
        if not isinstance(book_response, dict):
            raise ProviderError(f"Kalshi returned invalid order book for market {market_ticker}")
        orderbook = book_response.get("orderbook_fp", {})
        if not isinstance(orderbook, dict):
            raise ProviderError(f"Kalshi returned invalid order book for market {market_ticker}")
        yes_liquidity = self._side_notional(orderbook.get("yes_dollars"))
        no_liquidity = self._side_notional(orderbook.get("no_dollars"))
        grade = classify_event(f"{series_title} {event.get('title', '')}")
        return normalize_snapshot({
            "event_id": event_ticker,
            "market_id": market_ticker,
            "event_name": str(event.get("title") or event_ticker),
            "market_name": "Match Winner",
            "competitors": competitors,
            "start_time": market.get("open_time") or observed.isoformat(),
            "available_back": yes_liquidity,
            "available_unmatched": no_liquidity,
            "matched_volume": market.get("volume_fp") or market.get("volume", 0),
            "grade": grade.value,
            "currency": "USD",
            "source_url": f"https://kalshi.com/markets/{series_ticker}/{event_ticker}/{market_ticker}",
            "raw": {
                "series": {"ticker": series_ticker, "title": series_title},
                "event": event,
                "market": market,
                "orderbook": orderbook,
            },
        }, self.name, observed)

    def snapshots(self, observed_at: datetime | None = None) -> list[LiquiditySnapshot]:
        observed = observed_at or datetime.now(timezone.utc)
        series = self._tennis_match_series()
        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_DISCOVERY_REQUESTS) as executor:
            event_groups = executor.map(self._events_for_series, series)
            events = [item for group in event_groups for item in group]
        unique_events = []
        seen_events: set[str] = set()
        for event, ticker, title in events:
            event_ticker = str(event.get("event_ticker") or "")
            if event_ticker and event_ticker not in seen_events:
                seen_events.add(event_ticker)
                unique_events.append((event, ticker, title))
        if self.max_events is not None:
            unique_events = unique_events[:self.max_events]
        with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_REQUESTS) as executor:
            snapshots = list(executor.map(
                lambda item: self._snapshot_for_event(item, observed), unique_events,
            ))
        return [snapshot for snapshot in snapshots if snapshot is not None]


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

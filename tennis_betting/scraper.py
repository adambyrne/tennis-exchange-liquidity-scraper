from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Iterable

from .models import LiquiditySnapshot
from .providers import LiquidityProvider
from .storage import replace_snapshots


def collect_once(providers: Iterable[LiquidityProvider], connection) -> list[LiquiditySnapshot]:
    observed_at = datetime.now(timezone.utc)
    provider_list = list(providers)
    if not provider_list:
        raise ValueError("at least one liquidity provider is required")
    with ThreadPoolExecutor(max_workers=len(provider_list)) as executor:
        provider_results = list(executor.map(
            lambda provider: provider.snapshots(observed_at), provider_list,
        ))
    snapshots_by_key: dict[tuple[str, str, datetime], LiquiditySnapshot] = {}
    for snapshot in (item for result in provider_results for item in result):
        key = (snapshot.provider, snapshot.source_market_id, snapshot.observed_at)
        snapshots_by_key.setdefault(key, snapshot)
    snapshots = list(snapshots_by_key.values())
    replace_snapshots(connection, snapshots)
    return snapshots


def collection_summary(
    providers: Iterable[LiquidityProvider], snapshots: list[LiquiditySnapshot],
) -> str:
    counts = Counter(snapshot.provider for snapshot in snapshots)
    providers_text = ", ".join(
        f"{provider.name.title()}: {counts[provider.name]}" for provider in providers
    )
    return f"Collected {len(snapshots)} snapshots ({providers_text})"


def backfill(provider, connection, start: datetime, end: datetime) -> int:
    """Persist a provider's historical page without inventing missing observations.

    Live adapters can opt into this boundary once their official historical API
    and pagination semantics are implemented.
    """
    fetch = getattr(provider, "backfill", None)
    if fetch is None:
        raise NotImplementedError(f"{provider.name} does not expose historical backfill")
    snapshots = list(fetch(start, end))
    return save_snapshots(connection, snapshots)


def run_scheduler(providers: Iterable[LiquidityProvider], connection, interval_seconds: int = 600) -> None:
    if interval_seconds < 1:
        raise ValueError("interval must be positive")
    provider_list = list(providers)
    while True:
        snapshots = collect_once(provider_list, connection)
        print(collection_summary(provider_list, snapshots))
        time.sleep(interval_seconds)

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterable

from .models import LiquiditySnapshot
from .providers import LiquidityProvider
from .storage import save_snapshots


def collect_once(providers: Iterable[LiquidityProvider], connection) -> list[LiquiditySnapshot]:
    observed_at = datetime.now(timezone.utc)
    snapshots: list[LiquiditySnapshot] = []
    for provider in providers:
        snapshots.extend(provider.snapshots(observed_at))
    save_snapshots(connection, snapshots)
    return snapshots


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
    while True:
        collect_once(providers, connection)
        time.sleep(interval_seconds)

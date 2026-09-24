from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


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

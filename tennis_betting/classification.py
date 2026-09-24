from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from .models import CompetitionGrade

_RULES = (
    (CompetitionGrade.GRAND_SLAM, ("grand slam", "australian open", "roland garros", "wimbledon", "us open")),
    (CompetitionGrade.ATP_CHALLENGER, ("challenger",)),
    (CompetitionGrade.ITF, ("itf",)),
    (CompetitionGrade.UTR, ("utr",)),
    (CompetitionGrade.WTA, ("wta",)),
    (CompetitionGrade.ATP, ("atp",)),
)


def classify_event(name: str, override: CompetitionGrade | str | None = None) -> CompetitionGrade:
    if override is not None:
        return override if isinstance(override, CompetitionGrade) else CompetitionGrade(override)
    text = re.sub(r"[^a-z0-9]+", " ", name.lower())
    for grade, terms in _RULES:
        if any(term in text for term in terms):
            return grade
    return CompetitionGrade.UNKNOWN


@dataclass
class ClassificationOverrides:
    """Manual exceptions persisted by callers in the override table."""

    values: dict[str, CompetitionGrade]

    @classmethod
    def from_connection(cls, connection: sqlite3.Connection) -> "ClassificationOverrides":
        rows = connection.execute("SELECT event_key, grade FROM classification_overrides").fetchall()
        return cls({row[0]: CompetitionGrade(row[1]) for row in rows})

    def grade(self, event_key: str, event_name: str) -> CompetitionGrade:
        return classify_event(event_name, self.values.get(event_key))

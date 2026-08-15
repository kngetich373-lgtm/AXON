from __future__ import annotations
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Activity:
    event: str
    timestamp: str
    data: dict[str, Any]

class ActivityLog:
    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
        self.entries: list[Activity] = []

    def record(self, event: str, **data: Any) -> Activity:
        item = Activity(event, datetime.now(timezone.utc).isoformat(), data)
        self.entries.append(item)
        del self.entries[:-self.max_entries]
        return item

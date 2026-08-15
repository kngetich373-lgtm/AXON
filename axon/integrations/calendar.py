"""Calendar integration contract used by the AXON planning engine."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class CalendarEvent:
    title: str
    start: datetime
    end: datetime
    calendar: str | None = None
    event_id: str | None = None

class CalendarIntegration:
    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        raise NotImplementedError

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        raise NotImplementedError

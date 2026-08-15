"""Small synchronous event bus for decoupled AXON components."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass(frozen=True)
class Event:
    name: str
    data: dict[str, Any] = field(default_factory=dict)

class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, name: str, handler: Callable[[Event], None]) -> None:
        if handler not in self._handlers[name]:
            self._handlers[name].append(handler)

    def publish(self, name: str, **data: Any) -> Event:
        event = Event(name, data)
        for handler in tuple(self._handlers.get(name, ())):
            try:
                handler(event)
            except Exception:
                # Observers must never break the operation that emitted an event.
                continue
        return event

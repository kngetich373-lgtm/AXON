from __future__ import annotations
from .base import Integration

class IntegrationRegistry:
    def __init__(self):
        self._items: dict[str, Integration] = {}

    def register(self, integration: Integration) -> None:
        key = integration.info.name.lower()
        if key in self._items:
            raise ValueError(f"Integration already registered: {key}")
        self._items[key] = integration

    def get(self, name: str) -> Integration | None:
        return self._items.get(name.lower())

    def list(self) -> list[Integration]:
        return sorted(self._items.values(), key=lambda x: x.info.name.lower())

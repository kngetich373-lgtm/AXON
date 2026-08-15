"""Provider-neutral interfaces for future external AXON integrations."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class IntegrationInfo:
    name: str
    description: str
    scopes: tuple[str, ...] = ()

class Integration(ABC):
    info: IntegrationInfo

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> None: ...

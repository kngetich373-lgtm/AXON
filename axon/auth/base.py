from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class AuthState:
    provider: str
    connected: bool
    account_label: str | None = None
    scopes: tuple[str, ...] = ()

class AuthProvider(ABC):
    provider_name: str

    @abstractmethod
    def status(self) -> AuthState: ...

    @abstractmethod
    def begin(self, scopes: tuple[str, ...] = ()) -> AuthState: ...

    @abstractmethod
    def revoke(self) -> None: ...

"""Shared structured results for governed workspace actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, message: str, **data: Any) -> "ActionResult":
        return cls(True, message, data)

    @classmethod
    def failure(cls, message: str, error: str | None = None, **data: Any) -> "ActionResult":
        return cls(False, message, data, error)


@dataclass(frozen=True)
class ActionPlan:
    """A user-visible description shown before a governed action runs."""
    title: str
    summary: str
    details: str
    requires_confirmation: bool = True


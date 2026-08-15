"""Structured execution context shared by AXON's agent and tools."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Context:
    user_id: str | None = None
    session_id: str | None = None
    request: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    memories: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)

    def add_result(self, name: str, ok: bool, **data: Any) -> None:
        self.results.append({"name": name, "ok": ok, "data": data})

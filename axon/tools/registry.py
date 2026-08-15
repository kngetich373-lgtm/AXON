"""Central capability registry for AXON V15.

Existing V14 tools can be registered without rewriting them. This is deliberately
small and dependency-light so it can become the stable boundary for future tools
and integrations.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable
from axon.actions import ActionResult
from axon.security import PermissionManager, Risk

@dataclass
class ToolSpec:
    name: str
    description: str
    handler: Callable[..., Any]
    risk: Risk = Risk.MEDIUM
    requires_confirmation: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

class ToolRegistry:
    def __init__(self, permissions: PermissionManager | None = None):
        self.permissions = permissions or PermissionManager()
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec | None = None, **kwargs: Any) -> ToolSpec:
        if spec is None:
            spec = ToolSpec(**kwargs)
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def decorator(self, name: str, description: str, *, risk: Risk = Risk.MEDIUM, requires_confirmation: bool = True):
        def wrap(fn):
            self.register(ToolSpec(name, description, fn, risk, requires_confirmation))
            return fn
        return wrap

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list(self) -> list[ToolSpec]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def execute(self, name: str, *args: Any, confirmed: bool = False, context=None, **kwargs: Any) -> ActionResult:
        spec = self.get(name)
        if spec is None:
            return ActionResult.failure(f"Unknown AXON tool: {name}")
        decision = self.permissions.check(name, spec.risk, confirmed=confirmed)
        if not decision.allowed:
            return ActionResult.failure(f"Blocked by AXON security policy: {decision.reason}")
        if decision.requires_confirmation and spec.requires_confirmation:
            return ActionResult.failure(f"Confirmation required before running {name}.", requires_confirmation=True, risk=int(spec.risk))
        try:
            result = spec.handler(*args, context=context, **kwargs)
            return result if isinstance(result, ActionResult) else ActionResult.success(f"Tool {name} completed.", result=result)
        except Exception as exc:
            return ActionResult.failure(f"Tool {name} failed.", str(exc))

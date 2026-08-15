"""Deterministic task planning primitives for AXON V15."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class PlanStep:
    id: str
    title: str
    action: Callable[..., Any] | None = None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    requires_confirmation: bool = False

class Planner:
    def build(self, steps: list[PlanStep]) -> list[PlanStep]:
        """Validate dependencies and return a stable topological execution order."""
        by_id = {s.id: s for s in steps}
        if len(by_id) != len(steps):
            raise ValueError("Plan contains duplicate step IDs")
        for step in steps:
            missing = [dep for dep in step.depends_on if dep not in by_id]
            if missing:
                raise ValueError(f"Step {step.id!r} depends on unknown steps: {missing}")
        ordered: list[PlanStep] = []
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(step: PlanStep) -> None:
            if step.id in visiting:
                raise ValueError("Plan contains a dependency cycle")
            if step.id in visited:
                return
            visiting.add(step.id)
            for dep in step.depends_on:
                visit(by_id[dep])
            visiting.remove(step.id)
            visited.add(step.id)
            ordered.append(step)
        for step in steps:
            visit(step)
        return ordered

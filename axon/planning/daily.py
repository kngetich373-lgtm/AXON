"""Deterministic daily planning primitives; external calendars can feed these later."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date

@dataclass
class Task:
    title: str
    priority: int = 3
    duration_minutes: int = 30
    deadline: str | None = None
    tags: tuple[str, ...] = ()

@dataclass
class DailyPlan:
    day: date
    tasks: list[Task] = field(default_factory=list)

    def ordered_tasks(self) -> list[Task]:
        return sorted(self.tasks, key=lambda t: (-t.priority, t.deadline or "9999-12-31"))

class DailyPlanner:
    def build(self, tasks: list[Task], day: date | None = None) -> DailyPlan:
        return DailyPlan(day or date.today(), list(tasks))

"""Plan executor that delegates capability access to the Tool Registry."""
from __future__ import annotations
from typing import Any
from .event_bus import EventBus
from .planner import Planner, PlanStep
from axon.actions import ActionResult

class Executor:
    def __init__(self, registry=None, permissions=None, event_bus: EventBus | None = None):
        self.registry = registry
        self.permissions = permissions
        self.events = event_bus or EventBus()

    def execute(self, steps: list[PlanStep], *, context=None) -> list[ActionResult]:
        ordered = Planner().build(steps)
        results: list[ActionResult] = []
        completed: set[str] = set()
        for step in ordered:
            if any(dep not in completed for dep in step.depends_on):
                results.append(ActionResult.failure(f"Skipped step {step.id}: dependency failed."))
                continue
            self.events.publish("tool.started", step=step.id, title=step.title)
            try:
                if self.registry and step.action is None:
                    result = self.registry.execute(step.id, *step.args, context=context, **step.kwargs)
                elif step.action:
                    result = step.action(*step.args, **step.kwargs)
                else:
                    result = ActionResult.failure(f"No action registered for step {step.id}.")
                if not isinstance(result, ActionResult):
                    result = ActionResult.success(f"Completed {step.title}.", result=result)
            except Exception as exc:
                result = ActionResult.failure(f"Step failed: {step.title}", str(exc))
            results.append(result)
            self.events.publish("tool.completed", step=step.id, ok=result.ok, message=result.message)
            if result.ok:
                completed.add(step.id)
        return results

"""AXON V15 agent facade. It orchestrates existing AXON capabilities without replacing them."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from .context import Context
from .event_bus import EventBus
from .planner import Planner, PlanStep
from .executor import Executor
from axon.skills import SkillRegistry
from axon.memory import MemoryManager
from axon.knowledge import ProjectKnowledge

@dataclass
class AgentResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

class Agent:
    def __init__(self, router=None, memory=None, registry=None, permissions=None, event_bus=None, skills=None, layered_memory=None, knowledge=None):
        self.router = router
        self.memory = memory
        self.registry = registry
        self.events = event_bus or EventBus()
        self.planner = Planner()
        self.executor = Executor(registry, permissions, self.events)
        self.skills = skills or SkillRegistry()
        self.layered_memory = layered_memory or MemoryManager()
        self.knowledge = knowledge

    def understand(self, request: str) -> Context:
        ctx = Context(request=request)
        try:
            ctx.metadata["skills"] = [s.name for s in self.skills.match(request)[:3]]
            ctx.metadata["skill_context"] = self.skills.render_context(request)
            if self.knowledge is not None:
                ctx.metadata["knowledge_matches"] = [n.__dict__ for n in self.knowledge.search(request, limit=8)]
            ctx.memories.extend(self.layered_memory.context(request, limit=8))
        except Exception:
            pass
        if self.memory is not None:
            try:
                legacy = self.memory.relevant_context(request)
                if legacy:
                    ctx.memories.extend(legacy)
            except AttributeError:
                pass
        return ctx

    def handle(self, request: str, ui=None) -> AgentResult:
        ctx = self.understand(request)
        self.events.publish("agent.started", request=request)
        if self.router is None:
            return AgentResult(False, "AXON Agent has no compatible router configured.")
        try:
            result = self.router.route(request, ui)
            if result is not None:
                try: self.layered_memory.add("l0", "agent_action", f"request={request}; result={result.message}")
                except Exception: pass
                return AgentResult(result.ok, result.message, result.data)
            answer = self.router.answer(request)
            message = answer[0] if isinstance(answer, tuple) else str(answer)
            try: self.layered_memory.add("l0", "conversation", f"request={request}; response={message}")
            except Exception: pass
            return AgentResult(True, message, {"model": answer[1:] if isinstance(answer, tuple) else None})
        finally:
            self.events.publish("agent.completed", request=request)

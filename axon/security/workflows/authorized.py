"""Authorized cybersecurity workflow primitives.
No workflow executes a target action by itself; scope and permission checks are
explicit prerequisites and actual execution remains delegated to AXON tools.
"""
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Scope:
    targets: tuple[str, ...]
    authorization_ref: str
    restrictions: tuple[str, ...] = ()

@dataclass
class SecurityWorkflow:
    name: str
    scope: Scope | None = None
    evidence: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)

    def authorize(self, scope: Scope):
        if not scope.targets or not scope.authorization_ref.strip():
            raise ValueError("An explicit authorized scope and authorization reference are required")
        self.scope = scope
        return True

    def add_evidence(self, kind, value, *, source=None):
        self.evidence.append({"kind":kind,"value":value,"source":source})

    def add_finding(self, title, severity, description, *, evidence=None):
        item={"title":title,"severity":severity,"description":description,"evidence":evidence or []}
        self.findings.append(item); return item

    def report(self):
        return {"workflow":self.name,"scope":self.scope.targets if self.scope else [],"findings":list(self.findings),"evidence":list(self.evidence)}

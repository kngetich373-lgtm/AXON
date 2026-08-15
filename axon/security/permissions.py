"""Centralized capability permission policy for AXON V15."""
from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum

class Risk(IntEnum):
    LOW = 10
    MEDIUM = 30
    HIGH = 60
    CRITICAL = 90

@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str
    risk: Risk

class PermissionManager:
    def __init__(self, auto_confirm_max: Risk = Risk.LOW):
        self.auto_confirm_max = auto_confirm_max
        self._overrides: dict[str, bool] = {}

    def set_override(self, capability: str, allowed: bool) -> None:
        self._overrides[capability] = allowed

    def check(self, capability: str, risk: Risk, *, confirmed: bool = False) -> PermissionDecision:
        if capability in self._overrides and not self._overrides[capability]:
            return PermissionDecision(False, False, "Capability is disabled by policy.", risk)
        if confirmed:
            return PermissionDecision(True, False, "Explicitly approved for this action.", risk)
        if risk <= self.auto_confirm_max:
            return PermissionDecision(True, False, "Within automatic permission policy.", risk)
        return PermissionDecision(True, True, "User confirmation is required for this risk level.", risk)

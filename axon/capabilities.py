from __future__ import annotations
from dataclasses import dataclass, asdict
from importlib.util import find_spec
from pathlib import Path
from typing import Any

@dataclass
class CapabilityStatus:
    name: str
    status: str
    implemented: bool
    configured: bool
    available: bool
    executable: bool
    details: str = ""

class CapabilityAuditor:
    """Runtime truth source. Status is based on actual objects/imports/state."""
    def __init__(self, app=None):
        self.app = app

    def audit(self) -> list[CapabilityStatus]:
        a = self.app
        out = []
        out.append(self._obj("Agent Core", getattr(a, "agent", None), "Agent runtime object"))
        skills = getattr(a, "skills", None)
        count = len(skills.list()) if skills else 0
        out.append(CapabilityStatus("Skills", "WORKING" if count else "NOT AVAILABLE", True, True, bool(skills), bool(count), f"{count} SKILL.md skills discovered"))
        mem = getattr(a, "layered_memory", None)
        records = {}
        if mem:
            for layer in getattr(mem, "LAYERS", ("l0","l1","l2","l3")):
                records[layer] = len(mem.list(layer, limit=100000))
        out.append(CapabilityStatus("Layered Memory", "WORKING" if mem else "NOT IMPLEMENTED", bool(mem), bool(mem), bool(mem), bool(mem), f"records={records}"))
        kg = getattr(a, "knowledge", None)
        indexed = bool(getattr(kg, "indexed", False))
        nodes = len(getattr(getattr(kg, "graph", None), "nodes", {})) if kg else 0
        edges = len(getattr(getattr(kg, "graph", None), "edges", [])) if kg else 0
        out.append(CapabilityStatus("Knowledge Graph", "WORKING" if indexed else ("PARTIAL" if kg else "NOT IMPLEMENTED"), bool(kg), bool(kg), bool(kg), bool(kg and indexed), f"indexed={indexed}; nodes={nodes}; edges={edges}; root={getattr(kg,'root','')}"))
        perms = getattr(a, "permissions", None)
        out.append(CapabilityStatus("Security Controls", "WORKING" if perms else "NOT IMPLEMENTED", bool(perms), bool(perms), bool(perms), bool(perms), "Central PermissionManager"))
        reg = getattr(a, "tool_registry", None)
        out.append(CapabilityStatus("Tool Registry", "WORKING" if reg else "NOT IMPLEMENTED", bool(reg), bool(reg), bool(reg), bool(reg), f"registered={len(reg.list()) if reg else 0}"))
        integ = getattr(a, "integrations", None)
        if integ:
            connected = []
            for obj in (getattr(integ, "gmail", None), getattr(integ, "calendar", None), getattr(integ, "whatsapp", None), getattr(integ, "messenger", None), getattr(integ, "whatsapp_linked", None)):
                try:
                    if obj and obj.is_connected() if hasattr(obj, "is_connected") else obj and obj.status().get("connected"):
                        connected.append(getattr(getattr(obj, "info", None), "name", getattr(obj, "name", "integration")))
                except Exception:
                    pass
            out.append(CapabilityStatus("External Integrations", "WORKING" if connected else "NOT CONFIGURED", True, bool(connected), True, bool(connected), f"implemented: Gmail, Calendar, WhatsApp Cloud, WhatsApp linked-device, Meta Messenger; connected={connected}"))
        else:
            out.append(CapabilityStatus("External Integrations", "NOT IMPLEMENTED", False, False, False, False, "Integration manager missing"))
        out.append(CapabilityStatus("Browser", "WORKING" if find_spec("axon.browser_control") else "NOT IMPLEMENTED", bool(find_spec("axon.browser_control")), True, bool(find_spec("axon.browser_control")), bool(find_spec("axon.browser_control")), "Existing V14 browser control"))
        voice = getattr(a, "gemini_voice", None)
        voice_configured = bool(getattr(voice, "api_key", "")) if voice else False
        out.append(CapabilityStatus("Voice", "WORKING" if voice_configured else ("NOT CONFIGURED" if voice else "NOT IMPLEMENTED"), bool(voice), voice_configured, bool(voice), voice_configured, "Gemini Live configuration"))
        out.append(CapabilityStatus("Files", "WORKING" if find_spec("axon.file_tools") else "NOT IMPLEMENTED", bool(find_spec("axon.file_tools")), True, bool(find_spec("axon.file_tools")), bool(find_spec("axon.file_tools")), "Governed file/PDF tools"))
        return out

    def _obj(self, name, obj, details):
        ok = obj is not None
        return CapabilityStatus(name, "WORKING" if ok else "NOT IMPLEMENTED", ok, ok, ok, ok, details)

    def text(self) -> str:
        lines = ["AXON RUNTIME CAPABILITY AUDIT"]
        for s in self.audit():
            lines += [f"{s.name}: {s.status}", f"  implemented={s.implemented} configured={s.configured} available={s.available} executable={s.executable}", f"  {s.details}"]
        return "\n".join(lines)

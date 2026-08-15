"""AXON Agent Skills registry using SKILL.md files."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re

@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    instructions: str
    triggers: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

class SkillRegistry:
    def __init__(self, roots=None):
        default = Path(__file__).parent
        self.roots = [Path(x).expanduser() for x in (roots or [default])]
        self._skills: dict[str, Skill] = {}
        self.discover()

    def discover(self) -> list[Skill]:
        found = []
        for root in self.roots:
            if not root.exists(): continue
            for path in root.rglob("SKILL.md"):
                try:
                    skill = self._parse(path)
                    self._skills[skill.name.lower()] = skill; found.append(skill)
                except Exception: continue
        return sorted(found, key=lambda s: s.name)

    def _parse(self, path: Path) -> Skill:
        text = path.read_text(encoding="utf-8")
        meta, body = {}, text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                for line in parts[1].splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1); meta[k.strip()] = v.strip().strip('"\'')
                body = parts[2].lstrip()
        name = meta.get("name") or path.parent.name
        desc = meta.get("description") or self._heading_description(body)
        return Skill(name, desc, path, body, self._csv(meta.get("triggers")), self._csv(meta.get("required_tools")), self._csv(meta.get("required_permissions")), meta)

    @staticmethod
    def _csv(value): return tuple(x.strip() for x in str(value or "").split(",") if x.strip())
    @staticmethod
    def _heading_description(body):
        m = re.search(r"^#.*?\n+(.+)$", body, re.M)
        return m.group(1).strip() if m else ""

    def get(self, name): return self._skills.get(str(name).lower())
    def list(self): return sorted(self._skills.values(), key=lambda s: s.name)
    def match(self, request: str) -> list[Skill]:
        q = request.lower(); scored=[]
        for skill in self._skills.values():
            score = sum(1 for t in skill.triggers if t.lower() in q)
            if skill.name.lower() in q: score += 2
            if score: scored.append((score, skill))
        scored.sort(key=lambda x:x[0], reverse=True)
        return [x[1] for x in scored]
    def render_context(self, request: str, max_skills=3) -> str:
        skills = self.match(request)[:max_skills]
        return "\n\n".join(f"## Skill: {s.name}\n{s.instructions}" for s in skills)

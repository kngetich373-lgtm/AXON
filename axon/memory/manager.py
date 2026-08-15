"""Layered AXON memory inspired by agent-memory architectures.

L0: raw conversation/experience records
L1: atomic facts, preferences and constraints
L2: projects, missions and scenarios
L3: stable profile/patterns

This layer is intentionally file-backed and dependency-light so it can coexist
with AXON's existing Memory implementation and later migrate to a database.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
import json, re
from typing import Any

_SECRET = re.compile(r"(?:api[ _-]?key|secret|password|passphrase|access[ _-]?token|bearer\s+|private[ _-]?key)", re.I)

@dataclass(frozen=True)
class MemoryItem:
    id: str
    layer: str
    kind: str
    content: str
    source: str = "agent"
    visibility: str = "private"
    created_at: str = ""
    metadata: dict[str, Any] | None = None

class MemoryManager:
    LAYERS = ("l0", "l1", "l2", "l3")
    VISIBILITIES = ("private", "team", "restricted", "agent")

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or Path.home() / ".config" / "axon" / "memory").expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        for layer in self.LAYERS:
            (self.root / layer).mkdir(exist_ok=True)

    def add(self, layer: str, kind: str, content: str, *, source="agent", visibility="private", metadata=None) -> MemoryItem:
        layer = layer.lower()
        if layer not in self.LAYERS: raise ValueError(f"Unknown memory layer: {layer}")
        if visibility not in self.VISIBILITIES: raise ValueError(f"Unknown visibility: {visibility}")
        if _SECRET.search(f"{kind} {content}"): raise ValueError("AXON refuses to persist secrets in memory")
        stamp = datetime.now().isoformat(timespec="seconds")
        item = MemoryItem(f"{layer}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}", layer, str(kind), str(content), str(source), visibility, stamp, metadata or {})
        path = self.root / layer / f"{item.id}.json"
        path.write_text(json.dumps(asdict(item), ensure_ascii=False, indent=2), encoding="utf-8")
        return item

    def list(self, layer: str | None = None, *, visibility: str | None = None, limit: int = 100) -> list[MemoryItem]:
        layers = [layer] if layer else list(self.LAYERS)
        out: list[MemoryItem] = []
        for name in layers:
            if name not in self.LAYERS: continue
            for p in sorted((self.root / name).glob("*.json"), reverse=True):
                try:
                    data = json.loads(p.read_text(encoding="utf-8")); item = MemoryItem(**data)
                    if visibility is None or item.visibility == visibility: out.append(item)
                except Exception: continue
        return out[:max(0, limit)]

    def search(self, query: str, *, layers=None, visibility=None, limit=20) -> list[MemoryItem]:
        terms = [t.lower() for t in re.findall(r"[\w-]+", query) if len(t) > 1]
        if not terms: return []
        items = self.list(visibility=visibility, limit=5000)
        if layers: items = [x for x in items if x.layer in layers]
        scored = []
        for item in items:
            hay = f"{item.kind} {item.content} {item.source}".lower()
            score = sum(hay.count(t) for t in terms)
            if score: scored.append((score, item))
        scored.sort(key=lambda x: (x[0], x[1].created_at), reverse=True)
        return [x[1] for x in scored[:limit]]

    def context(self, query: str, *, visibility="private", limit=12) -> list[dict[str, Any]]:
        items = self.search(query, visibility=visibility, limit=limit)
        return [asdict(x) for x in items]

    def distill(self, *, source_layer="l0", target_layer="l1", kind="distilled", limit=20) -> list[MemoryItem]:
        """Create explicit, human-readable atomic memories from recent records.
        AXON never silently invents facts; callers provide/approve distilled text.
        """
        return self.list(source_layer, limit=limit)

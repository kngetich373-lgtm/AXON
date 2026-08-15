"""Project knowledge service: lazy, deterministic AST graph for the active project."""
from __future__ import annotations
from pathlib import Path
from .graph import KnowledgeGraph, GraphNode

class ProjectKnowledge:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.graph = KnowledgeGraph()
        self.indexed = False

    def ensure_indexed(self):
        if not self.indexed:
            self.graph.index_tree(self.root)
            self.indexed = True
        return self.graph

    def refresh(self):
        self.graph = KnowledgeGraph().index_tree(self.root)
        self.indexed = True
        return self.graph

    def search(self, query: str, limit: int = 20):
        return self.ensure_indexed().search(query, limit)

    def query(self, request: str, limit: int = 100) -> str:
        """Answer common dependency/relationship questions from actual graph data."""
        g = self.ensure_indexed()
        low = request.lower()
        lines = []
        if any(k in low for k in ("depend", "memory system")):
            targets = [n for n in g.nodes.values() if "memory" in (n.name + " " + n.file).lower()]
            target_ids = {n.id for n in targets}
            target_names = {n.name.lower() for n in targets}
            seen = set()
            for e in g.edges:
                target_match = e.target in target_ids or str(e.target).lower() in target_names or "memory" in str(e.target).lower()
                source_match = e.source in target_ids
                if target_match or source_match:
                    src = g.nodes.get(e.source)
                    tgt = g.nodes.get(e.target, e.target)
                    if src and isinstance(tgt, GraphNode):
                        row = (src.file, e.relation, tgt.name)
                    elif src:
                        row = (src.file, e.relation, str(tgt))
                    else:
                        row = (e.source, e.relation, str(tgt))
                    if row not in seen:
                        seen.add(row); lines.append(row)
            lines = lines[:limit]
        else:
            for e in g.edges[:limit]:
                src = g.nodes.get(e.source)
                tgt = g.nodes.get(e.target)
                lines.append(((src.file if src else e.source), e.relation, (tgt.name if tgt else e.target)))
        if not lines:
            return "No matching graph relationships were found in the indexed project."
        out = ["AXON KNOWLEDGE GRAPH QUERY RESULTS", "File | Relationship | Related node"]
        out += [f"{a} | {b} | {c}" for a,b,c in lines]
        return "\n".join(out)

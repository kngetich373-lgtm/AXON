"""Deterministic local knowledge graph for AXON projects.

Python source is parsed with the standard AST. No code is executed while
indexing. The graph is intentionally provider-neutral and can later be backed
by a graph database.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import ast, json

@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    name: str
    file: str
    line: int = 0

@dataclass(frozen=True)
class GraphEdge:
    source: str
    relation: str
    target: str

class KnowledgeGraph:
    def __init__(self): self.nodes: dict[str, GraphNode] = {}; self.edges: list[GraphEdge] = []
    def add_node(self, node): self.nodes[node.id] = node
    def add_edge(self, source, relation, target): self.edges.append(GraphEdge(source, relation, target))

    def index_python_file(self, path: str | Path):
        path=Path(path); tree=ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        module=str(path)
        mid=f"file:{path.resolve()}"; self.add_node(GraphNode(mid,"file",path.name,str(path),1))
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                nid=f"function:{path.resolve()}:{node.lineno}:{node.name}"; self.add_node(GraphNode(nid,"function",node.name,str(path),node.lineno)); self.add_edge(mid,"defines",nid)
            elif isinstance(node,ast.ClassDef):
                nid=f"class:{path.resolve()}:{node.lineno}:{node.name}"; self.add_node(GraphNode(nid,"class",node.name,str(path),node.lineno)); self.add_edge(mid,"defines",nid)
            elif isinstance(node,ast.Import):
                for alias in node.names: self.add_edge(mid,"imports",alias.name)
            elif isinstance(node,ast.ImportFrom):
                self.add_edge(mid,"imports",node.module or "")
        return self

    def index_tree(self, root: str | Path, extensions=(".py",)):
        root=Path(root)
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in extensions and ".venv" not in p.parts and "__pycache__" not in p.parts:
                try: self.index_python_file(p)
                except (SyntaxError,OSError): continue
        return self

    def search(self, query: str, limit=20):
        q=query.lower(); scored=[]
        for n in self.nodes.values():
            hay=f"{n.kind} {n.name} {n.file}".lower(); score=sum(hay.count(t) for t in q.split() if t)
            if score: scored.append((score,n))
        scored.sort(key=lambda x:x[0], reverse=True); return [n for _,n in scored[:limit]]

    def neighbors(self, node_id: str, relation: str | None = None):
        ids=[]
        for e in self.edges:
            if e.source==node_id and (relation is None or e.relation==relation): ids.append(e.target)
            if e.target==node_id and (relation is None or e.relation==relation): ids.append(e.source)
        return [self.nodes.get(x, x) for x in ids]

    def to_dict(self): return {"nodes":[asdict(x) for x in self.nodes.values()],"edges":[asdict(x) for x in self.edges]}
    def save(self,path): Path(path).write_text(json.dumps(self.to_dict(),indent=2),encoding="utf-8")

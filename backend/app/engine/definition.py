"""The versioned workflow JSON format (schema_version 1)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1
MAX_NODES = 200
MAX_EDGES = 500


class RetrySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=1, ge=1, le=5)
    delay_ms: int = Field(default=1000, ge=0, le=60_000)
    backoff: float = Field(default=2.0, ge=1.0, le=5.0)
    # Non-idempotent nodes are never retried unless this is explicitly true.
    allow_non_idempotent: bool = False


class NodeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retry: RetrySettings = Field(default_factory=RetrySettings)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    on_error: Literal["stop", "continue", "error_branch"] = "stop"


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = 0
    y: float = 0


class NodeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    type: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1000)
    position: Position = Field(default_factory=Position)
    config: dict[str, Any] = Field(default_factory=dict)
    settings: NodeSettings = Field(default_factory=NodeSettings)


class EdgeDef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    source: str
    source_port: str = "main"
    target: str
    target_port: str = "main"


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = SCHEMA_VERSION
    nodes: list[NodeDef] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[EdgeDef] = Field(default_factory=list, max_length=MAX_EDGES)

    def node(self, node_id: str) -> NodeDef | None:
        return next((n for n in self.nodes if n.id == node_id), None)


def empty_definition() -> dict:
    return WorkflowDefinition().model_dump()


def definition_hash(definition: dict) -> str:
    """Content hash ignoring canvas positions (moving a node is not a new version)."""
    copy = {
        "nodes": [{k: v for k, v in n.items() if k != "position"} for n in definition.get("nodes", [])],
        "edges": definition.get("edges", []),
    }
    return hashlib.sha256(json.dumps(copy, sort_keys=True, default=str).encode()).hexdigest()


def auto_layout(definition: dict, x_gap: int = 290, y_gap: int = 150) -> dict:
    """Layered left-to-right layout (longest path from sources, barycentric ordering)."""
    nodes = definition.get("nodes", [])
    edges = definition.get("edges", [])
    ids = [n["id"] for n in nodes]
    preds: dict[str, list[str]] = {i: [] for i in ids}
    succs: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e["source"] in preds and e["target"] in preds:
            preds[e["target"]].append(e["source"])
            succs[e["source"]].append(e["target"])
    indeg = {i: len(preds[i]) for i in ids}
    layer = {i: 0 for i in ids}
    queue = [i for i in ids if indeg[i] == 0]
    seen = 0
    while queue:
        cur = queue.pop(0)
        seen += 1
        for nxt in succs[cur]:
            layer[nxt] = max(layer[nxt], layer[cur] + 1)
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    columns: dict[int, list[str]] = {}
    for i in ids:
        columns.setdefault(layer[i], []).append(i)
    rank: dict[str, float] = {}
    for col in sorted(columns):
        def key(nid: str) -> float:
            parents = [rank[p] for p in preds[nid] if p in rank]
            return sum(parents) / len(parents) if parents else 0.0

        columns[col].sort(key=key)
        for idx, nid in enumerate(columns[col]):
            rank[nid] = float(idx)
    by_id = {n["id"]: n for n in nodes}
    for col, members in columns.items():
        offset = -(len(members) - 1) * y_gap / 2
        for idx, nid in enumerate(members):
            by_id[nid]["position"] = {"x": 80 + col * x_gap, "y": 300 + offset + idx * y_gap}
    return definition

"""Node type registry: the single source of truth for what FlowForge can do.

The API publishes this catalogue to the frontend (which builds config forms from
it) and to the AI planner (which may only use types registered here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class NodeError(Exception):
    """A node failed. ``error_type`` feeds the failure analytics."""

    def __init__(self, message: str, error_type: str = "execution", retryable: bool = False):
        super().__init__(message)
        self.error_type = error_type
        self.retryable = retryable


@dataclass
class NodeResult:
    outputs: dict[str, Any]
    simulated: bool = False
    ai_provider: Optional[str] = None
    ai_input_tokens: Optional[int] = None
    ai_output_tokens: Optional[int] = None

    @classmethod
    def main(cls, value: Any, **kwargs: Any) -> "NodeResult":
        return cls(outputs={"main": value}, **kwargs)


@dataclass
class PortSpec:
    id: str = "main"
    label: str = ""
    data_type: str = "any"  # any | object | array

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "data_type": self.data_type}


@dataclass
class FieldSpec:
    key: str
    label: str
    type: str = "string"  # string text number boolean select json expression keyvalue rows credential string_list
    required: bool = False
    default: Any = None
    help: str = ""
    placeholder: str = ""
    options: Optional[list[dict]] = None
    columns: Optional[list["FieldSpec"]] = None  # for type=rows
    credential_types: Optional[list[str]] = None
    visible_if: Optional[dict[str, list]] = None
    raw: bool = False  # not rendered before the handler runs (per-item expressions)
    min: Optional[float] = None
    max: Optional[float] = None
    no_expressions: bool = False

    def public(self) -> dict:
        data = {
            "key": self.key,
            "label": self.label,
            "type": self.type,
            "required": self.required,
            "default": self.default,
            "help": self.help,
            "placeholder": self.placeholder,
        }
        for attr in ("options", "credential_types", "visible_if", "min", "max"):
            value = getattr(self, attr)
            if value is not None:
                data[attr] = value
        if self.columns:
            data["columns"] = [c.public() for c in self.columns]
        return data


@dataclass
class NodeSpec:
    type: str
    label: str
    category: str  # trigger logic data ai integration
    description: str
    icon: str
    handler: Callable[[Any], NodeResult]
    inputs: list[PortSpec] = field(default_factory=lambda: [PortSpec()])
    outputs: list[PortSpec] = field(default_factory=lambda: [PortSpec()])
    fields: list[FieldSpec] = field(default_factory=list)
    output_schema: dict = field(default_factory=dict)
    input_schema: dict = field(default_factory=dict)
    is_trigger: bool = False
    multi_input: bool = False
    dynamic_outputs: Optional[Callable[[dict], list[PortSpec]]] = None
    # Does running this (with this config) change the outside world?
    has_side_effects: Callable[[dict], bool] = lambda _c: False
    # Is it safe to automatically retry? Defaults to "no side effects".
    idempotent: Optional[Callable[[dict], bool]] = None
    requires_integration: Optional[str] = None
    planner_hint: str = ""

    def output_ports(self, config: dict) -> list[PortSpec]:
        return self.dynamic_outputs(config) if self.dynamic_outputs else self.outputs

    def is_idempotent(self, config: dict) -> bool:
        if self.idempotent is not None:
            return self.idempotent(config)
        return not self.has_side_effects(config)

    def defaults(self) -> dict:
        return {f.key: f.default for f in self.fields if f.default is not None}

    def public(self) -> dict:
        return {
            "type": self.type,
            "label": self.label,
            "category": self.category,
            "description": self.description,
            "icon": self.icon,
            "is_trigger": self.is_trigger,
            "multi_input": self.multi_input,
            "dynamic_outputs": self.dynamic_outputs is not None,
            "inputs": [p.public() for p in self.inputs],
            "outputs": [p.public() for p in self.outputs],
            "fields": [f.public() for f in self.fields],
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "defaults": self.defaults(),
            "requires_integration": self.requires_integration,
        }


REGISTRY: dict[str, NodeSpec] = {}


def register(spec: NodeSpec) -> NodeSpec:
    if spec.type in REGISTRY:
        raise ValueError(f"Duplicate node type {spec.type}")
    REGISTRY[spec.type] = spec
    return spec


def get_spec(node_type: str) -> Optional[NodeSpec]:
    _ensure_loaded()
    return REGISTRY.get(node_type)


def all_specs() -> list[NodeSpec]:
    _ensure_loaded()
    return list(REGISTRY.values())


_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        _loaded = True
        from . import nodes_ai, nodes_core, nodes_integration  # noqa: F401

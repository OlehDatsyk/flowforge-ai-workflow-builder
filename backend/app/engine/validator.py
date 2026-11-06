"""Static workflow validation. The API, executor and AI planner all use this."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from .definition import NodeDef, WorkflowDefinition
from .expressions import ExpressionError, FILTERS, _split_top, find_expressions, parse_path
from .registry import FieldSpec, NodeSpec, get_spec

_SECRET_HEADER = re.compile(r"^(authorization|x-api-key|api-key|cookie|proxy-authorization)$", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|Bearer\s+[A-Za-z0-9._-]{12,})")


@dataclass
class Issue:
    code: str
    message: str
    node_id: str | None = None
    edge_id: str | None = None
    field: str | None = None


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    definition: WorkflowDefinition | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def public(self) -> dict:
        return {"valid": self.ok, "errors": [asdict(e) for e in self.errors], "warnings": [asdict(w) for w in self.warnings]}


def field_visible(f: FieldSpec, config: dict, spec: NodeSpec) -> bool:
    if not f.visible_if:
        return True
    defaults = spec.defaults()
    return all(config.get(k, defaults.get(k)) in allowed for k, allowed in f.visible_if.items())


def _is_blank(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _check_field(node: NodeDef, spec: NodeSpec, f: FieldSpec, result: ValidationResult, credential_ids, mode: str) -> None:
    config = node.config
    value = config.get(f.key, f.default)
    label = f"{node.name}: {f.label}"
    if _is_blank(value):
        if f.required and f.type != "credential":
            result.errors.append(Issue("missing_config", f"{label} is required", node.id, field=f.key))
        elif f.required and f.type == "credential":
            issue = Issue("missing_credential", f"{label}: choose a credential before running for real", node.id, field=f.key)
            (result.warnings if mode == "test" else result.errors).append(issue)
        return
    is_expr = isinstance(value, str) and "{{" in value
    if f.no_expressions and is_expr and f.type != "credential":
        result.errors.append(Issue("invalid_config", f"{label} does not accept expressions", node.id, field=f.key))
        return
    if f.type == "number" and not is_expr:
        try:
            number = float(value)
        except (TypeError, ValueError):
            result.errors.append(Issue("invalid_config", f"{label} must be a number", node.id, field=f.key))
            return
        if (f.min is not None and number < f.min) or (f.max is not None and number > f.max):
            result.errors.append(Issue("invalid_config", f"{label} must be between {f.min:g} and {f.max:g}", node.id, field=f.key))
    elif f.type == "select" and f.options and not is_expr:
        if value not in [o["value"] for o in f.options]:
            result.errors.append(Issue("invalid_config", f"{label} has an unsupported value '{value}'", node.id, field=f.key))
    elif f.type == "credential":
        if credential_ids is not None and value not in credential_ids:
            result.errors.append(Issue("unknown_credential", f"{label}: the selected credential no longer exists in this workspace", node.id, field=f.key))
    elif f.type == "rows":
        if not isinstance(value, list):
            result.errors.append(Issue("invalid_config", f"{label} must be a list", node.id, field=f.key))
            return
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                result.errors.append(Issue("invalid_config", f"{label}: row {index + 1} is malformed", node.id, field=f.key))
                continue
            for col in f.columns or []:
                cell = row.get(col.key)
                if col.required and _is_blank(cell):
                    result.errors.append(Issue("missing_config", f"{label}: row {index + 1} needs {col.label}", node.id, field=f.key))
                elif col.type == "select" and col.options and not _is_blank(cell):
                    if not (isinstance(cell, str) and "{{" in cell) and cell not in [o["value"] for o in col.options]:
                        result.errors.append(Issue("invalid_config", f"{label}: row {index + 1} has unsupported {col.label} '{cell}'", node.id, field=f.key))
    elif f.type == "keyvalue":
        if not isinstance(value, list):
            result.errors.append(Issue("invalid_config", f"{label} must be a list of key/value pairs", node.id, field=f.key))


def _check_secrets(node: NodeDef, result: ValidationResult) -> None:
    """Credentials belong in the credential store, never in the workflow JSON."""

    def walk(value, path: str) -> None:
        if isinstance(value, str):
            if _SECRET_VALUE.search(value):
                result.errors.append(Issue("plaintext_secret", f"{node.name}: {path} appears to contain a secret. Store it under Credentials instead.", node.id, field=path.split(".")[0]))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    walk(node.config, "")
    for row in node.config.get("headers") or [] if isinstance(node.config.get("headers"), list) else []:
        if isinstance(row, dict) and _SECRET_HEADER.match(str(row.get("key") or "")) and row.get("value") and "{{" not in str(row.get("value")):
            result.errors.append(Issue("plaintext_secret", f"{node.name}: header {row.get('key')} must use a stored credential, not a literal value", node.id, field="headers"))


def _check_expressions(node: NodeDef, names: set[str], result: ValidationResult) -> None:
    for expr in find_expressions(node.config):
        parts = _split_top(expr, "|")
        for flt in parts[1:]:
            name = flt.partition(":")[0].strip()
            if name not in FILTERS:
                result.errors.append(Issue("invalid_expression", f"{node.name}: unknown filter '{name}' in {{{{ {expr} }}}}", node.id))
        head = parts[0]
        if not head or head[0] in "\"'" or re.fullmatch(r"-?\d+(\.\d+)?|true|false|null|none", head):
            continue
        try:
            tokens = parse_path(head)
        except ExpressionError:
            result.errors.append(Issue("invalid_expression", f"{node.name}: cannot parse {{{{ {expr} }}}}", node.id))
            continue
        root = tokens[0] if tokens else ""
        if root not in ("input", "trigger", "nodes", "vars", "item", "index", "execution", "workflow", "now"):
            result.warnings.append(Issue("unknown_reference", f"{node.name}: '{root}' is not a known variable (use input, trigger, nodes, vars, item)", node.id))
        elif root == "nodes" and len(tokens) > 1 and str(tokens[1]) not in names:
            result.warnings.append(Issue("unknown_reference", f"{node.name}: references a node '{tokens[1]}' that is not in this workflow", node.id))


def _check_schedule(node: NodeDef, result: ValidationResult) -> None:
    tz = node.config.get("timezone") or "UTC"
    try:
        ZoneInfo(str(tz))
    except (ZoneInfoNotFoundError, ValueError):
        result.errors.append(Issue("invalid_config", f"{node.name}: unknown time zone '{tz}'", node.id, field="timezone"))
    if node.config.get("schedule_type") == "once" and node.config.get("run_at"):
        try:
            datetime.fromisoformat(str(node.config["run_at"]))
        except ValueError:
            result.errors.append(Issue("invalid_config", f"{node.name}: run time must be an ISO date-time such as 2027-01-15T09:00", node.id, field="run_at"))


def _types_compatible(out_type: str, in_type: str) -> bool:
    return out_type == "any" or in_type == "any" or out_type == in_type


def topological_order(node_ids: list[str], edges: list[tuple[str, str]]) -> list[str] | None:
    """Kahn's algorithm, stable on input order. None when there is a cycle."""
    indegree = {n: 0 for n in node_ids}
    successors: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        if src in indegree and dst in indegree:
            indegree[dst] += 1
            successors[src].append(dst)
    ready = [n for n in node_ids if indegree[n] == 0]
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        for nxt in successors[current]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order if len(order) == len(node_ids) else None


def reachable(start: str, adjacency: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(adjacency.get(start, []))
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(adjacency.get(cur, []))
    return seen


def validate_definition(raw: dict, credential_ids: set[str] | None = None, mode: str = "run") -> ValidationResult:
    """``credential_ids``: IDs in the caller's workspace (None skips the check).
    ``mode="test"`` downgrades a missing credential to a warning because test runs simulate side effects."""
    result = ValidationResult()
    try:
        definition = WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        for err in exc.errors()[:20]:
            location = ".".join(str(p) for p in err["loc"])
            result.errors.append(Issue("invalid_format", f"{location}: {err['msg']}"))
        return result
    result.definition = definition

    if not definition.nodes:
        result.errors.append(Issue("empty_workflow", "Add at least one trigger node to the workflow"))
        return result

    ids: set[str] = set()
    names_seen: set[str] = set()
    specs: dict[str, NodeSpec] = {}
    for node in definition.nodes:
        if node.id in ids:
            result.errors.append(Issue("duplicate_node_id", f"Duplicate node ID '{node.id}'", node.id))
        ids.add(node.id)
        if node.name in names_seen:
            result.warnings.append(Issue("duplicate_name", f"Two nodes are named '{node.name}'; {{{{ nodes[...] }}}} references will be ambiguous", node.id))
        names_seen.add(node.name)
        spec = get_spec(node.type)
        if spec is None:
            result.errors.append(Issue("unsupported_node", f"'{node.type}' is not a supported node type", node.id))
            continue
        specs[node.id] = spec
    reference_names = ids | names_seen

    triggers = [n for n in definition.nodes if n.id in specs and specs[n.id].is_trigger]
    if not triggers:
        result.errors.append(Issue("missing_trigger", "A workflow needs a trigger node to start from"))

    incoming: dict[str, list] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    seen_edges: set[tuple] = set()
    for edge in definition.edges:
        key = (edge.source, edge.source_port, edge.target, edge.target_port)
        if key in seen_edges:
            result.errors.append(Issue("duplicate_edge", "The same connection exists twice", edge_id=edge.id))
            continue
        seen_edges.add(key)
        if edge.source not in ids or edge.target not in ids:
            result.errors.append(Issue("dangling_edge", "A connection points to a node that does not exist", edge_id=edge.id))
            continue
        if edge.source == edge.target:
            result.errors.append(Issue("self_loop", "A node cannot connect to itself", edge.source, edge.id))
            continue
        adjacency[edge.source].append(edge.target)
        incoming[edge.target].append(edge)
        source_spec, target_spec = specs.get(edge.source), specs.get(edge.target)
        if not source_spec or not target_spec:
            continue
        source_node = definition.node(edge.source)
        ports = {p.id: p for p in source_spec.output_ports(source_node.config)}
        if source_node.settings.on_error == "error_branch":
            from .registry import PortSpec

            ports["error"] = PortSpec("error", "Error", "object")
        out_port = ports.get(edge.source_port)
        if out_port is None:
            hint = " Set 'On error' to 'Error branch' to use it." if edge.source_port == "error" else ""
            result.errors.append(Issue("invalid_port", f"{source_node.name} has no output named '{edge.source_port}'.{hint}", edge.source, edge.id))
            continue
        if target_spec.is_trigger or not target_spec.inputs:
            result.errors.append(Issue("invalid_connection", f"{definition.node(edge.target).name} is a trigger and cannot receive connections", edge.target, edge.id))
            continue
        in_port = next((p for p in target_spec.inputs if p.id == edge.target_port), None)
        if in_port is None:
            result.errors.append(Issue("invalid_port", f"{definition.node(edge.target).name} has no input named '{edge.target_port}'", edge.target, edge.id))
            continue
        if not _types_compatible(out_port.data_type, in_port.data_type):
            result.errors.append(
                Issue(
                    "incompatible_types",
                    f"{source_node.name} outputs {out_port.data_type} but {definition.node(edge.target).name} needs {in_port.data_type}. Use a Loop node to process list items.",
                    edge.target,
                    edge.id,
                )
            )

    order = topological_order(list(ids), [(e.source, e.target) for e in definition.edges])
    if order is None:
        result.errors.append(Issue("cycle", "This workflow contains a cycle. Use a Loop node to repeat steps."))

    from_triggers: set[str] = set()
    for trigger in triggers:
        from_triggers |= {trigger.id} | reachable(trigger.id, adjacency)

    for node in definition.nodes:
        spec = specs.get(node.id)
        if not spec:
            continue
        if not spec.is_trigger and spec.inputs and not incoming[node.id]:
            result.errors.append(Issue("missing_connection", f"{node.name} has no incoming connection", node.id))
        elif not spec.is_trigger and order is not None and node.id not in from_triggers:
            result.errors.append(Issue("unreachable_node", f"{node.name} cannot be reached from a trigger", node.id))
        if spec.type == "logic.merge" and len(incoming[node.id]) < 2:
            result.warnings.append(Issue("merge_inputs", f"{node.name} works best with two or more incoming connections", node.id))
        for f in spec.fields:
            if field_visible(f, node.config, spec):
                _check_field(node, spec, f, result, credential_ids, mode)
        _check_secrets(node, result)
        _check_expressions(node, reference_names, result)
        if spec.type == "trigger.schedule":
            _check_schedule(node, result)
        if spec.type == "logic.loop":
            body = {e.target for e in definition.edges if e.source == node.id and e.source_port == "body"}
            done = {e.target for e in definition.edges if e.source == node.id and e.source_port == "done"}
            body_reach = set(body)
            for b in body:
                body_reach |= reachable(b, adjacency)
            done_reach = set(done)
            for d in done:
                done_reach |= reachable(d, adjacency)
            overlap = body_reach & done_reach
            if overlap:
                result.errors.append(Issue("invalid_loop", f"{node.name}: the Each Item branch and the Done branch must stay separate", node.id))
            if not body:
                result.warnings.append(Issue("empty_loop", f"{node.name}: connect the Each Item output to something", node.id))
            for inner in body_reach:
                outside = [e for e in incoming[inner] if e.source != node.id and e.source not in body_reach]
                if outside:
                    result.errors.append(Issue("invalid_loop", f"{definition.node(inner).name} is inside a loop but also receives data from outside it", inner))
        if node.settings.retry.max_attempts > 1 and not spec.is_idempotent(node.config) and not node.settings.retry.allow_non_idempotent:
            result.warnings.append(Issue("retry_ignored", f"{node.name} changes external state, so it will not be retried unless you explicitly allow it", node.id))
    return result

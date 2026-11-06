"""The execution engine.

Executes one ``WorkflowExecution`` row: loads the exact version it points to,
re-validates it, walks the DAG in topological order, passes outputs along active
edges, and records a ``NodeExecution`` row per node. Nodes on inactive branches
are recorded as ``skipped``. Loop bodies run as a sub-graph once per item.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, update

from ..ai.providers import AIError, resolve_provider
from ..config import get_settings
from ..database import session_scope, utcnow
from ..models import Credential, NodeExecution, WorkflowExecution, WorkflowVersion
from ..security import decrypt_json, redact
from .definition import EdgeDef, NodeDef, WorkflowDefinition
from .expressions import ExpressionError, render
from .registry import NodeError, NodeResult, NodeSpec, get_spec
from .validator import reachable, topological_order, validate_definition


class ExecutionCancelled(Exception):
    pass


class ExecutionTimeout(Exception):
    pass


class _WorkflowFailed(Exception):
    def __init__(self, message: str, error_type: str, node_id: str | None):
        super().__init__(message)
        self.error_type = error_type
        self.node_id = node_id


def summarize_value(value: Any, secrets: set[str], limit: int) -> Any:
    """Redact, then cap the size of a value before it is written to the logs."""
    clean = redact(value, secrets)
    try:
        encoded = json.dumps(clean, default=str)
    except (TypeError, ValueError):
        return {"_summary": f"Unserialisable value of type {type(value).__name__}"}
    if len(encoded) <= limit:
        return json.loads(encoded)
    size = {"items": len(clean)} if isinstance(clean, (list, dict)) else {}
    return {"_truncated": True, "_size_bytes": len(encoded), **size, "_preview": encoded[: min(limit, 2000)]}


@dataclass
class ExecutionState:
    execution_id: str
    workspace_id: str
    workflow_id: str
    workflow_name: str
    mode: str
    trigger_data: Any
    definition: WorkflowDefinition
    deadline: float
    variables: dict[str, Any] = field(default_factory=dict)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    trigger_output: Any = None
    secrets: set[str] = field(default_factory=set)
    sequence: int = 0
    executed: int = 0
    warnings: list[str] = field(default_factory=list)
    last_output: Any = None


class NodeContext:
    """Everything a node handler may touch. Handlers never see the DB session or raw settings secrets."""

    def __init__(self, state: ExecutionState, node: NodeDef, spec: NodeSpec, inputs: list[Any], scope: dict, http_transport=None):
        self.state = state
        self.node = node
        self.spec = spec
        self.inputs = inputs
        self.input = inputs[0] if inputs else None
        self.raw_config = {**spec.defaults(), **node.config}
        self.scope = scope
        self.mode = state.mode
        self.trigger_data = state.trigger_data
        self.variables = state.variables
        self.workspace_id = state.workspace_id
        self.execution_id = state.execution_id
        self.settings = get_settings()
        self.timeout = float(node.settings.timeout_seconds)
        self.http_transport = http_transport
        self.logs: dict[str, Any] = {}
        raw_keys = {f.key for f in spec.fields if f.raw}
        self.config = {k: (v if k in raw_keys else render(v, scope)) for k, v in self.raw_config.items()}

    def log(self, key: str, value: Any) -> None:
        self.logs[key] = value

    def wait(self, seconds: float) -> None:
        _set_status(self.state.execution_id, "waiting")
        _interruptible_sleep(self.state, seconds)
        _set_status(self.state.execution_id, "running")

    def get_credential(self, credential_id: str, allowed_types: list[str]) -> dict:
        with session_scope() as db:
            cred = db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == self.workspace_id))
            if cred is None:
                raise NodeError("The selected credential does not exist in this workspace", "config")
            if cred.type not in allowed_types:
                raise NodeError(f"Credential '{cred.name}' has the wrong type for this node", "config")
            data = decrypt_json(cred.encrypted_data)
            for value in data.values():
                if isinstance(value, str):
                    self.state.secrets.add(value)
            return {"type": cred.type, "data": data, "name": cred.name}

    def resolve_ai(self, credential_id: str | None):
        with session_scope() as db:
            provider = resolve_provider(db, self.workspace_id, credential_id)
        if not provider.is_demo:
            self.state.secrets.add(provider.api_key)
        return provider


def _set_status(execution_id: str, status: str) -> None:
    with session_scope() as db:
        db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id, WorkflowExecution.status.in_(("running", "waiting")))
            .values(status=status, heartbeat_at=utcnow())
        )


def _check_interrupts(state: ExecutionState) -> None:
    if time.monotonic() > state.deadline:
        raise ExecutionTimeout()
    with session_scope() as db:
        cancelled = db.scalar(select(WorkflowExecution.cancel_requested).where(WorkflowExecution.id == state.execution_id))
        db.execute(update(WorkflowExecution).where(WorkflowExecution.id == state.execution_id).values(heartbeat_at=utcnow()))
    if cancelled:
        raise ExecutionCancelled()


def _interruptible_sleep(state: ExecutionState, seconds: float) -> None:
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        _check_interrupts(state)
        time.sleep(min(remaining, 0.25))


class Executor:
    def __init__(self, state: ExecutionState, http_transport: httpx.BaseTransport | None = None):
        self.state = state
        self.settings = get_settings()
        self.http_transport = http_transport
        d = state.definition
        self.nodes = {n.id: n for n in d.nodes}
        self.outgoing: dict[str, list[EdgeDef]] = defaultdict(list)
        self.incoming: dict[str, list[EdgeDef]] = defaultdict(list)
        for edge in d.edges:
            self.outgoing[edge.source].append(edge)
            self.incoming[edge.target].append(edge)
        self.adjacency = {src: [e.target for e in edges] for src, edges in self.outgoing.items()}

    # ---- records -------------------------------------------------------
    def _record_start(self, node: NodeDef, inputs: list[Any], iteration: int | None) -> str:
        self.state.sequence += 1
        summary = summarize_value(inputs[0] if len(inputs) == 1 else inputs, self.state.secrets, self.settings.max_log_value_bytes)
        with session_scope() as db:
            row = NodeExecution(
                execution_id=self.state.execution_id,
                node_id=node.id,
                node_name=node.name,
                node_type=node.type,
                sequence=self.state.sequence,
                iteration=iteration,
                status="running",
                started_at=utcnow(),
                input_summary=summary,
            )
            db.add(row)
            db.flush()
            return row.id

    def _record_finish(self, row_id: str, **values: Any) -> None:
        with session_scope() as db:
            row = db.get(NodeExecution, row_id)
            now = utcnow()
            row.finished_at = now
            row.duration_ms = int((now - row.started_at).total_seconds() * 1000)
            for key, value in values.items():
                setattr(row, key, value)
            db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == self.state.execution_id)
                .values(nodes_executed=self.state.executed, heartbeat_at=now)
            )

    def _record_skip(self, node: NodeDef, iteration: int | None) -> None:
        self.state.sequence += 1
        with session_scope() as db:
            db.add(
                NodeExecution(
                    execution_id=self.state.execution_id,
                    node_id=node.id,
                    node_name=node.name,
                    node_type=node.type,
                    sequence=self.state.sequence,
                    iteration=iteration,
                    status="skipped",
                )
            )

    # ---- scope ---------------------------------------------------------
    def _scope(self, input_value: Any, extra: dict | None) -> dict:
        state = self.state
        return {
            "input": input_value,
            "trigger": state.trigger_output,
            "nodes": state.node_outputs,
            "vars": state.variables,
            "execution": {"id": state.execution_id, "mode": state.mode},
            "workflow": {"id": state.workflow_id, "name": state.workflow_name},
            "now": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }

    def _store_output(self, node: NodeDef, value: Any) -> None:
        self.state.node_outputs[node.id] = value
        self.state.node_outputs[node.name] = value
        self.state.last_output = value

    # ---- node execution --------------------------------------------------
    def _execute_with_policy(self, node: NodeDef, spec: NodeSpec, inputs: list[Any], extra: dict | None) -> tuple[NodeResult, int]:
        retry = node.settings.retry
        attempt = 0
        while True:
            attempt += 1
            try:
                scope = self._scope(inputs[0] if inputs else None, extra)
                ctx = NodeContext(self.state, node, spec, inputs, scope, self.http_transport)
                result = spec.handler(ctx)
                if spec.has_side_effects(ctx.raw_config) and not result.simulated and self.state.mode == "test":
                    # Defensive: a handler must never perform a side effect in test mode.
                    raise NodeError("Test run refused an unsimulated side effect", "internal")
                return result, attempt
            except ExpressionError as exc:
                error = NodeError(f"Expression error: {exc}", "expression")
            except NodeError as exc:
                error = exc
            except (ExecutionCancelled, ExecutionTimeout):
                raise
            except AIError as exc:
                error = NodeError(str(exc), "ai", retryable=exc.retryable)
            except Exception as exc:  # noqa: BLE001 - a node bug must fail the node, not the worker
                error = NodeError(f"Unexpected {type(exc).__name__} in {node.name}", "internal")
            config = {**spec.defaults(), **node.config}
            allowed = spec.is_idempotent(config) or retry.allow_non_idempotent
            if attempt >= retry.max_attempts or not error.retryable or not allowed:
                error.attempts = attempt  # type: ignore[attr-defined]
                raise error
            delay = retry.delay_ms / 1000 * (retry.backoff ** (attempt - 1))
            _interruptible_sleep(self.state, delay)

    def _run_node(self, node: NodeDef, inputs: list[Any], extra: dict | None, iteration: int | None) -> dict[str, Any]:
        """Runs one node and returns its active output ports."""
        state = self.state
        spec = get_spec(node.type)
        _check_interrupts(state)
        if state.executed >= self.settings.max_node_executions:
            raise _WorkflowFailed(f"Execution limit reached ({self.settings.max_node_executions} node runs)", "resource_limit", node.id)
        state.executed += 1
        row_id = self._record_start(node, inputs, iteration)
        try:
            if spec.type == "logic.loop":
                outputs, attempts, simulated = self._run_loop(node, inputs, extra), 1, False
                result = NodeResult(outputs=outputs, simulated=simulated)
            else:
                result, attempts = self._execute_with_policy(node, spec, inputs, extra)
        except (ExecutionCancelled, ExecutionTimeout) as exc:
            status = "cancelled" if isinstance(exc, ExecutionCancelled) else "failed"
            message = "Cancelled" if isinstance(exc, ExecutionCancelled) else "Execution time limit reached"
            self._record_finish(row_id, status=status, error=redact(message, state.secrets))
            raise
        except _WorkflowFailed as exc:
            self._record_finish(row_id, status="failed", error=redact(str(exc), state.secrets), error_type=exc.error_type)
            raise
        except NodeError as exc:
            message = redact(str(exc), state.secrets)
            attempts = getattr(exc, "attempts", 1)
            on_error = node.settings.on_error
            payload = {"error": message, "error_type": exc.error_type, "node": node.name, "input": inputs[0] if inputs else None}
            self._record_finish(row_id, status="failed", error=message, error_type=exc.error_type, attempts=attempts)
            if on_error == "error_branch":
                self._store_output(node, payload)
                state.warnings.append(f"{node.name} failed and was handled by its error branch")
                return {"error": payload}
            if on_error == "continue":
                self._store_output(node, payload)
                state.warnings.append(f"{node.name} failed; continuing as configured")
                return {port.id: payload for port in spec.output_ports(node.config)[:1]}
            raise _WorkflowFailed(f"{node.name}: {message}", exc.error_type, node.id) from exc
        outputs = result.outputs
        primary = next(iter(outputs.values()), None)
        self._store_output(node, primary)
        summary = {"ports": list(outputs.keys()), "data": summarize_value(primary, state.secrets, self.settings.max_log_value_bytes)}
        self._record_finish(
            row_id,
            status="completed",
            output_summary=summary,
            attempts=attempts,
            simulated=result.simulated,
            ai_provider=result.ai_provider,
            ai_input_tokens=result.ai_input_tokens,
            ai_output_tokens=result.ai_output_tokens,
        )
        return outputs

    def _run_loop(self, node: NodeDef, inputs: list[Any], extra: dict | None) -> dict[str, Any]:
        spec = get_spec(node.type)
        scope = self._scope(inputs[0] if inputs else None, extra)
        config = {**spec.defaults(), **node.config}
        items = render(config.get("items"), scope)
        if isinstance(items, dict) and isinstance(items.get("rows"), list):
            items = items["rows"]
        if not isinstance(items, list):
            raise NodeError(f"Loop expected a list but received {type(items).__name__}", "validation")
        try:
            limit = int(render(config.get("max_iterations"), scope) or 100)
        except (TypeError, ValueError) as exc:
            raise NodeError("Maximum iterations must be a number", "config") from exc
        limit = min(limit, self.settings.max_loop_iterations)
        if len(items) > limit:
            raise NodeError(f"Loop received {len(items)} items, above its limit of {limit}", "resource_limit")
        body_entry = [e for e in self.outgoing[node.id] if e.source_port == "body"]
        body_nodes: set[str] = set()
        for edge in body_entry:
            body_nodes |= {edge.target} | reachable(edge.target, self.adjacency)
        results = []
        for index, item in enumerate(items):
            seeds = {edge.id: item for edge in body_entry}
            self.state.last_output = item
            self._run_graph(body_nodes, seeds, {**(extra or {}), "item": item, "index": index}, index)
            results.append(self.state.last_output)
        return {"done": results}

    # ---- graph walking ---------------------------------------------------
    def _run_graph(self, members: set[str], seeds: dict[str, Any], extra: dict | None, iteration: int | None) -> None:
        """Runs ``members`` in topological order. ``seeds`` maps edge ID -> payload for active entry edges."""
        ordered = [n.id for n in self.state.definition.nodes if n.id in members]
        edges = [(e.source, e.target) for e in self.state.definition.edges if e.source in members and e.target in members]
        order = topological_order(ordered, edges)
        if order is None:  # guarded by the validator, kept as a hard stop
            raise _WorkflowFailed("Cycle detected while executing", "validation", None)
        loop_bodies: set[str] = set()
        active_edges: dict[str, Any] = dict(seeds)
        for node_id in order:
            if node_id in loop_bodies:
                continue
            node = self.nodes[node_id]
            incoming = [e for e in self.incoming[node_id]]
            payloads = [active_edges[e.id] for e in incoming if e.id in active_edges]
            spec = get_spec(node.type)
            if not spec.is_trigger and not payloads:
                self._record_skip(node, iteration)
                continue
            outputs = self._run_node(node, payloads, extra, iteration)
            for edge in self.outgoing[node_id]:
                if edge.source_port in outputs:
                    active_edges[edge.id] = outputs[edge.source_port]
            if spec.type == "logic.loop":
                # The body already ran inside _run_loop; do not visit it again here.
                for edge in self.outgoing[node_id]:
                    if edge.source_port == "body":
                        loop_bodies |= {edge.target} | reachable(edge.target, self.adjacency)

    def run(self, trigger_node: NodeDef) -> Any:
        state = self.state
        spec = get_spec(trigger_node.type)
        outputs = self._run_node(trigger_node, [], None, None)
        state.trigger_output = next(iter(outputs.values()), None)
        downstream = reachable(trigger_node.id, self.adjacency)
        for node in state.definition.nodes:
            if node.id != trigger_node.id and node.id not in downstream:
                self._record_skip(node, None)  # other triggers and their exclusive branches
        seeds = {e.id: outputs[e.source_port] for e in self.outgoing[trigger_node.id] if e.source_port in outputs}
        self._run_graph(downstream, seeds, None, None)
        return state.last_output


def _mark_unvisited(state: ExecutionState) -> None:
    """After a failure or cancellation, record nodes that never ran so the canvas can show them."""
    with session_scope() as db:
        visited = set(db.scalars(select(NodeExecution.node_id).where(NodeExecution.execution_id == state.execution_id)))
        for node in state.definition.nodes:
            if node.id not in visited:
                state.sequence += 1
                db.add(NodeExecution(execution_id=state.execution_id, node_id=node.id, node_name=node.name, node_type=node.type, sequence=state.sequence, status="skipped"))


def _finish(execution_id: str, status: str, started: float, **values: Any) -> None:
    with session_scope() as db:
        now = utcnow()
        db.execute(
            update(WorkflowExecution)
            .where(WorkflowExecution.id == execution_id)
            .values(status=status, finished_at=now, heartbeat_at=now, duration_ms=int((time.monotonic() - started) * 1000), **values)
        )


def execute(execution_id: str, http_transport: httpx.BaseTransport | None = None) -> str:
    """Runs a claimed execution to completion and returns its final status. Never raises for workflow errors."""
    settings = get_settings()
    started = time.monotonic()
    with session_scope() as db:
        ex = db.get(WorkflowExecution, execution_id)
        if ex is None:
            raise ValueError(f"Execution {execution_id} not found")
        version = db.get(WorkflowVersion, ex.version_id)
        raw_definition = version.definition
        cred_ids = set(db.scalars(select(Credential.id).where(Credential.workspace_id == ex.workspace_id)))
        info = {
            "workspace_id": ex.workspace_id,
            "workflow_id": ex.workflow_id,
            "workflow_name": ex.workflow_name,
            "mode": ex.mode,
            "trigger_data": ex.trigger_data,
            "trigger_node_id": ex.trigger_node_id,
            "cancelled": ex.cancel_requested,
        }
    if info["cancelled"]:
        _finish(execution_id, "cancelled", started, error="Cancelled before it started")
        return "cancelled"

    validation = validate_definition(raw_definition, cred_ids, mode=info["mode"])
    if not validation.ok:
        message = "; ".join(e.message for e in validation.errors[:5])
        _finish(execution_id, "failed", started, error=f"Workflow is invalid: {message}", error_type="validation")
        return "failed"
    definition = validation.definition

    trigger = definition.node(info["trigger_node_id"]) if info["trigger_node_id"] else None
    if trigger is None or not get_spec(trigger.type).is_trigger:
        trigger = next(n for n in definition.nodes if get_spec(n.type).is_trigger)

    state = ExecutionState(
        execution_id=execution_id,
        workspace_id=info["workspace_id"],
        workflow_id=info["workflow_id"],
        workflow_name=info["workflow_name"],
        mode=info["mode"],
        trigger_data=info["trigger_data"],
        definition=definition,
        deadline=started + settings.max_execution_seconds,
    )
    try:
        result = Executor(state, http_transport).run(trigger)
    except ExecutionCancelled:
        _mark_unvisited(state)
        _finish(execution_id, "cancelled", started, error="Cancelled by user", nodes_executed=state.executed)
        return "cancelled"
    except ExecutionTimeout:
        _mark_unvisited(state)
        _finish(execution_id, "failed", started, error=f"Execution exceeded the {settings.max_execution_seconds}s time limit", error_type="timeout", nodes_executed=state.executed)
        return "failed"
    except _WorkflowFailed as exc:
        _mark_unvisited(state)
        _finish(execution_id, "failed", started, error=redact(str(exc), state.secrets), error_type=exc.error_type, failed_node_id=exc.node_id, nodes_executed=state.executed)
        return "failed"
    except Exception as exc:  # noqa: BLE001
        _finish(execution_id, "failed", started, error=f"Internal engine error ({type(exc).__name__})", error_type="internal", nodes_executed=state.executed)
        raise
    _finish(
        execution_id,
        "completed",
        started,
        result=summarize_value(result, state.secrets, settings.max_log_value_bytes),
        nodes_executed=state.executed,
    )
    return "completed"


def test_single_node(workspace_id: str, workflow_id: str, workflow_name: str, node: NodeDef, input_value: Any, allow_side_effects: bool) -> dict:
    """Runs one node in isolation with sample input. Side effects are simulated unless explicitly allowed."""
    from ..engine.definition import WorkflowDefinition as WD

    spec = get_spec(node.type)
    state = ExecutionState(
        execution_id="node-test",
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        mode="run" if allow_side_effects else "test",
        trigger_data=None,
        definition=WD(nodes=[node], edges=[]),
        deadline=time.monotonic() + get_settings().max_execution_seconds,
        trigger_output=input_value,
    )
    started = time.perf_counter()
    scope = {
        "input": input_value,
        "trigger": input_value,
        "nodes": {},
        "vars": {},
        "execution": {"id": "node-test", "mode": state.mode},
        "workflow": {"id": workflow_id, "name": workflow_name},
        "now": datetime.now(timezone.utc).isoformat(),
    }
    try:
        if spec.type == "logic.loop":
            raise NodeError("Loop nodes run as part of a workflow. Use Test workflow.", "config")
        ctx = NodeContext(state, node, spec, [input_value], scope)
        if spec.type == "logic.delay":
            ctx.wait = lambda _s: None  # do not hold a request open for a test
        result = spec.handler(ctx)
        return {
            "status": "completed",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "outputs": summarize_value(result.outputs, state.secrets, get_settings().max_log_value_bytes),
            "simulated": result.simulated,
            "logs": summarize_value(ctx.logs, state.secrets, 4000),
        }
    except (NodeError, ExpressionError, AIError) as exc:
        return {
            "status": "failed",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "error": redact(str(exc), state.secrets),
            "error_type": getattr(exc, "error_type", "expression"),
            "simulated": False,
        }

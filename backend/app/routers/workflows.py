"""Workflow CRUD, versions, activation, runs, single-node tests and definition helpers."""
from __future__ import annotations

import copy
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..deps import WorkspaceContext, editor, get_db, get_workspace, limit
from ..engine.definition import NodeDef, auto_layout, empty_definition
from ..engine.executor import test_single_node
from ..engine.registry import all_specs, get_spec
from ..engine.validator import validate_definition
from ..models import (
    Credential,
    NodeExecution,
    ScheduledTrigger,
    WebhookTrigger,
    Workflow,
    WorkflowExecution,
    WorkflowVersion,
)
from ..services import audit, create_execution, create_version, ensure_version, latest_version, set_draft, sync_triggers

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
meta_router = APIRouter(prefix="/api", tags=["definitions"])


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="General", max_length=60)
    folder: str = Field(default="", max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)
    definition: Optional[dict] = None


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=60)
    folder: Optional[str] = Field(default=None, max_length=80)
    tags: Optional[list[str]] = Field(default=None, max_length=20)
    definition: Optional[dict] = None
    revision: Optional[int] = None


class VersionCreate(BaseModel):
    note: str = Field(default="", max_length=240)


class RunBody(BaseModel):
    mode: str = Field(default="run", pattern="^(run|test)$")
    input: Any = None
    trigger_node_id: Optional[str] = None


class NodeTestBody(BaseModel):
    input: Any = None
    node: Optional[dict] = None  # unsaved node from the editor
    allow_side_effects: bool = False


class DefinitionBody(BaseModel):
    definition: dict
    mode: str = Field(default="run", pattern="^(run|test)$")


def get_workflow(db: Session, ctx: WorkspaceContext, workflow_id: str) -> Workflow:
    wf = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.workspace_id == ctx.workspace_id))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


def credential_ids(db: Session, workspace_id: str) -> set[str]:
    return set(db.scalars(select(Credential.id).where(Credential.workspace_id == workspace_id)))


def check_savable(definition: dict) -> dict:
    """A draft may be incomplete, but it must be well-formed, use real node types and hold no secrets."""
    result = validate_definition(definition, None, mode="test")
    blocking = [e for e in result.errors if e.code in ("invalid_format", "unsupported_node", "duplicate_node_id", "plaintext_secret")]
    if blocking:
        raise HTTPException(status_code=422, detail={"message": blocking[0].message, "issues": [e.__dict__ for e in blocking]})
    return result.definition.model_dump()


def serialize(wf: Workflow, full: bool = False, stats: dict | None = None) -> dict:
    node_types = [n["type"] for n in wf.draft_definition.get("nodes", [])]
    data = {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description,
        "category": wf.category,
        "folder": wf.folder,
        "tags": wf.tags,
        "is_active": wf.is_active,
        "active_version_id": wf.active_version_id,
        "is_demo": wf.is_demo,
        "revision": wf.revision,
        "node_count": len(node_types),
        "node_types": node_types[:8],
        "created_at": wf.created_at,
        "updated_at": wf.updated_at,
    }
    if stats is not None:
        data.update(stats)
    if full:
        data["definition"] = wf.draft_definition
    return data


@router.get("")
def list_workflows(
    search: str = Query("", max_length=160),
    status: str = Query("", pattern="^(|active|inactive)$"),
    category: str = Query("", max_length=60),
    folder: str = Query("", max_length=80),
    sort: str = Query("updated", pattern="^(updated|name|created)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    ctx: WorkspaceContext = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    base = select(Workflow).where(Workflow.workspace_id == ctx.workspace_id)
    if search:
        needle = f"%{search.replace('%', '').lower()}%"
        base = base.where(or_(func.lower(Workflow.name).like(needle), func.lower(Workflow.description).like(needle)))
    if status:
        base = base.where(Workflow.is_active.is_(status == "active"))
    if category:
        base = base.where(Workflow.category == category)
    if folder:
        base = base.where(Workflow.folder == folder)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    order = {"updated": Workflow.updated_at.desc(), "name": func.lower(Workflow.name), "created": Workflow.created_at.desc()}[sort]
    rows = db.scalars(base.order_by(order).offset((page - 1) * page_size).limit(page_size)).all()
    stats: dict[str, dict] = {}
    if rows:
        query = (
            select(
                WorkflowExecution.workflow_id,
                func.count().label("runs"),
                func.sum(case((WorkflowExecution.status == "failed", 1), else_=0)).label("failures"),
                func.max(WorkflowExecution.created_at).label("last_run"),
            )
            .where(WorkflowExecution.workflow_id.in_([w.id for w in rows]))
            .group_by(WorkflowExecution.workflow_id)
        )
        for row in db.execute(query):
            stats[row.workflow_id] = {"runs": row.runs, "failures": row.failures or 0, "last_run_at": row.last_run}
    facets = db.execute(select(Workflow.category, Workflow.folder).where(Workflow.workspace_id == ctx.workspace_id)).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [serialize(w, stats=stats.get(w.id, {"runs": 0, "failures": 0, "last_run_at": None})) for w in rows],
        "categories": sorted({f[0] for f in facets if f[0]}),
        "folders": sorted({f[1] for f in facets if f[1]}),
    }


@router.post("", status_code=201)
def create_workflow(body: WorkflowCreate, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    definition = check_savable(body.definition) if body.definition else empty_definition()
    wf = Workflow(
        workspace_id=ctx.workspace_id,
        name=body.name.strip(),
        description=body.description,
        category=body.category or "General",
        folder=body.folder,
        tags=body.tags,
        created_by=ctx.user.id,
        draft_definition=definition,
    )
    set_draft(wf, definition)
    db.add(wf)
    db.flush()
    create_version(db, wf, ctx.user.id, "Created")
    sync_triggers(db, wf)
    audit(db, "workflow.create", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"name": wf.name}, ip=ctx.ip)
    db.commit()
    return serialize(wf, full=True)


@router.get("/{workflow_id}")
def read_workflow(workflow_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    data = serialize(wf, full=True)
    data["validation"] = validate_definition(wf.draft_definition, credential_ids(db, ctx.workspace_id)).public()
    current = latest_version(db, wf.id)
    data["latest_version"] = current.version if current else None
    active = db.get(WorkflowVersion, wf.active_version_id) if wf.active_version_id else None
    data["active_version"] = active.version if active else None
    return data


@router.put("/{workflow_id}")
def update_workflow(workflow_id: str, body: WorkflowUpdate, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    if body.revision is not None and body.revision != wf.revision:
        raise HTTPException(status_code=409, detail="This workflow was changed elsewhere. Reload to get the latest version.")
    if body.name is not None:
        wf.name = body.name.strip()
    for attr in ("description", "category", "folder", "tags"):
        value = getattr(body, attr)
        if value is not None:
            setattr(wf, attr, value)
    if body.definition is not None:
        set_draft(wf, check_savable(body.definition))
    wf.revision += 1
    sync_triggers(db, wf)
    db.commit()
    data = serialize(wf, full=True)
    data["validation"] = validate_definition(wf.draft_definition, credential_ids(db, ctx.workspace_id)).public()
    return data


@router.post("/{workflow_id}/duplicate", status_code=201)
def duplicate_workflow(workflow_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    source = get_workflow(db, ctx, workflow_id)
    wf = Workflow(
        workspace_id=ctx.workspace_id,
        name=f"{source.name} (copy)"[:160],
        description=source.description,
        category=source.category,
        folder=source.folder,
        tags=list(source.tags),
        created_by=ctx.user.id,
        draft_definition=copy.deepcopy(source.draft_definition),
    )
    set_draft(wf, wf.draft_definition)
    db.add(wf)
    db.flush()
    create_version(db, wf, ctx.user.id, f"Duplicated from {source.name}")
    sync_triggers(db, wf)
    audit(db, "workflow.duplicate", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"source": source.id}, ip=ctx.ip)
    db.commit()
    return serialize(wf, stats={"runs": 0, "failures": 0, "last_run_at": None})


@router.delete("/{workflow_id}")
def delete_workflow(workflow_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    running = db.scalar(
        select(func.count()).select_from(WorkflowExecution).where(WorkflowExecution.workflow_id == wf.id, WorkflowExecution.status.in_(("pending", "running", "waiting")))
    )
    if running:
        raise HTTPException(status_code=409, detail="Cancel this workflow's running executions before deleting it")
    # Delete executions first: they restrict deletion of the versions they reference.
    for ex in db.scalars(select(WorkflowExecution).where(WorkflowExecution.workflow_id == wf.id)):
        db.delete(ex)
    db.flush()
    audit(db, "workflow.delete", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"name": wf.name}, ip=ctx.ip)
    db.delete(wf)
    db.commit()
    return {"ok": True}


def _require_valid(db: Session, wf: Workflow, ctx: WorkspaceContext, mode: str = "run") -> None:
    result = validate_definition(wf.draft_definition, credential_ids(db, ctx.workspace_id), mode=mode)
    if not result.ok:
        raise HTTPException(status_code=422, detail={"message": result.errors[0].message, "issues": [e.__dict__ for e in result.errors]})


@router.post("/{workflow_id}/activate")
def activate(workflow_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    _require_valid(db, wf, ctx)
    version = ensure_version(db, wf, ctx.user.id, "Published")
    wf.is_active = True
    wf.active_version_id = version.id
    sync_triggers(db, wf)
    audit(db, "workflow.activate", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"version": version.version}, ip=ctx.ip)
    db.commit()
    return serialize(wf)


@router.post("/{workflow_id}/deactivate")
def deactivate(workflow_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    wf.is_active = False
    sync_triggers(db, wf)
    audit(db, "workflow.deactivate", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, ip=ctx.ip)
    db.commit()
    return serialize(wf)


@router.get("/{workflow_id}/versions")
def versions(workflow_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    rows = db.scalars(select(WorkflowVersion).where(WorkflowVersion.workflow_id == wf.id).order_by(WorkflowVersion.version.desc()).limit(100)).all()
    return [
        {"id": v.id, "version": v.version, "note": v.note, "created_at": v.created_at, "node_count": len(v.definition.get("nodes", [])), "is_active": v.id == wf.active_version_id, "is_current": v.definition_hash == wf.draft_hash}
        for v in rows
    ]


@router.post("/{workflow_id}/versions", status_code=201)
def save_version(workflow_id: str, body: VersionCreate, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    version = create_version(db, wf, ctx.user.id, body.note or "Manual save")
    db.commit()
    return {"id": version.id, "version": version.version, "note": version.note}


@router.get("/{workflow_id}/versions/{version_id}")
def read_version(workflow_id: str, version_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == wf.id))
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return {"id": version.id, "version": version.version, "note": version.note, "definition": version.definition, "created_at": version.created_at}


@router.post("/{workflow_id}/versions/{version_id}/restore")
def restore_version(workflow_id: str, version_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    version = db.scalar(select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == wf.id))
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")
    ensure_version(db, wf, ctx.user.id, "Before restore")
    set_draft(wf, copy.deepcopy(version.definition))
    wf.revision += 1
    create_version(db, wf, ctx.user.id, f"Restored from v{version.version}")
    sync_triggers(db, wf)
    audit(db, "workflow.restore", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"version": version.version}, ip=ctx.ip)
    db.commit()
    return serialize(wf, full=True)


@router.post("/{workflow_id}/run", status_code=202)
def run_workflow(workflow_id: str, body: RunBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    """Queues an execution of the saved draft. mode=test simulates every external side effect."""
    limit(f"run:{ctx.user.id}", 60, 60)
    wf = get_workflow(db, ctx, workflow_id)
    _require_valid(db, wf, ctx, body.mode)
    version = ensure_version(db, wf, ctx.user.id, "Snapshot for run")
    node_ids = {n["id"]: n for n in version.definition.get("nodes", [])}
    if body.trigger_node_id and body.trigger_node_id not in node_ids:
        raise HTTPException(status_code=422, detail="That trigger is not part of this workflow")
    execution = create_execution(db, wf, version, mode=body.mode, trigger_type="manual" if body.mode == "run" else "test", trigger_node_id=body.trigger_node_id, trigger_data=body.input, user_id=ctx.user.id)
    db.commit()
    return {"execution_id": execution.id, "status": execution.status, "version": version.version}


@router.post("/{workflow_id}/nodes/{node_id}/test")
def test_node(workflow_id: str, node_id: str, body: NodeTestBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    limit(f"node-test:{ctx.user.id}", 60, 60)
    wf = get_workflow(db, ctx, workflow_id)
    raw = body.node or next((n for n in wf.draft_definition.get("nodes", []) if n["id"] == node_id), None)
    if raw is None:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        node = NodeDef.model_validate(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Node is malformed") from exc
    spec = get_spec(node.type)
    if spec is None:
        raise HTTPException(status_code=422, detail=f"'{node.type}' is not a supported node type")
    sample = body.input if body.input is not None else {}
    result = test_single_node(ctx.workspace_id, wf.id, wf.name, node, sample, body.allow_side_effects)
    if body.allow_side_effects and spec.has_side_effects({**spec.defaults(), **node.config}):
        audit(db, "node.live_test", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"node": node.name, "type": node.type, "status": result["status"]}, ip=ctx.ip)
        db.commit()
    return result


@router.get("/{workflow_id}/nodes/{node_id}/last-result")
def node_last_result(workflow_id: str, node_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    wf = get_workflow(db, ctx, workflow_id)
    row = db.scalar(
        select(NodeExecution)
        .join(WorkflowExecution, NodeExecution.execution_id == WorkflowExecution.id)
        .where(WorkflowExecution.workflow_id == wf.id, NodeExecution.node_id == node_id, NodeExecution.status != "skipped")
        .order_by(NodeExecution.started_at.desc())
        .limit(1)
    )
    if row is None:
        return None
    return {
        "execution_id": row.execution_id,
        "status": row.status,
        "started_at": row.started_at,
        "duration_ms": row.duration_ms,
        "input": row.input_summary,
        "output": row.output_summary,
        "error": row.error,
        "simulated": row.simulated,
    }


@router.get("/{workflow_id}/triggers")
def triggers(workflow_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    from ..config import get_settings

    wf = get_workflow(db, ctx, workflow_id)
    base = get_settings().public_base_url.rstrip("/")
    hooks = db.scalars(select(WebhookTrigger).where(WebhookTrigger.workflow_id == wf.id)).all()
    schedules = db.scalars(select(ScheduledTrigger).where(ScheduledTrigger.workflow_id == wf.id)).all()
    return {
        "webhooks": [
            {"id": h.id, "node_id": h.node_id, "url": f"{base}/hooks/{h.token}", "enabled": h.enabled, "live": h.enabled and wf.is_active, "request_count": h.request_count, "last_request_at": h.last_request_at}
            for h in hooks
        ],
        "schedules": [
            {"id": s.id, "node_id": s.node_id, "schedule": s.schedule, "enabled": s.enabled, "next_run_at": s.next_run_at, "last_run_at": s.last_run_at, "last_execution_id": s.last_execution_id}
            for s in schedules
        ],
    }


# ------------------------------------------------------------------ definitions
@meta_router.get("/nodes")
def node_catalogue(ctx: WorkspaceContext = Depends(get_workspace)):
    return [s.public() for s in all_specs()]


@meta_router.post("/definitions/validate")
def validate(body: DefinitionBody, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    return validate_definition(body.definition, credential_ids(db, ctx.workspace_id), mode=body.mode).public()


@meta_router.post("/definitions/ports")
def ports(body: DefinitionBody, ctx: WorkspaceContext = Depends(get_workspace)):
    out = {}
    for node in body.definition.get("nodes", []):
        spec = get_spec(node.get("type", ""))
        if spec:
            out[node["id"]] = [p.public() for p in spec.output_ports(node.get("config", {}))]
    return out


@meta_router.post("/definitions/layout")
def layout(body: DefinitionBody, ctx: WorkspaceContext = Depends(get_workspace)):
    return auto_layout(copy.deepcopy(body.definition))


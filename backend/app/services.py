"""Domain operations shared by routers, the worker and seed data."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import utcnow
from .engine.definition import definition_hash
from .engine.registry import get_spec
from .models import (
    AuditLog,
    ScheduledTrigger,
    WebhookTrigger,
    Workflow,
    WorkflowConnection,
    WorkflowExecution,
    WorkflowNode,
    WorkflowVersion,
)
from .security import encrypt_json, new_token


def audit(db: Session, action: str, *, workspace_id: str | None = None, user_id: str | None = None, entity_type: str = "", entity_id: str = "", details: dict | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(workspace_id=workspace_id, user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details or {}, ip_address=ip))


def latest_version(db: Session, workflow_id: str) -> WorkflowVersion | None:
    return db.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version.desc()).limit(1))


def create_version(db: Session, wf: Workflow, user_id: str | None, note: str = "") -> WorkflowVersion:
    last = db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == wf.id)) or 0
    version = WorkflowVersion(
        workflow_id=wf.id,
        version=last + 1,
        definition=copy.deepcopy(wf.draft_definition),
        definition_hash=wf.draft_hash or definition_hash(wf.draft_definition),
        note=note[:240],
        created_by=user_id,
    )
    db.add(version)
    db.flush()
    for node in wf.draft_definition.get("nodes", []):
        db.add(WorkflowNode(version_id=version.id, node_id=node["id"], node_type=node["type"], name=node["name"][:160]))
    for edge in wf.draft_definition.get("edges", []):
        db.add(WorkflowConnection(version_id=version.id, source_node_id=edge["source"], source_port=edge.get("source_port", "main"), target_node_id=edge["target"], target_port=edge.get("target_port", "main")))
    return version


def ensure_version(db: Session, wf: Workflow, user_id: str | None, note: str = "") -> WorkflowVersion:
    """The version matching the current draft, creating it if the logic has changed."""
    current = latest_version(db, wf.id)
    if current is not None and current.definition_hash == wf.draft_hash:
        return current
    return create_version(db, wf, user_id, note)


def set_draft(wf: Workflow, definition: dict) -> None:
    wf.draft_definition = definition
    wf.draft_hash = definition_hash(definition)


# ------------------------------------------------------------------ schedules
def compute_next_run(schedule: dict, after: datetime | None = None) -> datetime | None:
    """Next run strictly after ``after``, in UTC. Handles DST through zoneinfo."""
    after = after or utcnow()
    tz = ZoneInfo(str(schedule.get("timezone") or "UTC"))
    kind = schedule.get("schedule_type", "daily")
    local = after.astimezone(tz)
    if kind == "once":
        raw = schedule.get("run_at")
        if not raw:
            return None
        run_at = datetime.fromisoformat(str(raw))
        run_at = run_at.replace(tzinfo=tz) if run_at.tzinfo is None else run_at
        run_utc = run_at.astimezone(timezone.utc)
        return run_utc if run_utc > after else None
    minute = int(schedule.get("minute") or 0)
    if kind == "hourly":
        candidate = local.replace(minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(hours=1)
        return candidate.astimezone(timezone.utc)
    hour = int(schedule.get("hour") if schedule.get("hour") is not None else 9)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if kind == "daily":
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    weekday = int(schedule.get("weekday") or 0)
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate.astimezone(timezone.utc)


def sync_triggers(db: Session, wf: Workflow) -> None:
    """Makes trigger rows match the definition in force: the active version, or the draft."""
    definition = wf.draft_definition
    if wf.is_active and wf.active_version_id:
        version = db.get(WorkflowVersion, wf.active_version_id)
        if version:
            definition = version.definition
    # Editor needs endpoints for draft webhook nodes too, so include both when active.
    node_lists = [definition.get("nodes", [])]
    if definition is not wf.draft_definition:
        node_lists.append(wf.draft_definition.get("nodes", []))
    webhook_nodes = {n["id"]: n for nodes in node_lists for n in nodes if n["type"] == "trigger.webhook"}
    schedule_nodes = {n["id"]: n for n in definition.get("nodes", []) if n["type"] == "trigger.schedule"}

    existing_hooks = {t.node_id: t for t in db.scalars(select(WebhookTrigger).where(WebhookTrigger.workflow_id == wf.id))}
    for node_id, trigger in existing_hooks.items():
        if node_id not in webhook_nodes:
            db.delete(trigger)
    for node_id in webhook_nodes:
        if node_id not in existing_hooks:
            db.add(WebhookTrigger(workspace_id=wf.workspace_id, workflow_id=wf.id, node_id=node_id, encrypted_secret=encrypt_json({"secret": new_token(32)})))

    existing_schedules = {t.node_id: t for t in db.scalars(select(ScheduledTrigger).where(ScheduledTrigger.workflow_id == wf.id))}
    for node_id, trigger in existing_schedules.items():
        if node_id not in schedule_nodes:
            db.delete(trigger)
    for node_id, node in schedule_nodes.items():
        spec = get_spec("trigger.schedule")
        schedule = {**spec.defaults(), **node.get("config", {})}
        trigger = existing_schedules.get(node_id)
        if trigger is None:
            trigger = ScheduledTrigger(workspace_id=wf.workspace_id, workflow_id=wf.id, node_id=node_id, schedule=schedule)
            db.add(trigger)
        changed = trigger.schedule != schedule or trigger.next_run_at is None or trigger.enabled != wf.is_active
        trigger.schedule = schedule
        trigger.enabled = wf.is_active
        if not wf.is_active:
            trigger.next_run_at = None
        elif changed:
            trigger.next_run_at = compute_next_run(schedule)
            if trigger.next_run_at is None:
                trigger.enabled = False


# ----------------------------------------------------------------- executions
def create_execution(
    db: Session,
    wf: Workflow,
    version: WorkflowVersion,
    *,
    mode: str = "run",
    trigger_type: str = "manual",
    trigger_node_id: str | None = None,
    trigger_data: Any = None,
    user_id: str | None = None,
    retry_of_id: str | None = None,
) -> WorkflowExecution:
    settings = get_settings()
    pending = db.scalar(
        select(func.count()).select_from(WorkflowExecution).where(WorkflowExecution.workspace_id == wf.workspace_id, WorkflowExecution.status == "pending")
    )
    if (pending or 0) >= settings.max_pending_per_workspace:
        raise HTTPException(status_code=429, detail="Too many queued executions in this workspace. Try again shortly.")
    execution = WorkflowExecution(
        workspace_id=wf.workspace_id,
        workflow_id=wf.id,
        version_id=version.id,
        workflow_name=wf.name,
        mode=mode,
        status="pending",
        trigger_type=trigger_type,
        trigger_node_id=trigger_node_id,
        trigger_data=trigger_data if trigger_data is not None else {},
        created_by=user_id,
        retry_of_id=retry_of_id,
    )
    db.add(execution)
    db.flush()
    return execution

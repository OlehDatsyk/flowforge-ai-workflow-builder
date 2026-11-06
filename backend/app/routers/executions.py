"""Execution history, inspector, cancellation, retry and analytics."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from ..database import utcnow
from ..deps import WorkspaceContext, editor, get_db, get_workspace
from ..engine.registry import get_spec
from ..models import NodeExecution, Workflow, WorkflowExecution, WorkflowVersion
from ..security import redact
from ..services import audit, create_execution

router = APIRouter(prefix="/api/executions", tags=["executions"])
analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])
ACTIVE = ("pending", "running", "waiting")


class RetryBody(BaseModel):
    confirm_side_effects: bool = False


def _summary(ex: WorkflowExecution) -> dict:
    return {
        "id": ex.id,
        "workflow_id": ex.workflow_id,
        "workflow_name": ex.workflow_name,
        "status": ex.status,
        "mode": ex.mode,
        "trigger_type": ex.trigger_type,
        "created_at": ex.created_at,
        "started_at": ex.started_at,
        "finished_at": ex.finished_at,
        "duration_ms": ex.duration_ms,
        "nodes_executed": ex.nodes_executed,
        "error": ex.error,
        "error_type": ex.error_type,
        "retry_of_id": ex.retry_of_id,
        "is_demo": ex.is_demo,
    }


def _get(db: Session, ctx: WorkspaceContext, execution_id: str) -> WorkflowExecution:
    ex = db.scalar(
        select(WorkflowExecution)
        .options(selectinload(WorkflowExecution.nodes))
        .where(WorkflowExecution.id == execution_id, WorkflowExecution.workspace_id == ctx.workspace_id)
    )
    if ex is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return ex


@router.get("")
def list_executions(
    search: str = Query("", max_length=160),
    status: str = Query("", pattern="^(|pending|running|waiting|completed|failed|cancelled)$"),
    workflow_id: str = Query("", max_length=32),
    mode: str = Query("", pattern="^(|run|test)$"),
    include_demo: bool = True,
    sort: str = Query("created_at", pattern="^(created_at|duration_ms|workflow_name|status|nodes_executed|id)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: WorkspaceContext = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    base = select(WorkflowExecution).where(WorkflowExecution.workspace_id == ctx.workspace_id)
    if search:
        needle = f"%{search.replace('%', '').lower()}%"
        base = base.where(or_(func.lower(WorkflowExecution.workflow_name).like(needle), func.lower(WorkflowExecution.id).like(needle)))
    if status:
        base = base.where(WorkflowExecution.status == status)
    if workflow_id:
        base = base.where(WorkflowExecution.workflow_id == workflow_id)
    if mode:
        base = base.where(WorkflowExecution.mode == mode)
    if not include_demo:
        base = base.where(WorkflowExecution.is_demo.is_(False))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    column = getattr(WorkflowExecution, sort)
    ordering = column.asc() if order == "asc" else column.desc()
    rows = db.scalars(base.order_by(ordering, WorkflowExecution.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "items": [_summary(r) for r in rows]}


@router.get("/{execution_id}")
def read_execution(execution_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    ex = _get(db, ctx, execution_id)
    version = db.get(WorkflowVersion, ex.version_id)
    has_side_effects = False
    for n in version.definition.get("nodes", []):
        spec = get_spec(n.get("type", ""))
        if spec and spec.has_side_effects({**spec.defaults(), **n.get("config", {})}):
            has_side_effects = True
    data = _summary(ex)
    retries = db.scalars(select(WorkflowExecution.id).where(WorkflowExecution.retry_of_id == ex.id)).all()
    data.update(
        {
            "version": version.version,
            "version_id": version.id,
            "definition": version.definition,
            "failed_node_id": ex.failed_node_id,
            "trigger_data": redact(ex.trigger_data),
            "result": ex.result,
            "retry_ids": retries,
            "can_retry": ex.status in ("failed", "cancelled") and not ex.is_demo,
            "can_cancel": ex.status in ACTIVE,
            "has_side_effects": has_side_effects,
            "nodes": [
                {
                    "id": n.id,
                    "node_id": n.node_id,
                    "node_name": n.node_name,
                    "node_type": n.node_type,
                    "sequence": n.sequence,
                    "iteration": n.iteration,
                    "status": n.status,
                    "attempts": n.attempts,
                    "started_at": n.started_at,
                    "finished_at": n.finished_at,
                    "duration_ms": n.duration_ms,
                    "input": n.input_summary,
                    "output": n.output_summary,
                    "error": n.error,
                    "error_type": n.error_type,
                    "simulated": n.simulated,
                    "ai_provider": n.ai_provider,
                    "ai_input_tokens": n.ai_input_tokens,
                    "ai_output_tokens": n.ai_output_tokens,
                }
                for n in ex.nodes
            ],
        }
    )
    return data


@router.post("/{execution_id}/cancel")
def cancel(execution_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    ex = _get(db, ctx, execution_id)
    if ex.status not in ACTIVE:
        raise HTTPException(status_code=409, detail=f"This execution is already {ex.status}")
    # A pending job is finished atomically so the worker cannot claim it afterwards.
    now = utcnow()
    finished = db.execute(
        update(WorkflowExecution)
        .where(WorkflowExecution.id == ex.id, WorkflowExecution.status == "pending")
        .values(status="cancelled", finished_at=now, error="Cancelled before it started", cancel_requested=True, duration_ms=0)
    )
    if finished.rowcount == 0:
        db.execute(update(WorkflowExecution).where(WorkflowExecution.id == ex.id).values(cancel_requested=True))
    audit(db, "execution.cancel", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="execution", entity_id=ex.id, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@router.post("/{execution_id}/retry", status_code=202)
def retry(execution_id: str, body: RetryBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    ex = _get(db, ctx, execution_id)
    if ex.is_demo:
        raise HTTPException(status_code=400, detail="Demonstration records cannot be retried. Run the workflow instead.")
    if ex.status not in ("failed", "cancelled"):
        raise HTTPException(status_code=409, detail="Only failed or cancelled executions can be retried")
    version = db.get(WorkflowVersion, ex.version_id)
    if ex.mode == "run" and not body.confirm_side_effects:
        for n in version.definition.get("nodes", []):
            spec = get_spec(n.get("type", ""))
            if spec and spec.has_side_effects({**spec.defaults(), **n.get("config", {})}):
                raise HTTPException(status_code=409, detail={"message": f"Retrying repeats external actions such as '{n['name']}'. Confirm to continue.", "code": "confirm_side_effects"})
    wf = db.get(Workflow, ex.workflow_id)
    new = create_execution(db, wf, version, mode=ex.mode, trigger_type=ex.trigger_type, trigger_node_id=ex.trigger_node_id, trigger_data=ex.trigger_data, user_id=ctx.user.id, retry_of_id=ex.id)
    audit(db, "execution.retry", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="execution", entity_id=new.id, details={"retry_of": ex.id}, ip=ctx.ip)
    db.commit()
    return {"execution_id": new.id, "status": new.status}


RANGES = {"24h": (timedelta(hours=24), "hour"), "7d": (timedelta(days=7), "day"), "30d": (timedelta(days=30), "day")}


def _bucket(moment: datetime, unit: str) -> str:
    if unit == "hour":
        return moment.replace(minute=0, second=0, microsecond=0).isoformat()
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * pct))]


@analytics_router.get("/overview")
def overview(
    range: str = Query("7d", pattern="^(24h|7d|30d)$"),
    workflow_id: str = Query("", max_length=32),
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    include_demo: bool = True,
    ctx: WorkspaceContext = Depends(get_workspace),
    db: Session = Depends(get_db),
):
    """All numbers are computed from execution rows. Test runs are excluded; demo rows are counted separately."""
    span, unit = RANGES[range]
    now = utcnow()
    since = now - span
    until = now
    if start:
        since = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
        unit = "hour" if (until - since) <= timedelta(hours=48) else "day"
    if end:
        until = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        unit = "hour" if (until - since) <= timedelta(hours=48) else "day"
    query = select(WorkflowExecution).where(
        WorkflowExecution.workspace_id == ctx.workspace_id,
        WorkflowExecution.created_at >= since,
        WorkflowExecution.created_at <= until,
        WorkflowExecution.mode == "run",
    )
    if workflow_id:
        query = query.where(WorkflowExecution.workflow_id == workflow_id)
    if not include_demo:
        query = query.where(WorkflowExecution.is_demo.is_(False))
    rows = db.scalars(query.order_by(WorkflowExecution.created_at).limit(50_000)).all()

    series: dict[str, dict] = {}
    cursor = since
    step = timedelta(hours=1) if unit == "hour" else timedelta(days=1)
    while cursor <= until and len(series) < 800:
        key = _bucket(cursor, unit)
        series[key] = {"bucket": key, "completed": 0, "failed": 0, "cancelled": 0, "total": 0, "avg_duration_ms": None, "_durations": []}
        cursor += step
    per_workflow: Counter = Counter()
    per_workflow_failed: Counter = Counter()
    durations_by_workflow: dict[str, list[int]] = defaultdict(list)
    names: dict[str, str] = {}
    failures: Counter = Counter()
    durations: list[int] = []
    statuses: Counter = Counter()
    demo_count = 0
    for ex in rows:
        statuses[ex.status] += 1
        demo_count += 1 if ex.is_demo else 0
        key = _bucket(ex.created_at, unit)
        point = series.get(key)
        if point is None:
            point = series[key] = {"bucket": key, "completed": 0, "failed": 0, "cancelled": 0, "total": 0, "avg_duration_ms": None, "_durations": []}
        point["total"] += 1
        if ex.status in ("completed", "failed", "cancelled"):
            point[ex.status] += 1
        names[ex.workflow_id] = ex.workflow_name
        per_workflow[ex.workflow_id] += 1
        if ex.status == "failed":
            per_workflow_failed[ex.workflow_id] += 1
            failures[ex.error_type or "unknown"] += 1
        if ex.duration_ms is not None and ex.status in ("completed", "failed"):
            durations.append(ex.duration_ms)
            point["_durations"].append(ex.duration_ms)
            durations_by_workflow[ex.workflow_id].append(ex.duration_ms)
    for point in series.values():
        values = point.pop("_durations")
        point["avg_duration_ms"] = round(sum(values) / len(values)) if values else None

    categories: Counter = Counter()
    if names:
        cats = dict(db.execute(select(Workflow.id, Workflow.category).where(Workflow.id.in_(names.keys()))).all())
        for wf_id, count in per_workflow.items():
            categories[cats.get(wf_id, "General")] += count

    ai_query = (
        select(NodeExecution.ai_provider, func.count(), func.sum(NodeExecution.ai_input_tokens), func.sum(NodeExecution.ai_output_tokens))
        .join(WorkflowExecution, NodeExecution.execution_id == WorkflowExecution.id)
        .where(
            WorkflowExecution.workspace_id == ctx.workspace_id,
            WorkflowExecution.created_at >= since,
            WorkflowExecution.created_at <= until,
            WorkflowExecution.mode == "run",
            NodeExecution.ai_provider.is_not(None),
        )
        .group_by(NodeExecution.ai_provider)
    )
    if workflow_id:
        ai_query = ai_query.where(WorkflowExecution.workflow_id == workflow_id)
    if not include_demo:
        ai_query = ai_query.where(WorkflowExecution.is_demo.is_(False))
    ai_usage = [{"provider": p, "calls": c, "input_tokens": i or 0, "output_tokens": o or 0} for p, c, i, o in db.execute(ai_query)]

    finished = statuses["completed"] + statuses["failed"]
    total_workflows = db.scalar(select(func.count()).select_from(Workflow).where(Workflow.workspace_id == ctx.workspace_id))
    active_workflows = db.scalar(select(func.count()).select_from(Workflow).where(Workflow.workspace_id == ctx.workspace_id, Workflow.is_active.is_(True)))
    return {
        "range": range,
        "unit": unit,
        "since": since,
        "until": until,
        "demo_count": demo_count,
        "real_count": len(rows) - demo_count,
        "totals": {
            "workflows": total_workflows,
            "active_workflows": active_workflows,
            "executions": len(rows),
            "completed": statuses["completed"],
            "failed": statuses["failed"],
            "cancelled": statuses["cancelled"],
            "running": statuses["running"] + statuses["pending"] + statuses["waiting"],
            "success_rate": round(statuses["completed"] / finished * 100, 1) if finished else None,
            "failure_rate": round(statuses["failed"] / finished * 100, 1) if finished else None,
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else None,
            "p95_duration_ms": _percentile(durations, 0.95),
        },
        "series": [series[k] for k in sorted(series)],
        "top_workflows": [
            {
                "workflow_id": wf_id,
                "name": names[wf_id],
                "runs": count,
                "failed": per_workflow_failed[wf_id],
                "avg_duration_ms": round(sum(durations_by_workflow[wf_id]) / len(durations_by_workflow[wf_id])) if durations_by_workflow[wf_id] else None,
            }
            for wf_id, count in per_workflow.most_common(8)
        ],
        "categories": [{"category": c, "runs": n} for c, n in categories.most_common()],
        "failure_types": [{"type": t, "count": n} for t, n in failures.most_common(8)],
        "ai_usage": ai_usage,
    }

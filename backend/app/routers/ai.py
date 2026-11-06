"""AI builder endpoints. Every endpoint only proposes: applying a proposal is a separate user action."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.planner import explain_workflow, generate_workflow, modify_workflow
from ..ai.providers import AIError, resolve_provider
from ..deps import WorkspaceContext, editor, get_db, get_workspace, limit
from ..engine.validator import validate_definition
from ..models import AIConversation, Workflow
from ..services import audit, create_version, set_draft, sync_triggers
from .workflows import check_savable, credential_ids, get_workflow, serialize

router = APIRouter(prefix="/api/ai", tags=["ai"])

EXAMPLES = [
    "When a new email arrives containing an invoice, extract the invoice number, supplier name, amount and due date, save the information in the database, and notify me.",
    "Create a workflow that receives a webhook, validates the JSON data, and stores it in the database.",
    "When a new customer is registered, classify their account type and create a welcome message.",
    "Read an uploaded CSV file, identify missing information, and generate a report.",
    "Summarise new support tickets and assign a priority.",
]


class GenerateBody(BaseModel):
    prompt: str = Field(min_length=5, max_length=4000)


class ModifyBody(BaseModel):
    workflow_id: str
    instruction: str = Field(min_length=3, max_length=4000)
    definition: dict | None = None  # the editor's current state, if it has unsaved changes


class ExplainBody(BaseModel):
    workflow_id: str
    definition: dict | None = None


class AcceptBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    definition: dict | None = None  # the proposal after the user's edits in review


def _provider(db: Session, ctx: WorkspaceContext):
    try:
        return resolve_provider(db, ctx.workspace_id)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _record(db: Session, ctx: WorkspaceContext, kind: str, prompt: str, proposal: dict, started: float, workflow_id: str | None = None) -> AIConversation:
    usage = proposal.get("usage") or {}
    row = AIConversation(
        workspace_id=ctx.workspace_id,
        user_id=ctx.user.id,
        workflow_id=workflow_id,
        kind=kind,
        prompt=prompt,
        response=proposal,
        status=proposal.get("status", "proposed"),
        provider=proposal.get("provider", "demo"),
        model=proposal.get("model", ""),
        is_demo=bool(proposal.get("is_demo")),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    db.add(row)
    db.flush()
    return row


@router.get("/status")
def status(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    provider = _provider(db, ctx)
    return {"provider": provider.name, "model": provider.model, "is_demo": provider.is_demo, "examples": EXAMPLES}


@router.post("/generate")
def generate(body: GenerateBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    limit(f"ai:{ctx.user.id}", 30, 60)
    provider = _provider(db, ctx)
    started = time.perf_counter()
    try:
        proposal = generate_workflow(provider, body.prompt, credential_ids(db, ctx.workspace_id))
    except AIError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}") from exc
    row = _record(db, ctx, "generate", body.prompt, proposal, started)
    db.commit()
    return {**proposal, "conversation_id": row.id}


@router.post("/modify")
def modify(body: ModifyBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    limit(f"ai:{ctx.user.id}", 30, 60)
    wf = get_workflow(db, ctx, body.workflow_id)
    definition = check_savable(body.definition) if body.definition else wf.draft_definition
    provider = _provider(db, ctx)
    started = time.perf_counter()
    try:
        proposal = modify_workflow(provider, body.instruction, definition, wf.name, credential_ids(db, ctx.workspace_id))
    except AIError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}") from exc
    row = _record(db, ctx, "modify", body.instruction, proposal, started, wf.id)
    db.commit()
    return {**proposal, "conversation_id": row.id}


@router.post("/explain")
def explain(body: ExplainBody, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    limit(f"ai:{ctx.user.id}", 30, 60)
    wf = get_workflow(db, ctx, body.workflow_id)
    provider = _provider(db, ctx)
    started = time.perf_counter()
    try:
        result = explain_workflow(provider, body.definition or wf.draft_definition, wf.name)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}") from exc
    _record(db, ctx, "explain", f"Explain {wf.name}", result, started, wf.id)
    db.commit()
    return result


@router.post("/conversations/{conversation_id}/accept", status_code=201)
def accept(conversation_id: str, body: AcceptBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    """Saves a reviewed proposal as a NEW, INACTIVE workflow. Nothing runs and nothing is activated."""
    row = db.scalar(select(AIConversation).where(AIConversation.id == conversation_id, AIConversation.workspace_id == ctx.workspace_id))
    if row is None or row.kind != "generate":
        raise HTTPException(status_code=404, detail="Proposal not found")
    workflow = row.response.get("workflow") or {}
    definition = body.definition or workflow.get("definition")
    if not definition:
        raise HTTPException(status_code=422, detail="This proposal has no workflow to save")
    if row.status == "accepted":
        raise HTTPException(status_code=409, detail="This proposal was already saved")
    clean = check_savable(definition)
    wf = Workflow(
        workspace_id=ctx.workspace_id,
        name=(body.name or workflow.get("name") or "Generated workflow").strip()[:160],
        description=workflow.get("description") or row.prompt[:1000],
        category="AI Generated",
        created_by=ctx.user.id,
        draft_definition=clean,
        is_active=False,
    )
    set_draft(wf, clean)
    db.add(wf)
    db.flush()
    create_version(db, wf, ctx.user.id, "Generated by AI, reviewed by user" if not row.is_demo else "Generated by demo planner, reviewed by user")
    sync_triggers(db, wf)
    row.status = "accepted"
    row.workflow_id = wf.id
    audit(db, "ai.accept_proposal", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"provider": row.provider, "is_demo": row.is_demo}, ip=ctx.ip)
    db.commit()
    data = serialize(wf, full=True)
    data["validation"] = validate_definition(clean, credential_ids(db, ctx.workspace_id)).public()
    return data


@router.get("/conversations")
def conversations(page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50), ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    base = select(AIConversation).where(AIConversation.workspace_id == ctx.workspace_id, AIConversation.kind == "generate")
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(AIConversation.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "total": total,
        "items": [
            {"id": r.id, "prompt": r.prompt, "status": r.status, "provider": r.provider, "is_demo": r.is_demo, "workflow_id": r.workflow_id, "created_at": r.created_at, "proposal": r.response}
            for r in rows
        ],
    }

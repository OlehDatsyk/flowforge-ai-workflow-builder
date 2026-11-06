"""Template library backed by the workflow_templates table."""
from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select, func
from sqlalchemy.orm import Session

from ..deps import WorkspaceContext, editor, get_db, get_workspace
from ..engine.definition import auto_layout
from ..models import Workflow, WorkflowTemplate
from ..services import audit, create_version, set_draft, sync_triggers
from .workflows import serialize

router = APIRouter(prefix="/api/templates", tags=["templates"])


class UseTemplate(BaseModel):
    name: str | None = Field(default=None, max_length=160)


def _public(t: WorkflowTemplate, full: bool = True) -> dict:
    return {
        "id": t.id,
        "slug": t.slug,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "required_integrations": t.required_integrations,
        "expected_behaviour": t.expected_behaviour,
        "configuration_requirements": t.configuration_requirements,
        "needs_configuration": bool(t.configuration_requirements),
        "definition": t.definition if full else None,
        "node_count": len(t.definition.get("nodes", [])),
    }


@router.get("")
def list_templates(search: str = Query("", max_length=160), category: str = Query("", max_length=60), ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    query = select(WorkflowTemplate)
    if search:
        needle = f"%{search.replace('%', '').lower()}%"
        query = query.where(or_(func.lower(WorkflowTemplate.name).like(needle), func.lower(WorkflowTemplate.description).like(needle)))
    if category:
        query = query.where(WorkflowTemplate.category == category)
    rows = db.scalars(query.order_by(WorkflowTemplate.name)).all()
    return {"items": [_public(t) for t in rows], "categories": sorted(set(db.scalars(select(WorkflowTemplate.category))))}


@router.post("/{slug}/use", status_code=201)
def use_template(slug: str, body: UseTemplate, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    template = db.scalar(select(WorkflowTemplate).where(WorkflowTemplate.slug == slug))
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    definition = auto_layout(copy.deepcopy(template.definition))
    wf = Workflow(workspace_id=ctx.workspace_id, name=(body.name or template.name).strip() or template.name, description=template.description, category=template.category, created_by=ctx.user.id, draft_definition=definition, tags=["template"])
    set_draft(wf, definition)
    db.add(wf)
    db.flush()
    create_version(db, wf, ctx.user.id, f"Created from template: {template.name}")
    sync_triggers(db, wf)
    audit(db, "workflow.from_template", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workflow", entity_id=wf.id, details={"template": slug}, ip=ctx.ip)
    db.commit()
    return serialize(wf, full=True)

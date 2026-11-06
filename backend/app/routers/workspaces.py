"""Workspaces, members, audit log, and demo data management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..deps import WorkspaceContext, admin, get_db, get_user, get_workspace
from ..models import AuditLog, User, Workflow, WorkflowExecution, Workspace, WorkspaceMember
from ..services import audit

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
audit_router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


class WorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MemberBody(BaseModel):
    email: EmailStr
    role: str = Field(default="editor", pattern="^(admin|editor|viewer)$")


class RoleBody(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")


def _demo_guard(ctx: WorkspaceContext) -> None:
    if ctx.user.is_demo:
        raise HTTPException(status_code=403, detail="This is not available in the shared demo account. Register for your own workspace.")


@router.get("")
def list_workspaces(user: User = Depends(get_user), db: Session = Depends(get_db)):
    members = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at)).all()
    return [{"id": m.workspace_id, "name": m.workspace.name, "role": m.role} for m in members]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceBody, user: User = Depends(get_user), db: Session = Depends(get_db)):
    if user.is_demo:
        raise HTTPException(status_code=403, detail="Register for your own account to create workspaces")
    count = db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == user.id, WorkspaceMember.role == "owner"))
    if (count or 0) >= 20:
        raise HTTPException(status_code=400, detail="Workspace limit reached (20)")
    workspace = Workspace(name=body.name.strip(), settings={})
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    audit(db, "workspace.create", workspace_id=workspace.id, user_id=user.id, entity_type="workspace", entity_id=workspace.id)
    db.commit()
    return {"id": workspace.id, "name": workspace.name, "role": "owner"}


@router.get("/current")
def current(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    demo_workflows = db.scalar(select(func.count()).select_from(Workflow).where(Workflow.workspace_id == ctx.workspace_id, Workflow.is_demo.is_(True)))
    demo_execs = db.scalar(select(func.count()).select_from(WorkflowExecution).where(WorkflowExecution.workspace_id == ctx.workspace_id, WorkflowExecution.is_demo.is_(True)))
    return {"id": ctx.workspace_id, "name": ctx.workspace.name, "role": ctx.role, "demo_workflows": demo_workflows, "demo_executions": demo_execs}


@router.patch("/current")
def rename(body: WorkspaceBody, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    _demo_guard(ctx)
    workspace = db.get(Workspace, ctx.workspace_id)
    workspace.name = body.name.strip()
    audit(db, "workspace.rename", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="workspace", entity_id=ctx.workspace_id, ip=ctx.ip)
    db.commit()
    return {"id": workspace.id, "name": workspace.name, "role": ctx.role}


@router.delete("/current")
def delete_workspace(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    ctx.require("owner")
    _demo_guard(ctx)
    owned = db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == ctx.user.id))
    if (owned or 0) <= 1:
        raise HTTPException(status_code=400, detail="You cannot delete your only workspace")
    # Versions restrict deletion while executions reference them, so remove executions first.
    db.execute(delete(WorkflowExecution).where(WorkflowExecution.workspace_id == ctx.workspace_id))
    db.delete(db.get(Workspace, ctx.workspace_id))
    db.commit()
    return {"ok": True}


@router.get("/current/members")
def members(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    rows = db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.workspace_id).order_by(WorkspaceMember.created_at)).all()
    return [{"user_id": m.user_id, "email": m.user.email, "name": m.user.name, "role": m.role} for m in rows]


@router.post("/current/members", status_code=201)
def add_member(body: MemberBody, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    _demo_guard(ctx)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user is None:
        raise HTTPException(status_code=404, detail="No FlowForge account uses that email. Ask them to register first.")
    exists = db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == user.id))
    if exists:
        raise HTTPException(status_code=409, detail="That person is already a member")
    db.add(WorkspaceMember(workspace_id=ctx.workspace_id, user_id=user.id, role=body.role))
    audit(db, "member.add", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="user", entity_id=user.id, details={"role": body.role}, ip=ctx.ip)
    db.commit()
    return {"user_id": user.id, "email": user.email, "name": user.name, "role": body.role}


def _member(db: Session, ctx: WorkspaceContext, user_id: str) -> WorkspaceMember:
    member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ctx.workspace_id, WorkspaceMember.user_id == user_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="The workspace owner cannot be changed or removed")
    return member


@router.patch("/current/members/{user_id}")
def change_role(user_id: str, body: RoleBody, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    member = _member(db, ctx, user_id)
    member.role = body.role
    audit(db, "member.role", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="user", entity_id=user_id, details={"role": body.role}, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@router.delete("/current/members/{user_id}")
def remove_member(user_id: str, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    db.delete(_member(db, ctx, user_id))
    audit(db, "member.remove", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="user", entity_id=user_id, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@router.post("/current/demo-data")
def load_demo(ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    from ..seed import seed_demo_workspace

    if db.scalar(select(func.count()).select_from(Workflow).where(Workflow.workspace_id == ctx.workspace_id, Workflow.is_demo.is_(True))):
        raise HTTPException(status_code=409, detail="Demo data is already loaded")
    seed_demo_workspace(db, ctx.workspace_id, ctx.user.id)
    audit(db, "workspace.demo_loaded", workspace_id=ctx.workspace_id, user_id=ctx.user.id, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@router.delete("/current/demo-data")
def remove_demo(ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    _demo_guard(ctx)
    workflows = db.scalars(select(Workflow.id).where(Workflow.workspace_id == ctx.workspace_id, Workflow.is_demo.is_(True))).all()
    db.execute(delete(WorkflowExecution).where(WorkflowExecution.workspace_id == ctx.workspace_id, WorkflowExecution.workflow_id.in_(workflows)))
    db.execute(delete(Workflow).where(Workflow.id.in_(workflows)))
    audit(db, "workspace.demo_removed", workspace_id=ctx.workspace_id, user_id=ctx.user.id, ip=ctx.ip)
    db.commit()
    return {"ok": True, "removed_workflows": len(workflows)}


@audit_router.get("")
def audit_logs(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    base = select(AuditLog).where(AuditLog.workspace_id == ctx.workspace_id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id})))}
    return {
        "total": total,
        "items": [
            {"id": r.id, "action": r.action, "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.details, "user": names.get(r.user_id, "System"), "ip": r.ip_address, "created_at": r.created_at}
            for r in rows
        ],
    }

"""Request dependencies: DB session, authentication, CSRF and workspace authorisation."""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import SessionLocal, utcnow
from .models import AuthSession, User, Workspace, WorkspaceMember
from .security import hash_token, rate_limiter

SESSION_COOKIE = "ff_session"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2, "owner": 3}


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def get_session(request: Request, db: Session = Depends(get_db)) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if session is None or session.expires_at <= utcnow():
        raise HTTPException(status_code=401, detail="Your session has expired")
    if request.method not in _SAFE_METHODS:
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), session.csrf_token.encode()):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return session


def get_user(session: AuthSession = Depends(get_session)) -> User:
    return session.user


@dataclass
class WorkspaceContext:
    user: User
    workspace: Workspace
    role: str
    ip: str

    @property
    def workspace_id(self) -> str:
        return self.workspace.id

    def require(self, role: str) -> None:
        if _ROLE_RANK[self.role] < _ROLE_RANK[role]:
            raise HTTPException(status_code=403, detail=f"This action needs the {role} role or higher")


def get_workspace(
    request: Request,
    x_workspace_id: str | None = Header(default=None),
    user: User = Depends(get_user),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    """Membership is checked on every request. With no header, the user's first workspace is used."""
    query = select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
    if x_workspace_id:
        query = query.where(WorkspaceMember.workspace_id == x_workspace_id)
    member = db.scalar(query.order_by(WorkspaceMember.created_at).limit(1))
    if member is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceContext(user=user, workspace=member.workspace, role=member.role, ip=client_ip(request))


def editor(ctx: WorkspaceContext = Depends(get_workspace)) -> WorkspaceContext:
    ctx.require("editor")
    return ctx


def admin(ctx: WorkspaceContext = Depends(get_workspace)) -> WorkspaceContext:
    ctx.require("admin")
    return ctx


def limit(key: str, max_hits: int, window: float = 60.0) -> None:
    if not rate_limiter.allow(key, max_hits, window):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.", headers={"Retry-After": str(int(window))})

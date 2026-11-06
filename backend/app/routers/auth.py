"""Registration, login, sessions, profile and password reset."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import utcnow
from ..deps import SESSION_COOKIE, client_ip, get_db, get_session, get_user, limit
from ..models import AuthSession, PasswordResetToken, User, Workspace, WorkspaceMember
from ..security import hash_password, hash_token, new_token, verify_password
from ..services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
_DUMMY_HASH = hash_password("timing-equaliser")


class RegisterBody(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=256)
    workspace_name: str = Field(default="", max_length=120)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=10, max_length=256)


class ResetRequestBody(BaseModel):
    email: EmailStr


class ResetConfirmBody(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(min_length=10, max_length=256)


def user_payload(db: Session, user: User, csrf: str | None = None) -> dict:
    memberships = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at)).all()
    payload = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_demo": user.is_demo,
        "workspaces": [{"id": m.workspace_id, "name": m.workspace.name, "role": m.role} for m in memberships],
    }
    if csrf:
        payload["csrf_token"] = csrf
    return payload


def _start_session(db: Session, user: User, response: Response) -> AuthSession:
    settings = get_settings()
    token = new_token()
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(24),
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at <= utcnow()))
    user.last_login_at = utcnow()
    db.flush()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    return session


@router.post("/register", status_code=201)
def register(body: RegisterBody, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(f"register:{client_ip(request)}", 10, 3600)
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    workspace = Workspace(name=body.workspace_name.strip() or f"{body.name.strip()}'s Workspace", settings={})
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    session = _start_session(db, user, response)
    audit(db, "user.register", workspace_id=workspace.id, user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return user_payload(db, user, session.csrf_token)


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    limit(f"login:{client_ip(request)}:{email}", 10, 300)
    limit(f"login-ip:{client_ip(request)}", 50, 300)
    user = db.scalar(select(User).where(User.email == email))
    # Verify against a dummy hash when the user is unknown so timing does not reveal accounts.
    valid = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if not user or not valid:
        audit(db, "user.login_failed", details={"email": email}, ip=client_ip(request))
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    session = _start_session(db, user, response)
    audit(db, "user.login", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return user_payload(db, user, session.csrf_token)


@router.post("/demo")
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)):
    """One-click access to the shared demonstration workspace."""
    if not get_settings().demo_mode_enabled:
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    limit(f"demo:{client_ip(request)}", 30, 300)
    from ..seed import DEMO_EMAIL, ensure_demo_account

    ensure_demo_account(db)
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    session = _start_session(db, user, response)
    db.commit()
    return user_payload(db, user, session.csrf_token)


@router.post("/logout")
def logout(response: Response, session: AuthSession = Depends(get_session), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(session: AuthSession = Depends(get_session), db: Session = Depends(get_db)):
    return user_payload(db, session.user, session.csrf_token)


@router.patch("/me")
def update_profile(body: ProfileBody, session: AuthSession = Depends(get_session), db: Session = Depends(get_db)):
    if session.user.is_demo:
        raise HTTPException(status_code=403, detail="The shared demo profile cannot be changed")
    session.user.name = body.name.strip()
    db.commit()
    return user_payload(db, session.user, session.csrf_token)


@router.post("/change-password")
def change_password(body: PasswordBody, request: Request, session: AuthSession = Depends(get_session), db: Session = Depends(get_db)):
    user = session.user
    if user.is_demo:
        raise HTTPException(status_code=403, detail="The shared demo account's password cannot be changed")
    limit(f"pwchange:{user.id}", 10, 300)
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.id != session.id))
    audit(db, "user.password_changed", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}


@router.post("/password-reset/request")
def request_reset(body: ResetRequestBody, request: Request, db: Session = Depends(get_db)):
    """Always answers the same way, so it cannot be used to discover accounts.

    FlowForge has no system mail sender configured, so outside production the link
    is returned to the caller for local use. In production it is written nowhere:
    connect a transactional mail provider here before relying on self-service reset.
    """
    limit(f"pwreset:{client_ip(request)}", 5, 300)
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    result: dict = {"ok": True, "message": "If that account exists, a reset link has been issued."}
    if user and not user.is_demo:
        token = new_token()
        db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + timedelta(hours=1)))
        audit(db, "user.password_reset_requested", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
        if not settings.is_production:
            result["dev_reset_token"] = token
    db.commit()
    return result


@router.post("/password-reset/confirm")
def confirm_reset(body: ResetConfirmBody, request: Request, db: Session = Depends(get_db)):
    limit(f"pwreset-confirm:{client_ip(request)}", 10, 300)
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    row.used_at = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, "user.password_reset", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return {"ok": True}

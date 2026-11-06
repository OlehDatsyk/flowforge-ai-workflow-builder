"""Credentials, integrations catalogue, webhook endpoints and the data-store browser."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.providers import AIError, PROVIDER_CLASSES, provider_from_credential, resolve_provider
from ..config import get_settings
from ..database import utcnow
from ..deps import WorkspaceContext, admin, client_ip, editor, get_db, get_workspace, limit
from ..engine.nodes_integration import send_smtp
from ..engine.registry import NodeError
from ..models import Credential, DataRecord, Integration, WebhookRequest, WebhookTrigger, Workflow, WorkflowVersion
from ..security import decrypt_json, encrypt_json, mask_value, new_token, rate_limiter, redact
from ..services import audit, create_execution, ensure_version

credentials_router = APIRouter(prefix="/api/credentials", tags=["credentials"])
integrations_router = APIRouter(prefix="/api/integrations", tags=["integrations"])
webhooks_router = APIRouter(prefix="/api/webhook-triggers", tags=["webhooks"])
hooks_router = APIRouter(tags=["public webhooks"])
data_router = APIRouter(prefix="/api/data", tags=["data store"])

# Which fields each credential type has. `secret` fields are never returned, only masked.
CREDENTIAL_TYPES: dict[str, dict] = {
    "bearer_token": {"label": "Bearer token", "fields": [{"key": "token", "label": "Token", "secret": True, "required": True}]},
    "basic_auth": {
        "label": "Basic auth",
        "fields": [{"key": "username", "label": "Username", "required": True}, {"key": "password", "label": "Password", "secret": True, "required": True}],
    },
    "api_key_header": {
        "label": "API key header",
        "fields": [{"key": "header_name", "label": "Header name", "required": True, "placeholder": "X-API-Key"}, {"key": "api_key", "label": "API key", "secret": True, "required": True}],
    },
    "webhook_secret": {"label": "Webhook signing secret", "fields": [{"key": "secret", "label": "Secret", "secret": True, "required": True}]},
    "smtp": {
        "label": "SMTP server",
        "fields": [
            {"key": "host", "label": "Host", "required": True, "placeholder": "smtp.example.com"},
            {"key": "port", "label": "Port", "required": True, "placeholder": "587"},
            {"key": "security", "label": "Security (starttls, ssl or none)", "placeholder": "starttls"},
            {"key": "username", "label": "Username"},
            {"key": "password", "label": "Password", "secret": True},
            {"key": "from_email", "label": "From address", "required": True, "placeholder": "alerts@example.com"},
        ],
    },
    "anthropic": {"label": "Anthropic API key", "fields": [{"key": "api_key", "label": "API key", "secret": True, "required": True}, {"key": "model", "label": "Model (optional)", "placeholder": "claude-opus-5-5"}]},
    "openai": {"label": "OpenAI API key", "fields": [{"key": "api_key", "label": "API key", "secret": True, "required": True}, {"key": "model", "label": "Model (optional)", "placeholder": "gpt-4o-mini"}]},
    "gemini": {"label": "Google Gemini API key", "fields": [{"key": "api_key", "label": "API key", "secret": True, "required": True}, {"key": "model", "label": "Model (optional)", "placeholder": "gemini-2.0-flash"}]},
}


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: str
    data: dict[str, Any]


class CredentialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    data: dict[str, Any] | None = None  # blank or absent secret fields keep their stored value


def _masked(kind: str, data: dict) -> dict:
    out = {}
    for field in CREDENTIAL_TYPES[kind]["fields"]:
        value = data.get(field["key"])
        if value in (None, ""):
            continue
        out[field["key"]] = mask_value(value) if field.get("secret") else str(value)
    return out


def _check_fields(kind: str, data: dict) -> dict:
    spec = CREDENTIAL_TYPES[kind]
    allowed = {f["key"] for f in spec["fields"]}
    clean = {k: str(v).strip() for k, v in data.items() if k in allowed and v not in (None, "")}
    missing = [f["label"] for f in spec["fields"] if f.get("required") and not clean.get(f["key"])]
    if missing:
        raise HTTPException(status_code=422, detail=f"Required: {', '.join(missing)}")
    if kind == "smtp":
        try:
            port = int(clean["port"])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="SMTP port must be a number") from exc
        if not 1 <= port <= 65535:
            raise HTTPException(status_code=422, detail="SMTP port is out of range")
        if clean.get("security", "starttls") not in ("starttls", "ssl", "none"):
            raise HTTPException(status_code=422, detail="SMTP security must be starttls, ssl or none")
    return clean


def _credential_public(c: Credential, usage: int | None = None) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "type": c.type,
        "type_label": CREDENTIAL_TYPES.get(c.type, {}).get("label", c.type),
        "masked": c.masked,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "used_by": usage,
    }


@credentials_router.get("/types")
def credential_types(ctx: WorkspaceContext = Depends(get_workspace)):
    return CREDENTIAL_TYPES


@credentials_router.get("")
def list_credentials(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    rows = db.scalars(select(Credential).where(Credential.workspace_id == ctx.workspace_id).order_by(Credential.name)).all()
    drafts = db.scalars(select(Workflow.draft_definition).where(Workflow.workspace_id == ctx.workspace_id)).all()
    usage: dict[str, int] = {}
    for definition in drafts:
        ids = {n.get("config", {}).get("credential_id") for n in definition.get("nodes", [])}
        for cid in ids:
            if cid:
                usage[cid] = usage.get(cid, 0) + 1
    return [_credential_public(c, usage.get(c.id, 0)) for c in rows]


@credentials_router.post("", status_code=201)
def create_credential(body: CredentialCreate, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    if body.type not in CREDENTIAL_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported credential type")
    if ctx.user.is_demo:
        raise HTTPException(status_code=403, detail="The shared demo workspace cannot store credentials. Register for your own workspace.")
    if db.scalar(select(Credential.id).where(Credential.workspace_id == ctx.workspace_id, Credential.name == body.name.strip())):
        raise HTTPException(status_code=409, detail="A credential with this name already exists")
    data = _check_fields(body.type, body.data)
    cred = Credential(workspace_id=ctx.workspace_id, name=body.name.strip(), type=body.type, encrypted_data=encrypt_json(data), masked=_masked(body.type, data), created_by=ctx.user.id)
    db.add(cred)
    db.flush()
    audit(db, "credential.create", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="credential", entity_id=cred.id, details={"name": cred.name, "type": cred.type}, ip=ctx.ip)
    db.commit()
    return _credential_public(cred, 0)


def _get_credential(db: Session, ctx: WorkspaceContext, credential_id: str) -> Credential:
    cred = db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == ctx.workspace_id))
    if cred is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    return cred


@credentials_router.patch("/{credential_id}")
def update_credential(credential_id: str, body: CredentialUpdate, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    cred = _get_credential(db, ctx, credential_id)
    if body.name:
        cred.name = body.name.strip()
    if body.data is not None:
        current = decrypt_json(cred.encrypted_data)
        current.update({k: v for k, v in body.data.items() if v not in (None, "")})
        data = _check_fields(cred.type, current)
        cred.encrypted_data = encrypt_json(data)
        cred.masked = _masked(cred.type, data)
    audit(db, "credential.update", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="credential", entity_id=cred.id, ip=ctx.ip)
    db.commit()
    return _credential_public(cred)


@credentials_router.delete("/{credential_id}")
def delete_credential(credential_id: str, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    cred = _get_credential(db, ctx, credential_id)
    audit(db, "credential.delete", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="credential", entity_id=cred.id, details={"name": cred.name}, ip=ctx.ip)
    db.delete(cred)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- integrations
CATALOGUE = [
    {"provider": "http", "name": "HTTP Request", "category": "Core", "icon": "globe", "description": "Call any public HTTP API. Private networks are blocked. Authenticate with a Bearer, Basic or API key credential.", "builtin": True, "credential_types": [], "nodes": ["integration.http"]},
    {"provider": "webhook", "name": "Webhooks", "category": "Core", "icon": "webhook", "description": "Receive signed requests with the Webhook Trigger, and deliver signed payloads with Send Webhook.", "builtin": True, "credential_types": [], "nodes": ["trigger.webhook", "integration.webhook_send"]},
    {"provider": "database", "name": "Built-in Data Store", "category": "Core", "icon": "database", "description": "Insert, query, update and delete records in this workspace's collections.", "builtin": True, "credential_types": [], "nodes": ["integration.database"]},
    {"provider": "smtp", "name": "Email (SMTP)", "category": "Messaging", "icon": "mail", "description": "Send email through your own SMTP server.", "builtin": False, "credential_types": ["smtp"], "nodes": ["integration.email"]},
    {"provider": "anthropic", "name": "Anthropic Claude", "category": "AI", "icon": "sparkles", "description": "Powers AI nodes and the AI Workflow Builder.", "builtin": False, "credential_types": ["anthropic"], "nodes": ["ai.*"]},
    {"provider": "openai", "name": "OpenAI", "category": "AI", "icon": "sparkles", "description": "Powers AI nodes and the AI Workflow Builder.", "builtin": False, "credential_types": ["openai"], "nodes": ["ai.*"]},
    {"provider": "gemini", "name": "Google Gemini", "category": "AI", "icon": "sparkles", "description": "Powers AI nodes and the AI Workflow Builder.", "builtin": False, "credential_types": ["gemini"], "nodes": ["ai.*"]},
]
_PROVIDERS = {c["provider"]: c for c in CATALOGUE}


class ConnectBody(BaseModel):
    credential_id: str
    enabled: bool = True


@integrations_router.get("")
def list_integrations(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    rows = {i.provider: i for i in db.scalars(select(Integration).where(Integration.workspace_id == ctx.workspace_id))}
    settings = get_settings()
    env_keys = {"anthropic": settings.anthropic_api_key, "openai": settings.openai_api_key, "gemini": settings.gemini_api_key}
    out = []
    for item in CATALOGUE:
        row = rows.get(item["provider"])
        connected = item["builtin"] or bool(row and row.credential_id and row.enabled)
        source = "built_in" if item["builtin"] else "credential" if connected else None
        if not connected and env_keys.get(item["provider"]):
            connected, source = True, "server_environment"
        out.append(
            {
                **item,
                "status": "connected" if connected else "not_configured",
                "source": source,
                "credential_id": row.credential_id if row else None,
                "enabled": row.enabled if row else item["builtin"],
                "last_test_at": row.last_test_at if row else None,
                "last_test_ok": row.last_test_ok if row else None,
                "last_test_message": row.last_test_message if row else None,
            }
        )
    return out


def _get_catalogue(provider: str) -> dict:
    item = _PROVIDERS.get(provider)
    if item is None:
        raise HTTPException(status_code=404, detail="Unknown integration")
    return item


@integrations_router.put("/{provider}")
def connect(provider: str, body: ConnectBody, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    item = _get_catalogue(provider)
    if item["builtin"]:
        raise HTTPException(status_code=400, detail="This integration is built in and needs no connection")
    cred = _get_credential(db, ctx, body.credential_id)
    if cred.type not in item["credential_types"]:
        raise HTTPException(status_code=422, detail=f"{item['name']} needs a {', '.join(item['credential_types'])} credential")
    row = db.scalar(select(Integration).where(Integration.workspace_id == ctx.workspace_id, Integration.provider == provider))
    if row is None:
        row = Integration(workspace_id=ctx.workspace_id, provider=provider)
        db.add(row)
    row.credential_id = cred.id
    row.enabled = body.enabled
    row.last_test_at = row.last_test_ok = row.last_test_message = None
    audit(db, "integration.connect", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="integration", entity_id=provider, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@integrations_router.delete("/{provider}")
def disconnect(provider: str, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    _get_catalogue(provider)
    row = db.scalar(select(Integration).where(Integration.workspace_id == ctx.workspace_id, Integration.provider == provider))
    if row:
        db.delete(row)
    audit(db, "integration.disconnect", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="integration", entity_id=provider, ip=ctx.ip)
    db.commit()
    return {"ok": True}


@integrations_router.post("/{provider}/test")
def test_connection(provider: str, ctx: WorkspaceContext = Depends(admin), db: Session = Depends(get_db)):
    """A genuine connection test: authenticates against the provider and sends no messages."""
    limit(f"integration-test:{ctx.workspace_id}", 15, 60)
    item = _get_catalogue(provider)
    if item["builtin"]:
        return {"ok": True, "message": "Built in. Nothing to test."}
    row = db.scalar(select(Integration).where(Integration.workspace_id == ctx.workspace_id, Integration.provider == provider))
    ok, message = False, "Connect a credential first"
    if provider in PROVIDER_CLASSES:
        try:
            if row and row.credential_id:
                ai = provider_from_credential(db.get(Credential, row.credential_id))
            else:
                ai = resolve_provider(db, ctx.workspace_id)
                if ai.is_demo or ai.name != provider:
                    return {"ok": False, "message": message}
            ai.complete("Reply with the single word OK.", "Connection test", max_tokens=64)
            ok, message = True, f"Connected to {ai.name} ({ai.model})"
        except AIError as exc:
            message = str(exc)
    elif row and row.credential_id:
        try:
            send_smtp(decrypt_json(db.get(Credential, row.credential_id).encrypted_data), [], "", "", 15.0)
            ok, message = True, "SMTP server accepted the connection and login"
        except NodeError as exc:
            message = str(exc)
    if row:
        row.last_test_at, row.last_test_ok, row.last_test_message = utcnow(), ok, message[:300]
        db.commit()
    return {"ok": ok, "message": message}


# --------------------------------------------------------------- webhook admin
def _get_trigger(db: Session, ctx: WorkspaceContext, trigger_id: str) -> WebhookTrigger:
    trigger = db.scalar(select(WebhookTrigger).where(WebhookTrigger.id == trigger_id, WebhookTrigger.workspace_id == ctx.workspace_id))
    if trigger is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return trigger


class WebhookPatch(BaseModel):
    enabled: bool


class WebhookTestBody(BaseModel):
    body: Any = None


@webhooks_router.patch("/{trigger_id}")
def patch_webhook(trigger_id: str, body: WebhookPatch, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    trigger = _get_trigger(db, ctx, trigger_id)
    trigger.enabled = body.enabled
    audit(db, "webhook.toggle", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="webhook", entity_id=trigger.id, details={"enabled": body.enabled}, ip=ctx.ip)
    db.commit()
    return {"ok": True, "enabled": trigger.enabled}


@webhooks_router.post("/{trigger_id}/rotate-secret")
def rotate_secret(trigger_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    """Generates a new secret. This is the only response that ever contains it."""
    trigger = _get_trigger(db, ctx, trigger_id)
    secret = new_token(32)
    trigger.encrypted_secret = encrypt_json({"secret": secret})
    audit(db, "webhook.rotate_secret", workspace_id=ctx.workspace_id, user_id=ctx.user.id, entity_type="webhook", entity_id=trigger.id, ip=ctx.ip)
    db.commit()
    return {"secret": secret}


@webhooks_router.get("/{trigger_id}/requests")
def webhook_requests(trigger_id: str, ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    trigger = _get_trigger(db, ctx, trigger_id)
    rows = db.scalars(select(WebhookRequest).where(WebhookRequest.trigger_id == trigger.id).order_by(WebhookRequest.received_at.desc()).limit(50)).all()
    return [
        {"id": r.id, "received_at": r.received_at, "method": r.method, "status_code": r.status_code, "outcome": r.outcome, "headers": r.headers, "body": r.body_preview, "execution_id": r.execution_id, "source_ip": r.source_ip}
        for r in rows
    ]


@webhooks_router.post("/{trigger_id}/test", status_code=202)
def test_webhook(trigger_id: str, body: WebhookTestBody, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    """Runs the trigger's workflow in test mode with a sample request, from inside the app."""
    trigger = _get_trigger(db, ctx, trigger_id)
    wf = db.get(Workflow, trigger.workflow_id)
    version = ensure_version(db, wf, ctx.user.id, "Snapshot for webhook test")
    node = next((n for n in version.definition.get("nodes", []) if n["id"] == trigger.node_id), {})
    sample = body.body if body.body is not None else node.get("config", {}).get("sample_body") or {}
    data = {"body": sample, "headers": {"content-type": "application/json"}, "query": {}, "method": "POST"}
    execution = create_execution(db, wf, version, mode="test", trigger_type="webhook", trigger_node_id=trigger.node_id, trigger_data=data, user_id=ctx.user.id)
    db.add(WebhookRequest(trigger_id=trigger.id, method="TEST", status_code=202, outcome="In-app test (side effects simulated)", headers={}, body_preview=_preview(sample), execution_id=execution.id, source_ip="in-app"))
    db.commit()
    return {"execution_id": execution.id}


def _preview(value: Any) -> Any:
    encoded = json.dumps(redact(value), default=str)
    return json.loads(encoded) if len(encoded) <= 8000 else {"_truncated": True, "_preview": encoded[:2000]}


# ---------------------------------------------------------------- public hooks
def _verify_signature(request: Request, raw: bytes, secret: str, mode: str) -> str | None:
    """Returns a rejection reason, or None when the request is authentic."""
    if mode == "token":
        supplied = request.headers.get("x-flowforge-token", "")
        return None if hmac.compare_digest(supplied.encode(), secret.encode()) else "Missing or invalid X-FlowForge-Token"
    timestamp = request.headers.get("x-flowforge-timestamp", "")
    signature = request.headers.get("x-flowforge-signature", "")
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return "Missing or invalid X-FlowForge-Timestamp"
    if age > 300:
        return "Timestamp is outside the 5 minute window"
    expected = "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return None if hmac.compare_digest(signature.encode(), expected.encode()) else "Signature does not match"


@hooks_router.api_route("/hooks/{token}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def receive_webhook(token: str, request: Request):
    settings = get_settings()
    if not rate_limiter.allow(f"hook:{token}", settings.webhook_rate_per_minute, 60):
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429, headers={"Retry-After": "60"})
    declared = request.headers.get("content-length")
    too_big = bool(declared and declared.isdigit() and int(declared) > settings.webhook_max_body_bytes)
    raw = bytearray()
    if not too_big:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > settings.webhook_max_body_bytes:
                too_big = True
                break
    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(_process_webhook, token, request, bytes(raw), too_big)


def _process_webhook(token: str, request: Request, raw: bytes, too_big: bool) -> JSONResponse:
    from ..database import session_scope

    settings = get_settings()
    with session_scope() as db:
        trigger = db.scalar(select(WebhookTrigger).where(WebhookTrigger.token == token))
        if trigger is None:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        headers = redact({k: v for k, v in request.headers.items()})
        ip = client_ip(request)

        def respond(code: int, message: str, body_preview: Any = None, execution_id: str | None = None) -> JSONResponse:
            db.add(WebhookRequest(trigger_id=trigger.id, method=request.method, status_code=code, outcome=message[:200], headers=headers, body_preview=body_preview, execution_id=execution_id, source_ip=ip))
            trigger.request_count += 1
            trigger.last_request_at = utcnow()
            payload: dict = {"execution_id": execution_id, "status": "accepted"} if code < 300 else {"detail": message}
            return JSONResponse(payload, status_code=code)

        if too_big:
            return respond(413, f"Body is larger than {settings.webhook_max_body_bytes} bytes")
        wf = db.get(Workflow, trigger.workflow_id)
        if not trigger.enabled or not wf.is_active or not wf.active_version_id:
            return respond(409, "This webhook is not active. Activate the workflow to receive requests.")
        version = db.get(WorkflowVersion, wf.active_version_id)
        node = next((n for n in version.definition.get("nodes", []) if n["id"] == trigger.node_id), None)
        if node is None:
            return respond(409, "This webhook is not part of the published version. Publish the workflow again.")
        config = node.get("config", {})
        mode = config.get("auth_mode", "hmac")
        if mode == "none" and settings.is_production:
            return respond(403, "Unauthenticated webhooks are disabled in production")
        if mode != "none":
            reason = _verify_signature(request, raw, decrypt_json(trigger.encrypted_secret)["secret"], mode)
            if reason:
                return respond(401, reason)
        text = raw.decode("utf-8", errors="replace")
        is_json = "json" in request.headers.get("content-type", "").lower() or text.lstrip()[:1] in ("{", "[")
        body: Any = text
        if text and is_json:
            try:
                body = json.loads(text)
            except (ValueError, RecursionError):  # includes absurdly deep nesting
                return respond(400, "Body is not valid JSON")
        required = config.get("required_fields") or []
        if required:
            missing = [f for f in required if not (isinstance(body, dict) and body.get(f) not in (None, ""))]
            if missing:
                return respond(422, f"Missing required fields: {', '.join(missing)}", _preview(body))
        data = {
            "body": body,
            "headers": {k: v for k, v in headers.items() if not k.startswith("x-flowforge-")},
            "query": dict(request.query_params),
            "method": request.method,
        }
        try:
            execution = create_execution(db, wf, version, trigger_type="webhook", trigger_node_id=trigger.node_id, trigger_data=data)
        except HTTPException as exc:
            return respond(exc.status_code, str(exc.detail))
        return respond(202, "Accepted", _preview(body), execution.id)


# ------------------------------------------------------------------ data store
@data_router.get("/collections")
def collections(ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    rows = db.execute(
        select(DataRecord.collection, func.count(), func.max(DataRecord.created_at))
        .where(DataRecord.workspace_id == ctx.workspace_id)
        .group_by(DataRecord.collection)
        .order_by(DataRecord.collection)
    ).all()
    return [{"name": name, "count": count, "last_write_at": last} for name, count, last in rows]


@data_router.get("/collections/{name}")
def records(name: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), ctx: WorkspaceContext = Depends(get_workspace), db: Session = Depends(get_db)):
    base = select(DataRecord).where(DataRecord.workspace_id == ctx.workspace_id, DataRecord.collection == name)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.scalars(base.order_by(DataRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [{"id": r.id, "data": r.data, "created_at": r.created_at, "execution_id": r.execution_id} for r in rows]}


@data_router.delete("/records/{record_id}")
def delete_record(record_id: str, ctx: WorkspaceContext = Depends(editor), db: Session = Depends(get_db)):
    row = db.scalar(select(DataRecord).where(DataRecord.id == record_id, DataRecord.workspace_id == ctx.workspace_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


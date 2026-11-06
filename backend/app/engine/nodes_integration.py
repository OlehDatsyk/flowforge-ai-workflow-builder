"""Integration nodes: outbound HTTP, signed webhook delivery, SMTP email and the data store.

Test mode (``ctx.mode == "test"``) never changes the outside world: every side
effect returns an explicit ``{"simulated": true}`` result and the node execution
is flagged as simulated.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import func, select

from ..config import get_settings
from ..database import session_scope
from ..models import DataRecord
from .expressions import _stringify
from .registry import FieldSpec as F
from .registry import NodeError, NodeResult, NodeSpec, PortSpec, register
from .ssrf import BlockedDestination, ValidatedTarget, validate_host, validate_url

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HOP_HEADERS = {"host", "content-length", "transfer-encoding", "connection"}


def _pinned_request_args(target: ValidatedTarget) -> tuple[str, dict, dict]:
    """Connect to the validated IP while keeping Host/SNI/cert checks on the hostname."""
    if not target.pinned:
        return target.url, {}, {}
    parts = urlsplit(target.url)
    ip = f"[{target.ip}]" if ":" in target.ip else target.ip
    default_port = 443 if target.scheme == "https" else 80
    netloc = ip if target.port == default_port else f"{ip}:{target.port}"
    pinned = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    host_header = target.hostname if target.port == default_port else f"{target.hostname}:{target.port}"
    extensions = {"sni_hostname": target.hostname} if target.scheme == "https" else {}
    return pinned, {"Host": host_header}, extensions


def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """SSRF-validated request. Each redirect hop is re-validated; body size is capped."""
    settings = get_settings()
    current_url = url
    if params:
        merged = httpx.URL(url).copy_merge_params(params)
        current_url = str(merged)
    current_method = method
    current_content = content
    current_headers = dict(headers or {})
    started = time.perf_counter()
    with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
        for hop in range(settings.http_max_redirects + 1):
            try:
                target = validate_url(current_url)
            except BlockedDestination as exc:
                raise NodeError(str(exc), "security") from exc
            pinned_url, extra_headers, extensions = _pinned_request_args(target)
            try:
                request = client.build_request(
                    current_method,
                    pinned_url,
                    headers={**current_headers, **extra_headers},
                    content=current_content,
                    extensions=extensions,
                )
                response = client.send(request, stream=True)
            except httpx.TimeoutException as exc:
                raise NodeError(f"Request timed out after {timeout:.0f}s", "timeout", retryable=True) from exc
            except httpx.TransportError as exc:
                raise NodeError(f"Connection failed: {type(exc).__name__}", "network", retryable=True) from exc
            try:
                if response.is_redirect and response.headers.get("location"):
                    if hop == settings.http_max_redirects:
                        raise NodeError("Too many redirects", "network")
                    next_url = urljoin(current_url, response.headers["location"])
                    if urlsplit(next_url).hostname != urlsplit(current_url).hostname:
                        # Never forward credentials to a different host.
                        current_headers = {
                            k: v for k, v in current_headers.items() if k.lower() not in ("authorization", "cookie", "x-api-key")
                        }
                    if response.status_code in (301, 302, 303) and current_method not in ("GET", "HEAD"):
                        current_method, current_content = "GET", None
                    current_url = next_url
                    continue
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > settings.http_max_response_bytes:
                        raise NodeError(
                            f"Response is larger than the {settings.http_max_response_bytes} byte limit", "resource_limit"
                        )
                return {
                    "status": response.status_code,
                    "headers": {k: v for k, v in response.headers.items() if k.lower() not in ("set-cookie", "www-authenticate")},
                    "content": bytes(body),
                    "encoding": response.encoding or "utf-8",
                    "final_url": current_url,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
            except httpx.TimeoutException as exc:
                raise NodeError(f"Reading the response timed out after {timeout:.0f}s", "timeout", retryable=True) from exc
            except httpx.TransportError as exc:
                raise NodeError(f"Connection failed: {type(exc).__name__}", "network", retryable=True) from exc
            finally:
                response.close()
    raise NodeError("Too many redirects", "network")


def _kv(rows: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows or []:
        key = str((row or {}).get("key") or "").strip()
        if key:
            out[key] = _stringify(row.get("value"))
    return out


def _auth_headers(ctx, credential_id: str | None) -> dict[str, str]:
    if not credential_id:
        return {}
    cred = ctx.get_credential(credential_id, ["bearer_token", "basic_auth", "api_key_header"])
    kind, data = cred["type"], cred["data"]
    if kind == "bearer_token":
        return {"Authorization": f"Bearer {data['token']}"}
    if kind == "basic_auth":
        raw = f"{data['username']}:{data['password']}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
    return {data["header_name"]: data["api_key"]}


def _decode_body(result: dict) -> Any:
    text = result["content"].decode(result["encoding"], errors="replace")
    if "json" in result["headers"].get("content-type", "").lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _http(ctx) -> NodeResult:
    cfg = ctx.config
    method = str(cfg.get("method") or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise NodeError(f"Unsupported HTTP method {method}", "config")
    url = str(cfg.get("url") or "").strip()
    try:
        validate_url(url)  # Fails fast, and in test mode too.
    except BlockedDestination as exc:
        raise NodeError(str(exc), "security") from exc
    headers = _kv(cfg.get("headers"))
    params = _kv(cfg.get("query"))
    content: bytes | None = None
    body_type = cfg.get("body_type", "none")
    if method != "GET" and body_type != "none":
        body = cfg.get("body")
        if body_type == "json":
            if isinstance(body, str):
                try:
                    body = json.loads(body) if body.strip() else None
                except json.JSONDecodeError as exc:
                    raise NodeError(f"Request body is not valid JSON: {exc.msg}", "config") from exc
            content = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        else:
            content = _stringify(body).encode()
            headers.setdefault("Content-Type", "text/plain; charset=utf-8")
    if ctx.mode == "test" and method not in _SAFE_METHODS:
        return NodeResult.main(
            {"simulated": True, "note": "Test run: this request was NOT sent.", "would_send": {"method": method, "url": url, "query": params}},
            simulated=True,
        )
    headers.update(_auth_headers(ctx, cfg.get("credential_id")))
    try:
        timeout = min(float(cfg.get("timeout_seconds") or ctx.timeout), ctx.timeout)
    except (TypeError, ValueError) as exc:
        raise NodeError("Timeout must be a number", "config") from exc
    result = safe_request(method, url, headers=headers, params=params, content=content, timeout=timeout, transport=ctx.http_transport)
    output = {
        "status": result["status"],
        "ok": result["status"] < 400,
        "body": _decode_body(result),
        "headers": result["headers"],
        "url": result["final_url"],
        "elapsed_ms": result["elapsed_ms"],
    }
    if result["status"] >= 400 and cfg.get("fail_on_error_status", True):
        raise NodeError(f"{method} {url} returned HTTP {result['status']}", "http_status", retryable=result["status"] >= 500 or result["status"] == 429)
    return NodeResult.main(output)


register(
    NodeSpec(
        type="integration.http",
        label="HTTP Request",
        category="integration",
        description="Calls an external HTTP API. Internal and private destinations are blocked.",
        icon="globe",
        handler=_http,
        outputs=[PortSpec("main", "Response", "object")],
        has_side_effects=lambda c: str(c.get("method") or "GET").upper() not in _SAFE_METHODS,
        requires_integration="http",
        fields=[
            F("method", "Method", "select", required=True, default="GET", options=[{"value": m, "label": m} for m in ("GET", "POST", "PUT", "PATCH", "DELETE")], no_expressions=True),
            F("url", "URL", "string", required=True, placeholder="https://api.example.com/items"),
            F("credential_id", "Authentication", "credential", credential_types=["bearer_token", "basic_auth", "api_key_header"], help="Optional. Secrets stay encrypted and are never shown in logs.", no_expressions=True),
            F("query", "Query parameters", "keyvalue", default=[]),
            F("headers", "Headers", "keyvalue", default=[]),
            F("body_type", "Body", "select", default="none", options=[{"value": "none", "label": "None"}, {"value": "json", "label": "JSON"}, {"value": "text", "label": "Text"}], visible_if={"method": ["POST", "PUT", "PATCH", "DELETE"]}, no_expressions=True),
            F("body", "Body content", "text", visible_if={"body_type": ["json", "text"]}, placeholder='{"name": "{{ input.name }}"}'),
            F("timeout_seconds", "Timeout (seconds)", "number", default=30, min=1, max=120, no_expressions=True),
            F("fail_on_error_status", "Fail on HTTP 4xx/5xx", "boolean", default=True, no_expressions=True),
        ],
        output_schema={"type": "object", "properties": {"status": {"type": "number"}, "ok": {"type": "boolean"}, "body": {}, "headers": {"type": "object"}, "elapsed_ms": {"type": "number"}}},
        planner_hint="Reference the result as {{ input.body.field }}. Never put secrets in headers; use credential_id.",
    )
)


def _webhook_send(ctx) -> NodeResult:
    cfg = ctx.config
    url = str(cfg.get("url") or "").strip()
    try:
        validate_url(url)
    except BlockedDestination as exc:
        raise NodeError(str(exc), "security") from exc
    payload = cfg.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass
    content = json.dumps(payload, default=str).encode()
    if ctx.mode == "test":
        return NodeResult.main({"simulated": True, "note": "Test run: this webhook was NOT delivered.", "would_send": {"url": url, "payload": payload}}, simulated=True)
    headers = {"Content-Type": "application/json", "User-Agent": "FlowForge-Webhook/1.0"}
    if cfg.get("credential_id"):
        cred = ctx.get_credential(cfg["credential_id"], ["webhook_secret"])
        timestamp = str(int(time.time()))
        signature = hmac.new(cred["data"]["secret"].encode(), timestamp.encode() + b"." + content, hashlib.sha256).hexdigest()
        headers["X-FlowForge-Timestamp"] = timestamp
        headers["X-FlowForge-Signature"] = f"sha256={signature}"
    result = safe_request("POST", url, headers=headers, content=content, timeout=ctx.timeout, transport=ctx.http_transport)
    if result["status"] >= 400:
        raise NodeError(f"Webhook delivery returned HTTP {result['status']}", "http_status")
    return NodeResult.main({"delivered": True, "status": result["status"], "elapsed_ms": result["elapsed_ms"]})


register(
    NodeSpec(
        type="integration.webhook_send",
        label="Send Webhook",
        category="integration",
        description="Delivers a JSON payload to a URL, optionally signed with HMAC SHA-256.",
        icon="send",
        handler=_webhook_send,
        outputs=[PortSpec("main", "Delivery", "object")],
        has_side_effects=lambda _c: True,
        requires_integration="webhook",
        fields=[
            F("url", "Destination URL", "string", required=True, placeholder="https://example.com/hooks/orders"),
            F("payload", "Payload", "expression", required=True, default="{{ input }}"),
            F("credential_id", "Signing secret", "credential", credential_types=["webhook_secret"], no_expressions=True, help="Optional. Adds X-FlowForge-Signature and X-FlowForge-Timestamp headers."),
        ],
        output_schema={"type": "object", "properties": {"delivered": {"type": "boolean"}, "status": {"type": "number"}}},
    )
)


def send_smtp(data: dict, to: list[str], subject: str, body: str, timeout: float) -> None:
    host, port = data["host"], int(data.get("port") or 587)
    try:
        validate_host(host, port)
    except BlockedDestination as exc:
        raise NodeError(str(exc), "security") from exc
    message = EmailMessage()
    message["From"] = data.get("from_email") or data.get("username")
    message["To"] = ", ".join(to)
    message["Subject"] = subject.replace("\r", " ").replace("\n", " ")
    message.set_content(body)
    security = data.get("security") or "starttls"
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        with client:
            if security == "starttls":
                client.starttls(context=context)
            if data.get("username"):
                client.login(data["username"], data.get("password") or "")
            if to:
                client.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise NodeError("SMTP server rejected the username or password", "auth") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise NodeError(f"Could not send email: {type(exc).__name__}", "network") from exc


def _email(ctx) -> NodeResult:
    cfg = ctx.config
    recipients = [p.strip() for p in str(cfg.get("to") or "").replace(";", ",").split(",") if p.strip()]
    if not recipients:
        raise NodeError("Email needs at least one recipient", "config")
    if len(recipients) > 50:
        raise NodeError("Email is limited to 50 recipients", "resource_limit")
    if any("@" not in r or "\n" in r or "\r" in r for r in recipients):
        raise NodeError("Recipient list contains an invalid address", "config")
    subject, body = _stringify(cfg.get("subject")), _stringify(cfg.get("body"))
    if ctx.mode == "test":
        return NodeResult.main(
            {"simulated": True, "sent": False, "note": "Test run: this email was NOT sent.", "would_send": {"to": recipients, "subject": subject, "body": body[:2000]}},
            simulated=True,
        )
    if not cfg.get("credential_id"):
        raise NodeError("Choose an SMTP credential before running this node", "config")
    cred = ctx.get_credential(cfg["credential_id"], ["smtp"])
    send_smtp(cred["data"], recipients, subject, body, ctx.timeout)
    return NodeResult.main({"sent": True, "to": recipients, "subject": subject})


register(
    NodeSpec(
        type="integration.email",
        label="Send Email",
        category="integration",
        description="Sends email through your own SMTP server.",
        icon="mail",
        handler=_email,
        outputs=[PortSpec("main", "Result", "object")],
        has_side_effects=lambda _c: True,
        requires_integration="smtp",
        fields=[
            F("credential_id", "SMTP credential", "credential", required=True, credential_types=["smtp"], no_expressions=True),
            F("to", "To", "string", required=True, placeholder="me@example.com, {{ input.email }}"),
            F("subject", "Subject", "string", required=True),
            F("body", "Message", "text", required=True),
        ],
        output_schema={"type": "object", "properties": {"sent": {"type": "boolean"}, "to": {"type": "array"}}},
        planner_hint="Needs an SMTP credential the user must choose, so leave credential_id empty and report it in required_setup.",
    )
)


# ------------------------------------------------------------- built-in database
def _filter_rows(row: Any, filters: dict[str, str]) -> bool:
    if not isinstance(row, dict):
        return not filters
    return all(_stringify(row.get(k)).lower() == v.lower() for k, v in filters.items())


_MAX_SCAN = 5000


def _database(ctx) -> NodeResult:
    cfg = ctx.config
    op = cfg.get("operation", "insert")
    collection = str(cfg.get("collection") or "").strip()
    if not collection or len(collection) > 80:
        raise NodeError("Choose a collection name (1-80 characters)", "config")
    filters = _kv(cfg.get("filters"))
    filters = {k: _stringify(v) for k, v in filters.items()}
    writes = op in ("insert", "update", "delete")
    if ctx.mode == "test" and writes:
        with session_scope() as db:
            matched = None
            if op != "insert":
                rows = db.scalars(select(DataRecord).where(DataRecord.workspace_id == ctx.workspace_id, DataRecord.collection == collection).limit(_MAX_SCAN)).all()
                matched = sum(1 for r in rows if _filter_rows(r.data, filters))
        return NodeResult.main({"simulated": True, "note": "Test run: the data store was NOT changed.", "operation": op, "collection": collection, "would_match": matched, "data": cfg.get("data") if op != "delete" else None}, simulated=True)
    with session_scope() as db:
        base = select(DataRecord).where(DataRecord.workspace_id == ctx.workspace_id, DataRecord.collection == collection)
        if op == "insert":
            data = cfg.get("data")
            if data in (None, ""):
                raise NodeError("Insert needs data", "config")
            if len(json.dumps(data, default=str)) > 256_000:
                raise NodeError("Record is larger than the 256 KB limit", "resource_limit")
            total = db.scalar(select(func.count()).select_from(DataRecord).where(DataRecord.workspace_id == ctx.workspace_id))
            if (total or 0) >= 100_000:
                raise NodeError("Workspace data store is full (100,000 records)", "resource_limit")
            record = DataRecord(workspace_id=ctx.workspace_id, collection=collection, data=data, execution_id=ctx.execution_id)
            db.add(record)
            db.flush()
            return NodeResult.main({"id": record.id, "collection": collection, "data": data, "inserted": True})
        rows = [r for r in db.scalars(base.order_by(DataRecord.created_at.desc()).limit(_MAX_SCAN)).all() if _filter_rows(r.data, filters)]
        if op == "count":
            return NodeResult.main({"count": len(rows), "collection": collection})
        if op == "find":
            limit = max(1, min(int(cfg.get("limit") or 50), 500))
            return NodeResult.main({"records": [{"id": r.id, **(r.data if isinstance(r.data, dict) else {"value": r.data})} for r in rows[:limit]], "count": len(rows[:limit]), "collection": collection})
        if op == "update":
            if not filters:
                raise NodeError("Update needs at least one filter so it cannot rewrite a whole collection", "config")
            data = cfg.get("data")
            if not isinstance(data, dict):
                raise NodeError("Update data must be an object", "config")
            for r in rows:
                r.data = {**(r.data if isinstance(r.data, dict) else {}), **data}
            return NodeResult.main({"updated": len(rows), "collection": collection})
        if op == "delete":
            if not filters:
                raise NodeError("Delete needs at least one filter so it cannot empty a whole collection", "config")
            for r in rows:
                db.delete(r)
            return NodeResult.main({"deleted": len(rows), "collection": collection})
    raise NodeError(f"Unknown database operation '{op}'", "config")


register(
    NodeSpec(
        type="integration.database",
        label="Database Operation",
        category="integration",
        description="Reads and writes records in this workspace's built-in data store.",
        icon="database",
        handler=_database,
        outputs=[PortSpec("main", "Result", "object")],
        has_side_effects=lambda c: c.get("operation", "insert") in ("insert", "update", "delete"),
        requires_integration="database",
        fields=[
            F("operation", "Operation", "select", required=True, default="insert", options=[{"value": v, "label": v.capitalize()} for v in ("insert", "find", "count", "update", "delete")], no_expressions=True),
            F("collection", "Collection", "string", required=True, placeholder="invoices"),
            F("data", "Data", "expression", default="{{ input }}", visible_if={"operation": ["insert", "update"]}, required=True),
            F("filters", "Where field equals", "keyvalue", default=[], visible_if={"operation": ["find", "count", "update", "delete"]}),
            F("limit", "Limit", "number", default=50, min=1, max=500, visible_if={"operation": ["find"]}, no_expressions=True),
        ],
        output_schema={"type": "object", "description": "insert: {id,data} · find: {records,count} · count: {count} · update: {updated} · delete: {deleted}"},
        planner_hint="Built-in, no setup needed. Use this for 'store it in the database'.",
    )
)

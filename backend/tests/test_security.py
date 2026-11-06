"""SSRF, credentials, tenant isolation, CSRF, sessions, webhooks."""
from __future__ import annotations

import hashlib
import hmac
import json
import socket
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import session_scope
from app.engine.nodes_integration import safe_request
from app.engine.registry import NodeError
from app.engine.ssrf import BlockedDestination, is_forbidden_ip, validate_url
from app.main import app
from app.models import AuditLog, Credential

from .conftest import definition, edge, make_user, node, run_pending, run_workflow

MANUAL = node("start", "trigger.manual", {"sample_data": {"a": 1}})


# ------------------------------------------------------------------------ SSRF
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://localhost.localdomain/",
        "http://127.0.0.1:8000/api/health",
        "http://127.1/",
        "http://2130706433/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://metadata.google.internal/",
        "http://printer.local/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "http://user:pw@example.com/",
        "http:///nohost",
    ],
)
def test_ssrf_blocks(url):
    with pytest.raises(BlockedDestination):
        validate_url(url)


def _resolver_to(ip):
    return lambda *_a, **_k: [(2, 1, 6, "", (ip, 443))]


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "fd00::1", "fe80::1", "::ffff:10.0.0.1"])
def test_ssrf_blocks_hostnames_resolving_internally(ip):
    with pytest.raises(BlockedDestination):
        validate_url("https://innocent.example.org/", resolver=_resolver_to(ip))


def test_ssrf_allows_public_address():
    target = validate_url("https://example.org/x", resolver=_resolver_to("93.184.216.34"))
    assert target.ip == "93.184.216.34" and target.pinned


def test_is_forbidden_ip_nat64():
    assert is_forbidden_ip("64:ff9b::7f00:1") is not None


def test_redirect_to_internal_is_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_to("93.184.216.34"))
    transport = httpx.MockTransport(lambda _r: httpx.Response(302, headers={"location": "http://169.254.169.254/latest"}))
    with pytest.raises(NodeError) as err:
        safe_request("GET", "https://example.org/", transport=transport)
    assert err.value.error_type == "security"


def test_connection_is_pinned_to_validated_ip(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_to("93.184.216.34"))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, text="ok")

    safe_request("GET", "https://example.org/path", transport=httpx.MockTransport(handler))
    assert seen == {"host": "93.184.216.34", "header": "example.org", "sni": "example.org"}


def test_credentials_are_not_forwarded_across_hosts(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_to("93.184.216.34"))
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers.get("authorization"))
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://other.example.net/"})
        return httpx.Response(200)

    safe_request("GET", "https://example.org/", headers={"Authorization": "Bearer abc"}, transport=httpx.MockTransport(handler))
    assert requests == ["Bearer abc", None]


def test_response_size_limit(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_to("93.184.216.34"))
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, content=b"x" * 6_000_000))
    with pytest.raises(NodeError) as err:
        safe_request("GET", "https://example.org/", transport=transport)
    assert err.value.error_type == "resource_limit"


def test_http_node_to_private_address_fails_clearly(api):
    ex = run_workflow(api, definition([MANUAL, node("h", "integration.http", {"method": "GET", "url": "http://127.0.0.1:8000/api/health"})], [edge("start", "h")]))
    assert ex["status"] == "failed"
    assert ex["error_type"] == "security"
    assert "blocked" in ex["error"].lower()


# ----------------------------------------------------------------- credentials
def _cred(api, name="My Key", secret="s3cr3t-value-123456"):
    r = api.post("/api/credentials", json={"name": name, "type": "bearer_token", "data": {"token": secret}})
    assert r.status_code == 201, r.text
    return r.json()


def test_credentials_encrypted_masked_never_returned(api):
    secret = "s3cr3t-value-123456"
    cred = _cred(api, secret=secret)
    assert secret not in json.dumps(cred)
    listing = api.get("/api/credentials").json()
    assert secret not in json.dumps(listing)
    assert "•" in listing[0]["masked"]["token"]
    with session_scope() as db:
        row = db.get(Credential, cred["id"])
        assert secret.encode() not in bytes(row.encrypted_data)
    update = api.patch(f"/api/credentials/{cred['id']}", json={"name": "Renamed", "data": {"token": ""}})
    assert update.status_code == 200
    assert update.json()["masked"] == cred["masked"], "a blank secret keeps the stored value"
    assert api.delete(f"/api/credentials/{cred['id']}").status_code == 200
    assert api.get("/api/credentials").json() == []


def test_credential_value_is_scrubbed_from_execution_logs(api, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver_to("93.184.216.34"))
    secret = "s3cr3t-value-123456"
    cred = _cred(api, secret=secret)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        # A hostile server echoes the token back in its body.
        return httpx.Response(200, json={"echo": request.headers.get("authorization"), "note": secret})

    ex = run_workflow(api, definition([MANUAL, node("h", "integration.http", {"method": "GET", "url": "https://api.example.org", "credential_id": cred["id"]})], [edge("start", "h")]), http_transport=httpx.MockTransport(handler))
    assert ex["status"] == "completed"
    assert seen["auth"] == f"Bearer {secret}", "the credential was actually used"
    assert secret not in json.dumps(ex)
    wf = api.get(f"/api/workflows/{ex['workflow_id']}").json()
    assert secret not in json.dumps(wf)


def test_other_workspace_credential_cannot_be_used(api, other_api):
    cred = _cred(other_api)
    d = definition([MANUAL, node("h", "integration.http", {"method": "GET", "url": "https://api.example.org", "credential_id": cred["id"]})], [edge("start", "h")])
    wf = api.post("/api/workflows", json={"name": "Steal", "definition": d}).json()
    response = api.post(f"/api/workflows/{wf['id']}/run", json={})
    assert response.status_code == 422
    assert "no longer exists" in json.dumps(response.json())


def test_viewer_cannot_read_write_credentials_or_edit(api):
    viewer = make_user("viewer")
    added = api.post("/api/workspaces/current/members", json={"email": viewer.user["email"], "role": "viewer"})
    assert added.status_code == 201
    viewer.headers["X-Workspace-Id"] = api.workspace_id
    assert viewer.post("/api/workflows", json={"name": "x"}).status_code == 403
    assert viewer.post("/api/credentials", json={"name": "c", "type": "bearer_token", "data": {"token": "aaaaaaaaaaaa"}}).status_code == 403
    assert viewer.get("/api/workflows").status_code == 200


# ------------------------------------------------------------ tenant isolation
def test_users_cannot_access_each_others_data(api, other_api):
    defn = definition([MANUAL], [])
    wf = api.post("/api/workflows", json={"name": "Private", "definition": defn}).json()
    ex_id = api.post(f"/api/workflows/{wf['id']}/run", json={}).json()["execution_id"]
    run_pending()
    cred = _cred(api)
    hook_def = definition([node("h", "trigger.webhook", {"auth_mode": "hmac"})], [])
    hook_wf = api.post("/api/workflows", json={"name": "Hook", "definition": hook_def}).json()
    hook = api.get(f"/api/workflows/{hook_wf['id']}/triggers").json()["webhooks"][0]

    attempts = [
        ("GET", f"/api/workflows/{wf['id']}"),
        ("PUT", f"/api/workflows/{wf['id']}"),
        ("DELETE", f"/api/workflows/{wf['id']}"),
        ("POST", f"/api/workflows/{wf['id']}/run"),
        ("POST", f"/api/workflows/{wf['id']}/duplicate"),
        ("POST", f"/api/workflows/{wf['id']}/activate"),
        ("GET", f"/api/workflows/{wf['id']}/versions"),
        ("GET", f"/api/workflows/{wf['id']}/triggers"),
        ("GET", f"/api/executions/{ex_id}"),
        ("POST", f"/api/executions/{ex_id}/retry"),
        ("POST", f"/api/executions/{ex_id}/cancel"),
        ("PATCH", f"/api/credentials/{cred['id']}"),
        ("DELETE", f"/api/credentials/{cred['id']}"),
        ("GET", f"/api/webhook-triggers/{hook['id']}/requests"),
        ("POST", f"/api/webhook-triggers/{hook['id']}/rotate-secret"),
    ]
    for method, url in attempts:
        body = {"name": "x"} if method in ("PUT", "PATCH") else ({} if method == "POST" else None)
        response = other_api._do(method, url, **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (method, url, response.status_code)
    assert other_api.get("/api/workflows").json()["total"] == 0
    assert other_api.get("/api/executions").json()["total"] == 0
    assert other_api.get("/api/credentials").json() == []
    assert api.get(f"/api/workflows/{wf['id']}").status_code == 200

    # A forged workspace header is refused, too.
    other_api.headers["X-Workspace-Id"] = api.workspace_id
    assert other_api.get("/api/workflows").status_code == 404


def test_requests_without_session_are_refused():
    client = TestClient(app)
    for url in ("/api/workflows", "/api/executions", "/api/credentials", "/api/analytics/overview", "/api/nodes", "/api/auth/me"):
        assert client.get(url).status_code == 401, url


# ------------------------------------------------------------------- auth, CSRF
def test_csrf_required_on_mutations(api):
    assert api.client.post("/api/workflows", json={"name": "x"}, headers={"X-Workspace-Id": api.workspace_id}).status_code == 403
    assert api.client.post("/api/workflows", json={"name": "x"}, headers={"X-Workspace-Id": api.workspace_id, "X-CSRF-Token": "wrong"}).status_code == 403


def test_password_is_hashed_and_login_flow(api):
    from app.models import User

    with session_scope() as db:
        row = db.scalar(select(User).where(User.email == api.user["email"]))
        assert row.password_hash.startswith("$argon2")
        assert "correct-horse" not in row.password_hash
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"email": api.user["email"], "password": "nope-nope-nope"}).status_code == 401
    good = client.post("/api/auth/login", json={"email": api.user["email"], "password": "correct-horse-battery"})
    assert good.status_code == 200
    cookie = good.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": good.json()["csrf_token"]}).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_register_validation_and_duplicates(_app_started):
    client = TestClient(app)
    assert client.post("/api/auth/register", json={"email": "bad", "name": "x", "password": "correct-horse"}).status_code == 422
    short = client.post("/api/auth/register", json={"email": "ok@example.com", "name": "x", "password": "short"})
    assert short.status_code == 422
    assert "short" not in json.dumps(short.json()), "submitted values are not echoed"
    assert client.post("/api/auth/register", json={"email": "dupe@example.com", "name": "x", "password": "correct-horse-battery"}).status_code == 201
    assert TestClient(app).post("/api/auth/register", json={"email": "DUPE@example.com", "name": "x", "password": "correct-horse-battery"}).status_code == 409


def test_login_rate_limit(api):
    client = TestClient(app)
    codes = [client.post("/api/auth/login", json={"email": api.user["email"], "password": "wrong-password"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429


def test_password_reset_flow(api):
    client = TestClient(app)
    token = client.post("/api/auth/password-reset/request", json={"email": api.user["email"]}).json()["dev_reset_token"]
    unknown = client.post("/api/auth/password-reset/request", json={"email": "nobody@example.com"}).json()
    assert "dev_reset_token" not in unknown and unknown["ok"] is True
    assert client.post("/api/auth/password-reset/confirm", json={"token": "wrong", "new_password": "a-brand-new-password"}).status_code == 400
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "a-brand-new-password"}).status_code == 200
    assert client.post("/api/auth/password-reset/confirm", json={"token": token, "new_password": "another-new-password"}).status_code == 400
    assert api.get("/api/auth/me").status_code == 401, "existing sessions are revoked"
    assert client.post("/api/auth/login", json={"email": api.user["email"], "password": "a-brand-new-password"}).status_code == 200


def test_security_headers(api):
    response = api.get("/api/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_audit_log_records_sensitive_actions(api):
    _cred(api)
    with session_scope() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.workspace_id == api.workspace_id, AuditLog.action == "credential.create")).all()
    assert rows
    assert "s3cr3t" not in json.dumps([r.details for r in rows])
    assert api.get("/api/audit-logs").json()["total"] >= 1


# -------------------------------------------------------------------- webhooks
def _hook(api, config=None, activate=True, extra_nodes=None, extra_edges=None):
    d = definition([node("h", "trigger.webhook", {"auth_mode": "hmac", **(config or {})}), *(extra_nodes or [node("s", "data.set", {"assignments": [{"key": "got", "value": "{{ trigger.body.a }}"}]})])], extra_edges or [edge("h", "s")])
    wf = api.post("/api/workflows", json={"name": "Hook", "definition": d}).json()
    if activate:
        assert api.post(f"/api/workflows/{wf['id']}/activate").status_code == 200
    trigger = api.get(f"/api/workflows/{wf['id']}/triggers").json()["webhooks"][0]
    secret = api.post(f"/api/webhook-triggers/{trigger['id']}/rotate-secret").json()["secret"]
    return wf, trigger, secret


def _signed(secret: str, raw: bytes, ts: int | None = None) -> dict:
    stamp = str(ts or int(time.time()))
    sig = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"X-FlowForge-Timestamp": stamp, "X-FlowForge-Signature": f"sha256={sig}", "Content-Type": "application/json"}


def _path(trigger) -> str:
    return "/hooks/" + trigger["url"].rsplit("/", 1)[1]


def test_webhook_end_to_end_with_signature(api):
    _wf, trigger, secret = _hook(api)
    client = TestClient(app)
    raw = json.dumps({"a": 42}).encode()
    response = client.post(_path(trigger), content=raw, headers=_signed(secret, raw))
    assert response.status_code == 202, response.text
    run_pending()
    ex = api.get(f"/api/executions/{response.json()['execution_id']}").json()
    assert ex["status"] == "completed"
    assert ex["trigger_type"] == "webhook"
    assert ex["result"]["got"] == 42
    log = api.get(f"/api/webhook-triggers/{trigger['id']}/requests").json()
    assert log[0]["status_code"] == 202


def test_webhook_rejects_bad_auth_replay_and_tampering(api):
    _wf, trigger, secret = _hook(api)
    client = TestClient(app)
    raw = b'{"a":1}'
    assert client.post(_path(trigger), content=raw).status_code == 401
    assert client.post(_path(trigger), content=raw, headers=_signed("wrong", raw)).status_code == 401
    assert client.post(_path(trigger), content=b'{"a":2}', headers=_signed(secret, raw)).status_code == 401
    old = int(time.time()) - 3600
    assert client.post(_path(trigger), content=raw, headers=_signed(secret, raw, old)).status_code == 401
    assert client.post("/hooks/not-a-token", content=raw).status_code == 404
    entry = api.get(f"/api/webhook-triggers/{trigger['id']}/requests").json()[0]
    assert "x-flowforge-signature" not in json.dumps(entry["headers"]).lower() or entry["headers"].get("x-flowforge-signature") == "[REDACTED]"


def test_webhook_inactive_disabled_required_fields_size(api):
    _wf, inactive, secret = _hook(api, activate=False)
    client = TestClient(app)
    raw = b'{"a":1}'
    assert client.post(_path(inactive), content=raw, headers=_signed(secret, raw)).status_code == 409

    _wf2, trigger, secret2 = _hook(api, {"required_fields": ["must_have"]})
    assert client.post(_path(trigger), content=raw, headers=_signed(secret2, raw)).status_code == 422
    big = b'{"a":"' + b"x" * 1_100_000 + b'"}'
    assert client.post(_path(trigger), content=big, headers=_signed(secret2, big)).status_code == 413
    assert api.patch(f"/api/webhook-triggers/{trigger['id']}", json={"enabled": False}).status_code == 200
    ok = json.dumps({"must_have": 1}).encode()
    assert client.post(_path(trigger), content=ok, headers=_signed(secret2, ok)).status_code == 409


def test_webhook_token_auth_mode(api):
    _wf, trigger, secret = _hook(api, {"auth_mode": "token"})
    client = TestClient(app)
    assert client.post(_path(trigger), json={"a": 1}).status_code == 401
    assert client.post(_path(trigger), json={"a": 1}, headers={"X-FlowForge-Token": secret}).status_code == 202
    run_pending()


def test_webhook_rate_limit(api, monkeypatch):
    from app.config import get_settings

    _wf, trigger, secret = _hook(api)
    monkeypatch.setattr(get_settings(), "webhook_rate_per_minute", 3)
    client = TestClient(app)
    codes = [client.post(_path(trigger), content=b"{}").status_code for _ in range(5)]
    assert codes[-1] == 429


def test_webhook_handles_hostile_input(api):
    _wf, trigger, secret = _hook(api)
    client = TestClient(app, raise_server_exceptions=False)
    raw = b'{"a":1}'
    stamp = str(int(time.time()))
    assert client.post(_path(trigger), content=raw, headers={"X-FlowForge-Timestamp": stamp, "X-FlowForge-Signature": "sha256=caf\xe9".encode("latin-1")}).status_code == 401
    deep = b"[" * 200_000 + b"]" * 200_000
    assert client.post(_path(trigger), content=deep, headers=_signed(secret, deep)).status_code == 400


def test_trigger_data_secrets_are_redacted_in_api(api):
    wf = api.post("/api/workflows", json={"name": "R", "definition": definition([MANUAL], [])}).json()
    queued = api.post(f"/api/workflows/{wf['id']}/run", json={"input": {"password": "hunter2hunter2"}}).json()
    run_pending()
    assert "hunter2hunter2" not in json.dumps(api.get(f"/api/executions/{queued['execution_id']}").json())


def test_production_refuses_unsafe_configuration():
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(app_env="production", credentials_encryption_key="", cookie_secure=True, demo_mode_enabled=False)
    with pytest.raises(ValueError):
        Settings(app_env="production", credentials_encryption_key="x", cookie_secure=False, demo_mode_enabled=False)
    with pytest.raises(ValueError):
        Settings(app_env="production", credentials_encryption_key="x", cookie_secure=True, demo_mode_enabled=True)

"""Tests run against a throwaway database. TEST_DATABASE_URL may point at PostgreSQL."""
from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="flowforge-test-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["APP_ENV"] = "test"
os.environ["CREDENTIALS_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(b"t" * 32).decode()
os.environ["WORKER_ENABLED"] = "false"
os.environ["DEMO_MODE_ENABLED"] = "true"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["GEMINI_API_KEY"] = ""
os.environ["WEBHOOK_RATE_PER_MINUTE"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.engine.executor import execute  # noqa: E402
from app.main import app  # noqa: E402
from app.security import rate_limiter  # noqa: E402
from app.worker import claim_next  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clear_limits():
    rate_limiter.reset()


class Api:
    """A signed-in browser: keeps the session cookie and sends the CSRF header."""

    def __init__(self, client: TestClient, payload: dict):
        self.client = client
        self.user = payload
        self.workspace_id = payload["workspaces"][0]["id"]
        self.headers = {"X-CSRF-Token": payload["csrf_token"], "X-Workspace-Id": self.workspace_id}

    def _do(self, method: str, url: str, **kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return self.client.request(method, url, headers=headers, **kw)

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, json=None, **kw):
        return self._do("POST", url, json=json if json is not None else {}, **kw)

    def put(self, url, json=None, **kw):
        return self._do("PUT", url, json=json, **kw)

    def patch(self, url, json=None, **kw):
        return self._do("PATCH", url, json=json, **kw)

    def delete(self, url, **kw):
        return self._do("DELETE", url, **kw)


_counter = {"n": 0}


def make_user(role_name: str = "user") -> Api:
    _counter["n"] += 1
    client = TestClient(app)
    email = f"{role_name}{_counter['n']}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "name": role_name, "password": "correct-horse-battery"})
    assert response.status_code == 201, response.text
    return Api(client, response.json())


@pytest.fixture(scope="session")
def _app_started():
    with TestClient(app):  # runs the lifespan: seeds templates and the demo account
        yield


@pytest.fixture
def api(_app_started) -> Api:
    return make_user()


@pytest.fixture
def other_api(_app_started) -> Api:
    return make_user("other")


def run_pending(http_transport=None) -> None:
    """Drains the queue inline, standing in for the background worker."""
    while True:
        execution_id = claim_next()
        if execution_id is None:
            return
        execute(execution_id, http_transport=http_transport)


def node(node_id: str, node_type: str, config: dict | None = None, name: str | None = None, **settings) -> dict:
    return {"id": node_id, "type": node_type, "name": name or node_id, "config": config or {}, "settings": settings}


def edge(source: str, target: str, port: str = "main") -> dict:
    return {"id": f"{source}-{port}-{target}", "source": source, "source_port": port, "target": target, "target_port": "main"}


def definition(nodes: list[dict], edges: list[dict]) -> dict:
    return {"schema_version": 1, "nodes": nodes, "edges": edges}


def run_workflow(api: Api, defn: dict, mode: str = "run", input=None, http_transport=None) -> dict:
    created = api.post("/api/workflows", json={"name": "Test", "definition": defn})
    assert created.status_code == 201, created.text
    response = api.post(f"/api/workflows/{created.json()['id']}/run", json={"mode": mode, "input": input})
    assert response.status_code == 202, response.text
    run_pending(http_transport)
    return api.get(f"/api/executions/{response.json()['execution_id']}").json()

"""Workflow management, versions, templates, AI proposals, analytics, scheduling."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select

from app.ai import planner
from app.ai.providers import AIError, AnthropicProvider, GeminiProvider, OpenAIProvider
from app.database import session_scope
from app.models import ScheduledTrigger, WorkflowExecution, WorkflowNode, WorkflowVersion
from app.services import compute_next_run
from app.worker import fire_due_schedules, sweep_stale

from .conftest import definition, edge, node, run_pending, run_workflow

MANUAL = node("start", "trigger.manual", {"sample_data": {"a": 1}})


def test_workflow_crud_search_duplicate_delete(api):
    a = api.post("/api/workflows", json={"name": "Alpha flow", "category": "Finance", "folder": "Q3"}).json()
    b = api.post("/api/workflows", json={"name": "Beta flow"}).json()
    listing = api.get("/api/workflows").json()
    assert listing["total"] == 2
    assert "Finance" in listing["categories"] and "Q3" in listing["folders"]
    assert api.get("/api/workflows", params={"search": "alpha"}).json()["total"] == 1
    assert api.get("/api/workflows", params={"category": "Finance"}).json()["total"] == 1
    assert api.put(f"/api/workflows/{a['id']}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    copy = api.post(f"/api/workflows/{a['id']}/duplicate").json()
    assert copy["name"] == "Renamed (copy)" and copy["id"] != a["id"]
    assert api.delete(f"/api/workflows/{b['id']}").status_code == 200
    assert api.get(f"/api/workflows/{b['id']}").status_code == 404


def test_save_restore_and_optimistic_locking(api):
    wf = api.post("/api/workflows", json={"name": "V", "definition": definition([MANUAL], [])}).json()
    new = definition([MANUAL, node("d", "logic.delay", {"seconds": 0}, name="Wait")], [edge("start", "d")])
    saved = api.put(f"/api/workflows/{wf['id']}", json={"definition": new, "revision": wf["revision"]})
    assert saved.status_code == 200
    assert saved.json()["validation"]["valid"] is True
    reopened = api.get(f"/api/workflows/{wf['id']}").json()
    assert [n["name"] for n in reopened["definition"]["nodes"]] == ["start", "Wait"]
    stale = api.put(f"/api/workflows/{wf['id']}", json={"name": "x", "revision": wf["revision"]})
    assert stale.status_code == 409
    versions = api.get(f"/api/workflows/{wf['id']}/versions").json()
    assert len(versions) == 1
    assert api.post(f"/api/workflows/{wf['id']}/versions", json={"note": "Checkpoint"}).status_code == 201
    versions = api.get(f"/api/workflows/{wf['id']}/versions").json()
    assert versions[0]["note"] == "Checkpoint"
    first = versions[-1]
    restored = api.post(f"/api/workflows/{wf['id']}/versions/{first['id']}/restore").json()
    assert len(restored["definition"]["nodes"]) == 1


def test_unsupported_node_cannot_be_saved(api):
    response = api.post("/api/workflows", json={"name": "x", "definition": definition([node("a", "integration.notreal")], [])})
    assert response.status_code == 422
    assert "not a supported node type" in json.dumps(response.json())


def test_invalid_workflow_will_not_run_or_activate(api):
    wf = api.post("/api/workflows", json={"name": "Broken", "definition": definition([node("h", "integration.http")], [])}).json()
    assert api.post(f"/api/workflows/{wf['id']}/run", json={}).status_code == 422
    assert api.post(f"/api/workflows/{wf['id']}/activate").status_code == 422


def test_version_snapshots_and_projection(api):
    ex = run_workflow(api, definition([MANUAL, node("d", "logic.delay", {"seconds": 0})], [edge("start", "d")]))
    with session_scope() as db:
        version = db.get(WorkflowVersion, ex["version_id"])
        rows = db.scalars(select(WorkflowNode).where(WorkflowNode.version_id == version.id)).all()
        assert {r.node_type for r in rows} == {"trigger.manual", "logic.delay"}


def test_single_node_test_simulates_unless_confirmed(api, monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    d = definition([MANUAL, node("db", "integration.database", {"operation": "insert", "collection": "node_test", "data": "{{ input }}"})], [edge("start", "db")])
    wf = api.post("/api/workflows", json={"name": "T", "definition": d}).json()
    result = api.post(f"/api/workflows/{wf['id']}/nodes/db/test", json={"input": {"x": 1}}).json()
    assert result["status"] == "completed" and result["simulated"] is True
    assert api.get("/api/data/collections").json() == []
    live = api.post(f"/api/workflows/{wf['id']}/nodes/db/test", json={"input": {"x": 1}, "allow_side_effects": True}).json()
    assert live["status"] == "completed" and live["simulated"] is False
    assert api.get("/api/data/collections").json()[0]["count"] == 1
    bad = api.post(f"/api/workflows/{wf['id']}/nodes/x/test", json={"node": node("x", "data.parse_json", {"source": "{"}), "input": {}}).json()
    assert bad["status"] == "failed" and "Invalid JSON" in bad["error"]


def test_templates_create_runnable_workflows(api):
    data = api.get("/api/templates").json()
    assert len(data["items"]) == 8
    needing = [t for t in data["items"] if t["needs_configuration"]]
    assert needing, "templates flag required configuration"
    for slug in ("csv-data-analysis", "ai-text-classification", "webhook-data-processing", "customer-support-classification", "ai-email-summarisation"):
        wf = api.post(f"/api/templates/{slug}/use", json={}).json()
        queued = api.post(f"/api/workflows/{wf['id']}/run", json={"mode": "test"})
        assert queued.status_code == 202, (slug, queued.text)
        run_pending()
        ex = api.get(f"/api/executions/{queued.json()['execution_id']}").json()
        assert ex["status"] == "completed", (slug, ex["error"])
    wf = api.post("/api/templates/ai-text-classification/use", json={}).json()
    q = api.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    run_pending()
    result = api.get(f"/api/executions/{q['execution_id']}").json()["result"]
    assert result["total"] == 3 and set(result["groups"]) <= {"positive", "neutral", "negative"}


def test_invoice_template_real_run_needs_smtp_but_test_works(api):
    wf = api.post("/api/templates/invoice-data-extraction/use", json={}).json()
    assert api.post(f"/api/workflows/{wf['id']}/run", json={"mode": "run"}).status_code == 422
    q = api.post(f"/api/workflows/{wf['id']}/run", json={"mode": "test"}).json()
    run_pending()
    ex = api.get(f"/api/executions/{q['execution_id']}").json()
    assert ex["status"] == "completed"
    by_id = {n["node_id"]: n for n in ex["nodes"]}
    assert by_id["extract"]["output"]["data"]["data"]["invoice_number"] == "INV-2041"
    assert by_id["email"]["simulated"] is True


# -------------------------------------------------------------------------- AI
def test_ai_demo_generates_labelled_proposal_without_saving(api):
    assert api.get("/api/ai/status").json()["is_demo"] is True
    prompt = "When a new email arrives containing an invoice, extract the invoice number, supplier name, amount and due date, save the information in the database, and notify me."
    proposal = api.post("/api/ai/generate", json={"prompt": prompt}).json()
    assert proposal["is_demo"] is True and proposal["provider"] == "demo"
    assert proposal["status"] == "ready", proposal["validation"]
    types = [n["type"] for n in proposal["workflow"]["definition"]["nodes"]]
    assert types == ["trigger.webhook", "ai.extract", "integration.database", "integration.email"]
    extract = proposal["workflow"]["definition"]["nodes"][1]
    assert extract["config"]["fields"] == ["invoice_number", "supplier_name", "amount", "due_date"]
    assert any("inbound email" in u.lower() for u in proposal["unsupported_requirements"]), "must not pretend inbound email exists"
    assert proposal["required_setup"]
    assert api.get("/api/workflows").json()["total"] == 0, "nothing saved before review"

    saved = api.post(f"/api/ai/conversations/{proposal['conversation_id']}/accept", json={"name": "Invoices"})
    assert saved.status_code == 201
    assert saved.json()["is_active"] is False, "AI workflows are never auto-activated"
    assert api.get("/api/executions").json()["total"] == 0, "and never auto-run"
    assert api.post(f"/api/ai/conversations/{proposal['conversation_id']}/accept", json={}).status_code == 409


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Create a workflow that receives a webhook, validates the JSON data, and stores it in the database.", ["trigger.webhook", "data.validate", "integration.database"]),
        ("When a new customer is registered, classify their account type and create a welcome message.", ["trigger.webhook", "ai.classify", "ai.generate"]),
        ("Read an uploaded CSV file, identify missing information, and generate a report.", ["trigger.webhook", "data.parse_csv", "ai.generate"]),
        ("Summarise new support tickets and assign a priority.", ["trigger.webhook", "ai.classify", "ai.summarize"]),
    ],
)
def test_ai_demo_handles_brief_examples(api, prompt, expected):
    proposal = api.post("/api/ai/generate", json={"prompt": prompt}).json()
    assert proposal["status"] == "ready", proposal["validation"]
    assert [n["type"] for n in proposal["workflow"]["definition"]["nodes"]] == expected


def test_ai_demo_explains_what_is_missing(api):
    proposal = api.post("/api/ai/generate", json={"prompt": "Post a message to Slack whenever Salesforce changes"}).json()
    assert proposal["status"] == "rejected"
    assert proposal["workflow"]["definition"] is None
    assert any("Slack" in u for u in proposal["unsupported_requirements"])


def test_ai_generated_plan_with_invented_node_is_rejected():
    plan = {"feasible": True, "workflow_name": "x", "nodes": [{"id": "a", "type": "trigger.manual", "name": "A", "config_json": "{}"}, {"id": "b", "type": "integration.slack", "name": "B", "config_json": "{}"}], "edges": [{"source": "a", "source_port": "main", "target": "b"}]}
    proposal = planner._build_proposal(plan, "anthropic", "m", False, {}, set())
    assert proposal["status"] == "invalid"
    assert any(e["code"] == "unsupported_node" for e in proposal["validation"]["errors"])


def test_ai_cannot_inject_credentials():
    plan = {"feasible": True, "nodes": [{"id": "a", "type": "trigger.manual", "name": "A", "config_json": "{}"}, {"id": "b", "type": "integration.http", "name": "B", "config_json": json.dumps({"url": "https://x.example", "credential_id": "cred_stolen"})}], "edges": [{"source": "a", "source_port": "main", "target": "b"}]}
    definition_, notes = planner.plan_to_definition(plan)
    assert "credential_id" not in definition_["nodes"][1]["config"]
    assert notes


def test_real_provider_retry_uses_validator_feedback():
    calls = []

    class Fake:
        name, model, is_demo = "fake", "fake-1", False

        def complete(self, system, prompt, schema=None, max_tokens=0, effort="low"):
            calls.append(prompt)
            bad = {"feasible": True, "nodes": [{"id": "a", "type": "integration.slack", "name": "A", "config_json": "{}"}], "edges": []}
            good = {"feasible": True, "workflow_name": "Good", "workflow_description": "d", "analysis": {}, "unsupported_requirements": [], "required_setup": [], "changes": [], "nodes": [{"id": "a", "type": "trigger.manual", "name": "A", "config_json": "{}"}], "edges": []}
            return SimpleNamespace(data=bad if len(calls) == 1 else good, input_tokens=10, output_tokens=5, text="")

    proposal = planner.generate_workflow(Fake(), "do a thing please", set())
    assert len(calls) == 2
    assert "rejected by the validator" in calls[1]
    assert proposal["status"] == "ready" and proposal["is_demo"] is False
    assert proposal["usage"] == {"input_tokens": 20, "output_tokens": 10}


def test_ai_modify_proposes_without_applying(api):
    start = definition([MANUAL, node("db", "integration.database", {"operation": "insert", "collection": "c", "data": "{{ input }}"}, name="Save")], [edge("start", "db")])
    wf = api.post("/api/workflows", json={"name": "M", "definition": start}).json()
    add = api.post("/api/ai/modify", json={"workflow_id": wf["id"], "instruction": "Add an email notification after the successful execution."}).json()
    assert add["status"] == "ready", add["validation"]
    assert [n["type"] for n in add["diff"]["added_nodes"]] == ["integration.email"]
    assert len(api.get(f"/api/workflows/{wf['id']}").json()["definition"]["nodes"]) == 2, "not applied"

    cond = api.post("/api/ai/modify", json={"workflow_id": wf["id"], "instruction": "Add a condition to check whether the invoice amount exceeds £500."}).json()
    assert cond["status"] == "ready", cond["validation"]
    new_node = next(n for n in cond["workflow"]["definition"]["nodes"] if n["type"] == "logic.if")
    assert new_node["config"]["conditions"][0]["right"] == "500"

    err = api.post("/api/ai/modify", json={"workflow_id": wf["id"], "instruction": "Add an error-handling branch."}).json()
    assert err["status"] == "ready", err["validation"]
    run = run_workflow(api, err["workflow"]["definition"], mode="test")
    assert run["status"] == "completed"

    simplify = api.post("/api/ai/modify", json={"workflow_id": wf["id"], "instruction": "Simplify this workflow."}).json()
    assert simplify["status"] == "no_change"

    unknown = api.post("/api/ai/modify", json={"workflow_id": wf["id"], "instruction": "Send it to Slack"}).json()
    assert unknown["unsupported_requirements"]

    explanation = api.post("/api/ai/explain", json={"workflow_id": wf["id"]}).json()
    assert explanation["is_demo"] is True and len(explanation["steps"]) == 2
    assert any("Save" in r for r in explanation["risks"])


class _FakeAnthropicResponse:
    def __init__(self, stop_reason="end_turn", text='{"label": "billing"}'):
        self.stop_reason = stop_reason
        self.content = [SimpleNamespace(type="text", text=text)]
        self.usage = SimpleNamespace(input_tokens=11, output_tokens=7)


def test_anthropic_provider_request_shape_and_errors(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, response):
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
            self.response = response

        def _create(self, **kwargs):
            captured.update(kwargs)
            return self.response

    provider = AnthropicProvider("key", "claude-opus-5-5", 5)
    monkeypatch.setattr(provider, "_client", lambda: FakeClient(_FakeAnthropicResponse()))
    schema = {"type": "object", "properties": {"label": {"type": "string"}}, "required": ["label"], "additionalProperties": False}
    result = provider.complete("sys", "hi", schema=schema)
    assert result.data == {"label": "billing"} and result.input_tokens == 11
    assert captured["model"] == "claude-opus-5-5"
    assert captured["output_config"]["format"]["schema"] == schema
    assert captured["fallbacks"] == "default"
    assert "thinking" not in captured and "temperature" not in captured

    monkeypatch.setattr(provider, "_client", lambda: FakeClient(_FakeAnthropicResponse(stop_reason="refusal")))
    with pytest.raises(AIError):
        provider.complete("sys", "hi")


def _mock_provider(cls, handler):
    provider = cls("secret-key", "model-x", 5)
    provider.transport = httpx.MockTransport(handler)
    return provider


def test_openai_and_gemini_adapters():
    def openai(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-key"
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    result = _mock_provider(OpenAIProvider, openai).complete("s", "p", schema={"type": "object"})
    assert result.data == {"a": 1} and result.output_tokens == 2

    def gemini(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "secret-key"
        assert "secret-key" not in str(request.url), "the key must not be in the URL"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"a": 2}'}]}}], "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}})

    assert _mock_provider(GeminiProvider, gemini).complete("s", "p", schema={"type": "object"}).data == {"a": 2}

    with pytest.raises(AIError) as err:
        _mock_provider(OpenAIProvider, lambda r: httpx.Response(401, json={"error": "bad secret-key"})).complete("s", "p")
    assert "secret-key" not in str(err.value)
    with pytest.raises(AIError) as err:
        _mock_provider(OpenAIProvider, lambda r: httpx.Response(429)).complete("s", "p")
    assert err.value.retryable
    with pytest.raises(AIError):
        _mock_provider(OpenAIProvider, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})).complete("s", "p", schema={"type": "object"})


def test_ai_node_uses_real_provider_result_when_configured(api, monkeypatch):
    import app.ai.providers as providers

    def fake_call(self, system, prompt, schema, max_tokens, effort):
        return '{"label": "billing", "confidence": 0.9, "reasoning": "r"}', 5, 3

    monkeypatch.setattr(AnthropicProvider, "_call", fake_call)
    cred = api.post("/api/credentials", json={"name": "Claude", "type": "anthropic", "data": {"api_key": "sk-ant-test-value"}}).json()
    assert api.put("/api/integrations/anthropic", json={"credential_id": cred["id"]}).status_code == 200
    assert api.get("/api/ai/status").json()["is_demo"] is False
    ex = run_workflow(api, definition([node("start", "trigger.manual", {"sample_data": {"text": "refund"}}), node("c", "ai.classify", {"text": "{{ input.text }}", "labels": ["billing", "other"]})], [edge("start", "c")]))
    assert ex["status"] == "completed"
    row = ex["nodes"][1]
    assert row["ai_provider"] == "anthropic" and row["ai_input_tokens"] == 5 and row["simulated"] is False
    assert ex["result"]["ai"]["simulated"] is False
    assert "sk-ant-test-value" not in json.dumps(ex)
    assert providers  # module import used for monkeypatch clarity


def test_ai_node_demo_is_labelled_simulated(api):
    ex = run_workflow(api, definition([node("start", "trigger.manual", {"sample_data": {"text": "great product"}}), node("c", "ai.classify", {"text": "{{ input.text }}", "labels": ["positive", "negative"]})], [edge("start", "c")]))
    assert ex["result"]["label"] == "positive"
    assert ex["result"]["ai"]["provider"] == "demo" and ex["result"]["ai"]["simulated"] is True
    assert ex["nodes"][1]["simulated"] is True


# ------------------------------------------------------------------- analytics
def test_analytics_counts_real_rows_and_excludes_tests(api):
    d = definition([MANUAL, node("bad", "data.parse_json", {"source": "{x"})], [edge("start", "bad")])
    run_workflow(api, d)
    run_workflow(api, definition([MANUAL], []))
    run_workflow(api, definition([MANUAL], []), mode="test")
    data = api.get("/api/analytics/overview", params={"range": "24h"}).json()
    assert data["totals"]["executions"] == 2
    assert data["totals"]["completed"] == 1 and data["totals"]["failed"] == 1
    assert data["totals"]["success_rate"] == 50.0
    assert data["demo_count"] == 0 and data["real_count"] == 2
    assert data["failure_types"][0]["type"] == "validation"
    assert sum(p["total"] for p in data["series"]) == 2


def test_execution_list_search_filter_sort(api):
    run_workflow(api, definition([MANUAL, node("bad", "data.parse_json", {"source": "{x"})], [edge("start", "bad")]))
    run_workflow(api, definition([MANUAL], []))
    assert api.get("/api/executions", params={"status": "failed"}).json()["total"] == 1
    assert api.get("/api/executions", params={"search": "test"}).json()["total"] == 2
    assert api.get("/api/executions", params={"search": "zzz"}).json()["total"] == 0
    asc = api.get("/api/executions", params={"sort": "created_at", "order": "asc"}).json()["items"]
    desc = api.get("/api/executions", params={"sort": "created_at", "order": "desc"}).json()["items"]
    assert asc[0]["id"] == desc[-1]["id"]
    assert api.get("/api/executions", params={"sort": "password_hash"}).status_code == 422


def test_demo_account_is_labelled_and_restricted(_app_started):
    from fastapi.testclient import TestClient

    from app.main import app

    from .conftest import Api

    client = TestClient(app)
    response = client.post("/api/auth/demo")
    assert response.status_code == 200
    demo = Api(client, response.json())
    assert demo.user["is_demo"] is True
    overview = demo.get("/api/analytics/overview", params={"range": "30d"}).json()
    assert overview["demo_count"] > 50
    only_real = demo.get("/api/analytics/overview", params={"range": "30d", "include_demo": "false"}).json()
    assert only_real["totals"]["executions"] == overview["real_count"]
    workflows = demo.get("/api/workflows").json()["items"]
    assert workflows and all(w["is_demo"] for w in workflows)
    assert demo.post("/api/credentials", json={"name": "x", "type": "bearer_token", "data": {"token": "aaaaaaaaaaaa"}}).status_code == 403
    assert demo.post("/api/auth/change-password", json={"current_password": "x", "new_password": "yyyyyyyyyyyy"}).status_code == 403
    demo_row = demo.get("/api/executions", params={"page_size": 1}).json()["items"][0]
    assert demo_row["is_demo"] is True
    assert demo.post(f"/api/executions/{demo_row['id']}/retry", json={}).status_code == 400
    # A demo workflow still runs for real, and the result is not labelled demo.
    digest = next(w for w in workflows if w["name"] == "Daily Order Digest")
    queued = demo.post(f"/api/workflows/{digest['id']}/run", json={}).json()
    run_pending()
    ex = demo.get(f"/api/executions/{queued['execution_id']}").json()
    assert ex["status"] == "completed" and ex["is_demo"] is False
    assert ex["result"]["inserted"] is True
    assert ex["result"]["data"]["verdict"] == "Target met"


# ------------------------------------------------------------------ scheduling
def test_compute_next_run():
    base = datetime(2027, 3, 10, 10, 30, tzinfo=timezone.utc)  # a Wednesday
    assert compute_next_run({"schedule_type": "hourly", "minute": 45, "timezone": "UTC"}, base) == base.replace(minute=45)
    assert compute_next_run({"schedule_type": "hourly", "minute": 15, "timezone": "UTC"}, base) == base.replace(hour=11, minute=15)
    assert compute_next_run({"schedule_type": "daily", "hour": 9, "minute": 0, "timezone": "UTC"}, base) == datetime(2027, 3, 11, 9, 0, tzinfo=timezone.utc)
    assert compute_next_run({"schedule_type": "weekly", "weekday": 0, "hour": 9, "minute": 0, "timezone": "UTC"}, base) == datetime(2027, 3, 15, 9, 0, tzinfo=timezone.utc)
    # London is on BST by April: 09:00 local is 08:00 UTC.
    april = datetime(2027, 4, 5, 12, 0, tzinfo=timezone.utc)
    assert compute_next_run({"schedule_type": "daily", "hour": 9, "minute": 0, "timezone": "Europe/London"}, april) == datetime(2027, 4, 6, 8, 0, tzinfo=timezone.utc)
    assert compute_next_run({"schedule_type": "once", "run_at": "2020-01-01T00:00", "timezone": "UTC"}, base) is None
    assert compute_next_run({"schedule_type": "once", "run_at": "2027-05-01T12:00", "timezone": "UTC"}, base) == datetime(2027, 5, 1, 12, 0, tzinfo=timezone.utc)


def test_schedule_fires_from_database_when_active_only(api):
    d = definition([node("tick", "trigger.schedule", {"schedule_type": "daily", "hour": 9, "minute": 0, "timezone": "UTC"}), node("s", "data.set", {"assignments": [{"key": "ran", "value": True}]})], [edge("tick", "s")])
    wf = api.post("/api/workflows", json={"name": "Sched", "definition": d}).json()
    info = api.get(f"/api/workflows/{wf['id']}/triggers").json()["schedules"][0]
    assert info["enabled"] is False and info["next_run_at"] is None
    api.post(f"/api/workflows/{wf['id']}/activate")
    info = api.get(f"/api/workflows/{wf['id']}/triggers").json()["schedules"][0]
    assert info["enabled"] is True and info["next_run_at"]
    assert fire_due_schedules() == 0, "not due yet"
    with session_scope() as db:
        row = db.get(ScheduledTrigger, info["id"])
        row.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert fire_due_schedules() == 1
    assert fire_due_schedules() == 0, "fires once, then moves to the next slot"
    run_pending()
    items = api.get("/api/executions", params={"workflow_id": wf["id"]}).json()["items"]
    assert items[0]["trigger_type"] == "schedule" and items[0]["status"] == "completed"
    api.post(f"/api/workflows/{wf['id']}/deactivate")
    assert api.get(f"/api/workflows/{wf['id']}/triggers").json()["schedules"][0]["enabled"] is False


def test_stale_execution_is_failed_not_rerun(api):
    wf = api.post("/api/workflows", json={"name": "Stale", "definition": definition([MANUAL], [])}).json()
    ex_id = api.post(f"/api/workflows/{wf['id']}/run", json={}).json()["execution_id"]
    with session_scope() as db:
        row = db.get(WorkflowExecution, ex_id)
        row.status = "running"
        row.heartbeat_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert sweep_stale() >= 1
    ex = api.get(f"/api/executions/{ex_id}").json()
    assert ex["status"] == "failed" and ex["error_type"] == "worker_interrupted"

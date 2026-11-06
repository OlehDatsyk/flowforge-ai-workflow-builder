"""Engine behaviour through the real API and the real executor."""
from __future__ import annotations

import httpx

from app.engine.expressions import evaluate, render
from app.engine.registry import all_specs
from app.engine.validator import validate_definition
from app.templates_data import TEMPLATES

from .conftest import definition, edge, node, run_pending, run_workflow

MANUAL = node("start", "trigger.manual", {"sample_data": {"amount": 750, "name": " Ada ", "items": [{"v": 1}, {"v": 5}, {"v": 9}]}})


def statuses(ex: dict) -> dict[str, str]:
    return {n["node_id"]: n["status"] for n in ex["nodes"]}


def test_if_routes_and_skips_the_other_branch(api):
    ex = run_workflow(
        api,
        definition(
            [
                MANUAL,
                node("check", "logic.if", {"conditions": [{"left": "{{ input.amount }}", "operator": "gt", "right": "500"}]}),
                node("yes", "data.set", {"assignments": [{"key": "big", "value": True}]}),
                node("no", "data.set", {"assignments": [{"key": "big", "value": False}]}),
            ],
            [edge("start", "check"), edge("check", "yes", "true"), edge("check", "no", "false")],
        ),
    )
    assert ex["status"] == "completed"
    assert statuses(ex) == {"start": "completed", "check": "completed", "yes": "completed", "no": "skipped"}
    assert ex["result"]["big"] is True


def test_data_flows_between_nodes_and_transform_works(api):
    ex = run_workflow(
        api,
        definition(
            [
                MANUAL,
                node("f", "logic.filter", {"items": "{{ trigger.items }}", "conditions": [{"left": "{{ item.v }}", "operator": "gte", "right": "5"}]}),
                node("t", "data.transform", {"source": "{{ input }}", "operations": [{"operation": "sum", "field": "v"}]}),
            ],
            [edge("start", "f"), edge("f", "t")],
        ),
    )
    assert ex["status"] == "completed"
    assert ex["result"] == {"sum": 14, "count": 2}


def test_switch_merge_and_variables(api):
    ex = run_workflow(
        api,
        definition(
            [
                node("start", "trigger.manual", {"sample_data": {"p": "high"}}),
                node("sw", "logic.switch", {"value": "{{ input.p }}", "cases": [{"equals": "low"}, {"equals": "high"}]}),
                node("a", "data.set", {"assignments": [{"key": "lane", "value": "a"}]}),
                node("b", "data.set", {"assignments": [{"key": "lane", "value": "b"}]}),
                node("c", "data.set", {"assignments": [{"key": "lane", "value": "c"}]}),
                node("m", "logic.merge", {"mode": "first"}),
                node("out", "data.set", {"assignments": [{"key": "seen", "value": "{{ vars.lane }}-{{ input.lane }}"}]}),
            ],
            [edge("start", "sw"), edge("sw", "a", "case_0"), edge("sw", "b", "case_1"), edge("sw", "c", "default"), edge("a", "m"), edge("b", "m"), edge("c", "m"), edge("m", "out")],
        ),
    )
    assert ex["status"] == "completed", ex["error"]
    assert statuses(ex)["a"] == "skipped" and statuses(ex)["c"] == "skipped"
    assert ex["result"]["seen"] == "b-b"


def test_loop_runs_body_per_item_and_enforces_limit(api):
    good = definition(
        [
            node("start", "trigger.manual", {"sample_data": {"xs": [1, 2, 3]}}),
            node("loop", "logic.loop", {"items": "{{ trigger.xs }}", "max_iterations": 5}),
            node("body", "data.set", {"assignments": [{"key": "n", "value": "{{ item }}"}], "include_input": False}),
            node("after", "data.transform", {"source": "{{ input }}", "operations": [{"operation": "sum", "field": "n"}]}),
        ],
        [edge("start", "loop"), edge("loop", "body", "body"), edge("loop", "after", "done")],
    )
    ex = run_workflow(api, good)
    assert ex["status"] == "completed"
    assert ex["result"]["sum"] == 6
    assert len([n for n in ex["nodes"] if n["node_id"] == "body"]) == 3

    good["nodes"][1]["config"]["max_iterations"] = 2
    limited = run_workflow(api, good)
    assert limited["status"] == "failed"
    assert limited["error_type"] == "resource_limit"


def test_failed_node_fails_workflow_with_useful_error(api):
    ex = run_workflow(api, definition([MANUAL, node("bad", "data.parse_json", {"source": "{not json"}), node("next", "data.set", {"assignments": [{"key": "a", "value": 1}]})], [edge("start", "bad"), edge("bad", "next")]))
    assert ex["status"] == "failed"
    assert ex["failed_node_id"] == "bad"
    assert "Invalid JSON" in ex["error"]
    assert statuses(ex)["next"] == "skipped"


def test_continue_and_error_branch_policies(api):
    ex = run_workflow(
        api,
        definition(
            [MANUAL, node("bad", "data.parse_json", {"source": "{nope"}, on_error="error_branch"), node("ok", "data.set", {"assignments": [{"key": "a", "value": 1}]}), node("handler", "data.set", {"assignments": [{"key": "handled", "value": "{{ input.error }}"}]})],
            [edge("start", "bad"), edge("bad", "ok"), edge("bad", "handler", "error")],
        ),
    )
    assert ex["status"] == "completed"
    assert statuses(ex) == {"start": "completed", "bad": "failed", "ok": "skipped", "handler": "completed"}
    assert "Invalid JSON" in ex["result"]["handled"]

    ex2 = run_workflow(api, definition([MANUAL, node("bad", "data.parse_json", {"source": "{nope"}, on_error="continue"), node("ok", "data.set", {"assignments": [{"key": "a", "value": 1}]})], [edge("start", "bad"), edge("bad", "ok")]))
    assert ex2["status"] == "completed"
    assert statuses(ex2)["ok"] == "completed"


def _public_dns(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])


def test_http_retries_safe_get_but_not_post(api, monkeypatch):
    _public_dns(monkeypatch)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    retry = {"max_attempts": 3, "delay_ms": 0, "backoff": 1.0}
    ex = run_workflow(api, definition([MANUAL, node("h", "integration.http", {"method": "GET", "url": "https://api.example.org/x"}, retry=retry)], [edge("start", "h")]), http_transport=transport)
    assert ex["status"] == "completed"
    assert calls["n"] == 3
    http_node = next(n for n in ex["nodes"] if n["node_id"] == "h")
    assert http_node["attempts"] == 3
    assert ex["result"]["body"] == {"ok": True}

    calls["n"] = 0
    ex2 = run_workflow(api, definition([MANUAL, node("h", "integration.http", {"method": "POST", "url": "https://api.example.org/x", "body_type": "json", "body": "{}"}, retry=retry)], [edge("start", "h")]), http_transport=transport)
    assert ex2["status"] == "failed"
    assert calls["n"] == 1, "non-idempotent POST must not be retried by default"

    calls["n"] = 0
    explicit = {**retry, "allow_non_idempotent": True}
    ex3 = run_workflow(api, definition([MANUAL, node("h", "integration.http", {"method": "POST", "url": "https://api.example.org/x", "body_type": "json", "body": "{}"}, retry=explicit)], [edge("start", "h")]), http_transport=transport)
    assert ex3["status"] == "completed"
    assert calls["n"] == 3


def test_test_mode_simulates_side_effects(api, monkeypatch):
    _public_dns(monkeypatch)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        return httpx.Response(200)

    defn = definition(
        [
            MANUAL,
            node("h", "integration.http", {"method": "POST", "url": "https://api.example.org/x", "body_type": "json", "body": "{}"}),
            node("db", "integration.database", {"operation": "insert", "collection": "testmode", "data": "{{ trigger }}"}),
            node("mail", "integration.email", {"to": "a@example.com", "subject": "s", "body": "b"}),
        ],
        [edge("start", "h"), edge("h", "db"), edge("db", "mail")],
    )
    ex = run_workflow(api, defn, mode="test", http_transport=httpx.MockTransport(handler))
    assert ex["status"] == "completed"
    assert calls["n"] == 0
    for row in ex["nodes"][1:]:
        assert row["simulated"] is True
        assert row["output"]["data"]["simulated"] is True
    assert api.get("/api/data/collections").json() == []


def test_database_node_persists_scoped_records(api, other_api):
    ex = run_workflow(
        api,
        definition(
            [
                MANUAL,
                node("ins", "integration.database", {"operation": "insert", "collection": "people", "data": {"name": "Ada", "n": 1}}),
                node("find", "integration.database", {"operation": "find", "collection": "people", "filters": [{"key": "name", "value": "ada"}]}),
            ],
            [edge("start", "ins"), edge("ins", "find")],
        ),
    )
    assert ex["status"] == "completed"
    assert ex["result"]["count"] == 1
    assert api.get("/api/data/collections").json()[0]["name"] == "people"
    assert other_api.get("/api/data/collections").json() == []
    ex2 = run_workflow(other_api, definition([MANUAL, node("find", "integration.database", {"operation": "find", "collection": "people"})], [edge("start", "find")]))
    assert ex2["result"]["count"] == 0


def test_cancel_and_delay(api):
    wf = api.post("/api/workflows", json={"name": "Slow", "definition": definition([MANUAL, node("d", "logic.delay", {"seconds": 0})], [edge("start", "d")])}).json()
    queued = api.post(f"/api/workflows/{wf['id']}/run", json={}).json()
    assert api.post(f"/api/executions/{queued['execution_id']}/cancel").status_code == 200
    run_pending()
    ex = api.get(f"/api/executions/{queued['execution_id']}").json()
    assert ex["status"] == "cancelled"


def test_retry_links_records_and_confirms_side_effects(api):
    wf = api.post("/api/workflows", json={"name": "Retry", "definition": definition([MANUAL, node("bad", "data.parse_json", {"source": "{x"})], [edge("start", "bad")])}).json()
    first = api.post(f"/api/workflows/{wf['id']}/run", json={}).json()["execution_id"]
    run_pending()
    second = api.post(f"/api/executions/{first}/retry", json={})
    assert second.status_code == 202
    run_pending()
    retried = api.get(f"/api/executions/{second.json()['execution_id']}").json()
    assert retried["retry_of_id"] == first
    assert first != retried["id"]
    assert api.get(f"/api/executions/{first}").json()["retry_ids"] == [retried["id"]]

    # Executions stay linked to the version they ran.
    original = api.get(f"/api/executions/{first}").json()
    api.put(f"/api/workflows/{wf['id']}", json={"definition": definition([MANUAL], [])})
    assert api.get(f"/api/executions/{first}").json()["definition"] == original["definition"]


def test_logs_redact_secrets(api):
    ex = run_workflow(api, definition([node("start", "trigger.manual", {"sample_data": {"password": "hunter2hunter2", "api_key": "abc123456", "ok": "visible"}}), node("s", "data.set", {"assignments": [{"key": "copy", "value": "fine"}]})], [edge("start", "s")]))
    text = str(ex["nodes"])
    assert "hunter2hunter2" not in text and "abc123456" not in text
    assert "visible" in text


# ------------------------------------------------------------------- validator
def _errors(defn: dict, **kw) -> set[str]:
    return {e.code for e in validate_definition(defn, **kw).errors}


def test_validator_structure_rules():
    assert "missing_trigger" in _errors(definition([node("a", "data.set", {"assignments": [{"key": "x", "value": 1}]})], []))
    assert "unsupported_node" in _errors(definition([MANUAL, node("x", "integration.salesforce")], [edge("start", "x")]))
    assert "empty_workflow" in _errors(definition([], []))
    cyc = definition([MANUAL, node("a", "logic.delay", {"seconds": 1}), node("b", "logic.delay", {"seconds": 1})], [edge("start", "a"), edge("a", "b"), edge("b", "a")])
    assert "cycle" in _errors(cyc)
    assert "self_loop" in _errors(definition([MANUAL, node("a", "logic.delay", {"seconds": 1})], [edge("start", "a"), edge("a", "a")]))
    assert "missing_connection" in _errors(definition([MANUAL, node("a", "logic.delay", {"seconds": 1})], []))
    assert "invalid_connection" in _errors(definition([MANUAL, node("m2", "trigger.manual")], [edge("start", "m2")]))
    assert "invalid_port" in _errors(definition([MANUAL, node("a", "logic.delay", {"seconds": 1})], [edge("start", "a", "nope")]))
    assert "missing_config" in _errors(definition([MANUAL, node("h", "integration.http")], [edge("start", "h")]))
    assert "invalid_format" in _errors({"nodes": "wrong"})


def test_validator_incompatible_port_types():
    d = definition(
        [MANUAL, node("f", "logic.filter", {"conditions": [{"left": "{{ item.a }}", "operator": "equals", "right": "1"}]}), node("m", "data.map_fields", {"mappings": [{"target": "a", "source": "b"}]})],
        [edge("start", "f"), edge("f", "m")],
    )
    assert "incompatible_types" in _errors(d)


def test_validator_error_port_requires_policy():
    d = definition([MANUAL, node("p", "data.parse_json", {"source": "{}"}), node("h", "logic.delay", {"seconds": 0})], [edge("start", "p"), edge("p", "h", "error")])
    assert "invalid_port" in _errors(d)
    d["nodes"][1]["settings"] = {"on_error": "error_branch"}
    assert "invalid_port" not in _errors(d)


def test_validator_loop_branches_must_stay_separate():
    d = definition(
        [MANUAL, node("l", "logic.loop", {"items": "{{ input.items }}"}), node("a", "logic.merge"), ],
        [edge("start", "l"), edge("l", "a", "body"), edge("l", "a", "done")],
    )
    assert "invalid_loop" in _errors(d)


def test_validator_rejects_plaintext_secrets_on_save(api):
    d = definition([MANUAL, node("h", "integration.http", {"url": "https://x.example", "headers": [{"key": "Authorization", "value": "Bearer abcdefghijklmnopqrstuvwxyz"}]})], [edge("start", "h")])
    response = api.post("/api/workflows", json={"name": "Leaky", "definition": d})
    assert response.status_code == 422
    assert "credential" in str(response.json()).lower() or "secret" in str(response.json()).lower()


def test_validator_missing_credential_blocks_real_run_only():
    d = definition([MANUAL, node("m", "integration.email", {"to": "a@b.co", "subject": "s", "body": "b"})], [edge("start", "m")])
    assert "missing_credential" in _errors(d, mode="run")
    assert "missing_credential" not in _errors(d, mode="test")


def test_unknown_credential_is_rejected():
    d = definition([MANUAL, node("m", "integration.email", {"to": "a@b.co", "subject": "s", "body": "b", "credential_id": "cred_other"})], [edge("start", "m")])
    assert "unknown_credential" in _errors(d, credential_ids=set())


def test_every_template_is_valid_and_uses_supported_nodes():
    assert len(TEMPLATES) == 8
    types = {s.type for s in all_specs()}
    for template in TEMPLATES:
        result = validate_definition(template["definition"], set(), mode="test")
        assert result.ok, (template["slug"], result.public())
        assert {n["type"] for n in template["definition"]["nodes"]} <= types


# ----------------------------------------------------------------- expressions
def test_expressions_are_safe_and_typed():
    scope = {"input": {"a": {"b": [1, 2]}, "name": " x ", "n": "1,250.50"}, "nodes": {"My Node": {"v": 3}}}
    assert render("{{ input.a.b[1] }}", scope) == 2
    assert render("v={{ input.a.b[0] }}", scope) == "v=1"
    assert render('{{ nodes["My Node"].v }}', scope) == 3
    assert evaluate("input.name | trim | upper", scope) == "X"
    assert evaluate("input.n | number", scope) == 1250.5
    assert evaluate("input.missing | default:'none'", scope) == "none"
    # Attribute walking must not reach Python internals.
    assert evaluate("input.__class__", scope) is None
    assert evaluate("input.a.__init__.__globals__", scope) is None
    import pytest

    from app.engine.expressions import ExpressionError

    for bad in ("input | eval", "__import__('os')", "input.a; 1"):
        with pytest.raises(ExpressionError):
            evaluate(bad, scope)

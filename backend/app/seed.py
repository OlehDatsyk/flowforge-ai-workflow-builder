"""Seeds templates and the clearly labelled demonstration workspace.

Demo execution records have ``is_demo=True`` and are generated, not real runs. The
UI labels them everywhere. Demo workflows can still be run for real.
"""
from __future__ import annotations

import copy
import random
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import utcnow
from .engine.definition import auto_layout
from .engine.registry import get_spec
from .models import (
    NodeExecution,
    User,
    Workflow,
    WorkflowExecution,
    WorkflowTemplate,
    Workspace,
    WorkspaceMember,
)
from .security import hash_password
from .services import create_version, set_draft, sync_triggers
from .templates_data import TEMPLATES, _d, _e, _n

DEMO_EMAIL = "demo@flowforge.local"


def seed_templates(db: Session) -> None:
    existing = {t.slug: t for t in db.scalars(select(WorkflowTemplate))}
    for data in TEMPLATES:
        row = existing.get(data["slug"])
        definition = auto_layout(copy.deepcopy(data["definition"]))
        if row is None:
            db.add(WorkflowTemplate(**{**data, "definition": definition}))
        else:
            for key, value in {**data, "definition": definition}.items():
                setattr(row, key, value)


def _demo_failure(rng: random.Random, node: dict) -> tuple[str, str]:
    """A plausible failure for this node type, so demo records read consistently."""
    kind = node["type"]
    if kind == "integration.http":
        error_type, message = rng.choice([("network", "Connection failed: ConnectError"), ("http_status", "GET returned HTTP 503"), ("timeout", "Request timed out after 15s")])
    elif kind.startswith("ai."):
        error_type, message = rng.choice([("ai", "AI provider rate limit reached"), ("timeout", "AI request timed out after 90s")])
    elif kind == "integration.email":
        error_type, message = "auth", "SMTP server rejected the username or password"
    elif kind == "integration.database":
        error_type, message = "resource_limit", "Record is larger than the 256 KB limit"
    else:
        error_type, message = "validation", "Input data did not have the expected shape"
    return error_type, f"{node['name']}: {message}"


def _extra_workflows() -> list[dict]:
    return [
        {
            "name": "Daily Order Digest",
            "category": "Operations",
            "folder": "Operations",
            "description": "Filters today's orders, totals them, and stores a digest. Runs for real with the sample data, no setup needed.",
            "definition": _d(
                [
                    _n("start", "trigger.manual", "Orders", {"sample_data": {"orders": [{"id": 1, "status": "paid", "total": 120.5, "customer": "Ada"}, {"id": 2, "status": "refunded", "total": 40, "customer": "Grace"}, {"id": 3, "status": "paid", "total": 89.99, "customer": "Alan"}]}}),
                    _n("paid", "logic.filter", "Paid Orders", {"items": "{{ trigger.orders }}", "conditions": [{"left": "{{ item.status }}", "operator": "equals", "right": "paid"}], "combine": "all"}),
                    _n("sum", "data.transform", "Total Revenue", {"source": "{{ input }}", "operations": [{"operation": "sum", "field": "total"}]}),
                    _n("big", "logic.if", "Revenue Over 200?", {"conditions": [{"left": "{{ input.sum }}", "operator": "gt", "right": "200"}], "combine": "all"}),
                    _n("good", "data.set", "Good Day", {"assignments": [{"key": "verdict", "value": "Target met"}], "include_input": True}),
                    _n("low", "data.set", "Quiet Day", {"assignments": [{"key": "verdict", "value": "Below target"}], "include_input": True}),
                    _n("merge", "logic.merge", "Combine Branches", {"mode": "first"}),
                    _n("save", "integration.database", "Save Digest", {"operation": "insert", "collection": "order_digests", "data": "{{ input }}"}),
                ],
                [_e("start", "paid"), _e("paid", "sum"), _e("sum", "big"), _e("big", "good", "true"), _e("big", "low", "false"), _e("good", "merge"), _e("low", "merge"), _e("merge", "save")],
            ),
        },
    ]


def seed_demo_workspace(db: Session, workspace_id: str, user_id: str | None) -> None:
    rng = random.Random(20261105)
    now = utcnow()
    sources = [{**t, "folder": "Examples"} for t in TEMPLATES if t["slug"] in ("invoice-data-extraction", "customer-support-classification", "website-availability-monitoring", "webhook-data-processing", "csv-data-analysis", "ai-text-classification")] + _extra_workflows()
    created: list[tuple[Workflow, object]] = []
    for source in sources:
        definition = auto_layout(copy.deepcopy(source["definition"]))
        wf = Workflow(workspace_id=workspace_id, name=source["name"], description=source["description"], category=source["category"], folder=source.get("folder", ""), tags=["demo"], is_demo=True, created_by=user_id, draft_definition=definition)
        set_draft(wf, definition)
        db.add(wf)
        db.flush()
        version = create_version(db, wf, user_id, "Demo workflow")
        sync_triggers(db, wf)
        created.append((wf, version))

    # Generated history, weighted so the charts have realistic shape.
    weights = [5, 4, 8, 3, 2, 2, 3]
    for day in range(30):
        for _ in range(rng.randint(2, 7) if day else rng.randint(4, 8)):
            wf, version = rng.choices(created, weights=weights[: len(created)])[0]
            created_at = now - timedelta(days=day, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
            if created_at > now:
                created_at = now - timedelta(minutes=rng.randint(5, 600))
            failed = rng.random() < 0.13
            status = "failed" if failed else "completed"
            nodes = version.definition["nodes"]
            fail_at = rng.randint(1, max(1, len(nodes) - 1)) if failed else None
            error_type, error = _demo_failure(rng, nodes[fail_at]) if failed else (None, None)
            ex = WorkflowExecution(
                id=f"ex_demo{secrets.token_hex(7)}",
                workspace_id=workspace_id,
                workflow_id=wf.id,
                version_id=version.id,
                workflow_name=wf.name,
                status=status,
                mode="run",
                trigger_type=nodes[0]["type"].split(".")[1],
                trigger_data={"_demo": True},
                error=f"[Demo record] {error}" if failed else None,
                error_type=error_type,
                failed_node_id=nodes[fail_at]["id"] if failed else None,
                is_demo=True,
                created_at=created_at,
                started_at=created_at,
                result={"_demo": True, "note": "Generated demonstration record"} if not failed else None,
            )
            db.add(ex)
            elapsed = 0
            count = 0
            for i, node in enumerate(nodes):
                spec = get_spec(node["type"])
                is_ai = node["type"].startswith("ai.")
                base = rng.randint(400, 1800) if is_ai else rng.randint(80, 900) if node["type"] == "integration.http" else rng.randint(1, 40)
                node_status = "completed"
                if failed and i == fail_at:
                    node_status = "failed"
                elif failed and i > fail_at:
                    node_status = "skipped"
                started = created_at + timedelta(milliseconds=elapsed)
                ran = node_status != "skipped"
                if ran:
                    count += 1
                db.add(
                    NodeExecution(
                        execution_id=ex.id,
                        node_id=node["id"],
                        node_name=node["name"],
                        node_type=node["type"],
                        sequence=i + 1,
                        status=node_status,
                        started_at=started if ran else None,
                        finished_at=started + timedelta(milliseconds=base) if ran else None,
                        duration_ms=base if ran else None,
                        input_summary={"_demo": True} if ran else None,
                        output_summary={"ports": [spec.output_ports(node.get("config", {}))[0].id] if spec.output_ports(node.get("config", {})) else [], "data": {"_demo": True, "note": "Generated demonstration record"}} if node_status == "completed" else None,
                        error=f"[Demo record] {error}" if node_status == "failed" else None,
                        error_type=error_type if node_status == "failed" else None,
                        simulated=ran,
                        ai_provider="demo" if is_ai and ran else None,
                    )
                )
                if ran:
                    elapsed += base
            ex.nodes_executed = count
            ex.duration_ms = elapsed
            ex.finished_at = created_at + timedelta(milliseconds=elapsed)
    db.flush()


def ensure_demo_account(db: Session) -> None:
    if db.scalar(select(User.id).where(User.email == DEMO_EMAIL)):
        return
    # No one can log in with this password: demo access goes through /api/auth/demo.
    user = User(email=DEMO_EMAIL, name="Demo User", password_hash=hash_password(secrets.token_urlsafe(32)), is_demo=True)
    db.add(user)
    db.flush()
    workspace = Workspace(name="Demo Workspace", settings={"is_demo": True})
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    seed_demo_workspace(db, workspace.id, user.id)
    db.flush()

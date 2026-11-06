"""Relational schema. See ARCHITECTURE.md for the entity overview."""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base, UTCDateTime, utcnow


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


EXECUTION_STATUSES = ("pending", "running", "waiting", "completed", "failed", "cancelled")
NODE_STATUSES = ("pending", "running", "waiting", "completed", "failed", "skipped", "cancelled")
ROLES = ("owner", "admin", "editor", "viewer")


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class AuthSession(Base):
    """Server-side session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ses"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    user: Mapped[User] = relationship()


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prt"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wsp"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        CheckConstraint("role in ('owner','admin','editor','viewer')", name="ck_member_role"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mem"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="editor")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Workflow(TimestampMixin, Base):
    __tablename__ = "workflows"
    __table_args__ = (Index("ix_workflow_ws_updated", "workspace_id", "updated_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wf"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="General", nullable=False)
    folder: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    draft_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    draft_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active_version_id: Mapped[Optional[str]] = mapped_column(String(32))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    versions: Mapped[list["WorkflowVersion"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")


class WorkflowVersion(Base):
    """Immutable snapshot. Executions always point at one of these."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ver"))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    workflow: Mapped[Workflow] = relationship(back_populates="versions")


class WorkflowNode(Base):
    """Query projection of a version's nodes (the JSON definition stays authoritative)."""

    __tablename__ = "workflow_nodes"
    __table_args__ = (UniqueConstraint("version_id", "node_id", name="uq_version_node"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wnd"))
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class WorkflowConnection(Base):
    """Query projection of a version's edges."""

    __tablename__ = "workflow_connections"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wcn"))
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_port: Mapped[str] = mapped_column(String(64), nullable=False)
    target_node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_port: Mapped[str] = mapped_column(String(64), nullable=False)


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        Index("ix_exec_ws_created", "workspace_id", "created_at"),
        Index("ix_exec_status_created", "status", "created_at"),
        CheckConstraint(
            "status in ('pending','running','waiting','completed','failed','cancelled')", name="ck_exec_status"
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ex"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_versions.id", ondelete="RESTRICT"), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="run", nullable=False)  # run | test
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    trigger_node_id: Mapped[Optional[str]] = mapped_column(String(64))
    trigger_data: Mapped[Any] = mapped_column(JSON, default=dict, nullable=True)
    result: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    error_type: Mapped[Optional[str]] = mapped_column(String(40))
    failed_node_id: Mapped[Optional[str]] = mapped_column(String(64))
    nodes_executed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_of_id: Mapped[Optional[str]] = mapped_column(String(32))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    nodes: Mapped[list["NodeExecution"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="NodeExecution.sequence"
    )


class NodeExecution(Base):
    __tablename__ = "node_executions"
    __table_args__ = (Index("ix_nodeexec_exec_node", "execution_id", "node_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("nx"))
    execution_id: Mapped[str] = mapped_column(ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_name: Mapped[str] = mapped_column(String(160), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    iteration: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    input_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    output_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text)
    error_type: Mapped[Optional[str]] = mapped_column(String(40))
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_provider: Mapped[Optional[str]] = mapped_column(String(32))
    ai_input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    ai_output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    execution: Mapped[WorkflowExecution] = relationship(back_populates="nodes")


class Credential(TimestampMixin, Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_credential_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("cred"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    masked: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Integration(TimestampMixin, Base):
    """A workspace's connection state for a catalogue provider (see integrations catalogue)."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("workspace_id", "provider", name="uq_integration_provider"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("int"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    credential_id: Mapped[Optional[str]] = mapped_column(ForeignKey("credentials.id", ondelete="SET NULL"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_test_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    last_test_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    last_test_message: Mapped[Optional[str]] = mapped_column(String(300))


class WebhookTrigger(TimestampMixin, Base):
    __tablename__ = "webhook_triggers"
    __table_args__ = (UniqueConstraint("workflow_id", "node_id", name="uq_webhook_node"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("whk"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(24))
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_request_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class WebhookRequest(Base):
    __tablename__ = "webhook_requests"
    __table_args__ = (Index("ix_webhookreq_trigger_time", "trigger_id", "received_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wrq"))
    trigger_id: Mapped[str] = mapped_column(ForeignKey("webhook_triggers.id", ondelete="CASCADE"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(200), nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    body_preview: Mapped[Any] = mapped_column(JSON, nullable=True)
    execution_id: Mapped[Optional[str]] = mapped_column(String(32))
    source_ip: Mapped[Optional[str]] = mapped_column(String(64))


class ScheduledTrigger(TimestampMixin, Base):
    __tablename__ = "scheduled_triggers"
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_id", name="uq_schedule_node"),
        Index("ix_schedule_due", "enabled", "next_run_at"),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sch"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)
    last_execution_id: Mapped[Optional[str]] = mapped_column(String(32))


class WorkflowTemplate(TimestampMixin, Base):
    __tablename__ = "workflow_templates"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("tpl"))
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    required_integrations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    expected_behaviour: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_requirements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AIConversation(Base):
    """One AI builder exchange: prompt, validated proposal, provider, usage."""

    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_aiconv_ws_created", "workspace_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("aic"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    workflow_id: Mapped[Optional[str]] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # generate | modify | explain
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class DataRecord(TimestampMixin, Base):
    """Built-in workspace data store used by the Database Operation node."""

    __tablename__ = "data_records"
    __table_args__ = (Index("ix_data_ws_collection", "workspace_id", "collection", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rec"))
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    collection: Mapped[str] = mapped_column(String(80), nullable=False)
    data: Mapped[Any] = mapped_column(JSON, nullable=False)
    execution_id: Mapped[Optional[str]] = mapped_column(String(32))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_ws_created", "workspace_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("aud"))
    workspace_id: Mapped[Optional[str]] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

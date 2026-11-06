"""Durable background execution: a database-backed job queue plus scheduler.

``WorkflowExecution`` rows with status ``pending`` are the queue, so jobs survive
restarts and no extra infrastructure is required. Claiming uses a conditional
UPDATE, so several worker processes can safely share one PostgreSQL database.

Runs inside the API process by default (WORKER_ENABLED=true), or standalone:

    python -m app.worker
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import or_, select, update

from .config import get_settings
from .database import session_scope, utcnow
from .engine.executor import execute
from .models import NodeExecution, ScheduledTrigger, Workflow, WorkflowExecution, WorkflowVersion
from .services import compute_next_run, create_execution

log = logging.getLogger("flowforge.worker")


def claim_next() -> str | None:
    with session_scope() as db:
        candidates = db.scalars(
            select(WorkflowExecution.id).where(WorkflowExecution.status == "pending").order_by(WorkflowExecution.created_at).limit(5)
        ).all()
        for execution_id in candidates:
            now = utcnow()
            claimed = db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id, WorkflowExecution.status == "pending")
                .values(status="running", started_at=now, heartbeat_at=now)
            )
            if claimed.rowcount == 1:
                return execution_id
    return None


def sweep_stale() -> int:
    """Executions whose worker died are failed, not re-run: a node may have had side effects."""
    settings = get_settings()
    cutoff = utcnow() - timedelta(seconds=settings.stale_execution_seconds)
    with session_scope() as db:
        stale = db.scalars(
            select(WorkflowExecution).where(
                WorkflowExecution.status.in_(("running", "waiting")),
                or_(WorkflowExecution.heartbeat_at < cutoff, WorkflowExecution.heartbeat_at.is_(None)),
            )
        ).all()
        for ex in stale:
            now = utcnow()
            ex.status = "failed"
            ex.error = "The worker stopped while this execution was running. It was not retried automatically because a step may already have had external effects."
            ex.error_type = "worker_interrupted"
            ex.finished_at = now
            db.execute(
                update(NodeExecution)
                .where(NodeExecution.execution_id == ex.id, NodeExecution.status == "running")
                .values(status="failed", error="Worker stopped", finished_at=now)
            )
        return len(stale)


def fire_due_schedules() -> int:
    fired = 0
    with session_scope() as db:
        now = utcnow()
        due = db.scalars(
            select(ScheduledTrigger).where(ScheduledTrigger.enabled.is_(True), ScheduledTrigger.next_run_at.is_not(None), ScheduledTrigger.next_run_at <= now).limit(50)
        ).all()
        for trigger in due:
            next_run = compute_next_run(trigger.schedule, now)
            # Conditional update: if another worker got here first, skip this firing.
            won = db.execute(
                update(ScheduledTrigger)
                .where(ScheduledTrigger.id == trigger.id, ScheduledTrigger.next_run_at == trigger.next_run_at)
                .values(next_run_at=next_run, last_run_at=now, enabled=next_run is not None)
            )
            if won.rowcount != 1:
                continue
            wf = db.get(Workflow, trigger.workflow_id)
            version = db.get(WorkflowVersion, wf.active_version_id) if wf and wf.active_version_id else None
            if not wf or not wf.is_active or not version:
                continue
            try:
                execution = create_execution(db, wf, version, trigger_type="schedule", trigger_node_id=trigger.node_id, trigger_data={"scheduled_for": now.isoformat()})
            except Exception:  # noqa: BLE001 - queue full: skip this tick, keep the scheduler alive
                log.warning("Skipped scheduled run of %s: queue is full", wf.id)
                continue
            db.execute(update(ScheduledTrigger).where(ScheduledTrigger.id == trigger.id).values(last_execution_id=execution.id))
            fired += 1
    return fired


class BackgroundRunner:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pool = ThreadPoolExecutor(max_workers=self.settings.worker_concurrency, thread_name_prefix="ff-exec")
        self._slots = threading.Semaphore(self.settings.worker_concurrency)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="ff-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run_one(self, execution_id: str) -> None:
        try:
            execute(execution_id)
        except Exception:  # noqa: BLE001
            log.exception("Execution %s crashed", execution_id)
        finally:
            self._slots.release()

    def _loop(self) -> None:
        last_sweep = 0.0
        last_schedule = 0.0
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                if now - last_sweep > 30:
                    last_sweep = now
                    swept = sweep_stale()
                    if swept:
                        log.warning("Marked %d interrupted execution(s) as failed", swept)
                if now - last_schedule > 5:
                    last_schedule = now
                    fire_due_schedules()
                while self._slots.acquire(blocking=False):
                    execution_id = claim_next()
                    if execution_id is None:
                        self._slots.release()
                        break
                    self._pool.submit(self._run_one, execution_id)
            except Exception:  # noqa: BLE001 - e.g. transient DB error: keep polling
                log.exception("Worker loop error")
            self._stop.wait(self.settings.worker_poll_seconds)


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(level=logging.INFO)
    runner = BackgroundRunner()
    runner.start()
    log.info("FlowForge worker running. Press Ctrl+C to stop.")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    runner.stop()


if __name__ == "__main__":  # pragma: no cover
    main()

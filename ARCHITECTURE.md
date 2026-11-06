# Architecture

```
Browser (React, React Flow)
   │  JSON over HTTP, session cookie + CSRF header
   ▼
FastAPI app ───────────── /hooks/{token} (public, signed)
   │  routers -> services -> SQLAlchemy
   ▼
Database (PostgreSQL or SQLite) ◄──── pending executions are the job queue
   ▲
   │  conditional UPDATE to claim a job
Worker (in the API process, or `python -m app.worker`)
   ├── Scheduler: fires due ScheduledTrigger rows
   ├── Sweeper: fails executions whose worker died
   └── Executor -> node handlers -> HTTP, SMTP, AI providers, data store
```

## Repository layout

```
backend/app/
  main.py            App, security headers, static frontend
  config.py          Settings, including production safety checks
  models.py          All tables
  security.py        Hashing, encryption, masking, redaction, rate limiter
  deps.py            Auth, CSRF, workspace authorisation
  services.py        Versions, trigger sync, schedule maths, execution creation
  worker.py          Queue, scheduler, stale sweep
  seed.py            Templates and labelled demo data
  templates_data.py  The 8 templates
  engine/            definition, registry, validator, executor, expressions, ssrf, nodes_*
  ai/                providers, planner, demo_planner, demo
  routers/           auth, workspaces, workflows, executions, integrations, templates, ai
backend/migrations/  Alembic
backend/tests/       Pytest
frontend/src/
  editor/            Canvas, panels, AI assistant, graph helpers
  pages/             One file per screen
  components/        UI kit, layout, charts, execution table
  lib/               API client, auth context, hooks, types
frontend/e2e/        Playwright journeys
```

## Key decisions

### Database-backed queue instead of Celery and Redis

Celery does not support Windows, the primary target, and Redis was not available. `WorkflowExecution` rows with status `pending` are the queue:

- Jobs are durable by construction, because they are ordinary rows.
- Claiming uses `UPDATE ... WHERE id = ? AND status = 'pending'`, so several workers can share one database safely.
- Polling every 0.5 seconds costs a little latency and scales less far than a broker. The module boundary (`claim_next`, `execute`) is small if a broker is ever needed.

### SQLite locally, PostgreSQL in production

The same models and migration run on both, and the whole test suite passes on both. All types are portable: `JSON`, and `UTCDateTime`, which keeps timestamps timezone-aware even though SQLite drops the zone.

### Authoritative JSON, with a query projection

The workflow definition is versioned JSON. `WorkflowNode` and `WorkflowConnection` are per-version projections for querying; the JSON stays authoritative.

### A registry as the single source of truth

`engine/registry.py` holds every node type. The API publishes it, the frontend builds forms from it, and the AI planner's prompt and JSON schema enum come from it. A node type that is not registered cannot be saved, generated or run.

## Workflow definition format

```json
{
  "schema_version": 1,
  "nodes": [{
    "id": "check", "type": "logic.if", "name": "Amount over 500?",
    "description": "", "position": {"x": 0, "y": 0},
    "config": {"conditions": [{"left": "{{ input.amount }}", "operator": "gt", "right": "500"}]},
    "settings": {
      "retry": {"max_attempts": 1, "delay_ms": 1000, "backoff": 2, "allow_non_idempotent": false},
      "timeout_seconds": 30,
      "on_error": "stop"
    }
  }],
  "edges": [{"id": "e1", "source": "a", "source_port": "main", "target": "check", "target_port": "main"}]
}
```

Expressions are parsed, never evaluated as code: a path over plain JSON values, or a literal, piped through allow-listed filters. `{{ input.x }}`, `{{ trigger.body.x }}`, `{{ nodes["Name"].x }}`, `{{ vars.x }}`, `{{ item }}`.

## Supported nodes

| Category | Types |
|---|---|
| Trigger | `trigger.manual`, `trigger.webhook`, `trigger.schedule` |
| Logic | `logic.if`, `logic.switch`, `logic.filter`, `logic.merge`, `logic.delay`, `logic.loop` |
| Data | `data.set`, `data.transform`, `data.parse_json`, `data.parse_csv`, `data.extract_text`, `data.map_fields`, `data.validate` |
| AI | `ai.generate`, `ai.classify`, `ai.summarize`, `ai.extract`, `ai.decide` |
| Integration | `integration.http`, `integration.webhook_send`, `integration.email`, `integration.database` |

## Execution model

1. `POST /run` validates the draft, snapshots a version if the logic changed (canvas positions do not count), and inserts a `pending` execution.
2. The worker claims it and `execute()` loads that exact version and validates it again.
3. `_run_graph` walks nodes in topological order. An edge is active if its source produced that port. A node with no active inputs is recorded as `skipped`.
4. A loop runs its Each Item subgraph once per item, then continues from Done with the results.
5. Each node gets a `NodeExecution` row at start and finish, with input and output redacted and size-capped.
6. On failure, `on_error` decides: stop, continue, or follow the error branch.

**Retries:** only errors marked retryable (network, 5xx, 429, timeouts), and only for idempotent configurations, unless `allow_non_idempotent` is explicitly on.

**Test mode:** handlers with side effects return `{"simulated": true}` and flag the row. GET requests and AI calls really happen in test mode, because they do not change anything externally. AI calls with a real provider do cost tokens.

## Database schema

| Table | Purpose | Key relations and constraints |
|---|---|---|
| `users` | Accounts | Unique email |
| `auth_sessions` | Server-side sessions, hashed token | -> users |
| `password_reset_tokens` | Hashed, single-use, 1 hour | -> users |
| `workspaces`, `workspace_members` | Tenancy and roles | Unique (workspace, user); role check |
| `workflows` | Draft definition, active pointer | -> workspaces |
| `workflow_versions` | Immutable snapshots | Unique (workflow, version) |
| `workflow_nodes`, `workflow_connections` | Query projections | -> versions |
| `workflow_executions` | Runs and the job queue | -> version (RESTRICT); status check; indexed by workspace and status |
| `node_executions` | Per-node records | -> executions |
| `credentials` | Encrypted secrets and masked preview | Unique (workspace, name) |
| `integrations` | Connection state per provider | Unique (workspace, provider) |
| `webhook_triggers`, `webhook_requests` | Endpoints and request log | Unique token |
| `scheduled_triggers` | Schedules and next run | Index on (enabled, next_run_at) |
| `workflow_templates` | Template library | Unique slug |
| `ai_conversations` | Prompts, proposals, provider, usage | -> workspaces |
| `data_records` | Built-in data store | Index on (workspace, collection, created_at) |
| `audit_logs` | Security-relevant actions | Index on (workspace, created_at) |

## AI flow

```
prompt -> provider or demo planner -> plan JSON -> plan_to_definition (strips credentials)
       -> validate_definition -> retry once with validator feedback -> proposal
       -> user reviews and edits -> accept -> new INACTIVE workflow
```

To add a provider, subclass `AIProvider`, add it to `PROVIDER_CLASSES`, then add a credential type and a catalogue entry in `routers/integrations.py`.

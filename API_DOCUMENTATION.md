# API documentation

Interactive OpenAPI documentation is served by the running app at `/api/docs`, and is the authoritative reference for request and response bodies. This page is the map.

## Conventions

- **Auth:** an HttpOnly session cookie from `/api/auth/login`, `/register` or `/demo`.
- **CSRF:** every non-GET request needs `X-CSRF-Token`, returned by those endpoints and by `GET /api/auth/me`.
- **Workspace:** send `X-Workspace-Id`. Without it, your first workspace is used. Objects in other workspaces return 404.
- **Errors:** `{"detail": "message"}`, or `{"detail": {"message": "...", "issues": [...]}}` for validation.
- **Roles:** viewer < editor < admin < owner. Viewers read; editors change workflows; admins manage credentials, integrations and members.

## Auth

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Create an account and personal workspace |
| POST | `/api/auth/login`, `/logout` | Session |
| POST | `/api/auth/demo` | Enter the demo workspace (when enabled) |
| GET, PATCH | `/api/auth/me` | Current user and CSRF token; update name |
| POST | `/api/auth/change-password` | Change password, ending other sessions |
| POST | `/api/auth/password-reset/request`, `/confirm` | Reset flow |

## Workflows

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/workflows` | List (`search`, `status`, `category`, `folder`, `sort`, `page`); create |
| GET, PUT, DELETE | `/api/workflows/{id}` | Read with validation; save (`revision` gives optimistic locking); delete |
| POST | `/api/workflows/{id}/duplicate` | Copy |
| POST | `/api/workflows/{id}/activate`, `/deactivate` | Publish or stop triggers |
| GET, POST | `/api/workflows/{id}/versions` | History; save a checkpoint |
| GET | `/api/workflows/{id}/versions/{vid}` | One version |
| POST | `/api/workflows/{id}/versions/{vid}/restore` | Restore |
| POST | `/api/workflows/{id}/run` | Queue a run. Body: `mode` (`run` or `test`), `input`, `trigger_node_id`. Returns 202 |
| POST | `/api/workflows/{id}/nodes/{node}/test` | Test one node. Side effects are simulated unless `allow_side_effects` is true |
| GET | `/api/workflows/{id}/nodes/{node}/last-result` | Latest result for a node |
| GET | `/api/workflows/{id}/triggers` | Webhook endpoints and schedules |

## Definitions

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/nodes` | Node catalogue with fields, ports and schemas |
| POST | `/api/definitions/validate` | Validate without saving |
| POST | `/api/definitions/layout` | Auto layout |
| POST | `/api/definitions/ports` | Output ports for a definition's nodes |

## Executions and analytics

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/executions` | List (`search`, `status`, `workflow_id`, `mode`, `include_demo`, `sort`, `order`, `page`) |
| GET | `/api/executions/{id}` | Full record with node results and version definition |
| POST | `/api/executions/{id}/cancel` | Cancel |
| POST | `/api/executions/{id}/retry` | New run with the same version and input. Returns 409 with code `confirm_side_effects` unless `confirm_side_effects` is true when the workflow has external actions |
| GET | `/api/analytics/overview` | Totals, series, top workflows, categories, failures, AI usage (`range`, `workflow_id`, `start`, `end`, `include_demo`) |

## AI

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/ai/status` | Active provider, or demo mode |
| POST | `/api/ai/generate` | Propose a new workflow |
| POST | `/api/ai/modify` | Propose a change, with a computed diff. Does not apply it |
| POST | `/api/ai/explain` | Explain a workflow |
| POST | `/api/ai/conversations/{id}/accept` | Save a reviewed proposal as an inactive workflow |
| GET | `/api/ai/conversations` | Recent proposals |

## Integrations, credentials, data

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/credentials/types` | Credential types and fields |
| GET, POST | `/api/credentials` | List masked; create |
| PATCH, DELETE | `/api/credentials/{id}` | Update (blank secrets are kept); delete |
| GET | `/api/integrations` | Catalogue with status |
| PUT, DELETE | `/api/integrations/{provider}` | Connect a credential; disconnect |
| POST | `/api/integrations/{provider}/test` | Real connection test |
| GET | `/api/data/collections` | Data store collections |
| GET | `/api/data/collections/{name}` | Records |
| DELETE | `/api/data/records/{id}` | Delete a record |

## Webhooks

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/api/webhook-triggers/{id}` | Enable or disable |
| POST | `/api/webhook-triggers/{id}/rotate-secret` | New secret, returned only here |
| GET | `/api/webhook-triggers/{id}/requests` | Last 50 requests |
| POST | `/api/webhook-triggers/{id}/test` | In-app test run with side effects simulated |
| ANY | `/hooks/{token}` | **Public endpoint** |

### Calling a webhook

With `auth_mode: hmac`, send:

```
X-FlowForge-Timestamp: <unix seconds>
X-FlowForge-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<raw body>" using the secret>
```

With `auth_mode: token`, send `X-FlowForge-Token: <secret>`.

Example using the included helper:

```bash
python scripts/send_signed_webhook.py <webhook-url> <secret> sample_data/invoice.json
```

| Response | Meaning |
|---|---|
| 202 | Accepted: `{"execution_id": "...", "status": "accepted"}` |
| 400 | Body is not valid JSON |
| 401 | Bad or missing signature or token, or expired timestamp |
| 404 | Unknown token |
| 409 | Workflow not published, or webhook disabled |
| 413 | Body over the limit |
| 422 | Required body fields missing |
| 429 | Rate limit or queue full |

## Workspaces and system

| Method | Path | Purpose |
|---|---|---|
| GET, POST | `/api/workspaces` | List; create |
| GET, PATCH, DELETE | `/api/workspaces/current` | Current workspace |
| GET, POST | `/api/workspaces/current/members` | Members |
| PATCH, DELETE | `/api/workspaces/current/members/{user}` | Role; remove |
| POST, DELETE | `/api/workspaces/current/demo-data` | Load or remove labelled demo data |
| GET | `/api/templates` | Templates |
| POST | `/api/templates/{slug}/use` | Create a workflow from a template |
| GET | `/api/audit-logs` | Audit log (admin) |
| GET | `/api/health` | Health check |

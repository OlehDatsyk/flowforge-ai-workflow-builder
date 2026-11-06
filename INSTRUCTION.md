# Continuing development

For developers and AI coding agents picking up this project. Read [ARCHITECTURE.md](ARCHITECTURE.md) first.

## Get running

```bash
setup.bat
```

```bash
start.bat
```

For the commands on other setups, see the README. If `backend\.venv` does not exist, run `python scripts/venv_path.py` to find the Python environment.

## Rules that keep the product honest

These are product requirements, not style preferences. Do not weaken them to make something easier.

1. **Never claim something happened when it did not.** Simulated actions return `simulated: true` and show a badge. Demo records have `is_demo`. Demo AI says no model was called.
2. **Test runs change nothing external.** A handler with side effects must return a simulated result when `ctx.mode == "test"`. The executor refuses one that does not.
3. **AI only proposes.** No endpoint may let AI output save, activate or run anything without a separate user action.
4. **No arbitrary code execution** in nodes or expressions.
5. **Only list integrations that work.**
6. **Every query filters by workspace.** Use `get_workflow` and the other scoped helpers. Add new routes to `test_users_cannot_access_each_others_data`.
7. **Secrets never reach the frontend, logs or workflow JSON.**
8. **Do not auto-retry non-idempotent actions** unless the user has opted in.

## Common tasks

### Add a node type

1. Add a handler and `register(NodeSpec(...))` in `engine/nodes_*.py`. Declare `has_side_effects`, and simulate in test mode if it can be true.
2. If you use a new `icon` name, add it to `ICONS` in `frontend/src/editor/FlowNode.tsx`.
3. Add a test in `tests/test_engine.py`. Forms, the AI planner and validation pick it up automatically.
4. Set `planner_hint` if the AI needs special guidance.

If a node has dynamic outputs, also update `outputPorts` in `frontend/src/editor/graph.ts`.

### Add a credential type or integration

Edit `CREDENTIAL_TYPES` and `CATALOGUE` in `routers/integrations.py`. Mark secret fields with `"secret": True`.

### Change the schema

```bash
cd backend && python -m alembic revision --autogenerate -m "describe the change"
```

Review the generated file, then test on both SQLite and PostgreSQL. `pip install pgserver` gives you a real PostgreSQL without Docker; pass its URL as `TEST_DATABASE_URL`.

### Change the frontend

`start.bat` serves the built `frontend/dist`, so run `npm run build` to see changes there, or use `npm run dev` on port 5173.

Colours are in `tailwind.config.js`. Node category colours are in `CATEGORY` in `FlowNode.tsx`. Execution status colours are reserved for status.

## Before you finish

```bash
cd backend && python -m pytest
```

```bash
cd frontend && npm run build && npm test
```

With a server running, on a fresh or disposable database:

```bash
cd frontend && npx playwright test
```

This also regenerates `docs/screenshots`.

Then update `README.md` limitations and `CHANGELOG.md` if behaviour changed.

## Known gotchas

- **FastAPI runs dependency teardown after the response is sent.** Call `db.commit()` explicitly in mutating routes, or a client's next request can miss the change.
- **Long Windows paths** break native Python extensions. `scripts/venv_path.py` handles this.
- **`.env` at the root is loaded by config**, and tests override it through environment variables in `conftest.py`.
- **`TEMPLATE_RE` must not cross `}}`.** A naive lazy match treats `{{ a }}-{{ b }}` as one expression. There is a test.
- **Hash ignores positions.** Moving nodes does not create a version; changing logic does.

## Good next steps

See the roadmap in the README. The most valuable first: try a real AI provider key and a real SMTP server, because those are the two paths not yet verified live.

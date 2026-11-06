#!/bin/bash
# Starts FlowForge AI on macOS and Linux. Not tested on macOS yet; see README limitations.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${FLOWFORGE_PORT:-8000}"
VENV="$(python3 scripts/venv_path.py)"
[ -x "$VENV/bin/python" ] || { echo "Run ./setup.command first."; exit 1; }
(cd backend && "$VENV/bin/python" -m alembic upgrade head)
echo "FlowForge AI is running at http://localhost:$PORT (Ctrl+C to stop)"
if [ "${FLOWFORGE_NO_BROWSER:-0}" != "1" ] && command -v open >/dev/null; then open "http://localhost:$PORT"; fi
exec "$VENV/bin/python" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$PORT"

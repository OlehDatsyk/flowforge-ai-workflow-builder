#!/bin/bash
# FlowForge AI setup for macOS and Linux. Not tested on macOS yet; see README limitations.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "Python 3.11+ is required: https://www.python.org/downloads/"; exit 1; }
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" || { echo "FlowForge AI needs Python 3.11 or newer."; exit 1; }
command -v npm >/dev/null || { echo "Node.js 20+ is required: https://nodejs.org/"; exit 1; }

VENV="$(python3 scripts/venv_path.py)"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r backend/requirements.txt
"$VENV/bin/python" scripts/ensure_env.py
(cd frontend && npm install --no-audit --no-fund --loglevel=error && npm run build)
(cd backend && "$VENV/bin/python" -m alembic upgrade head)
echo "Setup complete. Run ./start.command to launch FlowForge AI."

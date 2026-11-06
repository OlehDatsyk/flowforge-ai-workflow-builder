"""Prints where this checkout's Python environment lives.

Normally backend/.venv. Windows cannot load native extensions from very long
paths, so deep checkouts use a short per-project folder under %LOCALAPPDATA%.
FLOWFORGE_VENV overrides both.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LONGEST_INSIDE_VENV = 110  # site-packages\...\_collections_cy.cp312-win_amd64.pyd and friends
WINDOWS_PATH_LIMIT = 250


def venv_path() -> Path:
    override = os.environ.get("FLOWFORGE_VENV")
    if override:
        return Path(override)
    local = ROOT / "backend" / ".venv"
    if os.name == "nt" and len(str(local)) + LONGEST_INSIDE_VENV > WINDOWS_PATH_LIMIT:
        key = hashlib.sha1(str(ROOT).lower().encode()).hexdigest()[:10]
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FlowForgeAI" / f"venv-{key}"
    return local


if __name__ == "__main__":
    print(venv_path())

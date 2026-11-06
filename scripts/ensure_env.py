"""Creates .env from .env.example with a freshly generated encryption key, if it does not exist."""
from __future__ import annotations

import base64
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = ROOT / ".env"
example = ROOT / ".env.example"

if env.exists():
    print(".env already exists; leaving it unchanged.")
else:
    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    text = example.read_text(encoding="utf-8").replace("CREDENTIALS_ENCRYPTION_KEY=", f"CREDENTIALS_ENCRYPTION_KEY={key}", 1)
    env.write_text(text, encoding="utf-8")
    print("Created .env with a new encryption key. Back this key up: credentials cannot be decrypted without it.")

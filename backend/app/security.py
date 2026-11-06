"""Password hashing, opaque tokens, credential encryption, secret masking, rate limiting."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fernet() -> Fernet:
    key = get_settings().credentials_encryption_key
    if not key:
        raise RuntimeError(
            "CREDENTIALS_ENCRYPTION_KEY is not configured. Run setup.bat or scripts/ensure_env.py."
        )
    return Fernet(key.encode())


def encrypt_json(value: Any) -> bytes:
    return _fernet().encrypt(json.dumps(value).encode())


def decrypt_json(blob: bytes) -> Any:
    try:
        return json.loads(_fernet().decrypt(bytes(blob)))
    except InvalidToken as exc:
        raise RuntimeError("Stored secret could not be decrypted; was the encryption key rotated?") from exc


def mask_value(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "••••••••"
    return f"{text[:3]}••••{text[-2:]}"


SENSITIVE_KEY_RE = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[-_ ]?key|authorization|auth[-_ ]?header|cookie|credential|private[-_ ]?key|x-flowforge-signature)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"


def redact(value: Any, secrets_to_hide: set[str] | None = None) -> Any:
    """Deep-copy ``value`` with sensitive keys and known secret strings removed."""
    hide = {s for s in (secrets_to_hide or set()) if s and len(s) >= 4}

    def walk(item: Any) -> Any:
        if isinstance(item, dict):
            out = {}
            for k, v in item.items():
                # Numeric/boolean values (e.g. "output_tokens": 120) are not secrets.
                if isinstance(k, str) and SENSITIVE_KEY_RE.search(k) and not isinstance(v, (bool, int, float)):
                    out[k] = REDACTED if v not in (None, "") else v
                else:
                    out[k] = walk(v)
            return out
        if isinstance(item, (list, tuple)):
            return [walk(v) for v in item]
        if isinstance(item, str) and hide:
            for s in hide:
                if s in item:
                    item = item.replace(s, REDACTED)
            return item
        return item

    return walk(value)


class RateLimiter:
    """In-process sliding window limiter. Sufficient for a single API process;
    swap for a shared store when scaling horizontally (documented in SECURITY.md)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()

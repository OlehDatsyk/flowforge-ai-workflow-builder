"""Sends an HMAC-signed request to a FlowForge webhook. Standard library only.

    python scripts/send_signed_webhook.py <webhook-url> <secret> sample_data/invoice.json
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if len(sys.argv) != 4:
    sys.exit(__doc__)
url, secret, path = sys.argv[1:]
body = Path(path).read_bytes()
stamp = str(int(time.time()))
signature = hmac.new(secret.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
request = urllib.request.Request(
    url,
    data=body,
    method="POST",
    headers={"Content-Type": "application/json", "X-FlowForge-Timestamp": stamp, "X-FlowForge-Signature": f"sha256={signature}"},
)
try:
    with urllib.request.urlopen(request) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.code, exc.read().decode())
    sys.exit(1)

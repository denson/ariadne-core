"""Presigned upload URL signing and verification.

Uploaders never need a per-user credential for /api/upload/signed —
instead they receive a time-limited HMAC-signed URL that they POST to
with no Authorization header. The server-side HMAC secret is
`ARIADNE_UPLOAD_SIGNING_SECRET` (previously `ARIADNE_API_KEY`, renamed
in ariadne--xft.2 to decouple the URL-signing concern from per-user
auth). If the secret is unset the /api/upload/signed route returns
503 rather than failing silently.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
import urllib.parse


def generate_presigned_url(
    base_url: str,
    filename: str,
    secret_key: str,
    expires_in: int = 300,  # 5 minutes
    max_size: int = 50 * 1024 * 1024,  # 50 MB
) -> str:
    """Generate a presigned upload URL."""
    expires_at = int(time.time()) + expires_in
    string_to_sign = f"{filename}\n{expires_at}\n{max_size}"
    signature = hmac.new(
        secret_key.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()

    params = urllib.parse.urlencode({
        "filename": filename,
        "expires": expires_at,
        "max_size": max_size,
        "signature": signature,
    })
    return f"{base_url.rstrip('/')}/api/upload/signed?{params}"


def verify_signature(
    filename: str,
    expires_at: int,
    max_size: int,
    signature: str,
    secret_key: str,
) -> bool:
    """Verify a presigned URL signature and that it has not expired."""
    if time.time() > expires_at:
        return False
    string_to_sign = f"{filename}\n{expires_at}\n{max_size}"
    expected = hmac.new(
        secret_key.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


# ── Single-use tracking ──────────────────────────────────────────────────────
#
# Signatures can only be consumed once. We keep used signatures in memory
# with their expiry time and prune on every check — no background thread,
# no Redis, no persistence. A signature is only valid for 5 minutes anyway,
# so the set stays tiny.

_used_lock = threading.Lock()
_used_signatures: dict[str, int] = {}  # signature -> expires_at


def mark_signature_used(signature: str, expires_at: int) -> bool:
    """Record a signature as consumed.

    Returns True if this is the first use (accept), False if it was
    already used (reject). Also prunes any expired entries.
    """
    now = int(time.time())
    with _used_lock:
        # Prune expired
        stale = [s for s, exp in _used_signatures.items() if exp <= now]
        for s in stale:
            del _used_signatures[s]

        if signature in _used_signatures:
            return False
        _used_signatures[signature] = expires_at
        return True

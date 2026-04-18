# Step 9: Presigned upload URLs — remove API key from agent context

## The problem

When agents upload files via REST, they read the API key from `.mcp.json` and put it in a curl command. The key appears in the chat history, terminal output, and logs. Telling agents "don't display the key" in the skill doesn't work — they do it anyway. This is a security issue.

## The fix

Add an MCP tool that generates a presigned upload URL. The agent never sees the API key.

**Flow:**
1. Agent calls MCP tool `request_upload_url(filename, content_type)` 
2. Server generates a signed URL with HMAC-SHA256, valid for 5 minutes, single-use
3. Agent curls the file to the signed URL — no auth header needed
4. Server validates the signature, stores the file, returns the server path
5. Agent calls `convert_document` with the server path (already goes through MCP, no key needed)

The API key stays server-side the entire time. The agent only ever sees a time-limited URL.

## Implementation

### 9a: Signing utility

**File:** `ariadne-core/src/pipeline/api/signing.py` (new file)

```python
import hashlib
import hmac
import time
import urllib.parse

def generate_presigned_url(
    base_url: str,
    filename: str, 
    secret_key: str,
    expires_in: int = 300,  # 5 minutes
    max_size: int = 50 * 1024 * 1024,  # 50MB
) -> str:
    """Generate a presigned upload URL."""
    expires_at = int(time.time()) + expires_in
    # String to sign: filename + expiry + max_size
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
    return f"{base_url}/api/upload/signed?{params}"


def verify_signature(
    filename: str,
    expires_at: int,
    max_size: int,
    signature: str,
    secret_key: str,
) -> bool:
    """Verify a presigned URL signature."""
    if time.time() > expires_at:
        return False
    string_to_sign = f"{filename}\n{expires_at}\n{max_size}"
    expected = hmac.new(
        secret_key.encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
```

The `secret_key` should be the existing `ARIADNE_API_KEY` — no new secret needed.

### 9b: Signed upload endpoint

**File:** `ariadne-core/src/pipeline/api/routes.py`

Add `POST /api/upload/signed` — accepts multipart file upload with query params (filename, expires, max_size, signature). No `X-API-Key` header required.

Validation:
1. Verify signature against ARIADNE_API_KEY
2. Check expiry hasn't passed
3. Check file size against max_size
4. Check filename matches
5. Single-use: after successful upload, the same signature cannot be reused (track used signatures in a TTL cache or set)

Returns the same response as the existing `/api/upload`: `{"path": "data/uploads/...", "filename": "...", "size_bytes": N}`

### 9c: MCP tool

**File:** `ariadne-core/src/pipeline/mcp_server.py`

Add MCP tool `request_upload_url`:

```
Parameters:
  filename: str (required) — the name of the file being uploaded
  content_type: str | None — MIME type hint (optional)
  
Returns: JSON with:
  upload_url: str — the presigned URL to POST the file to
  expires_in: int — seconds until the URL expires (300)
  method: "POST"
  instructions: "POST the file as multipart form data with field name 'file'. No authentication header needed."
```

The tool reads the server's base URL from the config and the API key from the env to generate the signature. The agent never sees either.

### 9d: Update instructions string

Update the FastMCP instructions to describe the new upload flow:

```
For local files: call request_upload_url to get a time-limited upload URL,
POST the file to that URL (no auth header needed), then call convert_document
with the returned server-side path.
```

### 9e: Track used signatures

Add a simple in-memory set with TTL for used signatures. After a signature is consumed, add it to the set. Reject any signature already in the set. Clean up expired entries periodically (or just let them age out — they're only valid for 5 minutes anyway).

Don't overthink this — a Python set with a 10-minute cleanup is fine. This doesn't need Redis.

## Do not touch

- The existing `/api/upload` endpoint (still works with API key for scripts and automation)
- SPEC.md, skills, docs
- `scripts/setup.py` or `.mcp.json.template` (those are Step 10, a separate task)

## Do not commit

Report when done. Leave for Bob.

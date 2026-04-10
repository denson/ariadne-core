"""Live test against the OpenAI embedding API.

Reads EMBEDDING_API_KEY from .env and calls the API with a single string.
Run with: python tests/test_openai_live.py
"""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

api_key = os.environ.get("EMBEDDING_API_KEY", "")
base_url = os.environ.get("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

print(f"API key: {api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else f"API key: {api_key!r}")
print(f"Base URL: {base_url}")
print(f"Model: {model}")

payload = json.dumps({
    "model": model,
    "input": ["Hello, world."],
}).encode()

req = Request(
    f"{base_url.rstrip('/')}/embeddings",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    },
    method="POST",
)

try:
    with urlopen(req) as resp:
        result = json.loads(resp.read())
    embedding = result["data"][0]["embedding"]
    tokens = result.get("usage", {}).get("total_tokens", "?")
    print(f"\nSuccess!")
    print(f"  Dimensions: {len(embedding)}")
    print(f"  Tokens used: {tokens}")
    print(f"  First 5 values: {embedding[:5]}")
except Exception as e:
    print(f"\nFailed: {e}")

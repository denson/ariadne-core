#!/usr/bin/env python3
"""
Ariadne Core — Setup Script
Handles the entire deployment from a single terminal window.

Author: Denson Smith

Usage:
  python scripts/setup.py              # Interactive guided setup
  python scripts/setup.py --help       # Show defaults and overrides
  python scripts/setup.py --skip-deploy # Configure .env only
"""
import argparse
import json
import os
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from getpass import getpass
from pathlib import Path

# ─────────────────────────────────────────────────────────────────
# Provider configurations
# ─────────────────────────────────────────────────────────────────

PROVIDERS = {
    "google": {
        "name": "Google Gemini",
        "key_url": "https://aistudio.google.com/apikey",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "models_endpoint": "https://generativelanguage.googleapis.com/v1beta/models",
        "docs_url": "https://ai.google.dev/gemini-api/docs/models",
        "default_embedding": "gemini-embedding-001",
        "default_vision": "gemini-3.1-flash-lite-preview",
    },
    "openai": {
        "name": "OpenAI",
        "key_url": "https://platform.openai.com/api-keys",
        "base_url": "https://api.openai.com/v1",
        "models_endpoint": "https://api.openai.com/v1/models",
        "docs_url": "https://developers.openai.com/api/docs/models",
        "default_embedding": "text-embedding-3-small",
        "default_vision": "gpt-4o-mini",
    },
    "together": {
        "name": "Together AI",
        "key_url": "https://api.together.xyz/settings/api-keys",
        "base_url": "https://api.together.xyz/v1",
        "models_endpoint": "https://api.together.xyz/v1/models",
        "docs_url": "https://docs.together.ai/docs/inference-models",
        "default_embedding": "BAAI/bge-large-en-v1.5",
        "default_vision": "Llama-3.2-11B-Vision",
        "vision_options": [
            ("Llama-3.2-11B-Vision", "cheapest, ultra-fast, ~$0.18/M tokens"),
            ("Qwen2.5-VL-7B", "best OCR accuracy, ~$0.18/M tokens"),
        ],
    },
}

# pgvector HNSW indexes support max 2000 dimensions.
# gemini-embedding-001 supports up to 3072 but we cap at 1536
# to stay within pgvector's HNSW limit. Weaviate (Managed edition)
# will support the full 3072.
DIMENSION_OPTIONS = [
    (1536, "highest quality within pgvector limits", "best for research, graph construction, precision search"),
    (768, "compact", "fastest search, lowest storage, good for large corpora 100K+ docs"),
]

DEFAULTS_TABLE = """
Provider defaults:
  Google Gemini (recommended):
    Embedding: gemini-embedding-001
    Vision:    gemini-3.1-flash-lite-preview
    Docs:      https://ai.google.dev/gemini-api/docs/models

  OpenAI:
    Embedding: text-embedding-3-small
    Vision:    gpt-4o-mini
    Docs:      https://developers.openai.com/api/docs/models

  Together AI:
    Embedding: BAAI/bge-large-en-v1.5
    Vision:    Llama-3.2-11B-Vision (cheapest) or Qwen2.5-VL-7B (best OCR)
    Docs:      https://docs.together.ai/docs/inference-models
"""

# Railway GraphQL API
RAILWAY_GQL_ENDPOINT = "https://backboard.railway.com/graphql/v2"
RAILWAY_TEMPLATE_CODE = "ariadne-core"


# ─────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────

def banner(text):
    width = 60
    print()
    print("=" * width)
    for line in text.strip().split("\n"):
        print(f"  {line.strip()}")
    print("=" * width)
    print()


def step_header(num, title):
    width = 60
    print()
    print("=" * width)
    print(f"  Step {num} of 4: {title}")
    print("=" * width)
    print()


def fmt_elapsed(seconds):
    """Format seconds as '45s' or '1m 30s'."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s"


def final_banner(health_ok, url):
    """Print the final setup banner. If the health check failed, surface
    that clearly instead of claiming 'Setup complete!'.
    """
    if health_ok:
        print()
        print("=" * 60)
        print("  Setup complete!")
        print("=" * 60)
        print()
        print("  What to do now:")
        print("    1. Restart Claude Code (close and reopen)")
        print('    2. Type: "what is ariadne core" to start the walkthrough')
        print("       -- or --")
        print('       Type: "search my documents for..." to start using it')
        print()
        if url:
            print(f"  Your server: {url}")
            print()
        return
    print()
    print("=" * 60)
    print("  !! Server deployed but health check did not pass yet.")
    print()
    print("  It may still be starting up -- check again in a few minutes:")
    print(f"    curl {url}/api/health")
    print()
    print("  If it keeps failing, check the Railway dashboard for logs.")
    print("=" * 60)
    print()


def action_needed(msg):
    print(f"  !! ACTION NEEDED: {msg}")
    print()


def success(msg):
    print(f"  OK {msg}")


def mask_key(key):
    """Show first 4 and last 4 chars only."""
    if len(key) <= 12:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def _provider_name_from_base_url(base_url):
    if not base_url:
        return "Custom"
    url = base_url.lower()
    if "generativelanguage.googleapis.com" in url:
        return "Google Gemini"
    if "api.openai.com" in url:
        return "OpenAI"
    if "api.together.xyz" in url:
        return "Together AI"
    return "Custom (OpenAI-compatible)"


def _read_env_dict(env_path):
    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values


def print_env_summary(env_path):
    """Print a human-readable summary of an existing .env — path, provider, masked keys."""
    values = _read_env_dict(env_path)

    emb_base = values.get("ARIADNE_EMBEDDING_BASE_URL", "") or values.get("EMBEDDING_BASE_URL", "")
    provider = _provider_name_from_base_url(emb_base)
    if provider.startswith("Custom") and emb_base:
        provider = emb_base

    emb_key = values.get("ARIADNE_EMBEDDING_API_KEY", "") or values.get("EMBEDDING_API_KEY", "")
    vis_key = values.get("ARIADNE_IMAGE_ENRICHMENT_API_KEY", "") or values.get("VISION_API_KEY", "")
    emb_model = values.get("ARIADNE_EMBEDDING_MODEL", "") or values.get("EMBEDDING_MODEL", "?")
    vis_model = values.get("ARIADNE_IMAGE_ENRICHMENT_MODEL", "") or values.get("VISION_MODEL", "?")
    dimensions = values.get("ARIADNE_EMBEDDING_DIMENSIONS", "?")
    ariadne_key = values.get("ARIADNE_API_KEY", "")

    print()
    print("  Existing configuration found at:")
    print(f"    {env_path}")
    print()
    print(f"    Provider:      {provider}")
    print(f"    Embedding key: {mask_key(emb_key) if emb_key else '(not set)'}")
    print(f"    Embedding:     {emb_model}")
    if vis_key and emb_key and vis_key == emb_key:
        print(f"    Vision key:    {mask_key(vis_key)} (same key)")
    else:
        print(f"    Vision key:    {mask_key(vis_key) if vis_key else '(not set)'}")
    print(f"    Vision:        {vis_model}")
    print(f"    Dimensions:    {dimensions}")
    print(f"    Ariadne key:   {mask_key(ariadne_key) if ariadne_key else '(not set)'}")
    print()


def backup_env(env_path):
    """Copy .env to .env.backup, or .env.backup.N if the first is taken. Returns the backup path."""
    backup_path = env_path.parent / ".env.backup"
    if not backup_path.exists():
        shutil.copy(env_path, backup_path)
        return backup_path
    n = 1
    while True:
        numbered = env_path.parent / f".env.backup.{n}"
        if not numbered.exists():
            shutil.copy(env_path, numbered)
            return numbered
        n += 1


def _keep_or_change(label, current_display):
    print(f"\n  {label}: {current_display}")
    return prompt_choice(["Keep", "Change"], default=1) == 1


def _provider_key_from_base_url(base_url):
    if not base_url:
        return None
    url = base_url.lower()
    if "generativelanguage.googleapis.com" in url:
        return "google"
    if "api.openai.com" in url:
        return "openai"
    if "api.together.xyz" in url:
        return "together"
    return None


def _pick_model_from_list(kind, current, model_list):
    """Offer a numbered picker over model_list with current marked. Returns the chosen model."""
    print(f"\n  {kind} models:")
    display = []
    if current and current not in model_list:
        model_list = [current] + list(model_list)
    for m in model_list[:6]:
        label = f"{m} (current)" if m == current else m
        display.append(label)
    display.append("Enter a model name manually")
    # Default to the current model's slot (always first after the prepend).
    default_idx = 1
    idx = prompt_choice(display, default=default_idx)
    if idx == len(display) - 1:
        entered = input("  Model name: ").strip()
        return entered or current
    return model_list[idx]


def edit_env(env_path, repo_root):
    """Walk through .env values, letting the user keep or change each one.
    Backs up the previous file and rewrites with the chosen values.
    """
    values = _read_env_dict(env_path)

    emb_key = values.get("ARIADNE_EMBEDDING_API_KEY", "") or values.get("EMBEDDING_API_KEY", "")
    vis_key = values.get("ARIADNE_IMAGE_ENRICHMENT_API_KEY", "") or values.get("VISION_API_KEY", "")
    emb_model = values.get("ARIADNE_EMBEDDING_MODEL", "") or values.get("EMBEDDING_MODEL", "")
    vis_model = values.get("ARIADNE_IMAGE_ENRICHMENT_MODEL", "") or values.get("VISION_MODEL", "")
    emb_base = values.get("ARIADNE_EMBEDDING_BASE_URL", "") or values.get("EMBEDDING_BASE_URL", "")
    vis_base = values.get("ARIADNE_IMAGE_ENRICHMENT_BASE_URL", "") or values.get("VISION_BASE_URL", "") or emb_base
    dimensions_raw = values.get("ARIADNE_EMBEDDING_DIMENSIONS", "")
    try:
        dimensions = int(dimensions_raw)
    except (TypeError, ValueError):
        dimensions = None
    ariadne_key = values.get("ARIADNE_API_KEY", "")

    provider_key = _provider_key_from_base_url(emb_base)

    print()
    print("  Edit mode: keep or change each value. Press Enter to keep.\n")

    emb_key_changed = False
    if _keep_or_change("Embedding API key", mask_key(emb_key) if emb_key else "(not set)"):
        while True:
            new_key = getpass("  New API key (won't be displayed): ").strip()
            if new_key:
                emb_key = new_key
                emb_key_changed = True
                success("Updated")
                break
            print("  Key cannot be empty. Try again.")

    if _keep_or_change("Embedding model", emb_model or "(not set)"):
        emb_list = None
        if provider_key == "google":
            emb_list, _ = query_google_models(emb_key)
        elif provider_key == "openai":
            emb_list, _ = query_openai_models(emb_key)
        elif provider_key == "together":
            emb_list, _ = query_together_models(emb_key)
        if emb_list:
            emb_model = _pick_model_from_list("Embedding", emb_model, emb_list)
        else:
            entered = input(f"  Model name [{emb_model}]: ").strip()
            if entered:
                emb_model = entered
        success(f"Embedding: {emb_model}")

    vis_key_same_as_emb_before = (vis_key == emb_key) and bool(vis_key)
    if emb_key_changed and vis_key_same_as_emb_before:
        print()
        print("  You changed the embedding key.")
        options = ["Use same key for vision", "Use a different vision key"]
        if prompt_choice(options, default=1) == 0:
            vis_key = emb_key
            success("Vision key: same as embedding")
        else:
            while True:
                new_key = getpass("  New vision API key (won't be displayed): ").strip()
                if new_key:
                    vis_key = new_key
                    success("Updated")
                    break
                print("  Key cannot be empty. Try again.")
    else:
        vis_display = mask_key(vis_key) + " (same key)" if vis_key == emb_key and vis_key else (mask_key(vis_key) if vis_key else "(not set)")
        if _keep_or_change("Vision API key", vis_display):
            while True:
                new_key = getpass("  New vision API key (won't be displayed): ").strip()
                if new_key:
                    vis_key = new_key
                    success("Updated")
                    break
                print("  Key cannot be empty. Try again.")

    if _keep_or_change("Vision model", vis_model or "(not set)"):
        vis_list = None
        if provider_key == "google":
            _, vis_list = query_google_models(vis_key)
        elif provider_key == "openai":
            _, vis_list = query_openai_models(vis_key)
        elif provider_key == "together":
            _, vis_list = query_together_models(vis_key)
        if vis_list:
            vis_model = _pick_model_from_list("Vision", vis_model, vis_list)
        else:
            entered = input(f"  Model name [{vis_model}]: ").strip()
            if entered:
                vis_model = entered
        success(f"Vision: {vis_model}")

    if _keep_or_change("Embedding dimensions", str(dimensions) if dimensions else "(not set)"):
        print()
        print("  !! Changing dimensions after ingesting documents requires")
        print("     re-embedding your entire corpus.\n")
        dim_choices = [d for d, _, _ in DIMENSION_OPTIONS]
        display = []
        for d, label, desc in DIMENSION_OPTIONS:
            marker = " (current)" if d == dimensions else ""
            display.append(f"{d} ({label}){marker}")
        idx = prompt_choice(display, default=1)
        dimensions = dim_choices[idx]
        success(f"Dimensions: {dimensions}")

    print(f"\n  Client key (ARIADNE_API_KEY): {mask_key(ariadne_key) if ariadne_key else '(not set)'}")
    options = ["Keep existing key", "Regenerate"]
    if prompt_choice(options, default=1) == 1:
        ariadne_key = secrets.token_urlsafe(32)
        success(f"Regenerated: {mask_key(ariadne_key)}")

    if dimensions is None:
        dimensions = DIMENSION_OPTIONS[0][0]

    backup_path = backup_env(env_path)
    print(f"\n  Backed up previous .env to:")
    print(f"    {backup_path}")

    env_content = f"""# .env -- generated by setup.py
# Do NOT commit this file (it's in .gitignore)

# Database (local development only -- for docker compose)
# Railway users: skip this. Railway injects DATABASE_URL automatically.
DB_PASSWORD=local-dev-only

# --- Embedding Provider ---
ARIADNE_EMBEDDING_API_KEY={emb_key}
ARIADNE_EMBEDDING_MODEL={emb_model}
ARIADNE_EMBEDDING_BASE_URL={emb_base}
ARIADNE_EMBEDDING_DIMENSIONS={dimensions}

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY={vis_key}
ARIADNE_IMAGE_ENRICHMENT_MODEL={vis_model}
ARIADNE_IMAGE_ENRICHMENT_BASE_URL={vis_base}

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY={ariadne_key}
"""
    env_path.write_text(env_content)
    success(".env updated")
    print(f"    {env_path}")
    verify_gitignore(repo_root)

    return ariadne_key, read_env_as_vars(env_path)


def prompt_choice(options, default=1):
    """Present numbered options, return the selected index (0-based)."""
    for i, opt in enumerate(options, 1):
        marker = " (default)" if i == default else ""
        print(f"    [{i}] {opt}{marker}")
    print()
    while True:
        raw = input(f"  Choice [{default}]: ").strip()
        if raw == "":
            return default - 1
        try:
            choice = int(raw)
            if 1 <= choice <= len(options):
                return choice - 1
            print(f"  Please enter 1-{len(options)}")
        except ValueError:
            print(f"  Please enter 1-{len(options)}")


# ─────────────────────────────────────────────────────────────────
# Railway GraphQL API helpers
# ─────────────────────────────────────────────────────────────────

def railway_gql(token, query, variables=None, timeout=120):
    """Execute a GraphQL query against Railway's API. Returns parsed JSON or None on error.

    Default timeout is 120s because templateDeployV2 provisions services synchronously
    and routinely takes 60-90s to return.
    """
    body = {"query": query}
    if variables:
        body["variables"] = variables
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        RAILWAY_GQL_ENDPOINT,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ariadne-core-setup/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:200] if e.fp else ""
        print(f"  Railway API error (HTTP {e.code}): {error_body}")
        return None
    except Exception as e:
        print(f"  Railway API error: {e}")
        return None


def railway_verify_token(token):
    """Check that a Railway API token is valid. Returns the user's name or None."""
    body = json.dumps({"query": "query { me { name email } }"}).encode()
    req = urllib.request.Request(
        RAILWAY_GQL_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "ariadne-core-setup/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:300] if e.fp else ""
        print(f"  Token validation failed (HTTP {e.code}): {error_body}")
        return None
    except Exception as e:
        print(f"  Token validation failed: {e}")
        return None

    errors = result.get("errors")
    if errors:
        print(f"  Token error: {errors[0].get('message', 'unknown')}")
        return None
    me = (result.get("data") or {}).get("me")
    if not me:
        print(f"  Token validation: unexpected response (no 'me' field): {json.dumps(result)[:200]}")
        return None
    return me.get("name") or me.get("email") or "authenticated"


# ─────────────────────────────────────────────────────────────────
# Step 1: Choose provider
# ─────────────────────────────────────────────────────────────────

def choose_provider():
    step_header(1, "Configure")
    print("  We need an API key for embedding and vision models.\n")
    print("  Providers:")
    options = [
        "Google Gemini (recommended -- best price/performance)",
        "OpenAI",
        "Together AI (open models, private cloud, fine-tuning)",
        "Other (any OpenAI-compatible provider)",
        "Skip -- I'll edit .env manually",
    ]
    choice = prompt_choice(options, default=1)

    if choice == 4:  # Skip
        return None, None

    if choice == 3:  # Other
        print("\n  Enter your provider details:\n")
        name = input("  Provider name: ").strip()
        base_url = input("  Base URL (OpenAI-compatible): ").strip()
        key_url = input("  Where to get an API key (URL, or press Enter to skip): ").strip()
        emb_model = input("  Embedding model name: ").strip()
        vis_model = input("  Vision model name: ").strip()
        return "other", {
            "name": name,
            "key_url": key_url or None,
            "base_url": base_url,
            "models_endpoint": f"{base_url.rstrip('/')}/models",
            "docs_url": None,
            "default_embedding": emb_model or None,
            "default_vision": vis_model or None,
        }

    provider_key = ["google", "openai", "together"][choice]
    provider_config = PROVIDERS[provider_key]
    return provider_key, provider_config


# ─────────────────────────────────────────────────────────────────
# Step 2: Get API key
# ─────────────────────────────────────────────────────────────────

def get_api_key(provider_config):
    key_url = provider_config.get("key_url")
    print()
    if key_url:
        print(f"  Get a key at: {key_url}\n")
    else:
        print("  Enter your API key for this provider.\n")

    action_needed("Paste your API key below (it won't be displayed)")

    while True:
        key = getpass("  API Key: ").strip()
        if key:
            success(f"Key received: {mask_key(key)}")
            return key
        print("  Key cannot be empty. Try again.\n")


def get_keys(provider_config):
    """Get API keys. Ask if user wants separate keys for embedding and vision."""
    print("\n  Do you want to use different keys for embedding and vision?")
    options = [
        "Same key for both (recommended)",
        "Different keys",
    ]
    choice = prompt_choice(options, default=1)

    if choice == 0:
        key = get_api_key(provider_config)
        return key, key
    else:
        print("\n  --- Embedding key ---")
        emb_key = get_api_key(provider_config)
        print("\n  --- Vision key ---")
        vis_key = get_api_key(provider_config)
        return emb_key, vis_key


# ─────────────────────────────────────────────────────────────────
# Step 3: Discover and choose models
# ─────────────────────────────────────────────────────────────────

def query_google_models(api_key):
    """Query Google's models API. Returns (embedding_list, vision_list) or (None, None)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  Could not query models API: {e}")
        print("  Falling back to hardcoded defaults.\n")
        return None, None

    embedding_models = []
    vision_models = []

    for model in data.get("models", []):
        name = model.get("name", "").replace("models/", "")
        methods = model.get("supportedGenerationMethods", [])
        desc = model.get("description", "")

        if "embedContent" in methods:
            embedding_models.append(name)
        if "generateContent" in methods and (
            "image" in desc.lower()
            or "multimodal" in desc.lower()
            or "flash" in name.lower()
        ):
            vision_models.append(name)

    return embedding_models or None, vision_models or None


def query_openai_models(api_key):
    """Query OpenAI's models API. Returns (embedding_list, vision_list) or (None, None)."""
    url = "https://api.openai.com/v1/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  Could not query models API: {e}")
        print("  Falling back to hardcoded defaults.\n")
        return None, None

    embedding_models = []
    vision_models = []

    for model in data.get("data", []):
        mid = model.get("id", "")
        if "embedding" in mid:
            embedding_models.append(mid)
        if "gpt-5" in mid or "gpt-4o" in mid or "gpt-4-turbo" in mid:
            vision_models.append(mid)

    return embedding_models or None, vision_models or None


def query_together_models(api_key):
    """Query Together's models API. Returns (embedding_list, vision_list) or (None, None)."""
    url = "https://api.together.xyz/v1/models"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  Could not query models API: {e}")
        print("  Falling back to hardcoded defaults.\n")
        return None, None

    embedding_models = []
    vision_models = []

    for model in data.get("data", data.get("models", [])):
        mid = model.get("id", "")
        mtype = model.get("type", "")
        if mtype == "embedding" or "embedding" in mid.lower() or "bge" in mid.lower():
            embedding_models.append(mid)
        if "vision" in mid.lower() or "vl" in mid.lower():
            vision_models.append(mid)

    return embedding_models or None, vision_models or None


def choose_models(provider_key, provider_config, api_key):
    print("\n  Querying available models...\n")

    embedding_models = None
    vision_models = None

    if provider_key == "google":
        embedding_models, vision_models = query_google_models(api_key)
    elif provider_key == "openai":
        embedding_models, vision_models = query_openai_models(api_key)
    elif provider_key == "together":
        embedding_models, vision_models = query_together_models(api_key)

    # --- Embedding model ---
    default_emb = provider_config.get("default_embedding")
    if embedding_models:
        if default_emb and default_emb in embedding_models:
            embedding_models.remove(default_emb)
            embedding_models.insert(0, default_emb)
        print("  Embedding models:")
        display = []
        for m in embedding_models[:6]:
            if m == default_emb:
                label = f"{m} (recommended)"
            elif "preview" in m.lower():
                label = f"{m} (experimental)"
            else:
                label = m
            display.append(label)
        display.append("Enter a model name manually")
        emb_idx = prompt_choice(display, default=1)
        if emb_idx == len(display) - 1:
            emb_model = input("  Model name: ").strip()
        else:
            emb_model = embedding_models[emb_idx]
    else:
        if default_emb:
            print(f"  Using default embedding model: {default_emb}")
            emb_model = default_emb
        else:
            emb_model = input("  Embedding model name: ").strip()

    print()

    # --- Vision model ---
    # Together AI: offer the two curated options with cost comparison
    if provider_key == "together" and "vision_options" in provider_config:
        vis_opts = provider_config["vision_options"]
        print("  Vision models (Together AI serves these):")
        display = [f"{name} -- {desc}" for name, desc in vis_opts]
        display.append("Enter a model name manually")
        vis_idx = prompt_choice(display, default=1)
        if vis_idx == len(display) - 1:
            vis_model = input("  Model name: ").strip()
        else:
            vis_model = vis_opts[vis_idx][0]
    else:
        default_vis = provider_config.get("default_vision")
        if vision_models:
            if default_vis and default_vis in vision_models:
                vision_models.remove(default_vis)
                vision_models.insert(0, default_vis)
            print("  Vision models (for image descriptions):")
            display = []
            for m in vision_models[:6]:
                label = f"{m} (recommended)" if m == default_vis else m
                display.append(label)
            display.append("Enter a model name manually")
            vis_idx = prompt_choice(display, default=1)
            if vis_idx == len(display) - 1:
                vis_model = input("  Model name: ").strip()
            else:
                vis_model = vision_models[vis_idx]
        else:
            if default_vis:
                print(f"  Using default vision model: {default_vis}")
                vis_model = default_vis
            else:
                vis_model = input("  Vision model name: ").strip()

    success(f"Embedding: {emb_model}")
    success(f"Vision: {vis_model}")

    return emb_model, vis_model


def choose_dimensions():
    print("\n  Embedding dimensions:\n")
    print("  Your embedding model supports up to 3072 dimensions, but pgvector's")
    print("  HNSW index is limited to 2000. Higher dimensions will be available")
    print("  when we add Weaviate support (coming in the Managed edition).\n")
    print("  !! Changing dimensions after ingesting documents requires")
    print("     re-embedding your entire corpus.\n")
    print("  For now:")
    options = [f"{d} ({label})" for d, label, _desc in DIMENSION_OPTIONS]
    idx = prompt_choice(options, default=1)
    dim = DIMENSION_OPTIONS[idx][0]
    success(f"Dimensions: {dim}")
    return dim


# ─────────────────────────────────────────────────────────────────
# Step 4: Write .env
# ─────────────────────────────────────────────────────────────────

def verify_gitignore(repo_root):
    """Check that .env is in .gitignore. Warn if not."""
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == ".env" or stripped == "/.env":
                return True
    print("  !! WARNING: .env is NOT in .gitignore!")
    print("  Add '.env' to .gitignore before committing.\n")
    return False


def read_env_value(env_path, key):
    """Read a single value from a .env file. Returns None if not found."""
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip()
    return None


def upsert_env_value(env_path, key, value):
    """Set key=value in .env, replacing an existing value or appending if new."""
    if not env_path.exists():
        with open(env_path, "a") as f:
            f.write(f"{key}={value}\n")
        return
    lines = env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                lines[i] = f"{key}={value}"
                found = True
                break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def remove_env_key(env_path, key):
    """Remove a key from .env if present."""
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines()
    filtered = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _, _ = stripped.partition("=")
            if k.strip() == key:
                continue
        filtered.append(line)
    env_path.write_text("\n".join(filtered) + "\n")


_ENV_VARS_DEFAULT_EXCLUDE = {"DB_PASSWORD", "RAILWAY_API_TOKEN", "RAILWAY_TOKEN", "RAILWAY_DEPLOY_URL"}


def read_env_as_vars(env_path, exclude=None):
    """Read .env into a dict of key=value pairs, skipping comments and excluded keys."""
    skip = _ENV_VARS_DEFAULT_EXCLUDE | (exclude or set())
    env_vars = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip()
            if k and v and k not in skip:
                env_vars[k] = v
    return env_vars


def write_env(
    env_path,
    repo_root,
    emb_key,
    vis_key,
    emb_model,
    vis_model,
    emb_base_url,
    vis_base_url,
    dimensions,
    ariadne_key,
):
    print()
    verify_gitignore(repo_root)

    if env_path.exists():
        print_env_summary(env_path)
        options = ["Keep existing .env", "Overwrite with new values"]
        choice = prompt_choice(options, default=1)
        if choice == 0:
            success(".env kept as-is")
            return

    env_content = f"""# .env -- generated by setup.py
# Do NOT commit this file (it's in .gitignore)

# Database (local development only -- for docker compose)
# Railway users: skip this. Railway injects DATABASE_URL automatically.
DB_PASSWORD=local-dev-only

# --- Embedding Provider ---
ARIADNE_EMBEDDING_API_KEY={emb_key}
ARIADNE_EMBEDDING_MODEL={emb_model}
ARIADNE_EMBEDDING_BASE_URL={emb_base_url}
ARIADNE_EMBEDDING_DIMENSIONS={dimensions}

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY={vis_key}
ARIADNE_IMAGE_ENRICHMENT_MODEL={vis_model}
ARIADNE_IMAGE_ENRICHMENT_BASE_URL={vis_base_url}

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY={ariadne_key}
"""

    env_path.write_text(env_content)

    print()
    success(".env configured")
    print(f"    {env_path}")


# ─────────────────────────────────────────────────────────────────
# Step 5: Deploy to Railway via GraphQL API
# ─────────────────────────────────────────────────────────────────

def _open_browser(url):
    try:
        webbrowser.open(url)
    except Exception:
        pass


def get_railway_token():
    """Walk the user through connecting to Railway in three stages:

    Stage 1 — do you have an account? (existing / new / deploy elsewhere)
    Stage 2 — new users: warn, open signup, wait for account creation
    Stage 3 — everyone: warn, open token page, paste + validate

    Returns the verified token, or None if the user opted to deploy elsewhere.
    The token lives in memory only — never written to disk.
    """
    step_header(2, "Connect to Railway")

    print("  To deploy your server, we need to connect to Railway")
    print("  (a cloud hosting platform).")
    print()
    print("  Do you have a Railway account?\n")
    options = [
        "Yes, I have an account",
        "No, I need to create one",
        "I want to deploy somewhere else",
    ]
    choice = prompt_choice(options, default=1)

    if choice == 2:
        return None

    # --- Stage 2a: new user signup ---
    if choice == 1:
        print()
        print("  We'll open Railway's signup page in your browser.")
        print("  You'll get $20 free credit to try it out.")
        print("  (We earn a small referral commission if you continue past the trial.)")
        print()
        print("  !! IMPORTANT: After you create your account, come back to THIS window.")
        print()
        print('  Look for "PowerShell" or "Terminal" in your taskbar at the bottom')
        print("  of your screen to get back here.")
        print()
        input("  Press Enter to open the signup page...")
        _open_browser("https://railway.com?referralCode=RxMpbX")
        print()
        input("  Press Enter when you have a Railway account...")

    # --- Stage 3: token explanation + creation (existing + new users) ---
    print()
    print("  Now we need a Railway API token. This is a one-time setup step.")
    print()
    print("  What the token allows this script to do:")
    print("    - Create a project in your Railway workspace")
    print("    - Deploy services and a database")
    print("    - Set environment variables and generate a public URL")
    print()
    print("  What the token does NOT allow:")
    print("    - Access your billing or payment information")
    print("    - Modify other projects you have on Railway")
    print("    - Do anything after this script finishes")
    print()
    print("  Safety:")
    print("    - The token stays in memory only -- never written to disk")
    print("    - You can revoke it anytime at railway.com/account/tokens")
    print("    - We recommend deleting it after setup is complete")
    print()
    print("  We're about to open the Railway token page in your browser.")
    print()
    print("  Here's what to do over there:")
    print('    1. Click "Create Token"')
    print('    2. Name it "ariadne-setup"')
    print("    3. Copy the token")
    print("    4. Come back to THIS window and paste it")
    print()
    print('  Look for "PowerShell" or "Terminal" in your taskbar to get back here.')
    print()
    input("  Press Enter to open the token page...")
    token_url = "https://railway.com/account/tokens"
    _open_browser(token_url)
    print()
    print(f"  If the page didn't open, go to: {token_url}")
    print()

    while True:
        action_needed("Paste your Railway API token below (it won't be displayed)")
        token = getpass("  Token: ").strip()
        if not token:
            print("  Token cannot be empty.\n")
            continue
        name = railway_verify_token(token)
        if name:
            success(f"Connected as: {name}")
            return token
        print("  Token not valid. Check that you copied the full token.\n")


def _time_ago(iso_str):
    """Format an ISO 8601 timestamp as a relative time string ("2h ago")."""
    if not iso_str:
        return ""
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ""


def inspect_railway_project(token, project_id):
    """Query Railway for a project's services, latest deployment, domain, health.

    Returns a dict with keys: id, short_id, services, status, deployed_at,
    url, health, stats. Best-effort — fields stay None on failure.
    """
    info = {
        "id": project_id,
        "short_id": project_id[:8],
        "services": [],
        "status": "unknown",
        "deployed_at": None,
        "url": None,
        "health": None,
        "stats": None,
    }
    query = """query($id: String!) {
        project(id: $id) {
            services {
                edges {
                    node {
                        id
                        name
                        deployments(first: 1) {
                            edges { node { status createdAt } }
                        }
                        serviceInstances {
                            edges {
                                node {
                                    domains {
                                        serviceDomains { domain }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }"""
    result = railway_gql(token, query, {"id": project_id})
    project = ((result or {}).get("data") or {}).get("project")
    if not project:
        return info

    latest_status = None
    latest_created = None
    for edge in (project.get("services") or {}).get("edges") or []:
        node = edge.get("node") or {}
        svc_name = node.get("name") or ""
        info["services"].append(svc_name)

        is_app = "pgvector" not in svc_name.lower() and "postgres" not in svc_name.lower()

        deploy_edges = ((node.get("deployments") or {}).get("edges")) or []
        if deploy_edges and is_app:
            dnode = deploy_edges[0].get("node") or {}
            latest_status = (dnode.get("status") or "").lower()
            latest_created = dnode.get("createdAt")

        if is_app and not info["url"]:
            for sie in ((node.get("serviceInstances") or {}).get("edges")) or []:
                sinode = sie.get("node") or {}
                domains = (sinode.get("domains") or {}).get("serviceDomains") or []
                for d in domains:
                    if d.get("domain"):
                        info["url"] = d["domain"]
                        break
                if info["url"]:
                    break

    if latest_status:
        if latest_status in ("success", "deployed"):
            info["status"] = "running"
        elif latest_status in ("building", "deploying", "initializing", "queued", "waiting"):
            info["status"] = "deploying"
        elif latest_status in ("failed", "crashed", "error"):
            info["status"] = "failed"
        elif latest_status == "removed":
            info["status"] = "removed"
        else:
            info["status"] = latest_status
        info["deployed_at"] = latest_created
    elif info["services"]:
        info["status"] = "empty"

    if info["url"] and info["status"] == "running":
        try:
            req = urllib.request.Request(
                f"https://{info['url']}/api/health",
                headers={"User-Agent": "ariadne-core-setup/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                hdata = json.loads(resp.read())
                info["health"] = "healthy" if hdata.get("status") == "healthy" else "unhealthy"
        except Exception:
            info["health"] = "unreachable"

        if info["health"] == "healthy":
            try:
                req = urllib.request.Request(
                    f"https://{info['url']}/api/stats",
                    headers={"User-Agent": "ariadne-core-setup/1.0"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    info["stats"] = json.loads(resp.read())
            except Exception:
                pass

    return info


def deploy_railway(env_path, env_vars):
    """Deploy Ariadne Core to Railway via the GraphQL API.

    Args:
        env_path: Path to .env file (kept for signature compatibility; no longer written to)
        env_vars: dict of environment variables to set on the service

    Returns:
        (url, health_ok) tuple. url is None if the user opted out or deploy failed.
        health_ok is True only if the final /api/health check returned healthy.
    """
    # --- Step 2: Connect to Railway (get token; user may opt out) ---
    token = get_railway_token()
    if token is None:
        # User chose "deploy somewhere else"
        return None, False

    # --- Step 3: Deploy ---
    step_header(3, "Deploy")
    deploy_start = time.time()

    # --- Fetch template (silent unless it fails) ---
    result = railway_gql(
        token,
        "query($code: String!) { template(code: $code) { id serializedConfig } }",
        {"code": RAILWAY_TEMPLATE_CODE},
    )
    if not result or not result.get("data", {}).get("template"):
        errors = (result or {}).get("errors", [])
        msg = errors[0].get("message", "unknown error") if errors else "template not found"
        print(f"  Could not fetch template: {msg}")
        return None, False

    template = result["data"]["template"]
    template_id = template["id"]
    raw_config = template["serializedConfig"]
    serialized_config = json.loads(raw_config) if isinstance(raw_config, str) else raw_config

    # --- Pick a workspace (and grab existing project names for collision check) ---
    ws_result = railway_gql(
        token,
        "{ me { workspaces { id name projects { edges { node { id name } } } } } }",
    )
    workspaces = []
    if ws_result and (ws_result.get("data") or {}).get("me"):
        for ws in ws_result["data"]["me"].get("workspaces") or []:
            if ws.get("id"):
                project_records = []  # list of {"id": ..., "name": ...}
                for edge in ((ws.get("projects") or {}).get("edges") or []):
                    node = edge.get("node") or {}
                    if node.get("name") and node.get("id"):
                        project_records.append({"id": node["id"], "name": node["name"]})
                workspaces.append((ws["id"], ws.get("name") or ws["id"], project_records))

    if len(workspaces) == 0:
        print("  No Railway workspaces found on this account.")
        print("  Create one in the Railway dashboard and try again.")
        return None, False
    if len(workspaces) == 1:
        team_id, team_name, existing_projects = workspaces[0]
    else:
        print("\n  Multiple workspaces found. Pick one:\n")
        display = [name for _, name, _ in workspaces]
        idx = prompt_choice(display, default=1)
        team_id, team_name, existing_projects = workspaces[idx]

    print(f"  Workspace: {team_name}\n")

    # --- Project name (optional), with collision check ---
    # Build a lowercase-name -> [project-ids] map so we can offer to update
    # any of the matching projects instead of creating a duplicate. Multiple
    # projects can share a name (Railway allows it), and the user needs to
    # see *which* one they're about to update.
    existing_by_name = {}
    for p in existing_projects:
        existing_by_name.setdefault(p["name"].lower(), []).append(p["id"])
    update_existing_id = None  # set if the user chooses "Update existing"
    print('  What would you like to name this project? (e.g. "my-ariadne", "ree-research")')
    print("  Press Enter for Railway's default:")
    while True:
        project_name = input("\n  Name: ").strip()
        if not project_name:
            break
        match_ids = existing_by_name.get(project_name.lower())
        if not match_ids:
            break
        print()
        print(f'  A project named "{project_name}" already exists in this workspace.\n')
        print("  Looking up existing project(s)...", end="", flush=True)
        infos = [inspect_railway_project(token, pid) for pid in match_ids]
        print(" OK\n")
        print("  Existing projects with this name:\n")
        for i, info in enumerate(infos, 1):
            status_line = info["status"]
            if info["status"] == "running" and info["deployed_at"]:
                ago = _time_ago(info["deployed_at"])
                if ago:
                    status_line = f"running (last deployed {ago})"
            print(f"  {i}. {project_name} ({info['short_id']})")
            print(f"     Status:   {status_line}")
            if info["url"]:
                print(f"     URL:      {info['url']}")
            if info["services"]:
                print(f"     Services: {', '.join(info['services'])}")
            if info["health"]:
                print(f"     Health:   {info['health']}")
            if info["stats"]:
                docs = (
                    info["stats"].get("documents")
                    or info["stats"].get("total_documents")
                    or info["stats"].get("document_count")
                )
                cols = (
                    info["stats"].get("collections")
                    or info["stats"].get("total_collections")
                    or info["stats"].get("collection_count")
                )
                if docs is not None:
                    line = f"{docs} documents"
                    if cols is not None:
                        line += f" across {cols} collections"
                    print(f"     Docs:     {line}")
            print()

        # Default to the first running+healthy match if any, else the first
        # entry. prompt_choice expects a 1-based default.
        default_pick = 1
        for i, info in enumerate(infos, 1):
            if info["status"] == "running" and info["health"] == "healthy":
                default_pick = i
                break

        options = []
        for i, info in enumerate(infos, 1):
            label = f"Update project {i} ({info['short_id']}"
            if info["status"] != "unknown":
                label += f" — {info['status']}"
            label += ")"
            options.append(label)
        rename_idx = len(options)  # 0-based index of "Use a different name"
        options.append("Use a different name")
        new_idx = len(options)
        options.append(f'Deploy as a new project (creates another "{project_name}")')

        choice = prompt_choice(options, default=default_pick)
        if choice == rename_idx:
            # loop and re-prompt for a name
            continue
        if choice == new_idx:
            break
        update_existing_id = infos[choice]["id"]
        break
    print()

    if update_existing_id:
        print(f'  Reusing existing project "{project_name}"...')
    else:
        print("  Deploying Ariadne Core...")

    # --- Phase 1: Creating project and database (or reusing existing) ---
    phase_start = time.time()
    if update_existing_id:
        # Reusing an existing project — skip templateDeployV2 and rename.
        # The services already exist; the env-var upsert below will trigger
        # Railway to redeploy them.
        project_id = update_existing_id
        workflow_id = None
        print("    Reusing existing project and services... OK")
    else:
        print("    Creating project and database...", end="", flush=True)
        # serializedConfig is a custom GraphQL scalar (SerializedTemplateConfig) —
        # pass the parsed dict, not a json.dumps()'d string, or the project
        # deploys empty with no services.
        result = railway_gql(
            token,
            """mutation deploy($input: TemplateDeployV2Input!) {
                templateDeployV2(input: $input) { projectId workflowId }
            }""",
            {
                "input": {
                    "templateId": template_id,
                    "serializedConfig": serialized_config,
                    "workspaceId": team_id,
                }
            },
        )
        if not result or not (result.get("data") or {}).get("templateDeployV2"):
            print(" failed")
            errors = (result or {}).get("errors", []) or []
            if errors:
                msg = errors[0].get("message", "unknown error")
                if "verif" in msg.lower() or "trial" in msg.lower() or "billing" in msg.lower():
                    print("\n  Railway requires account verification before deploying.")
                    print("  Go to https://railway.com/account to verify, then run this script again.")
                    print("  Your .env is saved -- you won't lose your configuration.")
                else:
                    print(f"\n  Railway error: {msg}")
                    for err in errors[1:]:
                        print(f"    - {err.get('message', 'unknown')}")
            else:
                print("\n  Deploy failed: no data returned from Railway")
            return None, False

        project_id = result["data"]["templateDeployV2"]["projectId"]
        workflow_id = result["data"]["templateDeployV2"].get("workflowId")
        print(f" OK")

        # --- Rename the project if the user gave it a name ---
        # TemplateDeployV2Input doesn't accept a name, so rename after creation.
        if project_name:
            rename_result = railway_gql(
                token,
                """mutation rename($id: String!, $input: ProjectUpdateInput!) {
                    projectUpdate(id: $id, input: $input) { id name }
                }""",
                {"id": project_id, "input": {"name": project_name}},
            )
            renamed = (rename_result or {}).get("data", {}).get("projectUpdate") if rename_result else None
            if renamed and renamed.get("name"):
                print(f"    Project name: {renamed['name']}")
            else:
                errs = (rename_result or {}).get("errors") or []
                msg = errs[0].get("message") if errs else "unknown"
                print(f"    Could not set project name ({msg}) -- using Railway default")

    # --- Phase 2: Configuring services (poll workflowStatus) ---
    phase_start = time.time()
    print("    Configuring services...", end="", flush=True)
    if workflow_id:
        last_status = None
        for _ in range(36):  # 36 x 5s = 3 minutes
            ws_result = railway_gql(
                token,
                "query($id: String!) { workflowStatus(workflowId: $id) { status error } }",
                {"id": workflow_id},
            )
            ws_data = (ws_result or {}).get("data", {}).get("workflowStatus") if ws_result else None
            status = ((ws_data or {}).get("status") or "unknown").upper()
            if status == "COMPLETE":
                print(f" OK  (elapsed: {fmt_elapsed(time.time() - phase_start)})")
                break
            if status == "ERROR":
                err = (ws_data or {}).get("error") or "unknown workflow error"
                print(f" failed\n  Railway workflow error: {err}")
                return None, False
            if status != last_status:
                last_status = status
            time.sleep(5)
        else:
            print(f" timeout after {fmt_elapsed(time.time() - phase_start)}")
            print("  Workflow did not complete within 3 minutes -- continuing anyway.")

    # --- Wait for services + environment IDs to appear ---
    project_query = """query($id: String!) {
        project(id: $id) {
            environments(first: 5) { edges { node { id name } } }
            services(first: 10) { edges { node { id name } } }
        }
    }"""
    env_id = None
    service_id = None
    for _ in range(24):  # 24 x 10s = 4 minutes
        result = railway_gql(token, project_query, {"id": project_id})
        project = (result or {}).get("data", {}).get("project") if result else None
        if project:
            env_edges = (project.get("environments") or {}).get("edges", []) or []
            svc_edges = (project.get("services") or {}).get("edges", []) or []
            env_id = None
            for edge in env_edges:
                if edge["node"]["name"].lower() == "production":
                    env_id = edge["node"]["id"]
                    break
            if not env_id and env_edges:
                env_id = env_edges[0]["node"]["id"]
            service_id = None
            for edge in svc_edges:
                name = edge["node"]["name"].lower()
                if "pgvector" not in name and "postgres" not in name:
                    service_id = edge["node"]["id"]
                    break
            if env_id and service_id:
                break
        time.sleep(10)

    if not env_id or not service_id:
        print("    Services did not appear within 4 minutes.")
        print("    Check the Railway dashboard -- the deploy may still complete.")
        return None, False

    # --- Upsert environment variables (silent on success) ---
    result = railway_gql(
        token,
        """mutation upsertVars($input: VariableCollectionUpsertInput!) {
            variableCollectionUpsert(input: $input)
        }""",
        {
            "input": {
                "projectId": project_id,
                "environmentId": env_id,
                "serviceId": service_id,
                "variables": env_vars,
            }
        },
    )
    if result and result.get("errors"):
        errors = result.get("errors") or []
        msg = errors[0].get("message", "unknown") if errors else "unknown"
        print(f"    Warning: could not set env vars: {msg}")
        print("    You may need to set them manually in the Railway dashboard.")

    # --- Domain: check for existing first, only create if none ---
    domain = None
    result = railway_gql(
        token,
        """query($projectId: String!, $environmentId: String!, $serviceId: String!) {
            domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
                serviceDomains { domain }
            }
        }""",
        {"projectId": project_id, "environmentId": env_id, "serviceId": service_id},
    )
    if result and (result.get("data") or {}).get("domains"):
        svc_domains = result["data"]["domains"].get("serviceDomains", []) or []
        if svc_domains:
            domain = svc_domains[0]["domain"]

    if not domain:
        result = railway_gql(
            token,
            """mutation createDomain($input: ServiceDomainCreateInput!) {
                serviceDomainCreate(input: $input) { domain }
            }""",
            {"input": {"environmentId": env_id, "serviceId": service_id}},
        )
        if result and (result.get("data") or {}).get("serviceDomainCreate"):
            domain = result["data"]["serviceDomainCreate"]["domain"]

    if domain:
        url = f"https://{domain}"
    else:
        print("    Could not generate a public domain automatically.")
        print("    Go to Railway dashboard -> service -> Settings -> Networking -> Generate Domain")
        url = input("    Paste your URL here: ").strip()
        if not url.startswith("https://"):
            url = f"https://{url}"

    # --- Phase 3: Building container / Deploying (watch deployment status) ---
    # Labels include an estimate so the user knows what "normal" looks like.
    # A \r-based ticker updates elapsed time on every poll so the line never
    # looks frozen. Trailing spaces on overwrites clear leftover chars from
    # longer prior strings.
    build_label = "Building container (usually 1-3 min)..."
    deploy_label = "Deploying (usually 15-30s)..."
    pad = " " * 20  # clears any leftover chars when overwriting

    phase_start = time.time()
    current = "building"  # "building" or "deploying"
    print(f"    {build_label} (elapsed: 0s)", end="", flush=True)

    deployment_ok = False
    for _ in range(40):  # 40 x 15s = 10 minutes max for the build+deploy cycle
        time.sleep(15)
        result = railway_gql(
            token,
            """query($input: DeploymentListInput!) {
                deployments(first: 1, input: $input) { edges { node { id status } } }
            }""",
            {"input": {"projectId": project_id, "environmentId": env_id, "serviceId": service_id}},
        )
        status = "unknown"
        if result and ((result.get("data") or {}).get("deployments") or {}).get("edges"):
            status = (result["data"]["deployments"]["edges"][0]["node"].get("status") or "unknown").upper()

        elapsed = fmt_elapsed(time.time() - phase_start)

        if status == "SUCCESS":
            if current == "building":
                # Jumped straight from BUILDING to SUCCESS without seeing DEPLOYING.
                print(f"\r    {build_label} OK  ({elapsed}){pad}")
                print(f"    {deploy_label} OK")
            else:
                print(f"\r    {deploy_label} OK  ({elapsed}){pad}")
            deployment_ok = True
            break

        if status in ("FAILED", "CRASHED"):
            label = build_label if current == "building" else deploy_label
            print(f"\r    {label} {status.lower()}  ({elapsed}){pad}")
            print("    Check the Railway dashboard for error logs.")
            return url, False

        if status == "DEPLOYING" and current == "building":
            print(f"\r    {build_label} OK  ({elapsed}){pad}")
            current = "deploying"
            phase_start = time.time()
            elapsed = fmt_elapsed(time.time() - phase_start)
            # Fall through to the normal ticker below so we only emit one
            # "Deploying..." line per iteration (previously printed twice:
            # once with elapsed=0s here and again in the ticker).

        # Still in the same phase (or just transitioned) -- tick the elapsed-time line.
        label = build_label if current == "building" else deploy_label
        print(f"\r    {label} (elapsed: {elapsed}){pad}", end="", flush=True)

    if not deployment_ok:
        elapsed = fmt_elapsed(time.time() - phase_start)
        label = build_label if current == "building" else deploy_label
        print(f"\r    {label} timeout  ({elapsed}){pad}")
        print("    Deployment did not finish within 10 minutes.")
        return url, False

    # --- Health check ---
    health_label = "Health check (usually 30-60s)..."
    phase_start = time.time()
    health_ok = False
    interval = 15
    iterations = 8  # 8 x 15s = 2 minutes
    print(f"    {health_label} (elapsed: 0s)", end="", flush=True)
    for _ in range(iterations):
        try:
            req = urllib.request.Request(
                f"{url}/api/health",
                headers={"User-Agent": "ariadne-core-setup/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "healthy":
                    health_ok = True
                    break
        except Exception:
            pass
        # Sleep with a per-second ticker so the elapsed counter advances
        # visibly instead of jumping by the full poll interval at once.
        for _ in range(interval):
            time.sleep(1)
            elapsed = fmt_elapsed(time.time() - phase_start)
            print(f"\r    {health_label} (elapsed: {elapsed}){pad}", end="", flush=True)

    elapsed = fmt_elapsed(time.time() - phase_start)
    if health_ok:
        print(f"\r    {health_label} OK  ({elapsed}){pad}")
    else:
        print(f"\r    {health_label} not yet  ({elapsed}){pad}")

    return url, health_ok


# ─────────────────────────────────────────────────────────────────
# Step 6: Output connection command
# ─────────────────────────────────────────────────────────────────

def show_connection(url, ariadne_key):
    # --- Ask for connection name ---
    print()
    print(f"  OK Live at: {url}")
    print()
    print("  Name for this MCP connection:")
    print('  (e.g. "ariadne-ree", "ariadne-cannabis", "ariadne-shared")')
    print('  Press Enter for "ariadne-core":')
    print()
    entry_name = input("  Name: ").strip() or "ariadne-core"
    print()

    # --- Ask for scope ---
    print("  Where should this connection be available?\n")
    scope_options = [
        "All Claude Code sessions (global)",
        "This project only",
    ]
    scope_choice = prompt_choice(scope_options, default=1)

    if scope_choice == 0:
        config_path = Path.home() / ".claude.json"
        scope = "global"
        project_dir = None
    else:
        scope = "project"
        # The script lives at <user-project>/ariadne-core/scripts/setup.py.
        # The user clones the repo into their own project directory, so the
        # MCP config belongs in the parent of the ariadne-core checkout — not
        # in cwd, which is usually inside the repo itself when the script runs.
        script_dir = Path(__file__).resolve().parent
        repo_dir = script_dir.parent
        suggested_dir = repo_dir.parent
        print()
        print("  Where should this MCP connection be available in?")
        print("  (This is where you'll run Claude Code to work with your documents)")
        print()
        print(f"  Suggested: {suggested_dir}")
        print("  (parent of the ariadne-core repo you cloned into)")
        print()
        print("  Press Enter to accept, or type a different path:")
        while True:
            raw = input("  Path: ").strip()
            if not raw:
                project_dir = suggested_dir
                break
            candidate = Path(raw).expanduser()
            if candidate.is_dir():
                project_dir = candidate
                break
            print()
            print(f'  "{candidate}" does not exist.')
            create_opts = [
                "Create it",
                "Enter a different path",
            ]
            create_choice = prompt_choice(create_opts, default=1)
            if create_choice == 0:
                try:
                    candidate.mkdir(parents=True, exist_ok=True)
                    project_dir = candidate
                    break
                except Exception as e:
                    print(f"  Could not create {candidate}: {e}")
                    print()
                    continue
            print()
        config_path = project_dir / ".mcp.json"

    print()
    print(f"    Configuring Claude Code...          ", end="", flush=True)

    # Read existing config (or start empty)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(" failed")
            print(f"    Could not parse {config_path}: {e}")
            print("    Fix the file manually, then re-run this script.")
            return
    else:
        config = {}

    mcp_servers = config.setdefault("mcpServers", {})

    # If an existing entry by the same name is there, ask whether to update.
    if entry_name in mcp_servers:
        print(" existing entry found")
        step_header(4, "Done")
        print(f'  MCP server "{entry_name}" already configured in Claude Code.\n')
        options = [
            "Update with new URL and key",
            "Keep existing configuration",
        ]
        choice = prompt_choice(options, default=1)
        if choice == 1:
            print("  Keeping existing configuration.")
            print("  Restart Claude Code if you haven't already.\n")
            return
    else:
        print("OK")
        step_header(4, "Done")

    mcp_servers[entry_name] = {
        "type": "http",
        "url": f"{url}/mcp",
        "headersHelper": "python ariadne-core/scripts/mcp_auth.py",
    }

    # One-time backup of the original config before our first modification
    backup_path = config_path.with_suffix(".json.bak")
    if config_path.exists() and not backup_path.exists():
        try:
            shutil.copy(config_path, backup_path)
        except Exception as e:
            print(f"  Warning: could not back up {config_path}: {e}")

    # Atomic write: write to temp, then rename into place
    try:
        tmp_path = config_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        tmp_path.replace(config_path)
    except Exception as e:
        print(f"  Warning: could not write {config_path}: {e}")
        print("  Configure Claude Code manually with the URL and key above.")
        return

    if scope == "project":
        print(f'  OK Claude Code configured for THIS project.')
        print(f'     Connection "{entry_name}" will only appear when working in:')
        print(f"       {project_dir}")
    else:
        print(f"  OK Claude Code configured globally.")
        print(f'     Connection "{entry_name}" will appear in all Claude Code sessions.')
    print(f"     (MCP config written to {config_path})")
    print()


def show_connection_template():
    """Show connection command with placeholder URL (for non-Railway deploys)."""
    step_header(4, "Done")

    print("  After deploying, run this command (replace YOUR-URL and YOUR-API-KEY):\n")
    print("  claude mcp add ariadne-core \\")
    print("    https://YOUR-URL/mcp \\")
    print("    --transport http --scope user \\")
    print('    --header "X-API-Key:YOUR-API-KEY"')
    print()
    print("  Your ARIADNE_API_KEY is in your .env file.")
    print()
    print("  Then restart Claude Code.\n")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Ariadne Core setup -- deploy and configure in one step.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=DEFAULTS_TABLE
        + """
Examples:
  python scripts/setup.py                              # Interactive guided setup
  python scripts/setup.py --embedding-model X          # Override embedding model
  python scripts/setup.py --vision-model Y             # Override vision model
  python scripts/setup.py --dimensions 1536            # Override embedding dimensions
  python scripts/setup.py --skip-deploy                # Configure .env only
""",
    )
    parser.add_argument(
        "--embedding-model", help="Override default embedding model name"
    )
    parser.add_argument("--vision-model", help="Override default vision model name")
    parser.add_argument(
        "--dimensions",
        type=int,
        choices=[768, 1536],
        help="Embedding dimensions",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Only configure .env, skip Railway deploy",
    )
    return parser.parse_args()


def main():
    # Terminal detection -- must run in a real terminal
    if not sys.stdin.isatty():
        print("This script must be run in a real terminal, not from Claude Code.")
        print("Open PowerShell or Terminal and run:")
        print("  python scripts/setup.py")
        sys.exit(1)

    args = parse_args()

    banner(
        """
ARIADNE CORE -- Setup
Document extraction + vector search for AI agents
    """
    )

    # setup.py lives at <project>/ariadne-core/scripts/setup.py.
    # .env belongs in the project root alongside .mcp.json so the
    # headersHelper script (scripts/mcp_auth.py) can find it when Claude
    # Code is started from the project root.
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    project_root = repo_root.parent
    env_path = project_root / ".env"
    env_example = repo_root / ".env.example"

    if not env_example.exists():
        print("  Error: .env.example not found. Are you running from the ariadne-core repo?")
        print(f"  Expected at: {env_example}")
        sys.exit(1)

    # --- Early .env check: offer use / edit / start fresh ---
    if env_path.exists() and (read_env_value(env_path, "ARIADNE_EMBEDDING_API_KEY") or read_env_value(env_path, "EMBEDDING_API_KEY")):
        print_env_summary(env_path)
        options = [
            "Use this and deploy",
            "Edit specific values",
            "Start fresh (backs up current .env)",
        ]
        choice = prompt_choice(options, default=1)

        if choice == 0 or choice == 1:
            if choice == 1:
                ariadne_key, env_vars = edit_env(env_path, repo_root)
            else:
                ariadne_key = read_env_value(env_path, "ARIADNE_API_KEY") or secrets.token_urlsafe(32)
                env_vars = read_env_as_vars(env_path)

            if args.skip_deploy:
                banner("""
.env already configured! To deploy, run:
  python scripts/setup.py
(without --skip-deploy)
                """)
                return

            url, health_ok = deploy_railway(env_path, env_vars)
            if url:
                show_connection(url, ariadne_key)
                final_banner(health_ok, url)
            else:
                show_connection_template()
            return

        # choice == 2: Start fresh — back up then fall through to Step 1
        backup_path = backup_env(env_path)
        print(f"\n  Backed up existing .env to:")
        print(f"    {backup_path}")
        print("\n  Starting fresh configuration...")
        env_path.unlink()

    # Step 1: Choose provider
    provider_key, provider_config = choose_provider()

    if provider_config is None:
        # User chose to skip provider setup
        print("\n  Skipping provider setup. Edit .env manually.\n")
        if not env_path.exists():
            shutil.copy(env_example, env_path)
            print(f"  Copied .env.example to .env -- edit it with your values.\n")

        if not args.skip_deploy:
            ariadne_key = read_env_value(env_path, "ARIADNE_API_KEY") or secrets.token_urlsafe(32)
            env_vars = read_env_as_vars(env_path)
            url, health_ok = deploy_railway(env_path, env_vars)
            if url:
                show_connection(url, ariadne_key)
                final_banner(health_ok, url)
            else:
                show_connection_template()
        return

    # Step 2: Get API key(s)
    emb_key, vis_key = get_keys(provider_config)

    # Step 3: Choose models (command-line overrides skip interactive selection)
    if args.embedding_model and args.vision_model:
        emb_model = args.embedding_model
        vis_model = args.vision_model
        print(f"\n  Using override models: embedding={emb_model}, vision={vis_model}\n")
    else:
        emb_model, vis_model = choose_models(provider_key, provider_config, emb_key)
        if args.embedding_model:
            emb_model = args.embedding_model
        if args.vision_model:
            vis_model = args.vision_model

    if args.dimensions:
        dimensions = args.dimensions
        print(f"\n  Using override dimensions: {dimensions}\n")
    else:
        dimensions = choose_dimensions()

    # Generate ARIADNE_API_KEY
    ariadne_key = secrets.token_urlsafe(32)

    # Determine base URLs
    emb_base_url = provider_config["base_url"]
    vis_base_url = provider_config["base_url"]

    # Step 4: Write .env
    write_env(
        env_path,
        repo_root,
        emb_key=emb_key,
        vis_key=vis_key,
        emb_model=emb_model,
        vis_model=vis_model,
        emb_base_url=emb_base_url,
        vis_base_url=vis_base_url,
        dimensions=dimensions,
        ariadne_key=ariadne_key,
    )

    if args.skip_deploy:
        banner(
            """
.env configured! To deploy later, run:
  python scripts/setup.py
(without --skip-deploy)
        """
        )
        return

    # Build env vars dict for Railway
    env_vars = {
        "ARIADNE_EMBEDDING_API_KEY": emb_key,
        "ARIADNE_EMBEDDING_MODEL": emb_model,
        "ARIADNE_EMBEDDING_BASE_URL": emb_base_url,
        "ARIADNE_EMBEDDING_DIMENSIONS": str(dimensions),
        "ARIADNE_IMAGE_ENRICHMENT_API_KEY": vis_key,
        "ARIADNE_IMAGE_ENRICHMENT_MODEL": vis_model,
        "ARIADNE_IMAGE_ENRICHMENT_BASE_URL": vis_base_url,
        "ARIADNE_API_KEY": ariadne_key,
    }

    # Steps 2-3: Deploy (includes Connect)
    url, health_ok = deploy_railway(env_path, env_vars)
    if not url:
        # User chose non-Railway deploy or deploy failed
        show_connection_template()
        return

    # Step 4: Connection info
    show_connection(url, ariadne_key)

    final_banner(health_ok, url)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Setup interrupted. Your .env is saved -- run again to continue.\n")
        sys.exit(1)

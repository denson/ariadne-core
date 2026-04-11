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
        "default_embedding": "gemini-embedding-2-preview",
        "default_vision": "gemini-3.1-flash-lite-preview",
    },
    "openai": {
        "name": "OpenAI",
        "key_url": "https://platform.openai.com/api-keys",
        "base_url": "https://api.openai.com/v1",
        "models_endpoint": "https://api.openai.com/v1/models",
        "docs_url": "https://developers.openai.com/api/docs/models",
        "default_embedding": "text-embedding-3-small",
        "default_vision": "gpt-5.4-nano",
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

DIMENSION_OPTIONS = [
    (3072, "highest quality", "best for research, graph construction, precision search"),
    (1536, "balanced", "good quality, moderate storage"),
    (768, "compact", "fastest search, lowest storage, good for large corpora 100K+ docs"),
]

DEFAULTS_TABLE = """
Provider defaults:
  Google Gemini (recommended):
    Embedding: gemini-embedding-2-preview
    Vision:    gemini-3.1-flash-lite-preview
    Docs:      https://ai.google.dev/gemini-api/docs/models

  OpenAI:
    Embedding: text-embedding-3-small
    Vision:    gpt-5.4-nano
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


def step_header(num, total, title):
    width = 60
    print()
    print("=" * width)
    print(f"  Step {num} of {total}: {title}")
    print("=" * width)
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

def railway_gql(token, query, variables=None):
    """Execute a GraphQL query against Railway's API. Returns parsed JSON or None on error."""
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
        with urllib.request.urlopen(req, timeout=30) as resp:
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
    step_header(1, 6, "Choose your AI provider")
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
    step_header(2, 6, "Get your API key")

    key_url = provider_config.get("key_url")
    if key_url:
        print(f"  Go to: {key_url}")
        print("  Create a key (or use an existing one).\n")
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
    step_header(3, 6, "Choose models")

    print("  Querying available models...\n")

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
            label = f"{m} (recommended)" if m == default_emb else m
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
    options = [f"{d} ({label} -- {desc})" for d, label, desc in DIMENSION_OPTIONS]
    print("  Higher dimensions = more semantic nuance, more storage per document.")
    print("  Most users should pick 3072 unless storage cost is a concern.\n")
    print("  !! Changing dimensions after ingesting documents requires")
    print("     re-embedding your entire corpus.\n")
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
    step_header(4, 6, "Configure .env")

    verify_gitignore(repo_root)

    if env_path.exists():
        print(f"  .env already exists at {env_path}\n")
        print("  Current values (keys masked):")
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if "KEY" in key.upper() or "PASSWORD" in key.upper() or "TOKEN" in key.upper():
                    print(f"    {key} = {mask_key(val)}")
                else:
                    print(f"    {key} = {val}")
        print()
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
EMBEDDING_API_KEY={emb_key}
EMBEDDING_MODEL={emb_model}
EMBEDDING_BASE_URL={emb_base_url}
ARIADNE_EMBEDDING_DIMENSIONS={dimensions}

# --- Vision Provider (for image descriptions in documents) ---
VISION_API_KEY={vis_key}
VISION_MODEL={vis_model}
VISION_BASE_URL={vis_base_url}

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY={ariadne_key}
"""

    env_path.write_text(env_content)

    print("  .env written:\n")
    print(f"    EMBEDDING_API_KEY    = {mask_key(emb_key)}")
    print(f"    EMBEDDING_MODEL      = {emb_model}")
    print(f"    EMBEDDING_BASE_URL   = {emb_base_url}")
    print(f"    EMBEDDING_DIMENSIONS = {dimensions}")
    print(f"    VISION_API_KEY       = {mask_key(vis_key)}")
    print(f"    VISION_MODEL         = {vis_model}")
    print(f"    VISION_BASE_URL      = {vis_base_url}")
    print(f"    ARIADNE_API_KEY      = {mask_key(ariadne_key)}")
    print()
    success(".env configured")


# ─────────────────────────────────────────────────────────────────
# Step 5: Deploy to Railway via GraphQL API
# ─────────────────────────────────────────────────────────────────

def get_railway_token(env_path):
    """Get Railway API token — check .env first, otherwise prompt."""
    existing = read_env_value(env_path, "RAILWAY_API_TOKEN")
    from_old_key = False
    if not existing:
        existing = read_env_value(env_path, "RAILWAY_TOKEN")
        from_old_key = bool(existing)
    if existing:
        print("  Found Railway API token in .env.\n")
        options = [
            "Use saved token",
            "Enter a new token",
        ]
        choice = prompt_choice(options, default=1)
        if choice == 0:
            name = railway_verify_token(existing)
            if name:
                success(f"Authenticated as: {name}")
                # Migrate old key name to new one
                if from_old_key:
                    upsert_env_value(env_path, "RAILWAY_API_TOKEN", existing)
                    remove_env_key(env_path, "RAILWAY_TOKEN")
                return existing
            else:
                print("  Saved token is invalid or expired.\n")

    print("  We need an API token so the script can deploy for you.\n")
    print("  Copy this URL and paste it into your browser:\n")
    print("    https://railway.com/account/tokens\n")
    print("  Click \"Create Token\", give it a name (e.g. \"ariadne-setup\"),")
    print("  and copy the token.\n")

    while True:
        action_needed("Paste your Railway API token below (it won't be displayed)")
        token = getpass("  Token: ").strip()
        if not token:
            print("  Token cannot be empty.\n")
            continue
        name = railway_verify_token(token)
        if name:
            success(f"Authenticated as: {name}")
            return token
        print("  Token not valid. Check that you copied the full token.\n")


def deploy_railway(env_path, env_vars):
    """Deploy Ariadne Core to Railway via the GraphQL API.

    Args:
        env_path: Path to .env file
        env_vars: dict of environment variables to set on the service

    Returns:
        (url, token) tuple on success, (None, None) on failure
    """
    step_header(5, 6, "Deploy to Railway")

    # --- Choose deployment target ---
    print("  We recommend Railway for hosting (simple, ~$5/mo).\n")
    options = [
        "Deploy to Railway (recommended)",
        "I'll deploy somewhere else -- just give me the .env",
    ]
    choice = prompt_choice(options, default=1)
    if choice == 1:
        return None, None

    # --- Railway account ---
    print()
    print("  Do you have a Railway account?\n")
    options = [
        "Yes",
        "No -- create one",
    ]
    choice = prompt_choice(options, default=1)
    if choice == 1:
        print()
        print("  Copy this URL and paste it into your browser to sign up:\n")
        print("    https://railway.com?referralCode=RxMpbX\n")
        print("  You'll get $20 in free credits to try it out. No commitment --")
        print("  cancel anytime. (We get a small referral commission if you stay.)\n")
        input("  Press Enter when you've created your account.")
        print()

    # --- Get token ---
    token = get_railway_token(env_path)

    # --- Fetch template ---
    print("\n  Fetching template configuration...")
    result = railway_gql(
        token,
        "query($code: String!) { template(code: $code) { id serializedConfig } }",
        {"code": RAILWAY_TEMPLATE_CODE},
    )
    if not result or not result.get("data", {}).get("template"):
        errors = (result or {}).get("errors", [])
        msg = errors[0].get("message", "unknown error") if errors else "template not found"
        print(f"  Could not fetch template: {msg}")
        print("  Try deploying manually from the Railway dashboard.")
        return None, None

    template = result["data"]["template"]
    template_id = template["id"]
    # serializedConfig is a JSON-encoded string from the API — parse it
    raw_config = template["serializedConfig"]
    if isinstance(raw_config, str):
        serialized_config = json.loads(raw_config)
    else:
        serialized_config = raw_config  # already parsed (some GraphQL clients do this)
    success("Template fetched")

    # --- Inject environment variables into serializedConfig ---
    # The template's serializedConfig has a 'services' dict. Find the main
    # service (not pgvector) and override its variable defaultValues.
    main_service_id = None
    for svc_id, svc in serialized_config.get("services", {}).items():
        if svc.get("name", "").lower() != "pgvector":
            main_service_id = svc_id
            break

    if main_service_id and "variables" in serialized_config["services"][main_service_id]:
        svc_vars = serialized_config["services"][main_service_id]["variables"]
        for var_name, var_value in env_vars.items():
            if var_name in svc_vars and isinstance(svc_vars[var_name], dict):
                svc_vars[var_name]["defaultValue"] = var_value
            elif var_name in svc_vars:
                svc_vars[var_name] = var_value

    # --- Deploy via templateDeployV2 ---
    print("\n  Deploying (this takes 2-3 minutes)...")
    result = railway_gql(
        token,
        """mutation deploy($input: TemplateDeployV2Input!) {
            templateDeployV2(input: $input) {
                projectId
                workflowId
            }
        }""",
        {
            "input": {
                "templateId": template_id,
                "serializedConfig": json.dumps(serialized_config),
            }
        },
    )
    if not result or not result.get("data", {}).get("templateDeployV2"):
        errors = (result or {}).get("errors", [])
        msg = errors[0].get("message", "unknown error") if errors else "deploy failed"
        print(f"  Deploy failed: {msg}")
        return None, None

    deploy_result = result["data"]["templateDeployV2"]
    project_id = deploy_result["projectId"]
    success(f"Deploy started (project: {project_id[:12]}...)")

    # --- Get environment and service IDs ---
    print("\n  Waiting for project to initialize...")
    time.sleep(5)

    result = railway_gql(
        token,
        """query($id: String!) {
            project(id: $id) {
                environments(first: 5) { edges { node { id name } } }
                services(first: 10) { edges { node { id name } } }
            }
        }""",
        {"id": project_id},
    )
    if not result or not result.get("data", {}).get("project"):
        print("  Could not query project details. Check the Railway dashboard.")
        return None, None

    project = result["data"]["project"]

    # Find the production environment
    env_id = None
    for edge in project.get("environments", {}).get("edges", []):
        env = edge["node"]
        if env["name"].lower() == "production":
            env_id = env["id"]
            break
    if not env_id:
        # Fall back to first environment
        edges = project.get("environments", {}).get("edges", [])
        if edges:
            env_id = edges[0]["node"]["id"]

    # Find the main service (not pgvector)
    service_id = None
    for edge in project.get("services", {}).get("edges", []):
        svc = edge["node"]
        if "pgvector" not in svc["name"].lower() and "postgres" not in svc["name"].lower():
            service_id = svc["id"]
            break

    if not env_id or not service_id:
        print(f"  Could not find environment or service (env={env_id}, svc={service_id}).")
        print("  Check the Railway dashboard.")
        return None, None

    # --- Upsert environment variables (overwrite template defaults with real values) ---
    print("\n  Setting environment variables...")
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
    if result and not result.get("errors"):
        success(f"Set {len(env_vars)} variables")
    else:
        errors = (result or {}).get("errors", [])
        msg = errors[0].get("message", "unknown") if errors else "unknown"
        print(f"  Warning: Could not set variables: {msg}")
        print("  You may need to set them manually in the Railway dashboard.")

    # --- Generate public domain ---
    print("\n  Generating public URL...")
    result = railway_gql(
        token,
        """mutation createDomain($input: ServiceDomainCreateInput!) {
            serviceDomainCreate(input: $input) { domain }
        }""",
        {
            "input": {
                "environmentId": env_id,
                "serviceId": service_id,
            }
        },
    )
    domain = None
    if result and result.get("data", {}).get("serviceDomainCreate"):
        domain = result["data"]["serviceDomainCreate"]["domain"]
    else:
        # Domain may already exist — query for it
        result = railway_gql(
            token,
            """query($projectId: String!, $environmentId: String!, $serviceId: String!) {
                domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
                    serviceDomains { domain }
                }
            }""",
            {
                "projectId": project_id,
                "environmentId": env_id,
                "serviceId": service_id,
            },
        )
        if result and result.get("data", {}).get("domains"):
            svc_domains = result["data"]["domains"].get("serviceDomains", [])
            if svc_domains:
                domain = svc_domains[0]["domain"]

    if domain:
        url = f"https://{domain}"
        success(f"URL: {url}")
    else:
        print("  Could not generate domain automatically.")
        print("  Go to Railway dashboard -> service -> Settings -> Networking -> Generate Domain")
        url = input("  Paste your URL here: ").strip()
        if not url.startswith("https://"):
            url = f"https://{url}"

    # --- Poll for deployment to be healthy ---
    print("\n  Waiting for deployment to be healthy...")
    for attempt in range(12):
        # Check deployment status via API
        result = railway_gql(
            token,
            """query($input: DeploymentListInput!) {
                deployments(first: 1, input: $input) {
                    edges { node { id status } }
                }
            }""",
            {
                "input": {
                    "projectId": project_id,
                    "environmentId": env_id,
                    "serviceId": service_id,
                }
            },
        )
        status = "unknown"
        if result and result.get("data", {}).get("deployments", {}).get("edges"):
            node = result["data"]["deployments"]["edges"][0]["node"]
            status = node.get("status", "unknown")

        if status == "SUCCESS":
            # Verify with health check
            try:
                req = urllib.request.Request(
                    f"{url}/api/health",
                    headers={"User-Agent": "ariadne-core-setup/1.0"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read())
                    if data.get("status") == "healthy":
                        success("Health check passed!")
                        # Save token and URL to .env
                        upsert_env_value(env_path, "RAILWAY_API_TOKEN", token)
                        upsert_env_value(env_path, "RAILWAY_DEPLOY_URL", url)
                        return url, token
            except Exception as e:
                if attempt == 11:  # last attempt
                    print(f"  Health check error: {e}")
            # Deployed but not healthy yet — keep trying
            print(f"    Attempt {attempt + 1}/12 -- deployed, waiting for health check...")
        elif status == "FAILED" or status == "CRASHED":
            print(f"  Deployment {status.lower()}.")
            print("  Check the Railway dashboard for error logs.")
            # Still save what we have
            upsert_env_value(env_path, "RAILWAY_API_TOKEN", token)
            return url, token
        else:
            status_label = status.lower().replace("_", " ")
            print(f"    Attempt {attempt + 1}/12 -- {status_label}...")

        time.sleep(15)

    print("  Health check did not pass after 3 minutes.")
    print("  The deployment may still be starting. Check the Railway dashboard.")
    # Save token and URL even if health check failed
    upsert_env_value(env_path, "RAILWAY_API_TOKEN", token)
    upsert_env_value(env_path, "RAILWAY_DEPLOY_URL", url)
    return url, token


# ─────────────────────────────────────────────────────────────────
# Step 6: Output connection command
# ─────────────────────────────────────────────────────────────────

def show_connection(url, ariadne_key):
    step_header(6, 6, "Connect Claude Code")

    print("  Your ARIADNE_API_KEY was auto-generated. It's in your .env file:")
    print(f"    ARIADNE_API_KEY = {mask_key(ariadne_key)}\n")

    print("  Run this command in Claude Code or a terminal:\n")
    print(f"  claude mcp add ariadne-core \\")
    print(f"    {url}/mcp \\")
    print(f"    --transport http --scope user \\")
    print(f'    --header "X-API-Key:{ariadne_key}"')
    print()
    print(f"  Your ARIADNE_API_KEY: {ariadne_key}")
    print("  (also saved in .env and set on Railway)")
    print()
    print("  Then restart Claude Code.\n")


def show_connection_template(ariadne_key):
    """Show connection command with placeholder URL (for non-Railway deploys)."""
    step_header(6, 6, "Connect Claude Code")

    print("  After deploying, run this command (replace YOUR-URL):\n")
    print("  claude mcp add ariadne-core \\")
    print("    https://YOUR-URL/mcp \\")
    print("    --transport http --scope user \\")
    print(f'    --header "X-API-Key:{ariadne_key}"')
    print()
    print(f"  Your ARIADNE_API_KEY: {ariadne_key}")
    print("  (saved in .env)")
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
        choices=[768, 1536, 3072],
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

    # Determine repo root
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    env_path = repo_root / ".env"
    env_example = repo_root / ".env.example"

    if not env_example.exists():
        print("  Error: .env.example not found. Are you running from the ariadne-core repo?")
        print(f"  Expected at: {env_example}")
        sys.exit(1)

    # --- Early .env check: skip Steps 1-4 if already configured ---
    if env_path.exists() and read_env_value(env_path, "EMBEDDING_API_KEY"):
        print("  Existing .env found:\n")
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if not key or not val:
                    continue
                if "KEY" in key.upper() or "PASSWORD" in key.upper() or "TOKEN" in key.upper():
                    print(f"    {key:<24} = {mask_key(val)}")
                else:
                    print(f"    {key:<24} = {val}")
        print("    (keys masked)\n")
        options = [
            "Use this configuration -- skip to deploy",
            "Reconfigure from scratch",
        ]
        choice = prompt_choice(options, default=1)
        if choice == 0:
            # Skip Steps 1-4, jump to deploy
            ariadne_key = read_env_value(env_path, "ARIADNE_API_KEY") or secrets.token_urlsafe(32)
            env_vars = read_env_as_vars(env_path)

            if args.skip_deploy:
                banner("""
.env already configured! To deploy, run:
  python scripts/setup.py
(without --skip-deploy)
                """)
                return

            url, _ = deploy_railway(env_path, env_vars)
            if url:
                show_connection(url, ariadne_key)
                banner("Setup complete!")
            else:
                show_connection_template(ariadne_key)
            return

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
            url, _ = deploy_railway(env_path, env_vars)
            if url:
                show_connection(url, ariadne_key)
                banner("Setup complete!")
            else:
                show_connection_template(ariadne_key)
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
        "EMBEDDING_API_KEY": emb_key,
        "EMBEDDING_MODEL": emb_model,
        "EMBEDDING_BASE_URL": emb_base_url,
        "ARIADNE_EMBEDDING_DIMENSIONS": str(dimensions),
        "VISION_API_KEY": vis_key,
        "VISION_MODEL": vis_model,
        "VISION_BASE_URL": vis_base_url,
        "ARIADNE_API_KEY": ariadne_key,
    }

    # Step 5: Deploy
    url, _ = deploy_railway(env_path, env_vars)
    if not url:
        # User chose non-Railway deploy or deploy failed
        show_connection_template(ariadne_key)
        return

    # Step 6: Connection info
    show_connection(url, ariadne_key)

    banner("Setup complete!")


if __name__ == "__main__":
    main()

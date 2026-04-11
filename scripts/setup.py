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
import subprocess
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


# ─────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────

RAILWAY_INSTALL_MSG = """\
  Railway CLI not found. Install it:
    Windows:  npm install -g @railway/cli
    Mac:      brew install railway
    Linux:    npm install -g @railway/cli

  Then run this script again. Your .env is saved -- you won't lose your configuration."""

# Resolved path to the railway binary — set by find_railway_cli()
_railway_bin = None


def find_railway_cli():
    """Find the Railway CLI binary. Checks PATH, then common install locations."""
    global _railway_bin

    # Already resolved in a previous call
    if _railway_bin is not None:
        return _railway_bin

    # 1. Check PATH via shutil.which
    found = shutil.which("railway")
    if found:
        _railway_bin = found
        return _railway_bin

    # 2. Probe common npm install locations not always on PATH
    candidates = []
    if sys.platform == "win32":
        candidates.append(os.path.expanduser("~/AppData/Roaming/npm/railway.cmd"))
    else:
        candidates.extend([
            "/usr/local/bin/railway",
            os.path.expanduser("~/.npm-global/bin/railway"),
        ])

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            _railway_bin = path
            print(f"  Found Railway CLI at {path} (not on PATH)")
            return _railway_bin

    # Not found anywhere
    _railway_bin = ""  # empty string = not found, avoids re-probing
    return ""


def offer_railway_install():
    """If Railway CLI isn't found, offer to install it. Returns True if installed."""
    npm_bin = shutil.which("npm")
    if not npm_bin:
        print(RAILWAY_INSTALL_MSG)
        print()
        print("  npm is also not installed. Get Node.js + npm from:")
        print("    https://nodejs.org")
        return False

    print("  Railway CLI not found, but npm is available.\n")
    options = [
        "Install Railway CLI now (npm install -g @railway/cli)",
        "Skip -- I'll install it myself",
    ]
    choice = prompt_choice(options, default=1)

    if choice == 1:
        print("\n  Skipped. Install Railway CLI and run this script again.")
        print("  Your .env is saved -- you won't lose your configuration.")
        return False

    print("\n  Installing Railway CLI...")
    try:
        result = subprocess.run(
            [npm_bin, "install", "-g", "@railway/cli"],
            timeout=120,
        )
    except FileNotFoundError:
        print("  npm not found during install. Install manually.")
        return False
    except subprocess.TimeoutExpired:
        print("  Install timed out. Try running manually:")
        print("    npm install -g @railway/cli")
        return False

    if result.returncode != 0:
        print("  Install failed. Try running manually:")
        print("    npm install -g @railway/cli")
        return False

    # Re-probe after install
    global _railway_bin
    _railway_bin = None  # reset cache
    found = find_railway_cli()
    if found:
        success(f"Railway CLI installed: {found}")
        return True
    else:
        print("  Install appeared to succeed but 'railway' still not found.")
        print("  You may need to restart your terminal for PATH changes.")
        return False


def check_railway_update():
    """Check if a Railway CLI update is available. Prompts user if so."""
    railway = find_railway_cli()
    if not railway:
        return

    # Get current version
    try:
        result = subprocess.run(
            [railway, "--version"], capture_output=True, text=True, timeout=10,
        )
        current = result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    if current:
        print(f"  Railway CLI version: {current}")

    # Check for updates via npm
    npm_bin = shutil.which("npm")
    if not npm_bin:
        return

    try:
        result = subprocess.run(
            [npm_bin, "outdated", "-g", "@railway/cli"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return

    # npm outdated returns exit code 1 when packages are outdated, 0 when up to date
    # Output contains the package line only when outdated
    if result.returncode == 1 and "@railway/cli" in result.stdout:
        print(f"  Update available: {result.stdout.strip()}\n")
        options = [
            "Update now (npm update -g @railway/cli)",
            "Skip -- continue with current version",
        ]
        choice = prompt_choice(options, default=1)
        if choice == 0:
            print("\n  Updating Railway CLI...")
            try:
                subprocess.run(
                    [npm_bin, "update", "-g", "@railway/cli"], timeout=120,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                print("  Update failed. Continuing with current version.")
            else:
                success("Railway CLI updated")
    else:
        success("Railway CLI is up to date")


def run_railway(args, **kwargs):
    """Wrapper for subprocess.run using the resolved railway binary path."""
    railway = find_railway_cli()
    if not railway:
        print()
        print(RAILWAY_INSTALL_MSG)
        return None
    try:
        return subprocess.run([railway] + args, **kwargs)
    except FileNotFoundError:
        print()
        print(RAILWAY_INSTALL_MSG)
        return None


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
# Step 1: Choose provider
# ─────────────────────────────────────────────────────────────────

def choose_provider():
    step_header(1, 7, "Choose your AI provider")
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
    step_header(2, 7, "Get your API key")

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
    step_header(3, 7, "Choose models")

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
    step_header(4, 7, "Configure .env")

    verify_gitignore(repo_root)

    if env_path.exists():
        print(f"  .env already exists at {env_path}\n")
        print("  Current values (keys masked):")
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if "KEY" in key.upper() or "PASSWORD" in key.upper():
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
# Step 5: Railway Login
# ─────────────────────────────────────────────────────────────────

def railway_login():
    step_header(5, 7, "Railway Login")

    # Find or install Railway CLI
    if not find_railway_cli():
        if not offer_railway_install():
            return False

    # CLI exists -- check for updates
    check_railway_update()

    # Check if already logged in
    result = run_railway(["whoami"], capture_output=True, text=True)
    if result is None:
        return False
    if result.returncode == 0 and result.stdout.strip():
        success(f"Already logged in: {result.stdout.strip()}")
        return True

    print("  Opening your browser to authenticate with Railway...\n")
    action_needed("Authorize in your browser, then come back here.")

    result = run_railway(["login"])
    if result is None or result.returncode != 0:
        print("  Railway login failed. Try running 'railway login' manually.")
        return False

    # Verify
    result = run_railway(["whoami"], capture_output=True, text=True)
    if result is not None and result.returncode == 0 and result.stdout.strip():
        success(result.stdout.strip())
        return True
    else:
        print("  Could not verify login. Try running 'railway login' manually.")
        return False


# ─────────────────────────────────────────────────────────────────
# Step 6: Deploy to Railway
# ─────────────────────────────────────────────────────────────────

def deploy_railway(env_path):
    step_header(6, 7, "Deploy to Railway")

    # Check if already linked to a project
    result = run_railway(["status"], capture_output=True, text=True)
    if result is None:
        return None
    already_linked = result.returncode == 0 and "Project:" in result.stdout

    if already_linked:
        print("  Already linked to a Railway project.\n")
        options = ["Use existing project", "Create a new project"]
        choice = prompt_choice(options, default=1)
        if choice == 1:
            run_railway(["unlink"], capture_output=True)
            already_linked = False

    if not already_linked:
        print("  Creating Railway project...\n")
        action_needed("Select your workspace and enter a project name when prompted.")
        result = run_railway(["init"])
        if result is None or result.returncode != 0:
            print("  Project creation failed.")
            return None
        success("Project created")

    # Add Postgres if not already present
    print("\n  Adding PostgreSQL with pgvector...")
    result = run_railway(
        ["add", "--database", "postgres"],
        capture_output=True,
        text=True,
    )
    if result is None or result.returncode != 0:
        print("  Note: Could not add database (it may already exist).")
    else:
        success("Database added")

    # Push env vars to Railway
    print("\n  Pushing environment variables to Railway...")
    env_vars = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Skip local-only vars
            if key and val and key != "DB_PASSWORD":
                env_vars[key] = val

    set_args = []
    for k, v in env_vars.items():
        set_args.extend(["--set", f"{k}={v}"])

    if set_args:
        result = run_railway(
            ["variables"] + set_args,
            capture_output=True,
            text=True,
        )
        if result is not None and result.returncode == 0:
            success(f"Set {len(env_vars)} variables")
        else:
            stderr = result.stderr if result else "Railway CLI not found"
            print(f"  Warning: Could not set variables: {stderr}")

    # Deploy
    print("\n  Deploying (this takes 2-3 minutes)...")
    result = run_railway(["up", "-d"], capture_output=True, text=True)
    if result is None or result.returncode != 0:
        stderr = result.stderr if result else "Railway CLI not found"
        print(f"  Deploy failed: {stderr}")
        print("  Try running 'railway up' manually.")
        return None
    success("Deploy started")

    # Get domain
    print("\n  Generating public URL...")
    result = run_railway(["domain"], capture_output=True, text=True)
    if result is not None and result.returncode == 0 and result.stdout.strip():
        url = result.stdout.strip()
        if not url.startswith("https://"):
            url = f"https://{url}"
        success(f"URL: {url}")
    else:
        print("  Could not generate domain automatically.")
        print("  Go to Railway dashboard -> service -> Settings -> Networking -> Generate Domain")
        url = input("  Paste your URL here: ").strip()
        if not url.startswith("https://"):
            url = f"https://{url}"

    # Health check with retries
    print("\n  Waiting for deployment to be healthy...")
    for attempt in range(10):
        try:
            req = urllib.request.Request(f"{url}/api/health")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "healthy":
                    success("Health check passed!")
                    return url
        except Exception:
            pass
        print(f"    Attempt {attempt + 1}/10 -- waiting 15 seconds...")
        time.sleep(15)

    print("  Health check failed after 10 attempts.")
    print("  Check 'railway logs' for errors.")
    return url


# ─────────────────────────────────────────────────────────────────
# Step 7: Output connection command
# ─────────────────────────────────────────────────────────────────

def show_connection(url, ariadne_key):
    step_header(7, 7, "Connect Claude Code")

    print("  Run this command in Claude Code or a terminal:\n")
    print(f"  claude mcp add ariadne-core \\")
    print(f"    {url}/mcp \\")
    print(f"    --transport http --scope user \\")
    print(f'    --header "X-API-Key:{ariadne_key}"')
    print()
    print(f"  Your ARIADNE_API_KEY: {ariadne_key}")
    print("  (also saved in .env and Railway variables)")
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

    # Step 1: Choose provider
    provider_key, provider_config = choose_provider()

    if provider_config is None:
        # User chose to skip provider setup
        print("\n  Skipping provider setup. Edit .env manually.\n")
        if not env_path.exists():
            shutil.copy(env_example, env_path)
            print(f"  Copied .env.example to .env -- edit it with your values.\n")

        if not args.skip_deploy:
            if railway_login():
                url = deploy_railway(env_path)
                if url:
                    print("\n  Edit .env with your API keys, then redeploy with 'railway up'.")
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

    # Determine base URLs -- if provider uses a separate vision config, handle it
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

    # Step 5: Railway login
    if not railway_login():
        print("\n  Fix the login issue and run this script again.")
        print("  Your .env has been saved -- you won't lose your configuration.\n")
        return

    # Step 6: Deploy
    url = deploy_railway(env_path)
    if not url:
        print("\n  Deploy failed. Your .env is saved -- fix the issue and run again.\n")
        return

    # Step 7: Connection info
    show_connection(url, ariadne_key)

    banner("Setup complete!")


if __name__ == "__main__":
    main()

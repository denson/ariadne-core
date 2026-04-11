"""Config file loader with ${VAR} interpolation.

Loads configuration from ariadne.yaml with three-layer resolution:
  1. Built-in defaults
  2. Config file values (with ${VAR} interpolation from environment)
  3. Environment variable overrides (ARIADNE_SECTION_KEY format)

Usage:
    config = load_config()                          # auto-discover
    config = load_config("/config/ariadne.yaml")    # explicit path
    config.embedding.model   # "text-embedding-3-small"
    config.database.url      # resolved from ${DB_PASSWORD}
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

# Matches ${VAR} or ${VAR:-default} patterns in config values
_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")

# Default config file search paths (in order)
_CONFIG_PATHS = [
    Path("config/ariadne.yaml"),           # relative to cwd
    Path("ariadne.yaml"),                  # cwd root
]


# ── Section dataclasses ──────────────────────────────────────────────────────


@dataclass
class DatabaseConfig:
    url: str = "postgresql://app:changeme@localhost:5432/pipeline"


@dataclass
class VectorStoreConfig:
    backend: str = "pgvector"


@dataclass
class EmbeddingConfig:
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""


@dataclass
class ImageEnrichmentConfig:
    enabled: bool = True
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    prompt: str = (
        "Describe this image in detail. Include any text, data, charts, "
        "diagrams, or visual elements. Be specific about numbers, labels, "
        "and relationships shown."
    )


@dataclass
class MarkitdownConfig:
    enable_plugins: bool = True


@dataclass
class ChunkingConfig:
    default_strategy: str = "by_title"
    max_characters: int = 1500
    new_after_n_chars: int = 1000
    overlap: int = 200
    combine_under_n_chars: int = 200


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    mcp_port: int = 8081
    require_auth: bool = False


@dataclass
class PathsConfig:
    incoming: str = "./data/incoming"
    processed: str = "./data/processed"
    temp: str = "./data/temp"


@dataclass
class LoggingConfig:
    level: str = "info"
    format: str = "json"


@dataclass
class AriadneConfig:
    """Top-level configuration container."""

    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    image_enrichment: ImageEnrichmentConfig = field(
        default_factory=ImageEnrichmentConfig
    )
    markitdown: MarkitdownConfig = field(default_factory=MarkitdownConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    api: APIConfig = field(default_factory=APIConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ── Section name → dataclass mapping ─────────────────────────────────────────

_SECTION_MAP: dict[str, type] = {
    "database": DatabaseConfig,
    "vector_store": VectorStoreConfig,
    "embedding": EmbeddingConfig,
    "image_enrichment": ImageEnrichmentConfig,
    "markitdown": MarkitdownConfig,
    "chunking": ChunkingConfig,
    "api": APIConfig,
    "paths": PathsConfig,
    "logging": LoggingConfig,
}


# ── Core functions ───────────────────────────────────────────────────────────


def interpolate_vars(value: str, env: dict[str, str] | None = None) -> str:
    """Replace ${VAR} and ${VAR:-default} patterns with environment values.

    Args:
        value: String potentially containing ${VAR} patterns.
        env: Environment dict (defaults to os.environ).

    Returns:
        String with variables resolved.
    """
    if env is None:
        env = dict(os.environ)

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        default = match.group(2)
        result = env.get(var_name)
        if result is not None:
            return result
        if default is not None:
            return default
        return match.group(0)  # leave unresolved

    return _VAR_PATTERN.sub(replacer, value)


def _interpolate_recursive(obj: Any, env: dict[str, str] | None = None) -> Any:
    """Recursively interpolate ${VAR} patterns in a nested dict/list structure."""
    if isinstance(obj, str):
        return interpolate_vars(obj, env)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(item, env) for item in obj]
    return obj


def _apply_env_overrides(
    raw: dict[str, Any], env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Apply ARIADNE_SECTION_KEY environment variable overrides.

    Env vars like ARIADNE_EMBEDDING_MODEL override raw["embedding"]["model"].
    For multi-word sections like image_enrichment, tries longest section match
    first (e.g., ARIADNE_IMAGE_ENRICHMENT_ENABLED → image_enrichment / enabled).
    """
    if env is None:
        env = dict(os.environ)

    # Sort section names longest-first so "image_enrichment" matches before "image"
    sorted_sections = sorted(_SECTION_MAP.keys(), key=len, reverse=True)

    prefix = "ARIADNE_"
    for key, value in env.items():
        if not key.startswith(prefix):
            continue
        remainder = key[len(prefix):].lower()

        matched = False
        for section in sorted_sections:
            section_prefix = section + "_"
            if remainder.startswith(section_prefix) and len(remainder) > len(section_prefix):
                field_name = remainder[len(section_prefix):]
                raw.setdefault(section, {})[field_name] = _coerce_value(
                    value, section, field_name
                )
                matched = True
                break

    return raw


def _coerce_value(value: str, section: str, field_name: str) -> Any:
    """Coerce an env var string to the correct type based on the dataclass field."""
    cls = _SECTION_MAP.get(section)
    if cls is None:
        return value

    for f in fields(cls):
        if f.name == field_name:
            if f.type in ("int", int):
                return int(value)
            if f.type in ("bool", bool):
                return value.lower() in ("true", "1", "yes")
            if f.type in ("float", float):
                return float(value)
            return value
    return value


def _build_section(cls: type, raw: dict[str, Any]) -> Any:
    """Build a dataclass instance from a raw dict, ignoring unknown keys."""
    valid_fields = {f.name for f in fields(cls)}
    filtered = {k: v for k, v in raw.items() if k in valid_fields}
    return cls(**filtered)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load and parse a YAML file with ${VAR} interpolation.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed dict with variables interpolated.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text) or {}
    return _interpolate_recursive(raw)


def load_config(
    path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> AriadneConfig:
    """Load the full Ariadne configuration.

    Resolution order: defaults → config file → env vars.

    Args:
        path: Explicit path to ariadne.yaml. If None, searches default locations.
        env: Environment dict override (for testing). Defaults to os.environ.

    Returns:
        AriadneConfig with all sections populated.
    """
    if env is None:
        env = dict(os.environ)

    # Step 1: Start with empty raw config (defaults come from dataclasses)
    raw: dict[str, Any] = {}

    # Step 2: Load config file (raw YAML without interpolation)
    if path is not None:
        p = Path(path)
        if p.exists():
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    else:
        for candidate in _CONFIG_PATHS:
            if candidate.exists():
                raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
                break

    # Interpolate ${VAR} patterns using the provided env
    raw = _interpolate_recursive(raw, env)

    # Step 3: Apply ARIADNE_* env var overrides
    raw = _apply_env_overrides(raw, env)

    # Step 4: Build typed config
    config = AriadneConfig()
    for section_name, cls in _SECTION_MAP.items():
        if section_name in raw and isinstance(raw[section_name], dict):
            section_obj = _build_section(cls, raw[section_name])
        else:
            section_obj = cls()
        setattr(config, section_name, section_obj)

    # Step 5: Handle common env vars that aren't in the ARIADNE_ namespace
    # Railway sets PORT directly; DATABASE_URL_PRIVATE is Railway's internal
    # Postgres URL (no egress fees), DATABASE_URL is the public fallback.
    if "PORT" in env:
        config.api.port = int(env["PORT"])
    if env.get("MCP_PORT"):
        config.api.mcp_port = int(env["MCP_PORT"])
    elif env.get("PORT"):
        config.api.mcp_port = int(env["PORT"])
    if "DATABASE_URL_PRIVATE" in env and not env.get("ARIADNE_DATABASE_URL"):
        config.database.url = env["DATABASE_URL_PRIVATE"]
    elif "DATABASE_URL" in env and not env.get("ARIADNE_DATABASE_URL"):
        config.database.url = env["DATABASE_URL"]

    return config

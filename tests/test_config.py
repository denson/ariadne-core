"""Tests for the config loader."""

import textwrap
from pathlib import Path

import pytest

from pipeline.config import (
    AriadneConfig,
    ChunkingConfig,
    DatabaseConfig,
    EmbeddingConfig,
    ImageEnrichmentConfig,
    interpolate_vars,
    load_config,
    load_yaml,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestInterpolateVars:
    def test_simple_var(self):
        result = interpolate_vars("${MY_VAR}", {"MY_VAR": "hello"})
        assert result == "hello"

    def test_var_in_string(self):
        result = interpolate_vars(
            "postgresql://app:${DB_PASSWORD}@host/db",
            {"DB_PASSWORD": "secret"},
        )
        assert result == "postgresql://app:secret@host/db"

    def test_multiple_vars(self):
        result = interpolate_vars(
            "${HOST}:${PORT}",
            {"HOST": "localhost", "PORT": "5432"},
        )
        assert result == "localhost:5432"

    def test_missing_var_unchanged(self):
        result = interpolate_vars("${MISSING_VAR}", {})
        assert result == "${MISSING_VAR}"

    def test_default_value(self):
        result = interpolate_vars("${MY_VAR:-fallback}", {})
        assert result == "fallback"

    def test_default_overridden_by_env(self):
        result = interpolate_vars("${MY_VAR:-fallback}", {"MY_VAR": "actual"})
        assert result == "actual"

    def test_empty_default(self):
        result = interpolate_vars("${MY_VAR:-}", {})
        assert result == ""

    def test_no_vars(self):
        result = interpolate_vars("plain string", {})
        assert result == "plain string"

    def test_nested_in_url(self):
        result = interpolate_vars(
            "https://${HOST:-api.openai.com}/v1",
            {},
        )
        assert result == "https://api.openai.com/v1"


class TestLoadYaml:
    def test_load_ariadne_yaml(self):
        path = Path(__file__).parent.parent / "config" / "ariadne.yaml"
        data = load_yaml(path)
        assert "database" in data
        assert "embedding" in data
        assert "chunking" in data

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_yaml("/nonexistent/config.yaml")

    def test_interpolation_applied(self, tmp_path):
        config_file = tmp_path / "test.yaml"
        config_file.write_text(
            "database:\n  url: postgresql://app:${TEST_PW}@host/db\n"
        )
        import os
        old = os.environ.get("TEST_PW")
        os.environ["TEST_PW"] = "mypassword"
        try:
            data = load_yaml(config_file)
            assert data["database"]["url"] == "postgresql://app:mypassword@host/db"
        finally:
            if old is None:
                os.environ.pop("TEST_PW", None)
            else:
                os.environ["TEST_PW"] = old


class TestLoadConfigDefaults:
    def test_defaults_without_file(self):
        # No config file, no env vars — pure defaults
        config = load_config(path="/nonexistent/path.yaml", env={})
        assert isinstance(config, AriadneConfig)
        assert config.embedding.model == "gemini-embedding-001"
        assert config.embedding.dimensions == 1536
        assert config.chunking.default_strategy == "by_title"
        assert config.chunking.max_characters == 1500
        assert config.api.port == 8000
        assert config.api.require_auth is False
        assert config.image_enrichment.model == "gemini-2.0-flash"
        assert config.logging.level == "info"
        assert config.database.url == "postgresql://app:changeme@localhost:5432/pipeline"

    def test_all_sections_present(self):
        config = load_config(path="/nonexistent/path.yaml", env={})
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.embedding, EmbeddingConfig)
        assert isinstance(config.image_enrichment, ImageEnrichmentConfig)
        assert isinstance(config.chunking, ChunkingConfig)


class TestLoadConfigFromFile:
    def test_file_overrides_defaults(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            embedding:
              model: gemini-embedding-001
              dimensions: 512
            chunking:
              max_characters: 2000
        """))
        config = load_config(path=str(config_file), env={})
        assert config.embedding.model == "gemini-embedding-001"
        assert config.embedding.dimensions == 512
        assert config.chunking.max_characters == 2000
        # Unset fields keep defaults
        assert config.embedding.base_url == "https://generativelanguage.googleapis.com/v1beta"
        assert config.chunking.default_strategy == "by_title"

    def test_var_interpolation_in_file(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            database:
              url: postgresql://app:${DB_PASSWORD}@host/db
            embedding:
              api_key: ${EMBEDDING_API_KEY}
        """))
        config = load_config(
            path=str(config_file),
            env={"DB_PASSWORD": "s3cret", "EMBEDDING_API_KEY": "sk-test"},
        )
        assert config.database.url == "postgresql://app:s3cret@host/db"
        assert config.embedding.api_key == "sk-test"

    def test_var_with_default_in_file(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            embedding:
              base_url: ${EMBEDDING_URL:-https://fallback.api/v1}
        """))
        config = load_config(path=str(config_file), env={})
        assert config.embedding.base_url == "https://fallback.api/v1"

    def test_unknown_keys_ignored(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            embedding:
              model: custom-model
              unknown_field: should_be_ignored
        """))
        config = load_config(path=str(config_file), env={})
        assert config.embedding.model == "custom-model"
        assert not hasattr(config.embedding, "unknown_field")


class TestEnvVarOverrides:
    def test_env_overrides_file(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            embedding:
              model: from-file
        """))
        config = load_config(
            path=str(config_file),
            env={"ARIADNE_EMBEDDING_MODEL": "from-env"},
        )
        assert config.embedding.model == "from-env"

    def test_env_overrides_defaults(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={"ARIADNE_EMBEDDING_MODEL": "env-model"},
        )
        assert config.embedding.model == "env-model"

    def test_int_coercion(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={"ARIADNE_EMBEDDING_DIMENSIONS": "768"},
        )
        assert config.embedding.dimensions == 768
        assert isinstance(config.embedding.dimensions, int)

    def test_bool_coercion(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={"ARIADNE_API_REQUIRE_AUTH": "true"},
        )
        assert config.api.require_auth is True

    def test_bool_coercion_false(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={"ARIADNE_IMAGE_ENRICHMENT_ENABLED": "false"},
        )
        assert config.image_enrichment.enabled is False

    def test_multiple_overrides(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={
                "ARIADNE_EMBEDDING_MODEL": "bge-m3",
                "ARIADNE_CHUNKING_MAX_CHARACTERS": "3000",
                "ARIADNE_LOGGING_LEVEL": "debug",
            },
        )
        assert config.embedding.model == "bge-m3"
        assert config.chunking.max_characters == 3000
        assert config.logging.level == "debug"

    def test_unknown_section_ignored(self):
        config = load_config(
            path="/nonexistent/path.yaml",
            env={"ARIADNE_FAKESECTION_KEY": "value"},
        )
        # Should not raise, just ignore
        assert isinstance(config, AriadneConfig)


class TestThreeLayerResolution:
    def test_file_beats_default(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text("api:\n  port: 9000\n")
        config = load_config(path=str(config_file), env={})
        assert config.api.port == 9000  # file wins over default 8000

    def test_env_beats_file(self, tmp_path):
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text("api:\n  port: 9000\n")
        config = load_config(
            path=str(config_file),
            env={"ARIADNE_API_PORT": "7000"},
        )
        assert config.api.port == 7000  # env wins over file 9000

    def test_full_chain(self, tmp_path):
        """default=8000, file=9000, env=7000 → env wins."""
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text("api:\n  port: 9000\n")
        config = load_config(
            path=str(config_file),
            env={"ARIADNE_API_PORT": "7000"},
        )
        assert config.api.port == 7000

    def test_interpolation_plus_override(self, tmp_path):
        """${VAR} in file resolved, then ARIADNE_* env overrides."""
        config_file = tmp_path / "ariadne.yaml"
        config_file.write_text(textwrap.dedent("""\
            embedding:
              api_key: ${EMBEDDING_API_KEY}
              model: file-model
        """))
        config = load_config(
            path=str(config_file),
            env={
                "EMBEDDING_API_KEY": "sk-from-dotenv",
                "ARIADNE_EMBEDDING_MODEL": "override-model",
            },
        )
        assert config.embedding.api_key == "sk-from-dotenv"
        assert config.embedding.model == "override-model"


class TestLoadRealConfig:
    def test_load_repo_config(self):
        """Load the actual config/ariadne.yaml from the repo."""
        path = Path(__file__).parent.parent / "config" / "ariadne.yaml"
        # Provide env vars that ariadne.yaml interpolates via ${VAR}
        env = {
            "EMBEDDING_MODEL": "gemini-embedding-001",
            "EMBEDDING_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
            "VISION_MODEL": "gemini-2.0-flash",
            "VISION_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
        }
        config = load_config(path=str(path), env=env)
        assert config.embedding.model == "gemini-embedding-001"
        assert config.chunking.default_strategy == "by_title"
        assert config.image_enrichment.model == "gemini-2.0-flash"
        assert config.vector_store.backend == "pgvector"

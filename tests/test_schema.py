"""Tests for schema validation and DDL generation."""

from pipeline.schema import (
    SchemaStatus,
    get_chunks_ddl,
    get_hnsw_index_ddl,
    validate_dimensions,
)


class TestGetChunksDDL:
    def test_contains_configured_dimension(self):
        ddl = get_chunks_ddl(1536)
        assert "vector(1536)" in ddl

    def test_different_dimension(self):
        ddl = get_chunks_ddl(768)
        assert "vector(768)" in ddl

    def test_creates_table(self):
        ddl = get_chunks_ddl(1536)
        assert "CREATE TABLE" in ddl
        assert "chunks" in ddl

    def test_contains_required_columns(self):
        ddl = get_chunks_ddl(1536)
        assert "document_id" in ddl
        assert "collection_id" in ddl
        assert "chunk_index" in ddl
        assert "embedding_model" in ddl
        assert "embedding" in ddl


class TestGetHNSWIndexDDL:
    def test_creates_index(self):
        ddl = get_hnsw_index_ddl()
        assert "CREATE INDEX" in ddl
        assert "hnsw" in ddl
        assert "vector_cosine_ops" in ddl

    def test_index_name(self):
        ddl = get_hnsw_index_ddl()
        assert "idx_chunks_embedding" in ddl


class TestValidateDimensions:
    def test_match(self):
        assert validate_dimensions(1536, 1536) is True

    def test_mismatch(self):
        assert validate_dimensions(1536, 1024) is False

    def test_store_none_always_valid(self):
        assert validate_dimensions(1536, None) is True

    def test_store_none_any_dimension(self):
        assert validate_dimensions(768, None) is True


class TestSchemaStatus:
    def test_fields(self):
        status = SchemaStatus(
            table_exists=True,
            dimension_match=True,
            current_dimension=1536,
            configured_dimension=1536,
            actions_taken=[],
        )
        assert status.table_exists is True
        assert status.dimension_match is True
        assert status.current_dimension == 1536
        assert status.configured_dimension == 1536
        assert status.actions_taken == []

    def test_mismatch_status(self):
        status = SchemaStatus(
            table_exists=True,
            dimension_match=False,
            current_dimension=1024,
            configured_dimension=1536,
            actions_taken=["altered embedding column"],
        )
        assert status.dimension_match is False
        assert status.current_dimension == 1024
        assert len(status.actions_taken) == 1

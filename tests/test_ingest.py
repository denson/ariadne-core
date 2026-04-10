"""Tests for the ingest MCP tool."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from pipeline.dedup import InMemoryDedupStore
from pipeline.mcp_server import (
    _dedup_store,
    _vector_store,
    convert_document,
    ingest,
    list_documents,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset stores between tests."""
    _dedup_store._documents.clear()
    _dedup_store._interactions.clear()
    _vector_store._chunks.clear()


def _create_test_dir(tmp_path: Path) -> Path:
    """Create a temp directory with test files."""
    (tmp_path / "report1.txt").write_text("Quarterly report Q1.")
    (tmp_path / "report2.txt").write_text("Quarterly report Q2.")
    (tmp_path / "notes.txt").write_text("Meeting notes from Monday.")
    (tmp_path / "data.csv").write_text("name,value\nfoo,1\nbar,2\n")
    (tmp_path / "readme.md").write_text("# README\nProject docs.")
    return tmp_path


@pytest.mark.asyncio
class TestIngestTool:
    async def test_ingest_basic(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        result = json.loads(await ingest(path=str(test_dir)))
        assert result["files_found"] == 5
        assert result["files_processed"] == 5
        assert result["files_skipped"] == 0
        assert result["files_errored"] == 0
        assert len(result["results"]) == 5

        # Verify all appear in list_documents
        docs = json.loads(await list_documents())
        assert docs["total_count"] == 5

    async def test_ingest_dedup(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        # First ingest
        await ingest(path=str(test_dir))
        # Second ingest — all should be dedup skipped
        result = json.loads(await ingest(path=str(test_dir)))
        assert result["files_found"] == 5
        assert result["files_processed"] == 0
        assert result["files_skipped"] == 5

    async def test_ingest_file_type_filter(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        result = json.loads(
            await ingest(path=str(test_dir), file_types=["txt"])
        )
        assert result["files_found"] == 3  # report1.txt, report2.txt, notes.txt

    async def test_ingest_force(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        await ingest(path=str(test_dir))
        result = json.loads(
            await ingest(path=str(test_dir), force=True)
        )
        assert result["files_processed"] == 5

    async def test_ingest_non_recursive(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        # Add a file in a subdirectory
        subdir = test_dir / "subdir"
        subdir.mkdir()
        (subdir / "deep.txt").write_text("Deep file content.")

        result = json.loads(
            await ingest(path=str(test_dir), recursive=False)
        )
        # Should not find the subdir file
        found_files = {r["source_file"] for r in result["results"]}
        assert "deep.txt" not in found_files
        assert result["files_found"] == 5

    async def test_ingest_corrupt_file(self, tmp_path):
        test_dir = _create_test_dir(tmp_path)
        # Create a zero-byte file with a supported extension
        (test_dir / "corrupt.pdf").write_bytes(b"")

        result = json.loads(await ingest(path=str(test_dir)))
        # The corrupt file may error or succeed with empty content
        # Either way, the other files should still be processed
        non_error = [
            r for r in result["results"]
            if r["error"] is None
        ]
        assert len(non_error) >= 5  # At least the 5 good files

    async def test_ingest_caller_metadata(self, tmp_path):
        (tmp_path / "single.txt").write_text("Test document.")
        result = json.loads(
            await ingest(
                path=str(tmp_path),
                agent_id="test-agent",
                agent_type="pytest",
                model="test-model",
                initiated_by="user:test",
                agent_notes="Test ingest",
            )
        )
        assert result["files_processed"] == 1
        doc_id = result["results"][0]["document_id"]

        # Check interactions
        interactions = _dedup_store.get_interactions(doc_id)
        assert len(interactions) == 1
        assert interactions[0].agent_id == "test-agent"
        assert interactions[0].agent_type == "pytest"

    async def test_ingest_not_a_directory(self):
        result = json.loads(await ingest(path="/nonexistent/dir"))
        assert result["error"] is True
        assert "Not a directory" in result["message"]

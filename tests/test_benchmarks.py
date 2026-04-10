"""Tests for the benchmark runner."""

from pathlib import Path

import pytest

from pipeline.extraction.markitdown import MarkItDownExtractor

# Import benchmark modules by adding to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))

from run_benchmarks import (
    BenchmarkResult,
    FormatSummary,
    benchmark_document,
    summarize_by_format,
)

BENCH_FIXTURES = Path(__file__).parent.parent / "benchmarks" / "fixtures"
TEST_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def extractor():
    return MarkItDownExtractor(enable_plugins=True)


class TestBenchmarkDocument:
    def test_benchmark_txt(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.txt"))
        if not files:
            pytest.skip("No TXT benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert isinstance(result, BenchmarkResult)
        assert result.extraction_ms > 0
        assert result.chunk_count > 0
        assert result.total_ms >= result.extraction_ms
        assert not result.errors

    def test_benchmark_html(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.html"))
        if not files:
            pytest.skip("No HTML benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert not result.errors
        assert result.markdown_len > 0

    def test_benchmark_csv(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.csv"))
        if not files:
            pytest.skip("No CSV benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert not result.errors
        assert result.chunk_count > 0

    def test_benchmark_docx(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.docx"))
        if not files:
            pytest.skip("No DOCX benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert not result.errors
        assert result.markdown_len > 0

    def test_benchmark_pptx(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.pptx"))
        if not files:
            pytest.skip("No PPTX benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert not result.errors

    def test_benchmark_xlsx(self, extractor):
        files = list(BENCH_FIXTURES.glob("*.xlsx"))
        if not files:
            pytest.skip("No XLSX benchmark fixtures")
        result = benchmark_document(files[0], extractor)
        assert not result.errors
        assert result.chunk_count > 0

    def test_nonexistent_file(self, extractor):
        result = benchmark_document(
            Path("/nonexistent/file.txt"), extractor
        )
        assert result.errors

    def test_result_fields(self, extractor):
        result = benchmark_document(TEST_FIXTURES / "sample.txt", extractor)
        assert result.file_name == "sample.txt"
        assert result.file_type == "txt"
        assert result.file_size_bytes > 0
        assert result.fingerprint_ms >= 0
        assert result.token_estimate > 0


class TestSummarizeByFormat:
    def test_single_format(self):
        results = [
            BenchmarkResult(
                file_name="a.txt", file_type="txt", file_size_bytes=100,
                extraction_ms=10, markdown_len=50, token_estimate=20,
                token_savings_ratio=2.0, fingerprint_ms=0.1,
                chunk_count=3, chunking_ms=5, total_ms=15.1,
            ),
            BenchmarkResult(
                file_name="b.txt", file_type="txt", file_size_bytes=200,
                extraction_ms=20, markdown_len=100, token_estimate=40,
                token_savings_ratio=3.0, fingerprint_ms=0.2,
                chunk_count=5, chunking_ms=8, total_ms=28.2,
            ),
        ]
        summaries = summarize_by_format(results)
        assert len(summaries) == 1
        assert summaries[0].format == "txt"
        assert summaries[0].count == 2
        assert summaries[0].avg_extraction_ms == 15.0
        assert summaries[0].total_errors == 0

    def test_multiple_formats(self):
        results = [
            BenchmarkResult(
                file_name="a.txt", file_type="txt", file_size_bytes=100,
                extraction_ms=10, markdown_len=50, token_estimate=20,
                token_savings_ratio=2.0, fingerprint_ms=0.1,
                chunk_count=3, chunking_ms=5, total_ms=15.1,
            ),
            BenchmarkResult(
                file_name="b.html", file_type="html", file_size_bytes=300,
                extraction_ms=15, markdown_len=80, token_estimate=30,
                token_savings_ratio=2.5, fingerprint_ms=0.1,
                chunk_count=4, chunking_ms=6, total_ms=21.1,
            ),
        ]
        summaries = summarize_by_format(results)
        assert len(summaries) == 2
        formats = {s.format for s in summaries}
        assert formats == {"txt", "html"}

    def test_with_errors(self):
        results = [
            BenchmarkResult(
                file_name="bad.txt", file_type="txt", file_size_bytes=0,
                extraction_ms=5, markdown_len=0, token_estimate=0,
                token_savings_ratio=0, fingerprint_ms=0,
                chunk_count=0, chunking_ms=0, total_ms=5,
                errors=["File not found"],
            ),
        ]
        summaries = summarize_by_format(results)
        assert summaries[0].total_errors == 1


class TestBenchmarkFixtureCount:
    def test_at_least_30_fixtures(self):
        """Build step 8 requires 30+ benchmark documents."""
        if not BENCH_FIXTURES.exists():
            pytest.skip("Benchmark fixtures not generated")
        files = list(BENCH_FIXTURES.iterdir())
        assert len(files) >= 30, f"Expected 30+ fixtures, got {len(files)}"

    def test_multiple_formats_present(self):
        """Verify fixture diversity across formats."""
        if not BENCH_FIXTURES.exists():
            pytest.skip("Benchmark fixtures not generated")
        extensions = {f.suffix for f in BENCH_FIXTURES.iterdir()}
        # At minimum: txt, html, csv, md, pptx, xlsx
        assert len(extensions) >= 5, f"Expected 5+ formats, got {extensions}"

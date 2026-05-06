"""Ariadne Core benchmark suite.

Tests extraction, chunking, and end-to-end pipeline performance across
30+ documents in multiple formats. Outputs a summary table with timing,
token estimates, and chunk counts.

Usage:
    python benchmarks/run_benchmarks.py              # all fixtures
    python benchmarks/run_benchmarks.py --format txt  # filter by extension
    python benchmarks/run_benchmarks.py --verbose     # show per-document details
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add src to path so we can import pipeline modules
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pipeline.chunking.chunker import chunk_document
from pipeline.dedup import compute_fingerprint
from pipeline.extraction.markitdown import MarkItDownExtractor

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class BenchmarkResult:
    """Result for a single document benchmark."""

    file_name: str
    file_type: str
    file_size_bytes: int
    extraction_ms: float
    markdown_len: int
    token_estimate: int
    token_savings_ratio: float
    fingerprint_ms: float
    chunk_count: int
    chunking_ms: float
    total_ms: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class FormatSummary:
    """Aggregated stats for a file format."""

    format: str
    count: int
    avg_extraction_ms: float
    avg_chunking_ms: float
    avg_total_ms: float
    avg_chunks: float
    avg_token_savings: float
    total_errors: int


def benchmark_document(
    path: Path, extractor: MarkItDownExtractor
) -> BenchmarkResult:
    """Run the full pipeline on a single document and measure performance.

    Steps measured:
      1. Extraction (MarkItDown → Markdown)
      2. Fingerprinting (SHA-256)
      3. Chunking (auto-strategy selection + chunk)
    """
    file_type = path.suffix.lstrip(".")
    try:
        file_size = path.stat().st_size
    except OSError:
        file_size = 0

    # Step 1: Fingerprint (raw bytes, BEFORE extraction — ariadne--k7n)
    t1 = time.perf_counter()
    try:
        compute_fingerprint(path.read_bytes())
        fingerprint_ms = (time.perf_counter() - t1) * 1000
    except OSError as e:
        # Mirror the prior contract: nonexistent / unreadable path
        # surfaces as result.errors, not an exception out of the helper.
        fingerprint_ms = (time.perf_counter() - t1) * 1000
        return BenchmarkResult(
            file_name=path.name,
            file_type=file_type,
            file_size_bytes=file_size,
            extraction_ms=0.0,
            markdown_len=0,
            token_estimate=0,
            token_savings_ratio=0.0,
            fingerprint_ms=fingerprint_ms,
            chunk_count=0,
            chunking_ms=0.0,
            total_ms=fingerprint_ms,
            errors=[f"Source read failed: {e}"],
        )

    # Step 2: Extract
    t0 = time.perf_counter()
    result = extractor.extract(str(path))
    extraction_ms = (time.perf_counter() - t0) * 1000

    if result.errors:
        return BenchmarkResult(
            file_name=path.name,
            file_type=file_type,
            file_size_bytes=file_size,
            extraction_ms=extraction_ms,
            markdown_len=0,
            token_estimate=0,
            token_savings_ratio=0.0,
            fingerprint_ms=fingerprint_ms,
            chunk_count=0,
            chunking_ms=0.0,
            total_ms=extraction_ms + fingerprint_ms,
            errors=result.errors,
        )

    # Step 3: Chunk
    t2 = time.perf_counter()
    chunks = chunk_document(
        markdown=result.markdown,
        document_id=result.document_id,
        collection_id="benchmark",
        file_type=result.file_type,
    )
    chunking_ms = (time.perf_counter() - t2) * 1000

    total_ms = extraction_ms + fingerprint_ms + chunking_ms

    return BenchmarkResult(
        file_name=path.name,
        file_type=file_type,
        file_size_bytes=file_size,
        extraction_ms=round(extraction_ms, 2),
        markdown_len=len(result.markdown),
        token_estimate=result.output_tokens_estimate,
        token_savings_ratio=result.token_savings_ratio,
        fingerprint_ms=round(fingerprint_ms, 2),
        chunk_count=len(chunks),
        chunking_ms=round(chunking_ms, 2),
        total_ms=round(total_ms, 2),
        warnings=list(result.warnings),
    )


def summarize_by_format(results: list[BenchmarkResult]) -> list[FormatSummary]:
    """Aggregate results by file format."""
    by_format: dict[str, list[BenchmarkResult]] = {}
    for r in results:
        by_format.setdefault(r.file_type, []).append(r)

    summaries = []
    for fmt, group in sorted(by_format.items()):
        successful = [r for r in group if not r.errors]
        if not successful:
            summaries.append(FormatSummary(
                format=fmt,
                count=len(group),
                avg_extraction_ms=0,
                avg_chunking_ms=0,
                avg_total_ms=0,
                avg_chunks=0,
                avg_token_savings=0,
                total_errors=len(group),
            ))
            continue

        summaries.append(FormatSummary(
            format=fmt,
            count=len(group),
            avg_extraction_ms=round(statistics.mean(r.extraction_ms for r in successful), 1),
            avg_chunking_ms=round(statistics.mean(r.chunking_ms for r in successful), 1),
            avg_total_ms=round(statistics.mean(r.total_ms for r in successful), 1),
            avg_chunks=round(statistics.mean(r.chunk_count for r in successful), 1),
            avg_token_savings=round(statistics.mean(r.token_savings_ratio or 0 for r in successful), 2),
            total_errors=len(group) - len(successful),
        ))

    return summaries


def print_results(results: list[BenchmarkResult], verbose: bool = False) -> None:
    """Print benchmark results as formatted tables."""
    successful = [r for r in results if not r.errors]
    failed = [r for r in results if r.errors]

    # Per-document table (verbose mode)
    if verbose:
        print("\n" + "=" * 100)
        print("PER-DOCUMENT RESULTS")
        print("=" * 100)
        header = f"{'File':<35} {'Type':<6} {'Size':>8} {'Extract':>9} {'Chunk':>9} {'Total':>9} {'Chunks':>7} {'Tokens':>8} {'Savings':>8}"
        print(header)
        print("-" * 100)
        for r in results:
            if r.errors:
                print(f"{r.file_name:<35} {'ERROR':<6} {_fmt_size(r.file_size_bytes):>8} {r.extraction_ms:>8.1f}ms {'':>9} {'':>9} {'':>7} {'':>8} {'':>8}")
            else:
                savings = f"{r.token_savings_ratio:.1f}x" if r.token_savings_ratio else "N/A"
                print(
                    f"{r.file_name:<35} {r.file_type:<6} {_fmt_size(r.file_size_bytes):>8} "
                    f"{r.extraction_ms:>8.1f}ms {r.chunking_ms:>8.1f}ms {r.total_ms:>8.1f}ms "
                    f"{r.chunk_count:>7} {r.token_estimate:>8} {savings:>8}"
                )

    # Format summary table
    summaries = summarize_by_format(results)
    print("\n" + "=" * 90)
    print("FORMAT SUMMARY")
    print("=" * 90)
    header = f"{'Format':<8} {'Count':>6} {'Avg Extract':>12} {'Avg Chunk':>12} {'Avg Total':>12} {'Avg Chunks':>11} {'Avg Savings':>12} {'Errors':>7}"
    print(header)
    print("-" * 90)
    for s in summaries:
        print(
            f"{s.format:<8} {s.count:>6} {s.avg_extraction_ms:>10.1f}ms {s.avg_chunking_ms:>10.1f}ms "
            f"{s.avg_total_ms:>10.1f}ms {s.avg_chunks:>11.1f} {s.avg_token_savings:>11.2f}x {s.total_errors:>7}"
        )

    # Overall summary
    print("\n" + "=" * 50)
    print("OVERALL SUMMARY")
    print("=" * 50)
    print(f"  Total documents:    {len(results)}")
    print(f"  Successful:         {len(successful)}")
    print(f"  Failed:             {len(failed)}")

    if successful:
        total_time = sum(r.total_ms for r in successful)
        avg_time = statistics.mean(r.total_ms for r in successful)
        median_time = statistics.median(r.total_ms for r in successful)
        total_chunks = sum(r.chunk_count for r in successful)
        total_tokens = sum(r.token_estimate for r in successful)
        avg_savings = statistics.mean(r.token_savings_ratio or 0 for r in successful)

        print(f"  Total time:         {total_time:.0f}ms ({total_time/1000:.2f}s)")
        print(f"  Avg per document:   {avg_time:.1f}ms")
        print(f"  Median per doc:     {median_time:.1f}ms")
        print(f"  Total chunks:       {total_chunks}")
        print(f"  Total tokens:       {total_tokens}")
        print(f"  Avg token savings:  {avg_savings:.2f}x")
        print(f"  Throughput:         {len(successful) / (total_time / 1000):.1f} docs/sec")

    if failed:
        print(f"\n  ERRORS:")
        for r in failed:
            print(f"    {r.file_name}: {'; '.join(r.errors)}")


def _fmt_size(size_bytes: int) -> str:
    """Format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    return f"{size_bytes / (1024 * 1024):.1f}MB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ariadne Core benchmark suite"
    )
    parser.add_argument(
        "--format",
        type=str,
        default=None,
        help="Filter by file extension (e.g., txt, html, docx)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-document results",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=str,
        default=str(FIXTURES_DIR),
        help="Path to fixtures directory",
    )
    args = parser.parse_args()

    fixtures_dir = Path(args.fixtures_dir)
    if not fixtures_dir.exists():
        print(f"Fixtures directory not found: {fixtures_dir}")
        print("Run 'python benchmarks/generate_fixtures.py' first.")
        sys.exit(1)

    # Collect fixture files
    files = sorted(fixtures_dir.iterdir())
    if args.format:
        ext = args.format.lstrip(".")
        files = [f for f in files if f.suffix.lstrip(".") == ext]

    if not files:
        print("No fixture files found.")
        sys.exit(1)

    print(f"Ariadne Core Benchmark Suite")
    print(f"Fixtures: {fixtures_dir}")
    print(f"Documents: {len(files)}")
    print()

    extractor = MarkItDownExtractor(enable_plugins=True)
    results: list[BenchmarkResult] = []

    for i, path in enumerate(files, 1):
        print(f"  [{i}/{len(files)}] {path.name}...", end=" ", flush=True)
        result = benchmark_document(path, extractor)
        results.append(result)
        if result.errors:
            print(f"ERROR ({result.extraction_ms:.0f}ms)")
        else:
            print(f"OK ({result.total_ms:.0f}ms, {result.chunk_count} chunks)")

    print_results(results, verbose=args.verbose)


if __name__ == "__main__":
    main()

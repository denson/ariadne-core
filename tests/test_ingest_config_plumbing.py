"""Unit gates for ariadne--16a (Batch G) — IngestConfig + extract_from_bytes plumbing.

Covers the unit-tier beats from agents/design/ariadne--16a/design.md §8:

  Beat 1 — Cap fast-fail via Content-Length (URL path).
  Beat 2 — Cap enforced via chunked-read accumulator when Content-Length
           absent or unreliable.
  Beat 3 — URL is fetched exactly once per ingest (services._read_source_bytes
           is called once; the legacy markitdown.urlretrieve cache-miss
           re-fetch is NEVER called from the canonical flow).
  Beat 4 — Local file is read from disk exactly once per ingest.
  Beat 7 — Per-request ingest_config override surfaces operator typos as
           HTTP-422-equivalent error dicts (NOT 500). Cap override flows
           through to _read_source_bytes; YAML default still wins when
           override is None.

Integration-tier beats (5, 6, 9, 10) live in tests/test_dedup.py +
tests/test_extraction.py + the broader pytest run; the smoke probes
(beat 8 grep + beat 10 full suite) are enforced by the bug-detection
sentinel below + the standard pytest invocation.
"""
from __future__ import annotations

import hashlib
import io
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline import services
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore


_FIXTURE_TXT = Path(__file__).parent / "fixtures" / "sample.txt"


# ── Helpers (mirror tests/test_services_fingerprint_order.py shape) ─────────


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _make_extractor_mock(*, source_file: str = "sample.txt") -> MagicMock:
    """Stub services._extractor with extract_from_bytes returning a fixed result."""
    mock = MagicMock()

    def _fake_extract_from_bytes(content, source_file=source_file):
        return ExtractionResult(
            document_id="00000000-0000-0000-0000-000000000000",
            source_file=source_file,
            markdown="# fake\n\nhello world\n",
            title="fake",
            file_type="txt",
            pages=None,
            engine="markitdown-mock",
            processing_time_ms=1,
            output_tokens_estimate=10,
            token_savings_ratio=None,
            processing_chain=[{"step": "extraction", "tool": "markitdown-mock"}],
            warnings=[],
            errors=[],
        )

    mock.extract_from_bytes.side_effect = _fake_extract_from_bytes
    return mock


def _install_clean_state(monkeypatch) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())  # 200 MB default
    extractor = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def _kwargs(uri: str, *, collection: str, ingest_config=None, force=False) -> dict:
    return dict(
        uri=uri,
        store=True,
        collection=collection,
        tags=[],
        force=force,
        agent_id="ada-16a-probe",
        agent_type="pytest",
        model=None,
        initiated_by="ada",
        agent_notes="batch-g plumbing probe",
        agent_metadata={"source_reference": "ariadne--16a-probe"},
        chunking_config=None,
        ingest_config=ingest_config,
    )


# ── Beat 1 — Content-Length fast-fail ───────────────────────────────────────


def test_beat_1_url_content_length_fast_fail():
    """Cap-exceeded Content-Length must raise SourceTooLargeError before
    any body bytes are read. The error message names the declared size
    and the cap so the operator sees what happened."""
    cap = 1024
    declared_size = 200_000_000  # 200 MB > cap

    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": str(declared_size)}
    fake_resp.read = MagicMock(side_effect=AssertionError(
        "fast-fail must not call .read() once Content-Length over cap"
    ))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("pipeline.services.urlopen", return_value=fake_resp) as urlopen_mock:
        with pytest.raises(services.SourceTooLargeError) as excinfo:
            services._read_source_bytes("https://example.com/huge.bin", cap=cap)

    msg = str(excinfo.value)
    assert "Content-Length=200000000" in msg, msg
    assert "cap=1024" in msg, msg
    assert urlopen_mock.call_count == 1


def test_beat_1_url_content_length_under_cap_proceeds():
    """Honest Content-Length under cap must NOT trigger fast-fail; the
    chunked read still runs to completion and returns the body."""
    body = b"abc" * 100
    cap = 1024

    # Streamed reads: first call returns whole body, second returns b''.
    reads = iter([body, b""])
    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": str(len(body))}
    fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        out = services._read_source_bytes("https://example.com/small.bin", cap=cap)
    assert out == body


# ── Beat 2 — chunked-accumulator fallback ───────────────────────────────────


def test_beat_2_chunked_accumulator_catches_overrun():
    """When Content-Length is absent (chunked TE / server omission), the
    accumulator must catch the overrun. Worst-case overshoot is one
    _READ_CHUNK; the buffer must never exceed cap + _READ_CHUNK at the
    moment the error is raised."""
    cap = 1024
    chunks = [b"x" * services._READ_CHUNK, b"x" * services._READ_CHUNK]  # 2 MB total
    chunks_iter = iter(chunks + [b""])

    fake_resp = MagicMock()
    fake_resp.headers = {}  # No Content-Length
    fake_resp.read = MagicMock(side_effect=lambda n: next(chunks_iter))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        with pytest.raises(services.SourceTooLargeError) as excinfo:
            services._read_source_bytes(
                "https://example.com/chunked.bin", cap=cap
            )
    msg = str(excinfo.value)
    assert "during read" in msg, msg
    assert "1024" in msg, msg


def test_beat_2_unparseable_content_length_falls_through():
    """A garbled Content-Length string must NOT crash the read; the
    accumulator still enforces the cap. Defense-in-depth against weird
    proxies."""
    cap = 1024
    body = b"under cap"
    reads = iter([body, b""])

    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": "not-a-number"}
    fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        out = services._read_source_bytes("https://example.com/x.bin", cap=cap)
    assert out == body


def test_beat_2_local_file_pre_flight_size_check(tmp_path: Path):
    """Local file path: Path.stat().st_size must be checked BEFORE
    read_bytes(). A 2 KB file with cap=1024 must raise without ever
    calling read_bytes."""
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * 2048)
    with pytest.raises(services.SourceTooLargeError) as excinfo:
        services._read_source_bytes(str(big), cap=1024)
    assert "2048" in str(excinfo.value)
    assert "1024" in str(excinfo.value)


# ── Beat 3 — URL single-fetch invariant ─────────────────────────────────────


def test_beat_3_url_fetched_exactly_once_per_ingest(monkeypatch):
    """The canonical ingest path must fetch the URL body exactly once.
    The pre-Batch-G shape called urlopen for fingerprinting and then
    urlretrieve again inside markitdown for extraction (two fetches per
    ingest); post-fix the same buffer flows through both calls.

    m5e migration: ``_process_single_document`` now also issues a HEAD
    probe via ``_probe_size`` for HTTP sources (cheap, no body bytes),
    so the urlopen call_count for an HTTP source is 2 (one HEAD, one
    GET). The load-bearing invariant — a single *body* fetch shared
    between fingerprinting and extraction — is preserved; the HEAD
    probe is metadata-only. We assert (a) urlopen called twice (probe
    + GET) AND (b) urlretrieve never called (no extractor re-fetch).
    """
    extractor = _install_clean_state(monkeypatch)

    body = b"# real content over a fake URL\n"
    reads = iter([body, b""])
    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": str(len(body))}
    fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("pipeline.services.urlopen", return_value=fake_resp) as urlopen_mock, \
         patch("pipeline.extraction.markitdown.urlretrieve") as urlretrieve_mock:
        result = services._process_single_document(
            **_kwargs("https://example.com/fake.txt", collection="batch_g_beat3")
        )

    assert result.get("error") is not True, result
    # m5e: HEAD probe + GET = 2 urlopen calls. The "single body fetch"
    # invariant lives at the urlretrieve assertion below.
    assert urlopen_mock.call_count == 2, (
        f"URL must be HEAD-probed once and GET-fetched once "
        f"(m5e); got {urlopen_mock.call_count} urlopen calls"
    )
    assert urlretrieve_mock.call_count == 0, (
        f"markitdown.urlretrieve must NOT be called from the canonical "
        f"ingest flow; got {urlretrieve_mock.call_count}"
    )
    # Bytes-only seam was used
    assert extractor.extract_from_bytes.call_count == 1
    extractor.extract.assert_not_called()


def test_beat_3_bug_detection_validation_pre_fix_would_fail(monkeypatch):
    """Bug-detection capability validation (step 17 in the implementation
    brief).

    Constructs a deliberate pre-fix shape — an extractor that re-fetches
    the URL via urlretrieve internally during extract_from_bytes — and
    asserts beat 3's invariant fires on it. Confirms beat 3 has teeth:
    a regression where someone reintroduces the double-fetch would be
    caught by the same `urlretrieve.call_count == 0` assertion above.
    """
    _install_clean_state(monkeypatch)

    body = b"# bug-detection probe\n"
    reads = iter([body, b""])
    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": str(len(body))}
    fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    # Inject a pre-fix-shaped extractor: extract_from_bytes secretly
    # calls urlretrieve, simulating the bug we just fixed.
    pre_fix_extractor = MagicMock()

    def _bad_extract_from_bytes(content, source_file):
        # Pretend the extractor re-fetches via urlretrieve under the hood.
        from pipeline.extraction.markitdown import urlretrieve as _ur
        _ur("https://example.com/fake.txt", "/tmp/fake")
        return ExtractionResult(
            document_id="bad-shape",
            source_file=source_file,
            markdown="# bug",
            title=None,
            file_type="txt",
            pages=None,
            engine="markitdown-bad",
            processing_time_ms=1,
            output_tokens_estimate=1,
            token_savings_ratio=None,
            processing_chain=[],
            warnings=[],
            errors=[],
        )

    pre_fix_extractor.extract_from_bytes.side_effect = _bad_extract_from_bytes
    monkeypatch.setattr(services, "_extractor", pre_fix_extractor)

    with patch("pipeline.services.urlopen", return_value=fake_resp), \
         patch("pipeline.extraction.markitdown.urlretrieve") as urlretrieve_mock:
        services._process_single_document(
            **_kwargs("https://example.com/fake.txt", collection="batch_g_pre_fix_probe")
        )

    # Under the bug shape, urlretrieve fires; beat 3's call_count == 0
    # assertion would fail. This proves the gate has teeth.
    assert urlretrieve_mock.call_count == 1, (
        "bug-detection probe failed: pre-fix shape did not exhibit the "
        "double-fetch bug, which means beat 3's gate is vacuous"
    )


# ── Beat 4 — Local file single-read invariant ───────────────────────────────


def test_beat_4_local_file_read_exactly_once_per_ingest(monkeypatch):
    """Local file path: Path.read_bytes must be called exactly once per
    ingest. The canonical seam is bytes-only (extract_from_bytes never
    re-reads from disk), so the spy on Path.read_bytes counts exactly
    one hit."""
    extractor = _install_clean_state(monkeypatch)

    # The pre-flight stat() also touches the file; we count read_bytes
    # specifically (the load-bearing operation).
    original_read_bytes = Path.read_bytes
    call_count = {"n": 0}

    def _spying_read_bytes(self):
        call_count["n"] += 1
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _spying_read_bytes)

    uri = str(_FIXTURE_TXT)
    result = services._process_single_document(
        **_kwargs(uri, collection="batch_g_beat4")
    )
    assert result.get("error") is not True, result
    assert call_count["n"] == 1, (
        f"local file must be read from disk exactly once per ingest; "
        f"got {call_count['n']}"
    )
    assert extractor.extract_from_bytes.call_count == 1


# ── Beat 7 — Per-request ingest_config override ─────────────────────────────


def test_beat_7_per_request_cap_override_triggers_confirmation(monkeypatch):
    """Per-request ``ingest_config={"max_source_bytes": 1024}`` against a
    2 KB local file must trigger the m5e confirmation flow (default
    deployment).

    m5e migration of the legacy 422-on-oversize semantic. Pre-m5e the
    soft cap was a strict cap (oversize → "Source read failed:" error-
    dict → HTTP 422). Post-m5e the soft cap triggers the confirmation
    flow: oversize → ``code: "confirmation_required"`` error-dict →
    HTTP 413 with a token. The hard cap (5 GB default) is well above
    the 2 KB fixture so this lands on the confirmation path, not the
    hard-limit path.

    Pinned by the design's §3.9 migration table: ``per-request
    max_source_bytes override above default still triggers
    413-confirmation when default soft cap is exceeded``.
    """
    _install_clean_state(monkeypatch)

    # 2 KB local file
    big = Path(__file__).parent / "fixtures" / "_batch_g_beat7_2k.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"x" * 2048)
    try:
        result = services._process_single_document(
            **_kwargs(
                str(big),
                collection="batch_g_beat7",
                ingest_config={"max_source_bytes": 1024},
            )
        )
        assert result.get("error") is True, result
        assert result.get("code") == "confirmation_required", result
        # Wire-shape pin: every m5e 413 field is present.
        for field in (
            "soft_cap",
            "hard_cap",
            "reported_size",
            "source",
            "confirmation_token",
            "ttl_seconds",
        ):
            assert field in result, (field, result)
        assert result["soft_cap"] == 1024, result
        assert result["reported_size"] == 2048, result
        assert result["confirmation_token"], result  # non-empty
    finally:
        big.unlink()


def test_beat_7_per_request_hard_cap_override_rejects(monkeypatch):
    """Per-request ``ingest_config={"max_source_bytes_hard": 1024}``
    against a 2 KB local file must trigger the m5e hard-limit path
    (HTTP 422 with ``code: "exceeds_hard_limit"``, no token).

    Pinned by the design's §3.9 migration table: ``per-request
    max_source_bytes_hard override (new) triggers 422-exceeds_hard_limit
    when exceeded``. Confirms the hard cap is per-request-overridable
    (matching the soft cap) and that bytes_seen >= effective_hard
    short-circuits before any token issuance.
    """
    _install_clean_state(monkeypatch)

    big = Path(__file__).parent / "fixtures" / "_batch_g_beat7_2k_hard.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"x" * 2048)
    try:
        result = services._process_single_document(
            **_kwargs(
                str(big),
                collection="batch_g_beat7_hard",
                ingest_config={
                    "max_source_bytes": 512,  # also below file size
                    "max_source_bytes_hard": 1024,  # 2 KB > this → hard
                },
            )
        )
        assert result.get("error") is True, result
        assert result.get("code") == "exceeds_hard_limit", result
        assert result.get("hard_cap") == 1024, result
        assert result.get("reported_size") == 2048, result
        # Hard-limit dict is intentionally narrow (no token, no soft_cap).
        assert "confirmation_token" not in result, result
    finally:
        big.unlink()


def test_beat_7_strict_mode_oversize_returns_strict_error(monkeypatch):
    """``require_confirmation_above_soft=False`` restores the legacy
    'soft cap acts strict' semantics. Oversize must produce the m5e
    strict-mode error code, not the confirmation flow.

    Distinguishes the three 422 sentinel codes per §11.B.4 (route A
    risk 4): ``exceeds_soft_cap_strict`` carries ``soft_cap`` (the
    strict-mode hint) AND ``hard_cap``; ``exceeds_hard_limit`` carries
    ``hard_cap`` but NOT ``soft_cap``.
    """
    _install_clean_state(monkeypatch)

    big = Path(__file__).parent / "fixtures" / "_batch_g_beat7_2k_strict.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"x" * 2048)
    try:
        result = services._process_single_document(
            **_kwargs(
                str(big),
                collection="batch_g_beat7_strict",
                ingest_config={
                    "max_source_bytes": 1024,
                    "require_confirmation_above_soft": False,
                },
            )
        )
        assert result.get("error") is True, result
        assert result.get("code") == "exceeds_soft_cap_strict", result
        assert result.get("soft_cap") == 1024, result
        assert "hard_cap" in result, result
        assert "confirmation_token" not in result, result
    finally:
        big.unlink()


def test_beat_7_per_request_unknown_key_returns_invalid_dict(monkeypatch):
    """Bogus key in ingest_config must surface as the standard
    ``{"error": True, "message": "Invalid ingest config: ..."}`` dict
    (which routes.py:282 turns into HTTP 422), NOT escape as a raw
    ValueError to FastAPI's global handler (which would yield 500)."""
    _install_clean_state(monkeypatch)
    result = services._process_single_document(
        **_kwargs(
            str(_FIXTURE_TXT),
            collection="batch_g_beat7_bogus",
            ingest_config={"bogus_key": 1},
        )
    )
    assert result.get("error") is True, result
    assert result["message"].startswith("Invalid ingest config:"), result
    assert "bogus_key" in result["message"], result
    assert result["document_id"] is None
    assert result["source_file"] == "sample.txt"


def test_beat_7_no_override_uses_yaml_default(monkeypatch):
    """ingest_config=None must fall back to the module default
    (configure_ingest-installed value, here the dataclass default of
    200 MB), not silently zero-cap."""
    extractor = _install_clean_state(monkeypatch)
    result = services._process_single_document(
        **_kwargs(
            str(_FIXTURE_TXT),
            collection="batch_g_beat7_default",
            ingest_config=None,
        )
    )
    assert result.get("error") is not True, result
    assert extractor.extract_from_bytes.call_count == 1


def test_configure_ingest_rejects_nonpositive_cap():
    """configure_ingest must fail loud at lifespan-load time on cap<=0
    so misconfigured deployments don't silently reject every fetch."""
    with pytest.raises(ValueError) as excinfo:
        services.configure_ingest(IngestConfig(max_source_bytes=0))
    assert "must be > 0" in str(excinfo.value)
    with pytest.raises(ValueError):
        services.configure_ingest(IngestConfig(max_source_bytes=-1))


# ── Beat 8 — io5 cleanup grep sentinel ──────────────────────────────────────


# IMPORTANT: this test MUST NOT contain the literal grep target as a
# contiguous lexical token, or the grep below would match its own
# source file and the assertion would always fail. Build the search
# string at runtime by concatenation so this file's source is invisible
# to grep -rn for the target.
_TARGET_TOKEN = "normalize" + "_text"  # do NOT collapse — see comment above


def test_beat_8_target_token_only_in_historical_docstrings():
    """After io5 cleanup, the literal token built from the parts above
    must appear in the repo only as historical context inside the k7n
    verification docstrings. Two hits expected, both inside
    tests/verification/ariadne--k7n/test_smoke_beats.py."""
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    tests_dir = repo_root / "tests"
    assert src_dir.is_dir() and tests_dir.is_dir(), (src_dir, tests_dir)

    result = subprocess.run(
        ["grep", "-rn", _TARGET_TOKEN, str(src_dir), str(tests_dir)],
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("Binary file")
    ]
    expected_path = "test_smoke_beats.py"  # k7n verification fixture
    assert len(hits) == 2, (
        f"Expected exactly 2 historical hits in k7n docstrings; got "
        f"{len(hits)}:\n" + "\n".join(hits)
    )
    for hit in hits:
        assert expected_path in hit, (
            f"Unexpected hit outside the k7n docstrings: {hit}"
        )

"""Verification probes for ariadne--tol — vision extraction for URL-sourced standalone images.

Pre-fix (services.py:405-410): the standalone-image branch in
``_process_single_document`` set ``local_path = uri`` (with a ``file://``
strip) and passed the result into ``ImageEnricher.describe_image``, which
ultimately did ``Path(image_path).exists()`` — for an http(s) URL this
raised ``FileNotFoundError`` and the request never reached the vision
API. Post-fix: the bytes already fetched by ``_read_source_bytes``
(Batch G one-fetch invariant, services.py:299) are routed into a new
``ImageEnricher.describe_image_from_bytes(image_bytes, source_file)``
that base64-encodes them and calls ``VisionClient.describe_image_from_base64``
directly, with the MIME type guessed from the source_file extension.

Probes:
  Probe 1 — Happy path: URL-sourced PNG reaches the vision API with the
            bytes that ``urlopen`` returned, not the URL string. Asserts
            that the new bytes-based seam was called exactly once and the
            old path-based seam was NOT called.
  Probe 2 — Vision-API-failure surfaces as error dict: when the vision
            seam raises, the response is the standard
            ``{"error": True, "message": "Vision extraction failed for ...: ..."}``
            dict. (Renamed from the design's "Falsification" — the genuine
            falsification probe is Probe 1's
            ``describe_image_from_bytes.call_count == 1`` AND
            ``describe_image.call_count == 0`` pair, which fails against
            the pre-fix shape.)
  Probe 3 — No-regression: text-document URL ingest does NOT enter the
            vision branch. Guards against the new branch firing too
            broadly.
  Probe 4 — No-regression: ``file://`` standalone image still works. The
            deleted ``file://`` strip in services.py is safely replaced by
            ``_read_source_bytes``'s upstream handling at services.py:195.
  Probe 5 — One-fetch invariant (Batch G regression guard): URL is
            fetched exactly once per ingest. Catches a hypothetical
            "fix" where someone re-routed through
            ``describe_image_from_url`` (which would re-fetch).
  Probe 6 — Static guard against tempfile regression. The chosen seam
            intentionally avoids tempfile; this probe inspects the
            method's source so a future change re-introducing tempfile
            would surface here. (Downgraded from the design's mock-based
            probe — patching ``tempfile.NamedTemporaryFile`` was
            decorative since the seam doesn't import or call tempfile.
            The static-source assertion captures the same intent at
            zero runtime cost.)
  Probe 7 — MIME type derived from extension, not hardcoded. URL ending
            in ``.jpg`` flows ``image/jpeg`` (not the ``image/png``
            default) into ``VisionClient.describe_image_from_base64``.
            Asserts against the deeper VisionClient mock (the actual
            API contract layer), not the ImageEnricher wrapper, so a
            future wrapper refactor can't silently invalidate the probe.

Out-of-scope (untested):
  - HTTP redirects (301/302). Handled upstream by ``_read_source_bytes`` /
    ``urlopen``; the bytes that reach the vision branch are post-redirect
    by construction.
  - HTTP 404/500 fetch errors. Handled upstream by
    ``_read_source_bytes`` (services.py:298-306) and surfaced as the
    ``Source read failed: ...`` error dict before the vision branch fires.
  - Content-Type-vs-extension mismatch (e.g. ``url=foo.png`` returning
    ``Content-Type: image/jpeg``). MIME guessing is extension-based
    (matching the pre-existing ``describe_image_from_path`` convention,
    vision.py:67); plumbing real Content-Type through ``_read_source_bytes``
    is a separate ticket — see design §6 weak point 1.

Helpers (_install_clean_state, _kwargs, _make_extractor_mock) are
copy-shaped from ``tests/test_ingest_config_plumbing.py:42-104``. Cross-
import is awkward because the ariadne--tol directory name contains
double-dashes (not a valid Python module identifier); copy-shape is the
convention used across other verification dirs.

Run with ``PYTHONPATH=src python -m pytest tests/verification/ariadne--tol/``.
"""

from __future__ import annotations

import base64
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline import services
from pipeline.config import IngestConfig
from pipeline.dedup import InMemoryDedupStore
from pipeline.enrichment.images import ImageEnricher, ImageEnrichmentResult
from pipeline.enrichment.vision import VisionConfig
from pipeline.extraction.markitdown import ExtractionResult
from pipeline.storage.base import InMemoryVectorStore


# __file__ is .../tests/verification/ariadne--tol/test_tol_vision_url_bytes.py
# parents[0] = ariadne--tol, parents[1] = verification, parents[2] = tests
_FIXTURE_PNG = (
    Path(__file__).resolve().parents[2] / "fixtures" / "test_image.png"
)


# ── Local helpers (copy-shape from test_ingest_config_plumbing.py) ──────────


class _DisabledEmbeddingClient:
    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("disabled")


def _fake_extraction_result(
    *,
    source_file: str,
    markdown: str = "",
    file_type: str = "png",
) -> ExtractionResult:
    return ExtractionResult(
        document_id="00000000-0000-0000-0000-000000000000",
        source_file=source_file,
        markdown=markdown,
        title=None,
        file_type=file_type,
        pages=None,
        engine="markitdown-mock",
        processing_time_ms=1,
        output_tokens_estimate=1,
        token_savings_ratio=None,
        processing_chain=[{"step": "extraction", "tool": "markitdown-mock"}],
        warnings=[],
        errors=[],
    )


def _make_extractor_mock(
    *, markdown: str = "", file_type: str = "png"
) -> MagicMock:
    """Stub services._extractor with extract_from_bytes returning a fixed result.

    Default shape (markdown="", file_type="png") triggers the standalone-image
    vision branch. Tests that want the text-document path pass
    ``markdown="# fake\\n\\nhello\\n"`` and ``file_type="txt"``.
    """
    mock = MagicMock()

    def _fake_extract_from_bytes(content, source_file):
        return _fake_extraction_result(
            source_file=source_file, markdown=markdown, file_type=file_type
        )

    mock.extract_from_bytes.side_effect = _fake_extract_from_bytes
    return mock


def _install_clean_state(
    monkeypatch, *, extractor: MagicMock | None = None
) -> MagicMock:
    monkeypatch.setattr(services, "_dedup_store", InMemoryDedupStore())
    monkeypatch.setattr(services, "_vector_store", InMemoryVectorStore())
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    monkeypatch.setattr(services, "_ingest_config", IngestConfig())
    if extractor is None:
        extractor = _make_extractor_mock()
    monkeypatch.setattr(services, "_extractor", extractor)
    return extractor


def _install_image_enricher_mock(monkeypatch) -> MagicMock:
    """Mock services._image_enricher with enabled=True. Probes 1-6 use this.

    ``enrich`` is also called downstream (services.py:454) on the
    standalone-image markdown ("# Image: ..."); its return value flows
    into the chunker. Stub it to a no-op pass-through so the chunker
    receives a real string instead of a MagicMock.
    """
    mock = MagicMock(spec=ImageEnricher)
    # MagicMock(spec=...) does not auto-generate property mocks; set enabled
    # explicitly so the ``if is_image and _image_enricher.enabled:`` gate fires.
    mock.enabled = True
    mock.describe_image_from_bytes.return_value = "fake vision description"

    def _passthrough_enrich(markdown, source_dir=None):
        return ImageEnrichmentResult(
            markdown=markdown,
            images_processed=0,
            images_skipped=0,
            errors=[],
            processing_time_ms=0,
            processing_chain_entry={},
        )

    mock.enrich.side_effect = _passthrough_enrich
    monkeypatch.setattr(services, "_image_enricher", mock)
    return mock


def _install_real_enricher_with_mocked_client(monkeypatch) -> MagicMock:
    """Real ImageEnricher with a mocked underlying VisionClient.

    Probe 7 uses this to assert against the actual API contract layer
    (``VisionClient.describe_image_from_base64``) rather than the wrapper.
    Returns the VisionClient mock so tests can inspect call args.
    """
    enricher = ImageEnricher(VisionConfig(api_key="fake-key-for-tests"))
    client_mock = MagicMock()
    client_mock.describe_image_from_base64.return_value = "fake vision description"
    enricher._client = client_mock  # type: ignore[assignment]
    monkeypatch.setattr(services, "_image_enricher", enricher)
    return client_mock


def _kwargs(uri: str, *, collection: str) -> dict:
    return dict(
        uri=uri,
        store=True,
        collection=collection,
        tags=[],
        force=False,
        agent_id="ada-tol-probe",
        agent_type="pytest",
        model=None,
        initiated_by="ada",
        agent_notes="tol vision url bytes probe",
        agent_metadata={"source_reference": "ariadne--tol-probe"},
        chunking_config=None,
        ingest_config=None,
    )


def _make_urlopen_mock(body: bytes) -> MagicMock:
    """Build a urlopen context-manager mock returning ``body``."""
    reads = iter([body, b""])
    fake_resp = MagicMock()
    fake_resp.headers = {"Content-Length": str(len(body))}
    fake_resp.read = MagicMock(side_effect=lambda n: next(reads))
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)
    return fake_resp


# ── Probe 1 — Happy path: URL-sourced PNG reaches vision API with bytes ─────


def test_probe_1_url_sourced_png_reaches_vision_api_with_bytes(monkeypatch):
    """URL-sourced PNG: bytes flow into ``describe_image_from_bytes`` and the
    old path-based ``describe_image`` is NOT called.

    Falsification: reverting the §3.3 services.py change (restoring
    ``local_path = uri`` and ``describe_image(local_path)``) would flip
    ``describe_image_from_bytes.call_count`` to 0 and
    ``describe_image.call_count`` to 1 — both assertions below would fail.
    """
    _install_clean_state(monkeypatch)
    enricher_mock = _install_image_enricher_mock(monkeypatch)

    body = b"\x89PNG\r\n\x1a\nfake"  # arbitrary fake PNG-shaped bytes
    fake_resp = _make_urlopen_mock(body)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        result = services._process_single_document(
            **_kwargs("https://example.com/diagram.png", collection="tol_probe_1")
        )

    assert result.get("error") is not True, result
    assert enricher_mock.describe_image_from_bytes.call_count == 1, (
        f"new bytes-based seam called "
        f"{enricher_mock.describe_image_from_bytes.call_count} times; "
        "expected exactly 1"
    )
    # First positional arg is the body bytes (not the URL string).
    call_args = enricher_mock.describe_image_from_bytes.call_args
    assert call_args.args[0] == body, (
        f"first arg to describe_image_from_bytes must be the urlopen body "
        f"bytes; got {call_args.args[0]!r}"
    )
    # source_file kwarg derived from URI tail
    assert call_args.kwargs.get("source_file") == "diagram.png", call_args
    # Old path-based seam was NOT called
    assert enricher_mock.describe_image.call_count == 0, (
        "path-based describe_image must not be called from the URL flow; "
        f"got {enricher_mock.describe_image.call_count} calls"
    )
    # Output markdown shape mirrors services.py:421
    assert "# Image: diagram.png" in result["markdown"], result
    assert "fake vision description" in result["markdown"], result


# ── Probe 2 — Vision-API-failure surfaces as error dict ─────────────────────


def test_probe_2_vision_api_failure_surfaces_as_error_dict(monkeypatch):
    """When the vision seam raises (any reason — network, 4xx, malformed
    response), the response is the standard error dict with the
    ``Vision extraction failed for ...`` message. Confirms the existing
    try/except at services.py:411-419 still catches failures from the
    new bytes-based seam.

    This is NOT the falsification probe (the genuine falsification lives
    in Probe 1's ``call_count == 1`` AND ``call_count == 0`` pair); this
    probe specifically guards the error-dict shape so a future refactor
    that drops the try/except would surface here.
    """
    _install_clean_state(monkeypatch)
    enricher_mock = _install_image_enricher_mock(monkeypatch)
    enricher_mock.describe_image_from_bytes.side_effect = RuntimeError(
        "Vision API call failed: simulated 503"
    )

    body = b"\x89PNG\r\n\x1a\nfake"
    fake_resp = _make_urlopen_mock(body)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        result = services._process_single_document(
            **_kwargs("https://example.com/diagram.png", collection="tol_probe_2")
        )

    assert result.get("error") is True, result
    assert "Vision extraction failed for diagram.png" in result["message"], result
    assert "simulated 503" in result["message"], result
    assert result["source_file"] == "diagram.png"


# ── Probe 3 — No-regression: text-document URL ingest unchanged ─────────────


def test_probe_3_text_document_url_does_not_enter_vision_branch(monkeypatch):
    """Text-document URL ingest (markdown non-empty, file_type='txt') must
    NOT enter the vision branch. Guards against the new branch firing
    too broadly."""
    text_extractor = _make_extractor_mock(
        markdown="# fake\n\nhello world\n", file_type="txt"
    )
    _install_clean_state(monkeypatch, extractor=text_extractor)
    enricher_mock = _install_image_enricher_mock(monkeypatch)

    body = b"# real text content over a fake URL\n"
    fake_resp = _make_urlopen_mock(body)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        result = services._process_single_document(
            **_kwargs("https://example.com/note.txt", collection="tol_probe_3")
        )

    assert result.get("error") is not True, result
    assert enricher_mock.describe_image_from_bytes.call_count == 0, (
        "vision branch must not fire for non-empty markdown / non-image "
        f"file_type; got {enricher_mock.describe_image_from_bytes.call_count} calls"
    )
    assert enricher_mock.describe_image.call_count == 0


# ── Probe 4 — No-regression: file:// standalone image still works ───────────


def test_probe_4_file_uri_standalone_image_still_works(monkeypatch):
    """``file://`` standalone image must still work post-fix. The deleted
    ``file://`` strip is safely replaced by ``_read_source_bytes`` (which
    already strips the scheme at services.py:195-199 and returns bytes).

    Asserts that ``describe_image_from_bytes`` is called exactly once with
    the file's bytes (proves bytes flowed in, not the path string)."""
    assert _FIXTURE_PNG.is_file(), f"fixture missing: {_FIXTURE_PNG}"

    _install_clean_state(monkeypatch)
    enricher_mock = _install_image_enricher_mock(monkeypatch)

    expected_bytes = _FIXTURE_PNG.read_bytes()
    file_uri = f"file://{_FIXTURE_PNG.as_posix()}"

    result = services._process_single_document(
        **_kwargs(file_uri, collection="tol_probe_4")
    )

    assert result.get("error") is not True, result
    assert enricher_mock.describe_image_from_bytes.call_count == 1, result
    call_args = enricher_mock.describe_image_from_bytes.call_args
    assert call_args.args[0] == expected_bytes, (
        "bytes from the file:// fixture did not flow through to "
        "describe_image_from_bytes"
    )
    assert call_args.kwargs.get("source_file") == "test_image.png"


# ── Probe 5 — One-fetch invariant (Batch G regression guard) ────────────────


def test_probe_5_url_fetched_exactly_once_per_image_ingest(monkeypatch):
    """URL-sourced standalone image must have its body fetched exactly
    once. Catches a hypothetical "fix" that re-routes through
    ``describe_image_from_url``, which would re-fetch the URL inside
    the vision client and break Batch G's one-fetch invariant.

    m5e migration: ``_process_single_document`` now also issues a HEAD
    probe via ``_probe_size`` for HTTP sources (no body bytes), so the
    urlopen call_count is 2 (one HEAD, one GET). The load-bearing
    invariant — a single *body* fetch shared between fingerprinting
    and the image-enricher byte stream — is preserved; the HEAD probe
    is metadata-only.
    """
    _install_clean_state(monkeypatch)
    _install_image_enricher_mock(monkeypatch)

    body = b"\x89PNG\r\n\x1a\nfake"
    fake_resp = _make_urlopen_mock(body)

    with patch("pipeline.services.urlopen", return_value=fake_resp) as urlopen_mock:
        result = services._process_single_document(
            **_kwargs("https://example.com/diagram.png", collection="tol_probe_5")
        )

    assert result.get("error") is not True, result
    # m5e: HEAD probe + GET = 2 urlopen calls. The single-body-fetch
    # invariant survives via describe_image_from_bytes (the enricher
    # mock would catch a re-fetch by checking call_count of its own
    # bytes-based seam).
    assert urlopen_mock.call_count == 2, (
        f"m5e: URL must be HEAD-probed once + GET-fetched once per "
        f"image ingest; got {urlopen_mock.call_count}"
    )


# ── Probe 6 — Static guard against tempfile regression ──────────────────────


def test_probe_6_no_tempfile_in_describe_image_from_bytes_source():
    """Static guard — the bytes-based seam intentionally avoids tempfile.

    The chosen seam (design §2) deliberately did NOT round-trip through
    a tempfile because the bytes are already in memory. If a future
    change re-introduces ``tempfile`` in the new method's body, this
    assertion fails. Cheaper and stronger than a runtime mock-based
    probe (which would be decorative since the current seam doesn't
    import tempfile at all).

    The probe inspects the function's CODE only (not its docstring),
    because the docstring legitimately mentions "tempfile round-trip"
    while explaining what the method intentionally avoids.
    """
    func = ImageEnricher.describe_image_from_bytes
    src = inspect.getsource(func)
    # Strip docstring before scanning so the explanatory mention of
    # "tempfile round-trip" in the prose doesn't false-trigger this guard.
    if func.__doc__:
        src_no_doc = src.replace(func.__doc__, "")
    else:  # pragma: no cover — docstring is present
        src_no_doc = src
    assert "tempfile" not in src_no_doc, (
        "describe_image_from_bytes must not use tempfile — the design "
        "intent (ariadne--tol §2) is bytes-in-memory → base64 → vision "
        "API, with no fs round-trip. Source (docstring stripped) "
        "contained:\n" + src_no_doc
    )


# ── Probe 7 — MIME type derived from extension, not hardcoded ───────────────


def test_probe_7_mime_type_derived_from_url_extension(monkeypatch):
    """JPEG URL must flow ``image/jpeg`` (not the ``image/png`` default)
    into ``VisionClient.describe_image_from_base64``. Catches a regression
    where MIME is hardcoded.

    This probe asserts against the **deeper layer**
    (``VisionClient.describe_image_from_base64``) rather than the
    ``ImageEnricher`` wrapper, because the deeper layer is the actual
    vendor-API contract: even if a future refactor changes the wrapper
    signature, the assertion still pins the MIME flowing into Gemini's
    inlineData payload (vision.py:107-125).
    """
    _install_clean_state(monkeypatch)
    client_mock = _install_real_enricher_with_mocked_client(monkeypatch)

    body = b"\xff\xd8\xff\xe0fake-jpeg-bytes"  # arbitrary JPEG-shaped bytes
    fake_resp = _make_urlopen_mock(body)

    with patch("pipeline.services.urlopen", return_value=fake_resp):
        result = services._process_single_document(
            **_kwargs("https://example.com/diagram.jpg", collection="tol_probe_7")
        )

    assert result.get("error") is not True, result
    assert client_mock.describe_image_from_base64.call_count == 1, result
    call_args = client_mock.describe_image_from_base64.call_args
    # MIME flowed as kwarg per ImageEnricher.describe_image_from_bytes shape
    assert call_args.kwargs.get("mime_type") == "image/jpeg", (
        f"expected mime_type='image/jpeg' from .jpg extension; got "
        f"{call_args.kwargs.get('mime_type')!r}"
    )
    # Sanity: base64-encoded payload decodes back to the original body.
    b64_data = call_args.args[0]
    assert base64.b64decode(b64_data) == body, (
        "base64 payload to VisionClient must decode back to the original "
        "urlopen body bytes"
    )

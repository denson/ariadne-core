"""End-to-end coverage for the YAML chunking config plumbing (ariadne--lpf / Batch F / g47).

Pre-fix the YAML ``chunking:`` block was loaded into AriadneConfig at startup
but never threaded into chunk_document — operators editing any of the 6 knobs
saw zero behavioral effect. These tests close on the new contract:

  1. ``configure_chunking`` installs YAML defaults that reach the chunker.
  2. Per-request ``chunking_config`` overrides win over the YAML defaults.
  3. The "auto" strategy sentinel returns a FULL ChunkingConfig from
     ``auto_select_strategy`` (NOT just a strategy name) — Batch C's
     headingless-.txt overlap=400 boost survives the plumbing.
  4. Unknown per-request keys raise ValueError instead of silently
     no-op'ing (preserves pre-fix typo detection).

Test discipline note: each test rebinds module-level configure_* state in
its own body via either explicit configure_* calls or monkeypatch.setattr.
There is no conftest fixture that auto-resets configure_* state between
tests — tests must reset to the chunker built-in defaults at teardown if
they install non-default YAML values (see ``_reset_chunking_defaults``
helper below).

Beats covered (per agents/design/ariadne--lpf §8):
  Beat 1 — YAML knob takes effect (min_chunk_tokens floor).
  Beat 2 — Per-request override beats YAML.
  Beat 3 — All 6 knobs reachable via the strategy=fixed_size observable.
  Beat 5 — First heading preserved on consecutive-heading start (ruk).
  Beat 8 — Headingless .txt preserves overlap=400 (LOAD-BEARING R1
           regression gate; if this fails, R1's whole-config receive
           shape regressed to a strategy-only copy).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import services
from pipeline.chunking.chunker import (
    ChunkingConfig as _ChunkerConfig,
    chunk_document,
)
from pipeline.config import ChunkingConfig as _ConfigChunking


FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _reset_chunking_defaults():
    """Restore module-level chunking state to the chunker built-in defaults.

    Call from a test that installs non-default YAML values, in a finally
    or fixture, so the next test sees a clean slate. Mirrors the
    monkeypatch.setattr discipline used by tests/test_services.py and
    tests/test_services_fingerprint_order.py for other configure_*
    state, but here we bind the symbol explicitly because configure_*
    is the documented public API.
    """
    services.configure_chunking(_ConfigChunking())  # all-defaults


@pytest.fixture(autouse=True)
def _reset_chunking_state_around_each_test():
    """Reset chunking defaults before AND after each test in this module.

    Each test body may install YAML values via configure_chunking; the
    next test must not see those leaked values. This fixture is local
    to this module (autouse=True applies only here) so it does not
    affect other test modules.
    """
    _reset_chunking_defaults()
    yield
    _reset_chunking_defaults()


class _DisabledEmbeddingClient:
    """Embedding client that does nothing — keeps these tests focused on chunking."""

    def __init__(self) -> None:
        self.enabled = False
        self.model = None

    def embed_texts(self, texts):  # pragma: no cover
        raise AssertionError("embed_texts must not be called when enabled=False")


def _fresh_stores(monkeypatch):
    """Install fresh in-memory stores so each test starts with no documents."""
    from pipeline.dedup import InMemoryDedupStore
    from pipeline.storage.base import InMemoryVectorStore

    stub_dedup = InMemoryDedupStore()
    stub_vector = InMemoryVectorStore()
    monkeypatch.setattr(services, "_dedup_store", stub_dedup)
    monkeypatch.setattr(services, "_vector_store", stub_vector)
    monkeypatch.setattr(services, "_embedding_client", _DisabledEmbeddingClient())
    return stub_dedup, stub_vector


def _common_kwargs(uri: str, collection: str, chunking_config=None) -> dict:
    return dict(
        uri=uri,
        store=True,
        collection=collection,
        tags=[],
        force=False,
        agent_id=None,
        agent_type="test",
        model=None,
        initiated_by="test",
        agent_notes="test",
        agent_metadata={"source_reference": "test-fixture"},
        chunking_config=chunking_config,
    )


def _capture_chunk_cfg(monkeypatch):
    """Replace chunk_document with a stub that records its config kwarg.

    Returns a list that the stub appends to; tests inspect [-1] after
    triggering an ingest. Used by the headingless-.txt regression gate
    (Beat 8) — the load-bearing assertion is what the chunker RECEIVED,
    not what it returned, because auto_select_strategy returns the full
    config but the bug we're guarding against would silently strip it
    on the way TO the chunker.
    """
    captured: list = []

    def _stub_chunk_document(*, markdown, document_id, collection_id, file_type, config):
        captured.append({
            "config": config,
            "file_type": file_type,
            "markdown_len": len(markdown),
        })
        return []  # no chunks emitted; embedding is disabled, store path tolerates this

    monkeypatch.setattr(services, "chunk_document", _stub_chunk_document)
    return captured


# ── Beat 1 — YAML knob takes effect (min_chunk_tokens floor) ─────────────────


def test_beat_1_yaml_min_chunk_tokens_floor_takes_effect(monkeypatch, tmp_path):
    """YAML min_chunk_tokens=100 produces chunks all ≥100 tokens (when the
    floor fires — strategy must be by_title for _coalesce_undersized to run).

    Strategy is set to by_title explicitly because _coalesce_undersized
    only runs on the by_title path (chunker.py:155-156). Setting it via
    YAML rather than per-request exercises the YAML-defaults plumbing,
    which is the contract under test.
    """
    _fresh_stores(monkeypatch)

    # Install YAML defaults: by_title strategy, floor=100.
    services.configure_chunking(_ConfigChunking(
        strategy="by_title",
        min_chunk_tokens=100,
    ))

    # Build a synthetic .md doc with several sections each well below 100
    # tokens (~400 chars). Without coalesce these would be tiny chunks.
    md_path = tmp_path / "synthetic_yaml_floor.md"
    md_path.write_text(
        "# Section A\n\nShort body.\n\n"
        "# Section B\n\nAnother short body.\n\n"
        "# Section C\n\nThird short body.\n",
        encoding="utf-8",
    )

    response = services._process_single_document(
        **_common_kwargs(str(md_path), "test_yaml_floor")
    )
    assert response.get("error") is not True, response

    # Every emitted chunk should be at or above the YAML floor (100),
    # OR the document collapsed to a single chunk (the only-chunk
    # exception in _coalesce_undersized — sub-floor singletons are kept
    # rather than deleting the whole doc's content).
    from pipeline.chunking.chunker import estimate_tokens

    chunks = services._get_chunks_for_document(response["document_id"])
    assert chunks, "expected at least one chunk"
    if len(chunks) > 1:
        below_floor = [c for c in chunks if estimate_tokens(c.text) < 100]
        assert not below_floor, (
            f"YAML min_chunk_tokens=100 not honored: "
            f"{len(below_floor)}/{len(chunks)} chunks under floor"
        )


def test_beat_1_floor_default_50_after_revert(monkeypatch, tmp_path):
    """Companion to beat 1: revert to default YAML and confirm the
    chunker's built-in floor of 50 applies (not the prior test's 100).

    The autouse fixture resets state between tests, so this test sees
    chunker defaults — i.e., min_chunk_tokens=50.
    """
    _fresh_stores(monkeypatch)
    # Don't reconfigure — use the autouse-reset chunker defaults (floor=50).

    md_path = tmp_path / "synthetic_default_floor.md"
    md_path.write_text(
        "# A\n\nBody.\n\n# B\n\nBody.\n",
        encoding="utf-8",
    )

    response = services._process_single_document(
        **_common_kwargs(str(md_path), "test_default_floor")
    )
    assert response.get("error") is not True, response
    chunks = services._get_chunks_for_document(response["document_id"])
    # With floor=50 and a tiny doc, coalesce produces a single chunk
    # (single-chunk-exception keeps it). Confirm chunks emitted at all.
    assert chunks, "expected at least one chunk under default floor"


# ── Beat 2 — Per-request override beats YAML ─────────────────────────────────


def test_beat_2_per_request_overrides_yaml(monkeypatch, tmp_path):
    """YAML min_chunk_tokens=100, per-request min_chunk_tokens=25.

    Per-request must win — chunks should be allowed down to 25 tokens.
    Captured config inspection is the cleanest assertion: stub
    chunk_document and inspect what config it received.
    """
    _fresh_stores(monkeypatch)
    captured = _capture_chunk_cfg(monkeypatch)

    services.configure_chunking(_ConfigChunking(
        strategy="by_title",
        min_chunk_tokens=100,
    ))

    md_path = tmp_path / "synthetic_per_request.md"
    md_path.write_text("# H\n\nBody.\n", encoding="utf-8")

    response = services._process_single_document(
        **_common_kwargs(
            str(md_path),
            "test_per_request_override",
            chunking_config={"min_chunk_tokens": 25},
        )
    )
    assert response.get("error") is not True, response

    received: _ChunkerConfig = captured[-1]["config"]
    assert received.min_chunk_tokens == 25, (
        f"per-request override not honored: got min_chunk_tokens="
        f"{received.min_chunk_tokens}, expected 25 (YAML default was 100)"
    )
    # The other YAML knob (strategy=by_title) should still be in place
    # because per-request only set min_chunk_tokens.
    assert received.strategy == "by_title", (
        f"YAML strategy should persist when per-request omits it: "
        f"got {received.strategy!r}"
    )


# ── Beat 3 — All 6 knobs reachable ───────────────────────────────────────────


@pytest.mark.parametrize(
    "knob,value",
    [
        ("strategy", "fixed_size"),
        ("max_characters", 999),
        ("new_after_n_chars", 777),
        ("overlap", 333),
        ("combine_under_n_chars", 444),
        ("min_chunk_tokens", 73),
    ],
)
def test_beat_3_each_yaml_knob_reaches_chunker(monkeypatch, tmp_path, knob, value):
    """Set each knob non-default in YAML, confirm chunker receives it.

    Stubs chunk_document and inspects the received ChunkingConfig.
    Strategy-explicit branch (not "auto") so YAML knobs aren't filtered
    by the operator-set diff — every YAML field reaches the chunker.
    """
    _fresh_stores(monkeypatch)
    captured = _capture_chunk_cfg(monkeypatch)

    # Build a config with all defaults except the one knob under test.
    # Strategy is the only one we can't safely default-leave for this
    # parametrization because the per-request build branches on it; for
    # the strategy-knob row, the YAML strategy IS the parametrized value.
    if knob == "strategy":
        cfg = _ConfigChunking(strategy=value)
    else:
        cfg = _ConfigChunking(strategy="by_title", **{knob: value})

    services.configure_chunking(cfg)

    md_path = tmp_path / "synthetic_knob.md"
    md_path.write_text("# A\n\nBody.\n", encoding="utf-8")

    response = services._process_single_document(
        **_common_kwargs(str(md_path), f"test_knob_{knob}")
    )
    assert response.get("error") is not True, response

    received: _ChunkerConfig = captured[-1]["config"]
    assert getattr(received, knob) == value, (
        f"YAML knob {knob}={value!r} did not reach the chunker; "
        f"received {knob}={getattr(received, knob)!r}"
    )


# ── Beat 5 — First heading preserved on consecutive-heading start (ruk) ──────


def test_beat_5_first_heading_preserved_on_consecutive_start():
    """Pre-fix bug: chunker.py:178 filter dropped the first heading when
    a doc started with two consecutive headings. After the §6 fix, both
    headings must be substrings of the resulting chunk text.

    Direct chunk_document call (not services-layer) — the bug is in the
    chunker itself, not in the plumbing. Uses level-2 headings to match
    the design §6 trace exactly.
    """
    md = "## Heading A\n\n## Heading B\n\nProse under B.\n"
    chunks = chunk_document(
        markdown=md,
        document_id="doc-test",
        collection_id="col-test",
        file_type="md",
        config=_ChunkerConfig(strategy="by_title"),
    )

    assert chunks, "expected at least one chunk"
    combined_text = "\n".join(c.text for c in chunks)
    assert "Heading A" in combined_text, (
        f"first heading was dropped (ruk regression); chunk texts: "
        f"{[c.text for c in chunks]!r}"
    )
    assert "Heading B" in combined_text, (
        f"second heading missing; chunk texts: "
        f"{[c.text for c in chunks]!r}"
    )


# ── Beat 8 — Headingless .txt preserves overlap=400 (LOAD-BEARING R1 gate) ───


def test_beat_8_headingless_txt_preserves_overlap_400(monkeypatch, tmp_path):
    """LOAD-BEARING R1 regression gate.

    auto_select_strategy("txt", markdown_without_headings) returns
    ChunkingConfig(strategy="fixed_size", overlap=400). The plumbing
    must thread that FULL config through, NOT just the strategy name.
    If R1's whole-config receive shape ever regresses to a strategy-
    only copy, the chunker would receive overlap=200 (chunker default)
    instead of 400, silently regressing Batch C's headingless-.txt
    boost.

    This test stubs chunk_document and asserts on the resolved config
    object the chunker WOULD have received. YAML defaults are pristine
    (strategy=auto, all other knobs at chunker default) — the realistic
    deploy shape after Batch F lands.
    """
    _fresh_stores(monkeypatch)
    captured = _capture_chunk_cfg(monkeypatch)

    # Pristine YAML defaults — what an operator on freshly-shipped
    # ariadne.yaml would have. strategy="auto", all other knobs default.
    services.configure_chunking(_ConfigChunking())

    # Build a headingless .txt: ~3 KB of plain prose, no markdown
    # headings of any level. auto_select_strategy("txt", ...) hits the
    # fixed_size + overlap=400 branch.
    txt_path = tmp_path / "headingless_prose.txt"
    txt_path.write_text(
        "This is a paragraph of plain prose. " * 100,
        encoding="utf-8",
    )

    response = services._process_single_document(
        **_common_kwargs(str(txt_path), "test_headingless_overlap")
    )
    assert response.get("error") is not True, response

    received: _ChunkerConfig = captured[-1]["config"]
    assert received.strategy == "fixed_size", (
        f"auto-select for headingless .txt should resolve to "
        f"fixed_size; got strategy={received.strategy!r}"
    )
    assert received.overlap == 400, (
        f"R1 REGRESSION: auto_select_strategy returned overlap=400 for "
        f"headingless .txt but the chunker received overlap="
        f"{received.overlap}. The whole-config receive shape regressed "
        f"to strategy-only — Batch C's headingless-.txt boost is dead."
    )


# ── Operator typo detection (per ARGUS R4) ───────────────────────────────────


def test_unknown_per_request_key_raises_value_error(monkeypatch, tmp_path):
    """Per-request typo (e.g., max_chars instead of max_characters) must
    raise ValueError, not silently no-op. Preserves pre-fix
    ChunkingConfig(**chunking_config) raise-on-unknown behavior.
    """
    _fresh_stores(monkeypatch)

    txt_path = tmp_path / "typo_input.txt"
    txt_path.write_text("Plain content.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unknown chunking config keys"):
        services._process_single_document(
            **_common_kwargs(
                str(txt_path),
                "test_typo",
                chunking_config={"max_chars": 2000},  # typo of max_characters
            )
        )

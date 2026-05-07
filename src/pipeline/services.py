"""Ariadne Core service layer — shared state and document processing logic.

This module contains all the business logic for document extraction, storage,
search, and lifecycle management. The REST API routes and any future interfaces
import from here.
"""

import asyncio
import dataclasses
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from pipeline.chunking.chunker import (
    Chunk,
    ChunkingConfig as _ChunkerConfig,
    auto_select_strategy,
    chunk_document,
)
from pipeline.config import ChunkingConfig as _ConfigChunking, IngestConfig
from pipeline.dedup import (
    DocumentInteraction,
    InMemoryDedupStore,
    PgDedupStore,
    SearchLogEntry,
    StoredDocument,
    compute_fingerprint,
)
from pipeline.embedding.embedder import EmbeddingClient, EmbeddingConfig
from pipeline.enrichment.images import ImageEnricher
from pipeline.enrichment.vision import VisionConfig
from pipeline.extraction.markitdown import MarkItDownExtractor
from pipeline.storage.base import InMemoryVectorStore
from pipeline.storage.pgvector import PgVectorStore

logger = logging.getLogger(__name__)

# Shared services
_extractor = MarkItDownExtractor(enable_plugins=True)
_dedup_store = InMemoryDedupStore()
_vector_store = InMemoryVectorStore()
_embedding_client = EmbeddingClient()  # Disabled by default (no API key)

# Image enrichment — disabled by default, configured at startup via configure_image_enrichment()
_image_enricher = ImageEnricher(None)

# Chunking defaults loaded from YAML via configure_chunking() at startup.
# Until configured, falls back to chunker built-in defaults. Per-request
# `chunking_config` dicts always win at call-time (see _process_single_document).
# `_chunker_defaults_baseline` is the comparison anchor used to detect which
# YAML knobs the operator actually changed (operator-set knobs override
# auto-select heuristic knobs; chunker-default-equal knobs do not).
_chunking_defaults: _ChunkerConfig = _ChunkerConfig()
_chunker_defaults_baseline: _ChunkerConfig = _ChunkerConfig()

# Ingest defaults loaded from YAML via configure_ingest() at startup.
# Per-request `ingest_config` dicts win at call time (see
# _process_single_document). Until configure_ingest() runs, the dataclass
# default (200 MB) applies — important for direct callers that bypass the
# FastAPI lifespan (tests, scripts).
_ingest_config: IngestConfig = IngestConfig()


def configure_embedding(config: EmbeddingConfig) -> None:
    """Configure the embedding client. Call before using store/search."""
    global _embedding_client
    _embedding_client = EmbeddingClient(config)


def configure_image_enrichment(api_key: str, model: str, base_url: str) -> None:
    """Configure the image enrichment client. Call at startup from app.py."""
    global _image_enricher
    if api_key:
        _image_enricher = ImageEnricher(VisionConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
        ))
    else:
        _image_enricher = ImageEnricher(None)


def configure_stores(dedup_store, vector_store) -> None:
    """Replace the default in-memory stores with the given implementations."""
    global _dedup_store, _vector_store
    _dedup_store = dedup_store
    _vector_store = vector_store


def configure_ingest(config: IngestConfig) -> None:
    """Install YAML-loaded ingest defaults. Per-request overrides win at call time.

    Validates ``max_source_bytes > 0`` so a misconfigured deployment fails
    loud at lifespan-load time instead of silently rejecting every fetch
    on the first byte.
    """
    if config.max_source_bytes <= 0:
        raise ValueError(
            f"IngestConfig.max_source_bytes must be > 0, got "
            f"{config.max_source_bytes}"
        )
    global _ingest_config
    _ingest_config = config


def configure_chunking(config: _ConfigChunking) -> None:
    """Install YAML-loaded chunking defaults. Per-request overrides win at call time.

    Translates the config-loader ChunkingConfig (pipeline.config) into the
    chunker runtime ChunkingConfig (pipeline.chunking.chunker). Both
    dataclasses must keep the named knobs in sync; tests/test_config.py
    asserts ``set(config-fields) ⊆ set(chunker-fields)`` to catch drift
    (test_chunking_config_field_drift_protection).

    The "auto" sentinel value for ``strategy`` is preserved here verbatim;
    auto-resolution happens per-request in ``_process_single_document`` so
    the file_type and content of each document drive the strategy choice.
    """
    global _chunking_defaults
    _chunking_defaults = _ChunkerConfig(
        strategy=config.strategy,
        max_characters=config.max_characters,
        new_after_n_chars=config.new_after_n_chars,
        overlap=config.overlap,
        combine_under_n_chars=config.combine_under_n_chars,
        min_chunk_tokens=config.min_chunk_tokens,
    )


# File extensions that should be treated as standalone images when
# MarkItDown produces no extractable text. These trigger a direct
# vision-model call in _process_single_document.
_STANDALONE_IMAGE_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "svg",
}


# Supported file extensions for ingestion
SUPPORTED_EXTENSIONS = {
    "pdf", "docx", "pptx", "xlsx", "xls", "csv", "tsv",
    "html", "htm", "txt", "md", "json", "xml", "rtf",
    "epub", "eml", "msg", "zip", "ipynb", "rst", "org",
    "wav", "mp3", "m4a", "jpg", "jpeg", "png", "gif",
}


class SourceTooLargeError(ValueError):
    """Raised when a source URI's bytes exceed IngestConfig.max_source_bytes.

    Subclasses ValueError so any future caller that adds an explicit
    ``except ValueError`` clause picks this up with the right semantic.
    In the current flow the error is caught generically by the
    ``except Exception`` at the call site below and surfaced as HTTP 422
    via routes.py:282 with the descriptive message.
    """


_READ_CHUNK = 1024 * 1024  # 1 MB; size of each urlopen.read() iteration


def _read_source_bytes(uri: str, *, cap: int | None = None) -> bytes:
    """Return raw bytes for a uri (file://, http(s)://, or local path), cap-enforced.

    URL path: deliberately uses the same default urllib semantics as the
    extractor's ``_download_to_temp`` (stdlib ``urlretrieve`` at
    ``extraction/markitdown.py``). No ``Accept-Encoding`` header is
    sent; no decompression is performed. If a server unilaterally returns
    ``Content-Encoding: gzip`` (rare but legal), the fetched compressed
    bytes are what gets fingerprinted AND extracted (Batch G holds the
    same buffer through both calls, so divergence is structurally
    impossible — see agents/design/ariadne--16a §6).

    Cap enforcement (Batch G / ariadne--16a §3):
      - URL: fast-fail on Content-Length when present and honest;
        otherwise accumulator-fallback during chunked read raises
        SourceTooLargeError as soon as the buffer exceeds ``cap``
        (worst case overshoot is ``cap + _READ_CHUNK - 1``).
      - Local file (and ``file://``): pre-flight ``Path.stat().st_size``
        check before ``read_bytes``; raises SourceTooLargeError on
        oversize.
      - ``cap=None`` falls back to the module default loaded by
        configure_ingest (or the dataclass default, 200 MB, before
        lifespan).
    """
    if cap is None:
        cap = _ingest_config.max_source_bytes
    if uri.startswith("file://"):
        # urlparse(uri).path on Windows produces leading-slash paths like
        # /C:/Users/...; pre-existing services.py:144-145 behavior
        # unchanged — Path() tolerates the leading slash on Windows.
        return _read_file_capped(Path(urlparse(uri).path), cap, uri)
    if uri.startswith(("http://", "https://")):
        # Match urlretrieve default: no extra headers, follow redirects.
        with urlopen(uri) as resp:
            cl = resp.headers.get("Content-Length")
            if cl is not None:
                try:
                    declared = int(cl)
                except ValueError:
                    declared = None
                if declared is not None and declared > cap:
                    raise SourceTooLargeError(
                        f"URL source exceeds max_source_bytes "
                        f"(Content-Length={declared} > cap={cap}): {uri}"
                    )
            buf = bytearray()
            while True:
                chunk = resp.read(_READ_CHUNK)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > cap:
                    raise SourceTooLargeError(
                        f"URL source exceeds max_source_bytes during read "
                        f"(>{cap}, header may be absent or false): {uri}"
                    )
            return bytes(buf)
    return _read_file_capped(Path(uri), cap, uri)


def _read_file_capped(path: Path, cap: int, uri: str) -> bytes:
    """Read a local file, refusing to load anything larger than ``cap``."""
    size = path.stat().st_size
    if size > cap:
        raise SourceTooLargeError(
            f"File source exceeds max_source_bytes ({size} > {cap}): {uri}"
        )
    return path.read_bytes()


def _source_file_from_uri(uri: str) -> str:
    """Derive a display-name source_file from a URI without touching disk."""
    return Path(urlparse(uri).path).name if "://" in uri else Path(uri).name


def _process_single_document(
    uri: str,
    store: bool,
    collection: str,
    tags: list[str],
    force: bool,
    agent_id: Optional[str],
    agent_type: Optional[str],
    model: Optional[str],
    initiated_by: Optional[str],
    agent_notes: Optional[str],
    agent_metadata: Optional[dict],
    chunking_config: Optional[dict],
    ingest_config: Optional[dict] = None,
    action: str = "ingest",
) -> dict[str, Any]:
    """Shared pipeline logic for convert_document and ingest.

    Returns a response dict (not JSON string).
    """
    # Resolve per-request ingest overrides against the YAML/module default
    # (Batch G / ariadne--16a §F2). Mirrors the Batch F chunking_config
    # validation pattern below: raise loudly on unknown keys so operator
    # typos surface as 422 rather than silently no-op'ing. The validation
    # is wrapped in its OWN try/except (mirroring the source-read pattern
    # below) so the raised ValueError converts to the standard
    # ``{"error": True, ...}`` dict that routes.py:282 turns into HTTP 422.
    # WITHOUT this local catch the ValueError would propagate to FastAPI's
    # global handler at app.py:125-137 and surface as HTTP 500 — beat 7's
    # 422 contract requires the local catch.
    effective_cap = _ingest_config.max_source_bytes
    if ingest_config:
        try:
            valid_keys = {f.name for f in dataclasses.fields(IngestConfig)}
            unknown = set(ingest_config) - valid_keys
            if unknown:
                raise ValueError(
                    f"Unknown ingest config keys: {sorted(unknown)}. "
                    f"Valid keys: {sorted(valid_keys)}."
                )
            effective_cap = ingest_config.get("max_source_bytes", effective_cap)
        except ValueError as e:
            return {
                "error": True,
                "message": f"Invalid ingest config: {e}",
                "document_id": None,
                "source_file": _source_file_from_uri(uri),
            }

    # Read source bytes for fingerprinting BEFORE extraction. The same
    # buffer is reused by extract_from_bytes below — one fetch, one read,
    # one buffer (Batch G / ariadne--16a §6). Cap-enforced via
    # _read_source_bytes (URL: Content-Length first, then chunked
    # accumulator; local file: stat-based pre-flight).
    try:
        raw_bytes = _read_source_bytes(uri, cap=effective_cap)
    except Exception as e:
        return {
            "error": True,
            "message": f"Source read failed: {e}",
            "document_id": None,
            "source_file": _source_file_from_uri(uri),
        }

    fingerprint = compute_fingerprint(raw_bytes)

    if not force:
        existing = _dedup_store.find_by_fingerprint(collection, fingerprint)
        if existing is not None:
            logger.info(
                "dedup-skip",
                extra={
                    "collection": collection,
                    "fingerprint_prefix": fingerprint[:8],
                    "source_file": _source_file_from_uri(uri),
                    "algorithm": "raw-bytes",
                },
            )
            _dedup_store.record_interaction(
                DocumentInteraction(
                    document_id=existing.document_id,
                    collection_id=collection,
                    agent_id=agent_id,
                    agent_type=agent_type,
                    model=model,
                    initiated_by=initiated_by,
                    agent_notes=agent_notes,
                    agent_metadata=agent_metadata,
                    action=action,
                    was_dedup_skip=True,
                )
            )
            interactions = _dedup_store.get_interactions(existing.document_id)
            chunk_count = _count_chunks_for_document(existing.document_id)
            # Get embedding_model from the first chunk, if any
            doc_chunks = _get_chunks_for_document(existing.document_id)
            embedding_model = doc_chunks[0].embedding_model if doc_chunks else None
            return {
                "document_id": existing.document_id,
                "source_file": existing.source_file,
                "title": existing.title,
                "file_type": existing.file_type,
                "engine": existing.engine,
                "processing_time_ms": existing.processing_time_ms,
                "output_tokens_estimate": existing.output_tokens_estimate,
                "token_savings_ratio": existing.token_savings_ratio,
                "content_fingerprint": existing.content_fingerprint,
                "collection": collection,
                "was_dedup_skip": True,
                "chunk_count": chunk_count,
                "store_status": "skipped",
                "embedding_model": embedding_model,
                "provenance": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "model": model,
                    "initiated_by": initiated_by,
                    "processing_chain": existing.processing_chain,
                },
                "interactions": [
                    {
                        "agent_id": i.agent_id,
                        "agent_type": i.agent_type,
                        "model": i.model,
                        "initiated_by": i.initiated_by,
                        "agent_notes": i.agent_notes,
                        "agent_metadata": i.agent_metadata,
                        "action": i.action,
                        "was_dedup_skip": i.was_dedup_skip,
                        "created_at": i.created_at,
                    }
                    for i in interactions
                ],
                "warnings": existing.warnings,
                "warnings_count": len(existing.warnings or []),
                "markdown": existing.markdown,
            }

    # Cache miss (or force=True): now do the expensive extraction. Reuse
    # the bytes already in `raw_bytes` instead of re-fetching from the URI
    # (Batch G / ariadne--16a §5). Same buffer, no network or disk hit.
    result = _extractor.extract_from_bytes(
        raw_bytes, source_file=_source_file_from_uri(uri)
    )

    if result.errors:
        return {
            "error": True,
            "message": f"Extraction failed: {'; '.join(result.errors)}",
            "document_id": result.document_id,
            "source_file": result.source_file,
        }

    if not result.markdown or not result.markdown.strip():
        ext = (result.file_type or "").lower().lstrip(".")
        is_image = ext in _STANDALONE_IMAGE_EXTENSIONS

        if is_image and _image_enricher.enabled:
            # Standalone image: MarkItDown produced no text, so call the
            # vision model directly on the bytes already fetched by
            # _read_source_bytes (Batch G one-fetch invariant). For a
            # URL source the previous shape passed the URL string into
            # describe_image, which then resolved it as a local path and
            # raised FileNotFoundError (ariadne--tol). file://-stripping
            # is no longer needed here — _read_source_bytes already
            # normalized file://, http(s)://, and bare paths to bytes.
            vision_start = time.perf_counter()
            try:
                description = _image_enricher.describe_image_from_bytes(
                    raw_bytes, source_file=result.source_file
                )
            except Exception as e:
                return {
                    "error": True,
                    "message": (
                        f"Vision extraction failed for {result.source_file}: {e}"
                    ),
                    "document_id": result.document_id,
                    "source_file": result.source_file,
                }
            vision_ms = int((time.perf_counter() - vision_start) * 1000)
            result.markdown = f"# Image: {result.source_file}\n\n{description}"
            result.file_type = ext
            result.output_tokens_estimate = max(1, len(result.markdown) // 4)
            result.processing_chain.append({
                "step": "vision_extraction",
                "tool": "image_enricher",
                "ts": datetime.now(timezone.utc).isoformat(),
                "ms": vision_ms,
            })
        else:
            return {
                "error": True,
                "message": f"Extraction produced empty output for {result.source_file}. "
                           "Image files require vision API configuration. "
                           "Check ARIADNE_IMAGE_ENRICHMENT_API_KEY.",
                "document_id": result.document_id,
                "source_file": result.source_file,
            }

    # Fingerprint already computed before extraction — do NOT recompute from
    # result.markdown.
    processing_chain = list(result.processing_chain)
    markdown = result.markdown
    warnings = list(result.warnings)

    # Image enrichment (SPEC pipeline step 3) — after fingerprint, before chunking
    if _image_enricher.enabled:
        source_dir = str(Path(uri).parent) if not uri.startswith(("http://", "https://")) else None
        try:
            enrich_result = _image_enricher.enrich(markdown, source_dir=source_dir)
            markdown = enrich_result.markdown
            if enrich_result.processing_chain_entry:
                processing_chain.append(enrich_result.processing_chain_entry)
            warnings.extend(enrich_result.errors)
        except Exception as e:
            warnings.append(f"Image enrichment failed: {e}")
    else:
        # Count image references and warn if vision key is missing
        image_count = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown))
        if image_count > 0:
            warnings.append(
                f"Document contains {image_count} image(s) but no VISION_API_KEY "
                "is configured — image descriptions were not generated"
            )

    # Merge encoding/language tags from extraction into the document's tag list
    if hasattr(result, 'suggested_tags') and result.suggested_tags:
        tags = list(tags or []) + result.suggested_tags

    stored_doc = StoredDocument(
        document_id=result.document_id,
        collection_id=collection,
        source_file=result.source_file,
        content_fingerprint=fingerprint,
        file_type=result.file_type,
        engine=result.engine,
        markdown=markdown,
        title=result.title,
        processing_time_ms=result.processing_time_ms,
        output_tokens_estimate=result.output_tokens_estimate,
        token_savings_ratio=result.token_savings_ratio,
        processing_chain=processing_chain,
        tags=tags,
        warnings=warnings,
    )

    # BL-19 transactional ingest: chunk + embed BEFORE any Postgres write.
    # On embed failure we bail here — no documents row, no chunks, no
    # vectors, no interaction are written.
    chunks: list[Chunk] = []
    if store:
        # Build the per-request chunker config by layering three sources
        # in precedence order: per-request > YAML defaults > auto-select
        # heuristic. See agents/design/ariadne--lpf §4 for the worked
        # examples; the load-bearing property is that auto-select returns
        # a FULL ChunkingConfig (e.g., headingless .txt → overlap=400),
        # NOT just a strategy name. Without the full-config receive shape,
        # Batch C's per-file-type behavior would silently regress.
        #
        # 1. Identify operator-set YAML knobs by diffing against chunker
        #    defaults. An operator who explicitly types the chunker default
        #    into YAML is indistinguishable from one who left it blank;
        #    that's acceptable per the design's §4 PLINY-confirmed caveat.
        yaml_explicit = {
            f.name: getattr(_chunking_defaults, f.name)
            for f in dataclasses.fields(_ChunkerConfig)
            if (
                getattr(_chunking_defaults, f.name)
                != getattr(_chunker_defaults_baseline, f.name)
                and f.name != "strategy"  # strategy handled by sentinel below
            )
        }

        # 2. Resolve strategy. "auto" sentinel asks the chunker for a
        #    full ChunkingConfig per file type; an explicit YAML strategy
        #    starts from the YAML defaults directly.
        if _chunking_defaults.strategy == "auto":
            base = auto_select_strategy(result.file_type, markdown)
            if yaml_explicit:
                # YAML-set knobs win over auto-select heuristic knobs.
                base = dataclasses.replace(base, **yaml_explicit)
        else:
            base = _chunking_defaults  # explicit strategy; YAML knobs already in place

        # 3. Per-request overrides win over both. Preserve the pre-fix
        #    raise-on-unknown-key behavior so operator typos surface as
        #    a clear ValueError instead of silently no-op'ing (per the
        #    R4 ARGUS revision). The validation is wrapped in its OWN
        #    try/except (mirroring the ingest_config equivalent at
        #    services.py:268-291) so the raised ValueError converts to
        #    the standard ``{"error": True, ...}`` dict that
        #    routes.py:287 turns into HTTP 422. WITHOUT this local catch
        #    the ValueError would propagate to FastAPI's global handler
        #    at app.py:125-137 and surface as HTTP 500 — the 422 contract
        #    requires the local catch (parallel to Batch G F2).
        if chunking_config:
            try:
                valid_keys = {f.name for f in dataclasses.fields(_ChunkerConfig)}
                unknown = set(chunking_config) - valid_keys
                if unknown:
                    raise ValueError(
                        f"Unknown chunking config keys: {sorted(unknown)}. "
                        f"Valid keys: {sorted(valid_keys)}."
                    )
                chunk_cfg = dataclasses.replace(base, **chunking_config)
            except ValueError as e:
                return {
                    "error": True,
                    "message": f"Invalid chunking config: {e}",
                    "document_id": None,
                    "source_file": result.source_file,
                }
        else:
            chunk_cfg = base

        chunks = chunk_document(
            markdown=markdown,
            document_id=result.document_id,
            collection_id=collection,
            file_type=result.file_type,
            config=chunk_cfg,
        )

        if _embedding_client.enabled and chunks:
            try:
                texts = [c.text for c in chunks]
                embed_result = _embedding_client.embed_texts(texts)
                for chunk, embedding in zip(chunks, embed_result.embeddings):
                    chunk.embedding = embedding
                    chunk.embedding_model = _embedding_client.model
                processing_chain.append(embed_result.processing_chain_entry)
            except RuntimeError as e:
                failure_warnings = warnings + [f"Embedding failed: {e}"]
                return {
                    "error": True,
                    "message": f"Embedding failed: {e}",
                    "document_id": None,
                    "source_file": result.source_file,
                    "collection": collection,
                    "store_status": "error",
                    "chunk_count": 0,
                    "warnings": failure_warnings,
                    "warnings_count": len(failure_warnings),
                }

    if store:
        # Probe-then-store: detect would-be resurrection BEFORE storing so the
        # resurrection warning can be appended to `warnings` alongside the
        # metadata-hygiene warnings below — all of which must land in the list
        # BEFORE store_document is called. PgDedupStore.store_document
        # snapshots `doc.warnings or []` into the SQL parameter dict and
        # commits before returning (dedup.py:294-300), so any append after
        # the call never reaches Postgres. The two probe calls answer the
        # probe-time question; the function's own internal SELECT-in-
        # transaction remains the race-correct signal for its bool return,
        # which we don't second-guess from here.
        existing_visible = _dedup_store.find_by_fingerprint(
            collection, fingerprint, include_deleted=False
        )
        existing_any = _dedup_store.find_by_fingerprint(
            collection, fingerprint, include_deleted=True
        )
        would_resurrect = (existing_visible is None) and (existing_any is not None)
        if would_resurrect:
            warnings.append(
                "This document was previously soft-deleted and has been "
                "resurrected by re-ingest. Its deletion_scheduled_at has "
                "been cleared."
            )

    # Warn when key metadata conventions aren't followed
    if collection == "default":
        warnings.append(
            "Document stored in 'default' collection. Consider using a named "
            "collection (project, topic, or task) for better searchability."
        )
    if not agent_notes:
        warnings.append(
            "No agent_notes provided. Future agents won't know why this "
            "document was processed."
        )
    if not agent_metadata or (
        "source_url" not in agent_metadata
        and "source_reference" not in agent_metadata
    ):
        warnings.append(
            "No source_url or source_reference in agent_metadata. "
            "Future agents won't know where this document came from. "
            "See SPEC.md Metadata Conventions for provenance guidelines."
        )

    if store:
        # All warnings must be appended BEFORE store_document — PgDedupStore
        # snapshots warnings into the SQL params at call time and commits
        # before returning (dedup.py:294-300). Return value (was_resurrected)
        # ignored here; would_resurrect above drove the user-facing warning
        # using probe-time state.
        _dedup_store.store_document(stored_doc)
        logger.info(
            "dedup-miss-store",
            extra={
                "collection": collection,
                "fingerprint_prefix": fingerprint[:8],
                "source_file": _source_file_from_uri(uri),
                "algorithm": "raw-bytes",
            },
        )
    doc_id = stored_doc.document_id

    response: dict[str, Any] = {
        "document_id": doc_id,
        "source_file": result.source_file,
        "title": result.title,
        "file_type": result.file_type,
        "engine": result.engine,
        "processing_time_ms": result.processing_time_ms,
        "output_tokens_estimate": result.output_tokens_estimate,
        "token_savings_ratio": result.token_savings_ratio,
        "content_fingerprint": fingerprint,
        "collection": collection,
        "was_dedup_skip": False,
        "provenance": {
            "agent_id": agent_id,
            "agent_type": agent_type,
            "model": model,
            "initiated_by": initiated_by,
            "processing_chain": processing_chain,
        },
        "warnings": warnings,
        "warnings_count": len(warnings),
    }

    # When the document is being stored, the full markdown is already
    # persisted and retrievable via get_document / search — returning it
    # inline blows up the LLM context window (a 110-chunk PDF is ~160K
    # chars). Send a short preview instead. When store=false, the caller
    # has nowhere else to get the content, so we return the full text.
    if store:
        if len(markdown) > 500:
            response["markdown"] = (
                markdown[:500]
                + "... [truncated, use get_document for full content]"
            )
            response["markdown_truncated"] = True
        else:
            response["markdown"] = markdown
            response["markdown_truncated"] = False
    else:
        response["markdown"] = markdown

    if store:
        if force:
            _vector_store.delete_by_document(doc_id)
        _vector_store.insert(chunks)
        response["chunk_count"] = len(chunks)
        response["embedding_model"] = (
            _embedding_client.model if _embedding_client.enabled else None
        )
        response["store_status"] = "stored"

        # Record interaction AFTER all processing (SPEC pipeline step 7).
        # Under BL-19 transactional ingest this only runs on the success
        # path — store=False and embed-fail both skip the interaction row.
        _dedup_store.record_interaction(
            DocumentInteraction(
                document_id=doc_id,
                collection_id=collection,
                agent_id=agent_id,
                agent_type=agent_type,
                model=model,
                initiated_by=initiated_by,
                agent_notes=agent_notes,
                agent_metadata=agent_metadata,
                action=action,
                was_dedup_skip=False,
            )
        )
    else:
        response["store_status"] = "not_stored"
        response["chunk_count"] = 0

    return response


def _find_document_by_id(document_id: str) -> StoredDocument | None:
    """Find a document by ID across all collections."""
    if isinstance(_dedup_store, PgDedupStore):
        return _dedup_store.get_document_by_id(document_id)
    # In-memory fallback: scan all documents
    for (collection, fp), doc in _dedup_store._documents.items():
        if doc.document_id == document_id:
            return doc
    return None


def _get_chunks_for_document(document_id: str) -> list:
    """Get all chunks for a document, ordered by chunk index."""
    if isinstance(_vector_store, PgVectorStore):
        return _vector_store.get_document_chunks(document_id)
    # In-memory fallback
    doc_chunks = [
        c for c in _vector_store._chunks.values()
        if c.document_id == document_id
    ]
    doc_chunks.sort(key=lambda c: c.chunk_id)
    return doc_chunks


def _count_chunks_for_document(document_id: str) -> int:
    """Count chunks for a specific document."""
    if isinstance(_vector_store, PgVectorStore):
        return _vector_store.count_by_document(document_id)
    # In-memory fallback
    return sum(
        1 for c in _vector_store._chunks.values()
        if c.document_id == document_id
    )


def _post_filter_results(
    results: list, filters: dict[str, Any]
) -> list:
    """Post-filter search results for source_file, file_type, tags.

    Used with InMemoryVectorStore which doesn't have access to document
    metadata during search. Looks up the source document from the dedup
    store to apply these filters.
    """
    if not any(k in filters for k in ("source_file", "file_type", "tags")):
        return results

    filtered = []
    for r in results:
        doc = _find_document_by_id(r.document_id)
        if doc is None:
            continue

        if "source_file" in filters:
            if filters["source_file"].lower() not in doc.source_file.lower():
                continue

        if "file_type" in filters:
            ft = filters["file_type"].lstrip(".")
            if doc.file_type != ft:
                continue

        if "tags" in filters:
            filter_tags = set(filters["tags"])
            doc_tags = set(doc.tags) if doc.tags else set()
            if not filter_tags & doc_tags:
                continue

        filtered.append(r)

    return filtered

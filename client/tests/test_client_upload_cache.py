"""Probes for ariadne--nud §2 (cache cap) and §5 (cache-hit alignment).

§2 — ``AriadneClient._uploaded_paths`` is bounded.
    Pre-fix the cache was an unbounded ``dict`` keyed by file
    ``(absolute_path, mtime_ns)`` or ``("bytes", sha256)``. A long-
    running daemon ingesting many distinct files would grow this
    cache without bound. Bounded at 1000 entries with FIFO eviction.

§5 — Cache-hit and cache-miss paths return aligned responses.
    Pre-fix the ``ingest_bytes`` cache-hit path bypassed
    ``_upload_with_cache_key`` and synthesized its own upload reply
    inline. Both paths now flow through the shared core so any
    downstream consumer gets the same response shape regardless of
    cache state.

Hermetic — no network. Uses ``captured_http`` fixture from
``conftest.py``.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from ariadne_core_client import AriadneClient
from ariadne_core_client.client import _UPLOADED_PATHS_CACHE_MAX


# ─────────────────────────────────────────────────────────── §2 cap behavior


def test_uploaded_paths_cache_is_bounded_at_documented_cap(captured_http, tmp_path):
    """A client that uploads (cap+5) distinct files keeps exactly cap
    entries. The first N-cap entries are evicted FIFO; the latest cap
    entries remain.
    """
    client = AriadneClient()
    captured_http.set_upload_response(
        {"path": "/srv/upload/sentinel", "filename": "x.bin", "size_bytes": 1}
    )

    cap = _UPLOADED_PATHS_CACHE_MAX
    overflow = 5

    # Exercise the file-keyed code path. Use the per-file mtime_ns to
    # produce distinct cache keys; we don't actually need real files
    # because ``captured_http`` short-circuits the network call. The
    # client does call ``path.stat()`` to build the cache key, so the
    # files must exist on disk.
    for i in range(cap + overflow):
        f = tmp_path / f"f_{i:05d}.bin"
        f.write_bytes(b"x")
        # Each upload call records the (path, mtime_ns) tuple. Force
        # the captured_http response.path to a unique value so the
        # cache stores distinct values too.
        captured_http.set_upload_response(
            {"path": f"/srv/upload/srv_{i}", "filename": f.name, "size_bytes": 1}
        )
        client._upload(f)

    assert len(client._uploaded_paths) == cap, (
        f"cache must cap at {cap}; got {len(client._uploaded_paths)}"
    )

    # FIFO: the oldest ``overflow`` entries are gone, the newest cap remain.
    keys = list(client._uploaded_paths.keys())
    # First-inserted should be evicted; last-inserted should remain.
    last_inserted_path = (tmp_path / f"f_{cap + overflow - 1:05d}.bin").resolve()
    assert any(
        Path(k[0]) == last_inserted_path
        for k in keys
        if isinstance(k, tuple) and isinstance(k[1], int)
    ), "most-recent insertion must remain in cache"

    first_inserted_path = (tmp_path / "f_00000.bin").resolve()
    assert not any(
        Path(k[0]) == first_inserted_path
        for k in keys
        if isinstance(k, tuple) and isinstance(k[1], int)
    ), "first insertion (overflowed) must be evicted"


def test_uploaded_paths_repeat_upload_does_not_inflate_cache(captured_http, tmp_path):
    """Re-uploading the same (path, mtime) hits cache and does NOT
    add a new entry. Pinned because a naive ``self._uploaded_paths[k]
    = path; popitem(last=False) while > cap`` could evict an entry
    we just touched.
    """
    client = AriadneClient()
    captured_http.set_upload_response(
        {"path": "/srv/upload/same", "filename": "f.bin", "size_bytes": 1}
    )

    f = tmp_path / "f.bin"
    f.write_bytes(b"x")

    client._upload(f)
    initial_size = len(client._uploaded_paths)

    # Second call: cache hit, no new upload, no new entry.
    client._upload(f)
    assert len(client._uploaded_paths) == initial_size
    # And no second multipart_upload call.
    assert len(captured_http.upload_calls) == 1


# ─────────────────────────────────────────────── §5 cache-hit/-miss alignment


def _document_response_dict() -> dict[str, Any]:
    return {
        "document_id": "doc-aligned-1",
        "source_file": "/srv/upload/aligned",
        "title": "x",
        "file_type": "txt",
        "engine": "markitdown-mock",
        "collection": "default",
        "warnings": [],
        "warnings_count": 0,
    }


def test_ingest_bytes_cache_hit_uses_shared_upload_core(captured_http):
    """nud §5 — on cache hit, ingest_bytes does NOT re-upload (parity
    with cache-miss in that respect) AND its downstream
    ``_create_document`` call uses the cached server path as the
    ``uri`` field (parity with what cache-miss would have produced).

    Pre-fix the cache-hit path was an inline branch with its own
    synthesis; the alignment fix routes both paths through
    ``_upload_with_cache_key`` so any future schema drift is felt
    in one place, not two.
    """
    client = AriadneClient()
    content = b"hello-world-aligned"
    fingerprint = hashlib.sha256(content).hexdigest()
    cache_key = ("bytes", fingerprint)

    # Pre-seed the cache as if a prior call already uploaded.
    client._remember_upload(cache_key, "/srv/upload/preseeded")

    captured_http.set_json_response(_document_response_dict())

    doc = client.ingest_bytes(content, "x.bin", collection="aligned")

    # No upload call: cache hit means no multipart_upload.
    assert len(captured_http.upload_calls) == 0

    # The /api/documents POST used the cached server path as the URI.
    last_json = captured_http.last_json_call()
    assert last_json["json_body"]["uri"] == "/srv/upload/preseeded", (
        f"cache-hit URI must come from the cached server path; "
        f"got {last_json['json_body']['uri']!r}"
    )
    assert doc.document_id == "doc-aligned-1"


def test_ingest_bytes_cache_miss_routes_through_shared_core(captured_http):
    """Sanity companion to the alignment probe: on cache miss the
    upload happens, the cache is populated via ``_remember_upload``
    (so the cap applies uniformly), and the downstream ``uri`` is
    the server-returned path.
    """
    client = AriadneClient()
    content = b"hello-cache-miss"
    fingerprint = hashlib.sha256(content).hexdigest()
    cache_key = ("bytes", fingerprint)

    captured_http.set_upload_response(
        {"path": "/srv/upload/freshly-uploaded", "filename": "y.bin", "size_bytes": len(content)}
    )
    captured_http.set_json_response(_document_response_dict())

    doc = client.ingest_bytes(content, "y.bin", collection="miss")

    assert len(captured_http.upload_calls) == 1
    assert client._uploaded_paths.get(cache_key) == "/srv/upload/freshly-uploaded"
    last_json = captured_http.last_json_call()
    assert last_json["json_body"]["uri"] == "/srv/upload/freshly-uploaded"
    assert doc.document_id == "doc-aligned-1"

"""Unit probes for `_format_search` — the `ariadne search` human-readable
display (ariadne--uuo.4).

`_format_search` is a pure `SearchResponse -> str` function with no
network seam, so these are in-process unit tests rather than the
subprocess canned-server pattern used by `test_confirmation_cli.py`
(that pattern exists to exercise `sys.stdin.isatty()`, which is
irrelevant here). The shared shape — assert on the formatted string —
is the same.

Covers design §8.2 / §8.3:
- bw-ingested result: a `status=/ticket=/assignee=` metadata summary
  line is emitted from `r.metadata`, between the collection/tokens
  line and the content snippet.
- non-bw result (`metadata == {}`): the metadata line is omitted
  entirely and nothing breaks.
- partial metadata: only the present fields render; absent (or falsy,
  e.g. `assignee: null`) fields are dropped.
- the content snippet is `r.text` truncated as before — the formatter
  is correct regardless of whether the text is YAML-polluted (pre
  uuo-2) or clean (post uuo-2); it just formats what the API returns.
"""

from __future__ import annotations

from ariadne_core_client.cli import _format_search
from ariadne_core_client.models import SearchResponse, SearchResult


def _resp(*results: SearchResult, query: str = "ticket lock scope") -> SearchResponse:
    return SearchResponse(
        query=query,
        top_k=5,
        collection="aresense",
        results_count=len(results),
        results=list(results),
    )


def test_bw_result_emits_metadata_summary_line() -> None:
    """A bw-ingested result renders a status/ticket/assignee line."""
    r = SearchResult(
        chunk_id="c1",
        document_id="doc-1",
        collection="aresense",
        text="The per-ticket lock spans the whole ticket.",
        section="6.8",
        token_count=142,
        relevance_score=0.8123,
        metadata={
            "bw_status": "open",
            "ticket_id": "ariadne--uuo",
            "assignee": "denson",
            "source_type": "bw_ticket",
        },
    )
    out = _format_search(_resp(r))
    assert "status=open" in out
    assert "ticket=ariadne--uuo" in out
    assert "assignee=denson" in out
    # Rendered as one space-joined line, in the curated order.
    assert "status=open  ticket=ariadne--uuo  assignee=denson" in out
    # The content snippet is still present.
    assert "The per-ticket lock spans the whole ticket." in out


def test_metadata_line_sits_between_tokens_line_and_snippet() -> None:
    """Design §8.2 ordering: collection/tokens line, then metadata
    summary line, then the content snippet."""
    r = SearchResult(
        document_id="doc-1",
        collection="aresense",
        text="body snippet here",
        token_count=10,
        relevance_score=0.5,
        metadata={"bw_status": "open", "ticket_id": "t-1", "assignee": "denson"},
    )
    out = _format_search(_resp(r))
    lines = [ln.strip() for ln in out.splitlines()]
    tokens_idx = next(i for i, ln in enumerate(lines) if ln.startswith("collection="))
    meta_idx = next(i for i, ln in enumerate(lines) if ln.startswith("status="))
    snippet_idx = next(i for i, ln in enumerate(lines) if ln == "body snippet here")
    assert tokens_idx < meta_idx < snippet_idx


def test_non_bw_result_omits_metadata_line() -> None:
    """A non-bw document has `metadata == {}` — the summary line is
    omitted entirely and the snippet still renders."""
    r = SearchResult(
        document_id="pdf-doc-1",
        collection="pdf-corpus",
        text="Chapter 3 of the manual describes the calibration step.",
        token_count=200,
        relevance_score=0.42,
        metadata={},
    )
    out = _format_search(_resp(r, query="calibration"))
    assert "status=" not in out
    assert "ticket=" not in out
    assert "assignee=" not in out
    # Nothing broke — the result is still rendered.
    assert "doc=pdf-doc-1" in out
    assert "Chapter 3 of the manual describes the calibration step." in out


def test_default_metadata_is_empty_dict_and_omits_line() -> None:
    """A SearchResult constructed without `metadata` (the dataclass
    default) behaves exactly like the non-bw `{}` case."""
    r = SearchResult(
        document_id="doc-x",
        collection="aresense",
        text="some text",
        token_count=5,
        relevance_score=0.1,
    )
    assert r.metadata == {}
    out = _format_search(_resp(r))
    assert "status=" not in out
    assert "doc=doc-x" in out


def test_partial_metadata_renders_only_present_fields() -> None:
    """Only the fields present in `r.metadata` render; absent or falsy
    (e.g. `assignee: null`) fields are dropped per §8.2."""
    r = SearchResult(
        document_id="doc-2",
        collection="aresense",
        text="unassigned ticket body",
        token_count=20,
        relevance_score=0.6,
        metadata={
            "bw_status": "open",
            "ticket_id": "ariadne--abc",
            "assignee": None,  # unassigned — dropped, not rendered as None
        },
    )
    out = _format_search(_resp(r))
    assert "status=open" in out
    assert "ticket=ariadne--abc" in out
    assert "assignee=" not in out


def test_no_results_message_unchanged() -> None:
    """The empty-result path is untouched by uuo-4."""
    out = _format_search(_resp(query="nothing"))
    assert out == "(no results for 'nothing')"


def test_long_text_is_truncated_at_200_chars() -> None:
    """The content snippet truncation behavior is unchanged: >200 chars
    is cut with a trailing ellipsis. uuo-4 does not depend on the text
    being clean (uuo-2) — it formats whatever the API returns."""
    long_text = "x" * 500
    r = SearchResult(
        document_id="doc-3",
        collection="aresense",
        text=long_text,
        token_count=300,
        relevance_score=0.7,
        metadata={"bw_status": "closed", "ticket_id": "t-9", "assignee": "denson"},
    )
    out = _format_search(_resp(r))
    assert "x" * 200 + "..." in out
    assert "x" * 201 not in out

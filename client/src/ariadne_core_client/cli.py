"""Ariadne Core CLI — stdlib-only argparse front end for AriadneClient.

Entry point: ``ariadne`` (wired via pyproject.toml [project.scripts]).

Subcommands
-----------
- ``ariadne ingest <path-or-url>`` — ingests a URL, a file, or a directory of files.
- ``ariadne search <query>``       — POST /api/search.
- ``ariadne list-documents``       — GET /api/documents (metadata only).
- ``ariadne list-collections``     — GET /api/collections.
- ``ariadne stats``                — GET /api/stats.
- ``ariadne health``               — GET /api/health (no auth).
- ``ariadne setup``                — Create .env from template.

Every subcommand supports ``--json`` for raw machine-readable output.
Each subcommand instantiates ``AriadneClient()`` with no args, so the usual
credential-resolution chain (explicit → env → .env → .mcp.json) applies.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from ariadne_core_client.client import AriadneClient
from ariadne_core_client.exceptions import AriadneClientError
from ariadne_core_client.models import (
    Collection,
    Document,
    Health,
    SearchResponse,
    Stats,
)


_ENV_TEMPLATE = """\
# Database (local development only -- for docker compose)
# Railway users: skip this. Railway injects DATABASE_URL automatically.
DB_PASSWORD=local-dev-only

# --- Embedding Provider ---
ARIADNE_EMBEDDING_API_KEY=<your api key here>
ARIADNE_EMBEDDING_MODEL=gemini-embedding-001
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
ARIADNE_EMBEDDING_DIMENSIONS=1536

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY=<your api key here>
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-3.1-flash-lite-preview
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/

# --- Client Authentication ---
# Auto-generated. Clients connect with this key via X-API-Key header.
ARIADNE_API_KEY=<your api key here>


# --- Railway Deployment ---
ARIADNE_URL=https://your-deployment.up.railway.app
"""


# --------------------------------------------------------------------- helpers

def _parse_tags(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _is_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _to_jsonable(obj: Any) -> Any:
    """Recursively convert dataclasses / lists / dicts to JSON-native types."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(item) for item in obj]
    return obj


def _print_json(obj: Any) -> None:
    json.dump(_to_jsonable(obj), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _iter_dir_files(root: Path, *, recursive: bool) -> Iterable[Path]:
    """Yield regular files under ``root``. Skips dotfiles and dot-directories."""
    if recursive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            yield path
    else:
        for path in sorted(root.iterdir()):
            if not path.is_file():
                continue
            if path.name.startswith("."):
                continue
            yield path


# ----------------------------------------------------------------- formatters

def _format_health(h: Health) -> str:
    return (
        f"status:            {h.status}\n"
        f"version:           {h.version}\n"
        f"engine:            {h.engine}\n"
        f"embedding_enabled: {h.embedding_enabled}"
    )


def _format_stats(s: Stats) -> str:
    lines = [
        f"total_documents:   {s.total_documents}",
        f"total_chunks:      {s.total_chunks}",
        f"total_collections: {s.total_collections}",
        f"embedding_enabled: {s.embedding_enabled}",
    ]
    if s.collections:
        lines.append("collections:")
        for name in sorted(s.collections):
            lines.append(f"  {name}: {s.collections[name]}")
    return "\n".join(lines)


def _format_collections(items: list[Collection]) -> str:
    if not items:
        return "(no collections)"
    rows = [("NAME", "DOCS", "DESCRIPTION")]
    for c in items:
        rows.append((c.name, str(c.document_count), c.description or ""))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    out = []
    for i, row in enumerate(rows):
        out.append(f"{row[0]:<{widths[0]}}  {row[1]:>{widths[1]}}  {row[2]:<{widths[2]}}")
        if i == 0:
            out.append(f"{'-' * widths[0]}  {'-' * widths[1]}  {'-' * widths[2]}")
    return "\n".join(out)


def _format_documents(items: list[Document]) -> str:
    if not items:
        return "(no documents)"
    rows = [("DOCUMENT_ID", "FILE_TYPE", "COLLECTION", "CHUNKS", "SOURCE_FILE")]
    for d in items:
        chunks = d.chunk_count if d.chunk_count is not None else d.chunks_count
        rows.append(
            (
                d.document_id,
                d.file_type or "",
                d.collection or "",
                str(chunks),
                d.source_file,
            )
        )
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    out = []
    for i, row in enumerate(rows):
        out.append(
            f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  "
            f"{row[2]:<{widths[2]}}  {row[3]:>{widths[3]}}  {row[4]:<{widths[4]}}"
        )
        if i == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def _format_search(resp: SearchResponse) -> str:
    if not resp.results:
        return f"(no results for {resp.query!r})"
    lines = [f"query: {resp.query!r}  top_k={resp.top_k}  results={resp.results_count}", ""]
    for i, r in enumerate(resp.results, 1):
        preview = r.text.replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:200] + "..."
        lines.append(f"[{i}] score={r.relevance_score:.4f}  doc={r.document_id}")
        meta_bits = []
        if r.collection:
            meta_bits.append(f"collection={r.collection}")
        if r.section:
            meta_bits.append(f"section={r.section}")
        if r.page is not None:
            meta_bits.append(f"page={r.page}")
        meta_bits.append(f"tokens={r.token_count}")
        lines.append("    " + "  ".join(meta_bits))
        lines.append(f"    {preview}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_document(d: Document) -> str:
    lines = [
        f"document_id:  {d.document_id}",
        f"source_file:  {d.source_file}",
    ]
    if d.title:
        lines.append(f"title:        {d.title}")
    if d.file_type:
        lines.append(f"file_type:    {d.file_type}")
    if d.collection:
        lines.append(f"collection:   {d.collection}")
    lines.append(f"chunks:       {d.chunks_count}")
    lines.append(f"dedup_skip:   {d.was_dedup_skip}")
    if d.tags:
        lines.append(f"tags:         {', '.join(d.tags)}")
    if d.processing_time_ms is not None:
        lines.append(f"processing:   {d.processing_time_ms} ms")
    if d.output_tokens_estimate is not None:
        lines.append(f"output_tokens: {d.output_tokens_estimate}")
    if d.token_savings_ratio is not None:
        lines.append(f"savings_ratio: {d.token_savings_ratio}")
    if d.store_status:
        lines.append(f"store_status: {d.store_status}")
    if d.warnings:
        lines.append("warnings:")
        for w in d.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines)


# ---------------------------------------------------------------- subcommands

def _cmd_health(args: argparse.Namespace) -> int:
    client = AriadneClient()
    result = client.health()
    if args.json:
        _print_json(result)
    else:
        print(_format_health(result))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    client = AriadneClient()
    result = client.stats()
    if args.json:
        _print_json(result)
    else:
        print(_format_stats(result))
    return 0


def _cmd_list_collections(args: argparse.Namespace) -> int:
    client = AriadneClient()
    items = client.list_collections()
    if args.json:
        _print_json(items)
    else:
        print(_format_collections(items))
    return 0


def _cmd_list_documents(args: argparse.Namespace) -> int:
    client = AriadneClient()
    items = client.list_documents(
        collection=args.collection,
        file_type=args.file_type,
        limit=args.limit,
    )
    if args.json:
        _print_json(items)
    else:
        print(_format_documents(items))
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    client = AriadneClient()
    resp = client.search(
        args.query,
        collection=args.collection,
        top_k=args.top_k,
    )
    if args.json:
        _print_json(resp)
    else:
        print(_format_search(resp))
    return 0


def _ingest_one_file(
    client: AriadneClient,
    path: Path,
    *,
    collection: str,
    tags: list[str] | None,
    source: str | None,
    as_json: bool,
    label: str | None = None,
) -> tuple[bool, Document | None, str | None]:
    """Ingest a single file. Returns (ok, document, error_message)."""
    prefix = f"{label} " if label else ""
    if not as_json:
        print(f"{prefix}ingesting {path}...", file=sys.stderr, flush=True)
    try:
        doc = client.ingest_file(
            path,
            collection=collection,
            tags=tags,
            source=source,
        )
        return True, doc, None
    except AriadneClientError as err:
        return False, None, str(err)


def _cmd_ingest(args: argparse.Namespace) -> int:
    client = AriadneClient()
    tags = _parse_tags(args.tags)

    target = args.target

    # URL path -----------------------------------------------------------------
    if _is_url(target):
        doc = client.ingest_url(
            target,
            collection=args.collection,
            tags=tags,
            source=args.source,
        )
        if args.json:
            _print_json(doc)
        else:
            print(_format_document(doc))
        return 0

    # Filesystem path ----------------------------------------------------------
    path = Path(target)
    if not path.exists():
        raise AriadneClientError(f"Path not found: {path}")

    if path.is_file():
        ok, doc, err = _ingest_one_file(
            client,
            path,
            collection=args.collection,
            tags=tags,
            source=args.source,
            as_json=args.json,
        )
        if not ok:
            print(f"error: {err}", file=sys.stderr)
            return 1
        assert doc is not None
        if args.json:
            _print_json(doc)
        else:
            print(_format_document(doc))
        return 0

    if path.is_dir():
        files = list(_iter_dir_files(path, recursive=args.recursive))
        if not files:
            print("(no files found)", file=sys.stderr)
            return 0

        results: list[dict[str, Any]] = []
        successes = 0
        failures = 0

        for idx, file_path in enumerate(files, 1):
            label = f"[{idx}/{len(files)}]"
            ok, doc, err = _ingest_one_file(
                client,
                file_path,
                collection=args.collection,
                tags=tags,
                source=args.source,
                as_json=args.json,
                label=label,
            )
            if ok:
                successes += 1
                assert doc is not None
                results.append(
                    {
                        "path": str(file_path),
                        "ok": True,
                        "document": _to_jsonable(doc),
                    }
                )
                if not args.json:
                    print(
                        f"{label} ok  {doc.document_id}  chunks={doc.chunks_count}"
                        f"  dedup={doc.was_dedup_skip}",
                        file=sys.stderr,
                        flush=True,
                    )
            else:
                failures += 1
                results.append({"path": str(file_path), "ok": False, "error": err})
                print(f"{label} FAIL {file_path}: {err}", file=sys.stderr, flush=True)

        if args.json:
            _print_json(
                {
                    "files_found": len(files),
                    "files_processed": successes,
                    "files_errored": failures,
                    "results": results,
                }
            )
        else:
            print(
                f"\ningested {successes}/{len(files)} "
                f"({failures} errored)",
                file=sys.stderr,
            )
        return 0 if failures == 0 else 1

    raise AriadneClientError(f"Unsupported target: {path}")


def _cmd_setup(args: argparse.Namespace) -> int:
    env_path = Path(".env")

    if env_path.exists() and not args.force:
        print(f".env already exists at {env_path.resolve()}", file=sys.stderr)
        print("Use --force to overwrite.", file=sys.stderr)
        return 1

    example_path = None
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        check = candidate / ".env.example"
        if check.is_file():
            example_path = check
            break

    if example_path:
        content = example_path.read_text(encoding="utf-8")
        print(f"Using template: {example_path}")
    else:
        content = _ENV_TEMPLATE
        print("No .env.example found — using built-in template.")

    env_path.write_text(content, encoding="utf-8")
    print(f"Created {env_path.resolve()}")
    print("Edit the file to fill in your credentials (look for placeholder values).")
    return 0


# --------------------------------------------------------------------- parser

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ariadne",
        description="Ariadne Core client CLI — talk to an Ariadne Core REST server.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    def add_json_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument("--json", action="store_true", help="Emit raw JSON instead of a human-readable summary.")

    # ingest
    p_ingest = sub.add_parser(
        "ingest",
        help="Ingest a URL, a file, or a directory of files.",
        description=(
            "Ingest content into Ariadne Core. Accepts http(s) URLs, local "
            "files, or local directories (use --recursive to walk subtrees)."
        ),
    )
    p_ingest.add_argument("target", help="URL, file path, or directory path.")
    p_ingest.add_argument("--collection", default="default", help="Target collection (default: %(default)s).")
    p_ingest.add_argument("--tags", help="Comma-separated tags.")
    p_ingest.add_argument(
        "--source",
        help="Source reference (URL or other pointer). Stored in agent_metadata.source_reference.",
    )
    p_ingest.add_argument(
        "--recursive",
        action="store_true",
        help="When TARGET is a directory, walk it recursively.",
    )
    add_json_flag(p_ingest)
    p_ingest.set_defaults(func=_cmd_ingest)

    # search
    p_search = sub.add_parser("search", help="Run a vector search against the server.")
    p_search.add_argument("query", help="Search query string.")
    p_search.add_argument("--collection", help="Restrict search to a collection.")
    p_search.add_argument("--top-k", type=int, default=5, help="Max results (default: %(default)s).")
    add_json_flag(p_search)
    p_search.set_defaults(func=_cmd_search)

    # list-documents
    p_ld = sub.add_parser("list-documents", help="List documents (metadata only).")
    p_ld.add_argument("--collection", help="Filter by collection name.")
    p_ld.add_argument("--file-type", help="Filter by file type (pdf, docx, ...).")
    p_ld.add_argument("--limit", type=int, default=20, help="Max documents (default: %(default)s).")
    add_json_flag(p_ld)
    p_ld.set_defaults(func=_cmd_list_documents)

    # list-collections
    p_lc = sub.add_parser("list-collections", help="List all collections.")
    add_json_flag(p_lc)
    p_lc.set_defaults(func=_cmd_list_collections)

    # stats
    p_stats = sub.add_parser("stats", help="Show system statistics.")
    add_json_flag(p_stats)
    p_stats.set_defaults(func=_cmd_stats)

    # health
    p_health = sub.add_parser("health", help="Check server health.")
    add_json_flag(p_health)
    p_health.set_defaults(func=_cmd_health)

    # setup
    p_setup = sub.add_parser(
        "setup",
        help="Create a .env file from .env.example template.",
        description=(
            "Creates a .env file in the current directory from the nearest "
            ".env.example template. Edit the file to fill in your credentials."
        ),
    )
    p_setup.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .env file.",
    )
    p_setup.set_defaults(func=_cmd_setup)

    return parser


# ----------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except AriadneClientError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

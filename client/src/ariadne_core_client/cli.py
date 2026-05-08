"""Ariadne Core CLI — stdlib-only argparse front end for AriadneClient.

Entry point: ``ariadne`` (wired via pyproject.toml [project.scripts]).

Subcommands
-----------
- ``ariadne login``                — Start OAuth 2.1 + PKCE flow; cache tokens in OS keyring.
- ``ariadne whoami``               — Show cached identity (email, sub, expiry).
- ``ariadne logout``               — Clear cached tokens for one host (or all hosts with ``--all``).
- ``ariadne ingest <path-or-url>`` — Ingest a URL, a file, or a directory of files.
- ``ariadne search <query>``       — POST /api/search.
- ``ariadne list-documents``       — GET /api/documents (metadata only).
- ``ariadne list-collections``     — GET /api/collections.
- ``ariadne stats``                — GET /api/stats.
- ``ariadne health``               — GET /api/health (no auth).
- ``ariadne setup``                — Create ``.env`` from template (for embedding /
  vision API keys; optional ``ARIADNE_HOST`` and ``ARIADNE_ACCESS_TOKEN``).

Every subcommand supports ``--json`` for raw machine-readable output.

Credential resolution
---------------------
Each data-plane subcommand calls ``_build_client(args)`` to build an
``AriadneClient(host=args.host)``. ``--host`` is resolved by
``auth.resolve_host`` with precedence: ``--host`` flag > ``ARIADNE_HOST``
env > ``~/.config/ariadne/default`` (written by ``ariadne login``).
The bearer token is sourced by ``auth.get_access_token`` with precedence:
``ARIADNE_ACCESS_TOKEN`` env (escape hatch — bypasses keyring) > keyring
cached access token > silent refresh via stored refresh token. There is
no ``.env`` / ``.mcp.json`` auto-resolution; ``ariadne setup`` writes a
template ``.env`` for OTHER (embedding / vision) API keys, but the
client never reads tokens from a ``.env`` file.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from ariadne_core_client import auth as _auth
from ariadne_core_client.auth import (
    AuthError,
    KeyringBackendUnavailable,
    format_whoami_human,
    format_whoami_json,
)
from ariadne_core_client.client import AriadneClient
from ariadne_core_client.exceptions import (
    AriadneClientError,
    ConfirmationRequired,
)
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
ARIADNE_EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta
ARIADNE_EMBEDDING_DIMENSIONS=1536

# --- Vision Provider (for image descriptions in documents) ---
ARIADNE_IMAGE_ENRICHMENT_API_KEY=<your api key here>
ARIADNE_IMAGE_ENRICHMENT_MODEL=gemini-2.0-flash
ARIADNE_IMAGE_ENRICHMENT_BASE_URL=https://generativelanguage.googleapis.com/v1beta

# --- Client Authentication (OAuth 2.1 + PKCE) ---
# Clients authenticate via the ``ariadne login`` command; tokens are
# stored in the OS keyring. No API key needed. Optionally set
# ARIADNE_HOST to avoid re-typing --host every time, and/or set
# ARIADNE_ACCESS_TOKEN as an escape hatch that bypasses the keyring
# entirely (useful for CI / automated scripts).
# ARIADNE_HOST=https://your-deployment.up.railway.app
# ARIADNE_ACCESS_TOKEN=<paste a short-lived JWT here for CI only>
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


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 if they aren't already.

    On Windows, Python's default stdout encoding is the legacy
    locale-dependent cp1252, which cannot represent code points above
    U+00FF (e.g. Greek θ in math notation). ``_print_json`` uses
    ``ensure_ascii=False`` intentionally for human-readable output, so
    the fix is at the stream layer, not the JSON encoder.

    Equivalent effect to setting ``PYTHONUTF8=1`` in the environment,
    but scoped to the CLI process — operators don't need to know the
    trick. Idempotent and safe on POSIX (already UTF-8). Defensive
    against AttributeError (non-text streams in tests) and
    io.UnsupportedOperation (non-reconfigurable wrappers).
    """
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", None) or "").lower()
        if enc not in ("utf-8", "utf8"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (AttributeError, io.UnsupportedOperation):
                pass


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


def _format_size(n: int) -> str:
    """Human-readable byte size — ~10 LOC stdlib helper.

    Used by the m5e confirmation prompt to render soft/hard caps and
    reported sizes alongside their raw byte counts.
    """
    if n < 1024:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(n)
    for unit in units:
        value /= 1024.0
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{n} B"  # pragma: no cover (loop always returns)


def _confirm_source_size(
    err: ConfirmationRequired, *, auto_yes: bool
) -> bool:
    """Return True if the caller confirms; False to abort.

    Prompt is written to stderr (post-90e stream-split convention: stderr
    is the operator-message stream; stdout is reserved for JSON
    payloads). The prompt itself goes via ``sys.stderr.write/flush``,
    NOT via ``input(prompt)`` — the stdlib's ``input`` writes its prompt
    to stdout, which would corrupt ``--json`` mode. See design §5.5.

    Auto-yes short-circuits to True with a single audit-trail line on
    stderr (NOT silent — design §11.A.4 / Nit 4: stderr ≠ JSON
    corruption, and the line is useful operator-side observability).

    Non-TTY stdin without auto-yes is fail-fast: don't silently
    auto-confirm (defeats the whole point of the soft cap), don't
    silently auto-decline (loses the token without operator awareness).
    """
    size_human = _format_size(err.reported_size)
    soft_human = _format_size(err.soft_cap)
    hard_human = _format_size(err.hard_cap)
    print(f"Source:        {err.source}", file=sys.stderr)
    print(
        f"Reported size: {size_human} ({err.reported_size:,} bytes)",
        file=sys.stderr,
    )
    if err.content_type:
        print(f"Content-type:  {err.content_type}", file=sys.stderr)
    if err.last_modified:
        print(f"Last modified: {err.last_modified}", file=sys.stderr)
    print(
        f"Default cap:   {soft_human} ; Hard limit: {hard_human}",
        file=sys.stderr,
    )

    if auto_yes:
        print("Proceed? [auto-confirmed via --yes]", file=sys.stderr)
        return True

    if not sys.stdin.isatty():
        # Non-interactive without --yes: fail-fast. Don't lose the
        # token by auto-declining; don't defeat the purpose by auto-
        # confirming.
        print(
            "error: confirmation required but stdin is not a TTY. "
            "Pass --yes to auto-confirm.",
            file=sys.stderr,
        )
        return False  # caller exits with non-zero

    # Write the prompt explicitly to stderr; pass empty string to
    # input() so the stdlib's stdout-prompt behavior does NOT fire.
    # Load-bearing for --json mode purity.
    sys.stderr.write("Proceed? [y/N]: ")
    sys.stderr.flush()
    try:
        answer = input("").strip().lower()
    except EOFError:
        # Closed stdin between isatty() check and read (rare, but real
        # in test subprocesses with input=b""); treat as decline.
        return False
    return answer in ("y", "yes")


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
        chunks = d.chunk_count
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
    lines.append(f"chunks:       {d.chunk_count}")
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

def _build_client(args: argparse.Namespace) -> AriadneClient:
    """Instantiate an AriadneClient honoring the subcommand's ``--host`` flag.

    Every subcommand in this CLI declares ``--host`` via
    ``add_host_flag`` (nested in ``_build_parser``); ``getattr`` keeps
    this safe if a future subcommand forgets. An AriadneAuthError here
    surfaces cleanly via ``main``'s top-level exception handler.
    """
    return AriadneClient(host=getattr(args, "host", None))


def _cmd_health(args: argparse.Namespace) -> int:
    client = _build_client(args)
    result = client.health()
    if args.json:
        _print_json(result)
    else:
        print(_format_health(result))
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    client = _build_client(args)
    result = client.stats()
    if args.json:
        _print_json(result)
    else:
        print(_format_stats(result))
    return 0


def _cmd_list_collections(args: argparse.Namespace) -> int:
    client = _build_client(args)
    items = client.list_collections()
    if args.json:
        _print_json(items)
    else:
        print(_format_collections(items))
    return 0


def _cmd_list_documents(args: argparse.Namespace) -> int:
    client = _build_client(args)
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
    client = _build_client(args)
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
    confirmation_token: str | None = None,
) -> tuple[bool, Document | None, str | None]:
    """Ingest a single file. Returns (ok, document, error_message).

    Note on the m5e selective re-raise (design §5.2.0 / §11.A.1):
    ``ConfirmationRequired`` is a subclass of ``AriadneClientError`` but
    must propagate so the call-site retry wrapper can prompt + re-issue
    with a token. We re-raise it explicitly inside the broad
    ``except AriadneClientError`` so the helper's tuple-of-failure
    return contract is preserved for every other error class.
    """
    prefix = f"{label} " if label else ""
    if not as_json and confirmation_token is None:
        # Don't re-print the "ingesting ..." line on a confirmed retry.
        print(f"{prefix}ingesting {path}...", file=sys.stderr, flush=True)
    try:
        doc = client.ingest_file(
            path,
            collection=collection,
            tags=tags,
            source=source,
            confirmation_token=confirmation_token,
        )
        return True, doc, None
    except AriadneClientError as err:
        # m5e: ConfirmationRequired is signal, not failure — let it
        # propagate to the call-site retry wrapper. Every other
        # AriadneClientError subclass continues to be handled here.
        if isinstance(err, ConfirmationRequired):
            raise
        return False, None, str(err)


def _cmd_ingest(args: argparse.Namespace) -> int:
    client = _build_client(args)
    tags = _parse_tags(args.tags)
    auto_yes = bool(getattr(args, "yes", False))

    target = args.target

    # URL path -----------------------------------------------------------------
    if _is_url(target):
        # m5e §5.2.2: literal retry shape. First call threads
        # collection/tags/source; on ConfirmationRequired, retry
        # threads the same kwargs PLUS confirmation_token. Drop-on-
        # retry would silently produce a Document with different
        # metadata than the operator intended.
        try:
            doc = client.ingest_url(
                target,
                collection=args.collection,
                tags=tags,
                source=args.source,
            )
        except ConfirmationRequired as err:
            if not _confirm_source_size(err, auto_yes=auto_yes):
                if sys.stdin.isatty():
                    print("Aborted.", file=sys.stderr)
                return 1
            doc = client.ingest_url(
                target,
                collection=args.collection,
                tags=tags,
                source=args.source,
                confirmation_token=err.confirmation_token,
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
        # m5e §5.2.2: literal retry shape. The helper re-raises
        # ConfirmationRequired (selective re-raise per §5.2.0); the
        # retry call threads the same kwargs PLUS confirmation_token.
        try:
            ok, doc, err = _ingest_one_file(
                client,
                path,
                collection=args.collection,
                tags=tags,
                source=args.source,
                as_json=args.json,
            )
        except ConfirmationRequired as cerr:
            if not _confirm_source_size(cerr, auto_yes=auto_yes):
                if sys.stdin.isatty():
                    print("Aborted.", file=sys.stderr)
                return 1
            ok, doc, err = _ingest_one_file(
                client,
                path,
                collection=args.collection,
                tags=tags,
                source=args.source,
                as_json=args.json,
                confirmation_token=cerr.confirmation_token,
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
        skipped = 0
        failures = 0

        for idx, file_path in enumerate(files, 1):
            label = f"[{idx}/{len(files)}]"
            # m5e: same per-file retry shape as the single-file branch.
            # --yes blanket-confirms every file in the batch.
            try:
                ok, doc, err = _ingest_one_file(
                    client,
                    file_path,
                    collection=args.collection,
                    tags=tags,
                    source=args.source,
                    as_json=args.json,
                    label=label,
                )
            except ConfirmationRequired as cerr:
                if not _confirm_source_size(cerr, auto_yes=auto_yes):
                    if sys.stdin.isatty():
                        print(
                            f"{label} Aborted.",
                            file=sys.stderr,
                        )
                    # Treat as a per-file failure and continue with
                    # the rest of the batch (consistent with the
                    # legacy "one file errored, others continue"
                    # semantic at line ~466 below).
                    failures += 1
                    results.append(
                        {
                            "path": str(file_path),
                            "ok": False,
                            "error": "Aborted by operator at confirmation prompt.",
                        }
                    )
                    continue
                ok, doc, err = _ingest_one_file(
                    client,
                    file_path,
                    collection=args.collection,
                    tags=tags,
                    source=args.source,
                    as_json=args.json,
                    label=label,
                    confirmation_token=cerr.confirmation_token,
                )
            if ok:
                assert doc is not None
                if doc.was_dedup_skip:
                    skipped += 1
                    verb = "skip"
                else:
                    successes += 1
                    verb = "ok"
                results.append(
                    {
                        "path": str(file_path),
                        "ok": True,
                        "document": _to_jsonable(doc),
                    }
                )
                if not args.json:
                    print(
                        f"{label} {verb}  {doc.document_id}  chunks={doc.chunk_count}"
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
                    "files_skipped": skipped,
                    "files_errored": failures,
                    "results": results,
                }
            )
        else:
            if skipped:
                print(
                    f"\ningested {successes}/{len(files)} "
                    f"({skipped} skipped via dedup, {failures} errored)",
                    file=sys.stderr,
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


# ------------------------------------------------------------- auth subcommands

def _resolve_host_or_fail(flag_value: str | None) -> str:
    """Wrap auth.resolve_host so CLI callers can surface the message cleanly."""
    try:
        return _auth.resolve_host(flag_value)
    except AuthError as err:
        print(f"error: {err}", file=sys.stderr)
        raise SystemExit(1) from err


def _build_keyring_store_or_fail():
    """Instantiate the real KeyringStore; print a platform-aware error on failure."""
    try:
        return _auth.KeyringStore()
    except KeyringBackendUnavailable as err:
        print(str(err), file=sys.stderr)
        raise SystemExit(1) from err


def _cmd_login(args: argparse.Namespace) -> int:
    host = _resolve_host_or_fail(args.host)
    store = _build_keyring_store_or_fail()
    try:
        info = _auth.login(host, store=store)
    except AuthError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    email = info.get("email") or "(unknown email)"
    print(f"Logged in to {info.get('host', host)} as {email}")
    return 0


def _cmd_logout(args: argparse.Namespace) -> int:
    host = _resolve_host_or_fail(args.host)
    store = _build_keyring_store_or_fail()
    try:
        _auth.logout(host, store=store)
    except AuthError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"Logged out of {host}")
    return 0


def _cmd_whoami(args: argparse.Namespace) -> int:
    host = _resolve_host_or_fail(args.host)
    # whoami honors ARIADNE_ACCESS_TOKEN only indirectly (via
    # get_access_token); the command itself is a pure keyring query,
    # so we still need the keyring.
    store = _build_keyring_store_or_fail()
    try:
        info = _auth.whoami(host, store=store)
    except AuthError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if args.json:
        sys.stdout.write(format_whoami_json(info) + "\n")
    else:
        print(format_whoami_human(info))
    # If the stored access token is past its expiry, we still succeed
    # (the user can refresh via the next call to get_access_token) but
    # signal it in the exit code so scripts can detect stale state.
    remaining = info.get("expires_in_seconds")
    if isinstance(remaining, int) and remaining <= 0:
        return 2
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

    def add_host_flag(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--host",
            help=(
                "Ariadne server URL. Defaults to $ARIADNE_HOST, then "
                "~/.config/ariadne/default (written by 'ariadne login')."
            ),
        )

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
    p_ingest.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=(
            "Auto-confirm sources above the server's soft cap "
            "(m5e --max_source_bytes). Without this flag, the CLI "
            "prompts y/N when the server requests confirmation. "
            "Required when stdin is not a TTY (e.g. piped or scripted)."
        ),
    )
    add_json_flag(p_ingest)
    add_host_flag(p_ingest)
    p_ingest.set_defaults(func=_cmd_ingest)

    # search
    p_search = sub.add_parser("search", help="Run a vector search against the server.")
    p_search.add_argument("query", help="Search query string.")
    p_search.add_argument("--collection", help="Restrict search to a collection.")
    p_search.add_argument("--top-k", type=int, default=5, help="Max results (default: %(default)s).")
    add_json_flag(p_search)
    add_host_flag(p_search)
    p_search.set_defaults(func=_cmd_search)

    # list-documents
    p_ld = sub.add_parser("list-documents", help="List documents (metadata only).")
    p_ld.add_argument("--collection", help="Filter by collection name.")
    p_ld.add_argument("--file-type", help="Filter by file type (pdf, docx, ...).")
    p_ld.add_argument("--limit", type=int, default=20, help="Max documents (default: %(default)s).")
    add_json_flag(p_ld)
    add_host_flag(p_ld)
    p_ld.set_defaults(func=_cmd_list_documents)

    # list-collections
    p_lc = sub.add_parser("list-collections", help="List all collections.")
    add_json_flag(p_lc)
    add_host_flag(p_lc)
    p_lc.set_defaults(func=_cmd_list_collections)

    # stats
    p_stats = sub.add_parser("stats", help="Show system statistics.")
    add_json_flag(p_stats)
    add_host_flag(p_stats)
    p_stats.set_defaults(func=_cmd_stats)

    # health
    p_health = sub.add_parser("health", help="Check server health.")
    add_json_flag(p_health)
    add_host_flag(p_health)
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

    # login
    p_login = sub.add_parser(
        "login",
        help="Sign in to an Ariadne server via OAuth 2.1 + PKCE.",
        description=(
            "Run the OAuth 2.1 PKCE loopback flow to sign in to an Ariadne "
            "server. Opens a browser for the Auth0 consent step, captures the "
            "callback on a local loopback port, exchanges the code for "
            "access + refresh tokens, and stores them in your OS keyring."
        ),
    )
    p_login.add_argument(
        "--host",
        help=(
            "Ariadne server URL. Defaults to $ARIADNE_HOST, then "
            "~/.config/ariadne/default. A successful login overwrites "
            "~/.config/ariadne/default with this host."
        ),
    )
    p_login.set_defaults(func=_cmd_login)

    # logout
    p_logout = sub.add_parser(
        "logout",
        help="Clear all stored credentials for an Ariadne server.",
        description=(
            "Remove all refresh/access/expiry entries for the specified host "
            "from the OS keyring. Idempotent — safe to run when already logged out."
        ),
    )
    p_logout.add_argument(
        "--host",
        help="Ariadne server URL. Same precedence as 'login'.",
    )
    p_logout.set_defaults(func=_cmd_logout)

    # whoami
    p_whoami = sub.add_parser(
        "whoami",
        help="Show the user and expiry of the currently stored Ariadne token.",
        description=(
            "Decode the cached access token and print the user email, "
            "subject, and expiry. Does NOT contact the server or refresh the "
            "token — this is a local 'what's in my keyring' query. Exits with "
            "code 2 if the stored token has already expired."
        ),
    )
    p_whoami.add_argument(
        "--host",
        help="Ariadne server URL. Same precedence as 'login'.",
    )
    add_json_flag(p_whoami)
    p_whoami.set_defaults(func=_cmd_whoami)

    return parser


# ----------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfirmationRequired:
        # ConfirmationRequired must always be handled by the per-_cmd_*
        # wrapper that knows how to surface the prompt. If it leaks all
        # the way up here, a future _cmd_* called an ingest_* helper
        # without wrapping. Surface a distinct exit code (2) so the
        # regression is loud, not a silent ``error: [413] ...``.
        print(
            "internal error: confirmation required prompt was not surfaced",
            file=sys.stderr,
        )
        return 2
    except AriadneClientError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

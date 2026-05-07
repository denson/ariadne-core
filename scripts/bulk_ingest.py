#!/usr/bin/env python3
"""Bulk directory ingest for Ariadne Core.

Uploads each file under a directory via POST /api/upload, then calls
POST /api/documents to convert and store. Serial, stdlib-only.

Usage:
    python scripts/bulk_ingest.py <directory> --collection <name> [options]
"""
import argparse
import datetime as _dt
import signal
import sys
import time
from pathlib import Path

from ariadne_client import AriadneClient, AriadneClientError


DEFAULT_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".csv",
    ".html", ".txt", ".md", ".json", ".xml",
    ".rtf", ".epub", ".eml", ".msg", ".zip", ".ipynb",
    ".wav", ".mp3",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".svg",
}


class _Interrupted(Exception):
    pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="bulk_ingest",
        description="Bulk-ingest a directory into Ariadne Core.",
    )
    p.add_argument("directory", type=Path, help="Directory containing files to ingest")
    p.add_argument("--collection", required=True, help="Target collection name")
    p.add_argument("--recursive", action="store_true",
                   help="Walk subdirectories (default: top level only)")
    p.add_argument("--tags", default="",
                   help="Comma-separated tags applied to every document")
    p.add_argument("--agent-notes", default=None,
                   help="agent_notes applied to every document")
    p.add_argument("--dry-run", action="store_true",
                   help="List what would be ingested, don't upload")
    p.add_argument("--skip-existing", action="store_true",
                   help="Count server-side dedup hits as skipped rather than succeeded")
    p.add_argument("--max-files", type=int, default=None,
                   help="Stop after N successful ingests")
    p.add_argument("--extensions", default=None,
                   help="Comma-separated extensions to include "
                        "(default: all supported)")
    p.add_argument("--log-file", type=Path, default=None,
                   help="Write detailed log to this file (default: stderr)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip confirmation prompt")
    return p.parse_args(argv)


def _normalize_extensions(raw: str | None) -> set[str]:
    if not raw:
        return set(DEFAULT_EXTENSIONS)
    exts = set()
    for tok in raw.split(","):
        tok = tok.strip().lower()
        if not tok:
            continue
        if not tok.startswith("."):
            tok = "." + tok
        exts.add(tok)
    return exts


def _discover_files(directory: Path, recursive: bool, extensions: set[str]) -> list[Path]:
    if not directory.exists():
        raise AriadneClientError(f"Directory not found: {directory}")
    if not directory.is_dir():
        raise AriadneClientError(f"Not a directory: {directory}")
    it = directory.rglob("*") if recursive else directory.iterdir()
    files = [
        p for p in it
        if p.is_file() and p.suffix.lower() in extensions
    ]
    files.sort()
    return files


class _Logger:
    """Writes detailed events to either stderr or a file.

    Separately writes failed-file records to bulk_ingest_errors.log in the
    source directory. Honors TTY status for \\r-style progress rewrites.
    """

    def __init__(self, detail_path: Path | None, errors_path: Path):
        self._detail_fh = open(detail_path, "a", encoding="utf-8") if detail_path else None
        self._detail_is_file = detail_path is not None
        self._errors_fh = open(errors_path, "a", encoding="utf-8")
        self._tty = sys.stdout.isatty() and not self._detail_is_file
        self._last_was_carriage = False

    def status(self, line: str) -> None:
        """Transient per-file status. Uses \\r on a tty, newline otherwise."""
        if self._tty:
            sys.stdout.write("\r" + line.ljust(100))
            sys.stdout.flush()
            self._last_was_carriage = True
        else:
            self._write_detail(line)

    def event(self, line: str) -> None:
        """Permanent line (headers, errors, summary). Always on its own line."""
        if self._tty and self._last_was_carriage:
            sys.stdout.write("\n")
            self._last_was_carriage = False
        if self._detail_is_file:
            self._write_detail(line)
        else:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def error_record(self, filename: str, message: str) -> None:
        ts = _dt.datetime.now().isoformat(timespec="seconds")
        self._errors_fh.write(f"{ts}\t{filename}\t{message}\n")
        self._errors_fh.flush()

    def _write_detail(self, line: str) -> None:
        if self._detail_fh:
            self._detail_fh.write(line + "\n")
            self._detail_fh.flush()
        else:
            sys.stderr.write(line + "\n")
            sys.stderr.flush()

    def close(self) -> None:
        if self._tty and self._last_was_carriage:
            sys.stdout.write("\n")
            self._last_was_carriage = False
        if self._detail_fh:
            self._detail_fh.close()
        self._errors_fh.close()


def _confirm(prompt: str) -> bool:
    try:
        reply = input(prompt).strip().lower()
    except EOFError:
        return False
    return reply in ("y", "yes")


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _install_sigint_handler() -> None:
    def _raise(_signum, _frame):
        raise _Interrupted()
    signal.signal(signal.SIGINT, _raise)


def run(args: argparse.Namespace) -> int:
    extensions = _normalize_extensions(args.extensions)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()] or None

    directory = args.directory.resolve()
    files = _discover_files(directory, args.recursive, extensions)

    errors_path = directory / "bulk_ingest_errors.log"
    logger = _Logger(args.log_file, errors_path)

    logger.event("Ariadne Core bulk ingest")
    logger.event(f"  Source: {directory}")
    logger.event(f"  Target: {args.collection}")
    logger.event(f"  Files:  {len(files)}")

    if not files:
        logger.event("No matching files found.")
        logger.close()
        return 0

    if args.dry_run:
        logger.event("")
        logger.event("Dry run — files that would be ingested:")
        for f in files:
            logger.event(f"  {f.relative_to(directory)}")
        logger.close()
        return 0

    if not args.yes:
        if not _confirm(f"\nProceed with ingest into '{args.collection}'? [y/N] "):
            logger.event("Aborted.")
            logger.close()
            return 1

    try:
        client = AriadneClient()
    except AriadneClientError as e:
        logger.event(f"Config error: {e}")
        logger.close()
        return 2

    logger.event("")
    logger.event("Starting...")

    _install_sigint_handler()

    attempted = 0
    succeeded = 0
    failed = 0
    skipped = 0
    total = len(files)
    t0 = time.monotonic()
    width = len(str(total))

    try:
        for idx, local_path in enumerate(files, start=1):
            if args.max_files is not None and succeeded >= args.max_files:
                logger.event(f"Reached --max-files={args.max_files}, stopping.")
                break

            attempted += 1
            rel = local_path.relative_to(directory)
            prefix = f"  [{idx:0{width}d}/{total}] {rel}"
            logger.status(f"{prefix} ->uploading...")

            try:
                server_path = client.upload_file(local_path)
                logger.status(f"{prefix} ->converting...")
                result = client.convert_document(
                    uri=server_path,
                    collection=args.collection,
                    tags=tags,
                    agent_notes=args.agent_notes,
                )
            except AriadneClientError as e:
                failed += 1
                msg = str(e)
                logger.event(f"{prefix} ->FAILED: {msg}")
                logger.error_record(str(rel), msg)
                continue
            except OSError as e:
                failed += 1
                msg = f"read error: {e}"
                logger.event(f"{prefix} ->FAILED: {msg}")
                logger.error_record(str(rel), msg)
                continue

            chunks = result.get("chunk_count", result.get("chunks", 0))
            dedup = bool(result.get("was_dedup_skip"))

            if dedup and args.skip_existing:
                skipped += 1
                logger.status(f"{prefix} ->SKIPPED (dedup)")
                logger.event(f"{prefix} ->SKIPPED (dedup)")
            else:
                succeeded += 1
                tag = "OK (dedup)" if dedup else f"OK ({chunks} chunks)"
                logger.status(f"{prefix} ->{tag}")

    except _Interrupted:
        logger.event("")
        logger.event("Interrupted by user.")

    elapsed = time.monotonic() - t0

    logger.event("")
    logger.event("Done.")
    logger.event(f"  Attempted: {attempted}")
    logger.event(f"  Succeeded: {succeeded}")
    logger.event(f"  Failed:    {failed}")
    logger.event(f"  Skipped:   {skipped} (dedup)")
    logger.event(f"  Elapsed:   {_format_elapsed(elapsed)}")
    if failed:
        logger.event("")
        logger.event(f"Errors logged to: {errors_path}")

    logger.close()
    return 0 if failed == 0 else 3


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return run(args)
    except AriadneClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

# Path Resolution Feature Results

**Date:** 2026-04-05

## Files Modified

### 1. `src/pipeline/api/routes.py`
- Added imports: `os`, `uuid`, `UploadFile`, `File`
- Added `POST /api/upload` endpoint that saves files to `/data/incoming/<uuid>_<filename>` and returns the container-internal path

### 2. `src/pipeline/mcp_stdio_proxy.py`
- Added imports: `os`, `Path`, `PurePosixPath`, `PureWindowsPath`
- Added `_is_local_file()` helper — detects local file paths (not http/https, not `/data/` paths), handles `file://` URIs
- Added `_upload_file()` helper — uploads local file to `POST /api/upload`, returns container path
- Wired path resolution into `convert_document`: detects local paths and uploads before forwarding
- Added limitation comment to `ingest` docstring: local directory paths require bind mount

### 3. `src/Dockerfile`
- Moved `useradd` before `mkdir` so data directories are created after user exists
- Added `chown -R ariadne:ariadne /data` so the non-root user can write to `/data/incoming/`

### 4. `SPEC.md`
- Added "Path Resolution" section documenting the STDIO proxy upload flow and transport-specific behavior

## Verification Results

| # | Check | Pass/Fail | Notes |
|---|-------|-----------|-------|
| 1 | Upload endpoint works | Pass | `{"path": "/data/incoming/5f6e8940_test_upload.txt", "filename": "test_upload.txt", "size": 16}` |
| 2 | Uploaded file exists in container | Pass | File visible in `/data/incoming/` with correct ownership (ariadne:ariadne) |
| 3 | convert_document works with uploaded path | Pass | Successful conversion of `/data/incoming/5f6e8940_test_upload.txt` — got markdown output, file_type "txt" |
| 4 | STDIO proxy resolves local paths | N/A (code verified) | STDIO proxy not testable from HTTP MCP connection; verified by component testing (upload + convert both work) and code inspection |
| 5 | HTTP URLs still work | Pass | `https://httpbin.org/robots.txt` converted successfully, no regression |

## Issues Encountered

1. **Permission denied on `/data/incoming/`** — The Dockerfile created `/data/incoming/` as root before switching to the `ariadne` user. Fixed by reordering: create user first, then create directories and chown to ariadne. Also fixed the running container with `docker compose exec -u root api chown`.

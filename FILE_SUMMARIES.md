# Ariadne Core — File Summaries

## Root Directory

### FIXES.md
A gap tracker documenting the differences between the target specification and the current codebase, organized into 10 numbered fixes with target state, current state, what to change, and how to test each item. Fixes include config env vars, ffmpeg support, image warnings, search filters, the ingest tool, list_collections tool, format strings, MCP instructions, and skill merging.

### HTTP_proxy_fix.md
Comprehensive documentation of a path resolution fix for the MCP HTTP proxy running on the host machine to intercept and auto-upload local file paths before forwarding requests to the container, solving the issue where STDIO and Streamable HTTP connections fail with local paths.

### IMPLEMENT.md
Step-by-step implementation instructions for Claude Code to build the fixes listed in FIXES.md, organized into phases (independent fixes, new tools, string cleanup, validation) with detailed guidance on code changes, test approaches, and acceptance criteria based on the skill file.

### README.md
An overview of Ariadne Core as an open-source document extraction and retrieval pipeline for personal use that converts documents into clean Markdown and searchable embeddings, exposing them via MCP server and REST API with dedup, provenance tracking, and support for over 20 formats.

### SPEC.md
The source-of-truth technical specification describing how Ariadne Core works, including supported formats, deployment options, configuration, MCP tool definitions, REST API endpoints, dedup behavior, provenance tracking, caller metadata, and expected agent behavior patterns.

### eval-results.md
A format coverage evaluation report documenting test results across 231 files, showing format support by extension with pass/fail/skip/timeout counts and a support matrix indicating which formats are fully supported, partially supported, or unsupported by MarkItDown.

---

## docs/

### configuration.md
A configuration reference guide explaining the three-layer config system (built-in defaults, ariadne.yaml, environment variables), detailing every option in ariadne.yaml including database, redis, vector store, embedding, image enrichment, markitdown, chunking, API, paths, and logging settings.

### docint-architecture.md
A detailed architecture specification covering the design philosophy, system overview, extraction engine with format support and limitations, processing pipeline including dedup and chunking, vector store options, MCP server transport and tools, and the cost stack showing how extraction is free while only embedding and vision API calls incur costs.

### installation.md
A step-by-step installation guide covering prerequisites, configuration via .env, starting the Docker stack, verification of health endpoints, connecting MCP clients, and troubleshooting common issues like port conflicts and API key problems.

### mcp-setup.md
A client connection guide documenting how to connect Claude Desktop, Claude Code, Cursor, OpenAI Desktop, and Gemini Desktop to Ariadne Core via the HTTP proxy on port 8081, including server deployment instructions for remote agents and comprehensive troubleshooting steps.

### ob1-integration.md
An integration guide for connecting Open Brain agents to Ariadne Core via MCP or REST API, covering setup, collection strategy, provenance tracking, token efficiency benefits, and a pseudo-code example of a daily capture workflow.

---

## docs/patches/

### 001-search-response-fields.md
A documentation patch specifying the exact response fields for the search tool across four files (mcp_server.py, mcp_stdio_proxy.py, docint-architecture.md, and SKILL.md), ensuring consistency about what fields are returned and removing phantom fields like source_file and document link.

### 002-path-resolution.md
A skill documentation patch adding explicit guidance to SKILL.md about path resolution behavior across three transports (STDIO proxy auto-upload, HTTP MCP manual upload, bind mounts) and the ingest tool limitation with local directories.

### 003-path-resolution-streamable-http.md
An implementation specification for a new MCP HTTP proxy running on the host machine that intercepts local file paths, uploads them to the REST API, and rewrites URIs before forwarding to the container, with detailed implementation steps for new files and modifications.

---

## skills/ariadne-document-intelligence/

### README.md
A skill installation guide for the ariadne-document-intelligence skill (v2.0.0), describing what the skill teaches agents (ingestion, search, collection management, caller metadata), listing requirements, installation locations for different clients, and supported formats including image limitations.

### SKILL.md
A comprehensive skill definition teaching agents how to use Ariadne Core, covering tool availability, token efficiency rationale, chunking strategies, collection selection, caller metadata requirements, six key processes (ingesting documents, batch ingestion, searching, browsing, handling errors, Open Brain bridging), and search filter reference.

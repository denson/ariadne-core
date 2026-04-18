# DAVE_DONE — Query API Pass 4

Pass 4 complete on master. `source_reference` is denormalized onto the
`documents` table; all three list-level filters (`tag`, `has_warnings`,
`has_source_reference`) are pushed into SQL `WHERE`; migrations are
consolidated into a single clean `001_initial.sql`. `total_is_exact`
is now structurally always `true`.

This pass is **destructive on prod** — the consolidated 001 drops
`documents.markdown_path` and `documents.pages`, so the existing live
schema cannot be migrated forward. Bob must wipe and redeploy as one
atomic step (instructions at the bottom).

---

## 1. SHA pushed

The single Pass 4 commit is the current HEAD of `origin/main`
immediately after this push. Bob: run `git fetch origin && git log -1
origin/main` to see the exact SHA — it will be the first commit whose
message begins with **"Query API Pass 4: denormalize source_reference,
push down filters, consolidate migrations"**.

## 2. Files touched

Modified:

- `migrations/001_initial.sql` — overwritten as the single
  source-of-truth consolidated schema
- `src/pipeline/dedup.py` — `_extract_source_reference` helper;
  `PgDedupStore.record_interaction` and `update_document_metadata`
  propagate `agent_metadata.source_reference` into
  `documents.source_reference`; `PgDedupStore.list_documents` accepts
  `tag`, `has_warnings`, `has_source_reference` keyword-only filters
  pushed into SQL; `InMemoryDedupStore` gains symmetric filtering, a
  new `get_source_reference`, an internal `_doc_source_ref` dict, and
  a matching `list_documents`; `DedupStore` protocol extended
- `src/pipeline/api/routes.py` — `list_documents` and
  `aggregate_documents` now make a single `_dedup_store.list_documents(...)`
  call with all filters passed through; `_has_source_reference` helper
  deleted; post-query filter block deleted; `total_is_exact` is always
  `True`
- `SPEC.md` — removed the Pass-2 "`total_count` semantics" caveat
  paragraph (the one that said `total_is_exact` could be `false` when
  filters were active)
- `tests/test_routes_list_documents.py` — flipped
  `total_is_exact` assertion under tag filter to `True`; added
  `test_list_documents_pagination_under_filter` (30 docs, 10 with
  warnings, `limit=5 offset=5 has_warnings=true` returns 5 rows,
  `total_count==10`, `total_is_exact==True`)

Deleted:

- `migrations/002_add_agent_notes.sql`
- `migrations/003_search_log.sql`
- `migrations/004_soft_delete.sql`
- `migrations/005_warnings_column.sql`

Added:

- `tests/test_dedup_source_reference.py` — 4 tests exercising the Pg
  write path: `record_interaction` writes the column, subsequent
  interactions overwrite (latest-wins), the sentinel value
  `"unknown"` is stored verbatim but excluded by
  `has_source_reference=True`, and `update_document_metadata` also
  writes the column

## 3. Consolidated `migrations/001_initial.sql`

```sql
-- Ariadne Core — Initial Database Schema
-- Requires: PostgreSQL 16+ with pgvector extension
--
-- This file is the single source of truth for a fresh deploy. It
-- folds together what was historically 001-005 plus the Pass 4
-- source_reference denormalization and pushdown-index work. Prior
-- migration files (002-005) have been removed — this is the schema
-- we would write today. On an empty database the BL-25 runner
-- applies this file exactly once and records version
-- '001_initial.sql' in schema_migrations.

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Collections: logical namespaces for documents
-- ============================================================================
CREATE TABLE collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed the default collection
INSERT INTO collections (name, description)
VALUES ('default', 'Default collection');

-- ============================================================================
-- Documents: one row per unique document per collection
-- ============================================================================
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID REFERENCES collections(id),
    source_file TEXT NOT NULL,
    content_fingerprint TEXT,
    file_type TEXT NOT NULL,
    engine TEXT NOT NULL DEFAULT 'markitdown',
    processing_time_ms INTEGER,
    output_tokens_estimate INTEGER,
    token_savings_ratio REAL,
    markdown TEXT,
    title TEXT,
    tags TEXT[] DEFAULT '{}',
    warnings TEXT[] NOT NULL DEFAULT '{}',
    source_reference TEXT,
    processing_chain JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TIMESTAMPTZ DEFAULT NULL,
    deletion_scheduled_at TIMESTAMPTZ DEFAULT NULL
);

-- Content fingerprint dedup (scoped to collection)
CREATE UNIQUE INDEX idx_documents_fingerprint
    ON documents (collection_id, content_fingerprint)
    WHERE content_fingerprint IS NOT NULL;

-- Fast lookups by collection
CREATE INDEX idx_documents_collection ON documents (collection_id);

-- Partial index supporting has_source_reference=true filter.
-- Excludes empty and the sentinel 'unknown' value so those rows are
-- treated as "no provenance" for filter purposes while preserving the
-- raw value for display / audit.
CREATE INDEX idx_documents_source_reference
    ON documents (source_reference)
    WHERE source_reference IS NOT NULL
      AND source_reference <> ''
      AND source_reference <> 'unknown';

-- GIN indexes on array columns — near-free at current corpus size and
-- future-proof scale without changing filter semantics.
CREATE INDEX idx_documents_tags ON documents USING GIN (tags);
CREATE INDEX idx_documents_warnings ON documents USING GIN (warnings);

-- ============================================================================
-- Document interactions: one row per agent call, even on dedup collision
-- ============================================================================
CREATE TABLE document_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id),
    agent_id TEXT,
    agent_type TEXT,
    model TEXT,
    initiated_by TEXT,
    action TEXT NOT NULL DEFAULT 'ingest',
    was_dedup_skip BOOLEAN DEFAULT false,
    agent_notes TEXT,
    agent_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Interaction queries
CREATE INDEX idx_interactions_document ON document_interactions (document_id);
CREATE INDEX idx_interactions_agent ON document_interactions (agent_id);
CREATE INDEX idx_interactions_agent_type ON document_interactions (agent_type);
CREATE INDEX idx_interactions_collection ON document_interactions (collection_id);

-- ============================================================================
-- Chunks: document segments with vector embeddings
--
-- NOTE: The embedding column dimension is configured at runtime via
-- ariadne.yaml (embedding.dimensions). The app validates/creates the
-- column with the correct dimension on startup. Default: 1536
-- (gemini-embedding-001). If you run this migration manually, replace
-- %EMBEDDING_DIM% with your configured dimension (e.g. 1536, 1024, 768).
-- ============================================================================
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    collection_id UUID REFERENCES collections(id),
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    section TEXT,
    page_start INTEGER,
    page_end INTEGER,
    token_count INTEGER,
    embedding_model TEXT,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- HNSW index for vector search (created by the app on startup if missing,
-- using the configured embedding dimension)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Fast lookups by collection and document
CREATE INDEX idx_chunks_collection ON chunks (collection_id);
CREATE INDEX idx_chunks_document ON chunks (document_id);

-- ============================================================================
-- Search log: one row per /api/search call
-- ============================================================================
CREATE TABLE IF NOT EXISTS search_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    collection TEXT,
    filters JSONB,
    top_k INTEGER,
    results_count INTEGER,
    result_document_ids UUID[],
    agent_id TEXT,
    agent_type TEXT,
    model TEXT,
    initiated_by TEXT,
    agent_notes TEXT,
    agent_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_search_log_created_at ON search_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_log_agent_id ON search_log (agent_id);
CREATE INDEX IF NOT EXISTS idx_search_log_initiated_by ON search_log (initiated_by);

-- ============================================================================
-- Jobs: batch processing tracking
-- ============================================================================
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    collection_id UUID REFERENCES collections(id),
    agent_id TEXT,
    agent_type TEXT,
    initiated_by TEXT,
    total_files INTEGER DEFAULT 0,
    completed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]',
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- API keys: hashed keys for REST API authentication
-- ============================================================================
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    default_collection TEXT,
    org_id UUID DEFAULT '00000000-0000-0000-0000-000000000000',
    rate_limit_per_minute INTEGER DEFAULT 100,
    created_at TIMESTAMPTZ DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
```

## 4. Migration delete list

```
$ git ls-files migrations/
migrations/001_initial.sql
```

Only one file tracked. `002_add_agent_notes.sql`, `003_search_log.sql`,
`004_soft_delete.sql`, `005_warnings_column.sql` are gone.

## 5. Local fresh-volume proof

Fresh volume, boot, `/api/health`, and a `list_documents` call:

```
$ DB_PASSWORD=local-dev-only docker compose down -v
$ DB_PASSWORD=local-dev-only docker compose up -d
 Container ariadne-core-postgres-1 Started

$ docker exec ariadne-core-postgres-1 psql -U app -d pipeline \
    -c "SELECT version FROM schema_migrations ORDER BY applied_at;"
     version
-----------------
 001_initial.sql
(1 row)

$ python -m uvicorn pipeline.api.app:app --host 127.0.0.1 --port 8777 &
$ curl -s http://127.0.0.1:8777/api/health
{"status":"healthy","version":"0.1.0","engine":"markitdown","embedding_enabled":true}
HTTP 200

$ curl -s "http://127.0.0.1:8777/api/documents?collection=default&limit=5"
{"documents":[],"total_count":0,"total_is_exact":true,"limit":5,"offset":0}
HTTP 200
```

BL-25 migration runner sees the empty `schema_migrations` table,
applies `001_initial.sql`, records the version. Server boots; health
returns 200; list returns `total_is_exact: true` on an empty fresh
schema.

## 6. Test output

```
$ DATABASE_URL=postgresql://app:local-dev-only@localhost:5432/pipeline \
    python -m pytest tests/ -q
........................................................................ [ 30%]
........................................................................ [ 60%]
........................................................................ [ 91%]
.....................                                                    [100%]
237 passed in 9.26s

$ python -m pytest client/tests/ -q
............                                                             [100%]
12 passed in 0.04s
```

No skips of the Pg integration suite — `test_dedup_source_reference.py`
ran live against a real Postgres, proving the column is written by
`record_interaction` and `update_document_metadata`, and the
`'unknown'` sentinel is stored verbatim but excluded by the
`has_source_reference=True` filter.

## 7. Bob handoff — DESTRUCTIVE, READ BEFORE DEPLOY

> This pass requires a destructive prod action. **DO NOT DEPLOY UNTIL
> YOU WIPE THE RAILWAY POSTGRES SCHEMA.** The consolidated 001 will
> fail against the existing prod schema because columns were
> renamed/dropped. The intended procedure is:
>
> 1. `railway link` — confirm correct project / env
> 2. `railway run psql "$DATABASE_URL" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pgcrypto;"`
> 3. Trigger a manual redeploy in Railway (BL-9 — auto-deploy is
>    unreliable)
> 4. Watch logs: confirm the BL-25 runner sees empty
>    `schema_migrations`, applies `001_initial.sql`, no errors
> 5. Smoke per the usual list (health, ingest, list, search)
>
> If you skip the wipe, the app will hit errors on first write because
> the consolidated 001 already dropped the `pages` / `markdown_path`
> columns and any live row from the old schema would still have them.
> There is no production data to preserve.

## 8. Known deferred

Spotted during this pass but intentionally not touched — flagged for a
future pass:

- **Native SQL `GROUP BY` for aggregate.** `aggregate_documents` still
  calls `list_documents(limit=100000, ...)` and buckets in Python. A
  real `SELECT file_type, COUNT(*) FROM documents ... GROUP BY`
  implementation would replace this entirely. The in-Python pass is
  now correct (filters are pushed down), just not optimal.
- **`documents.metadata` column usage review.** The column is written
  by the PATCH path but the get/list paths don't surface it. Separate
  audit thread.
- **Batch-fetch of interactions.** `include=agent_metadata` and
  `include=last_interaction` still do one interaction fetch per
  document. N+1 remains. Row-level work is out of Pass 4 scope.
- **CLI parity.** The `ariadne-core` CLI was carried forward in Pass
  3 without aggregate/schema subcommands; still deferred.
- **`document_interactions` indexes.** Four separate indexes
  (`document_id`, `agent_id`, `agent_type`, `collection_id`). At least
  one is likely redundant given query patterns, but not audited —
  leaving them in for now.
- **`src/pipeline/config.py::_VAR_PATTERN` regex cannot handle nested
  `${VAR:-${INNER}}` in `ariadne.yaml`'s `database.url`.** The local
  smoke above set `DATABASE_URL` directly to sidestep this. Config.py
  was out of Pass 4 scope. Bob: Railway injects `DATABASE_URL`
  directly so this doesn't hit in prod, but the config.py parser
  should be fixed in a follow-up.

## 9. Scope fence — clean

No files outside the Pass 4 scope fence were touched. Specifically,
nothing in `client/`, `skills/`, `src/pipeline/cli.py`,
`src/pipeline/services.py`, `src/pipeline/schema.py`,
`src/pipeline/stores.py`, `docs/roadmap/`, or `.claude-plugin/`.

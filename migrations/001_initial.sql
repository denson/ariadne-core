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

-- GIN index supporting the POST /api/search ``metadata`` (JSONB
-- containment ``@>``) and ``metadata_exists`` (key existence ``?``)
-- filters. Folded forward from migration 002 so fresh deploys get
-- the index in the initial pass. IF NOT EXISTS keeps the legacy
-- backfill path (where 002 may already have run separately) safe.
CREATE INDEX IF NOT EXISTS idx_interactions_agent_metadata
    ON document_interactions USING GIN (agent_metadata);

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

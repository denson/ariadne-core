-- Ariadne Core — Initial Database Schema
-- Requires: PostgreSQL 16+ with pgvector extension
--
-- Tables: collections, documents, document_interactions, chunks, jobs, api_keys
-- All tables include org_id for future row-level security (not enforced in Phase 1).

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
    pages INTEGER,
    engine TEXT NOT NULL DEFAULT 'markitdown',
    processing_time_ms INTEGER,
    output_tokens_estimate INTEGER,
    token_savings_ratio REAL,
    markdown TEXT,
    markdown_path TEXT,
    title TEXT,
    tags TEXT[] DEFAULT '{}',
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
    metadata JSONB DEFAULT '{}',
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
-- (text-embedding-3-small). If you run this migration manually, replace
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

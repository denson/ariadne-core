-- Ariadne Core — bw → Ariadne ingest retry queue + dead-letter table
--
-- Phase 3 (ariadne--8fd.5): every successful bw write triggers an inline
-- Ariadne ingest under the same per-slug lock. If the ingest fails (Gemini
-- timeout, Postgres connection drop, embedding rate limit, etc.) the bw
-- write still succeeds (the bw repo is canonical) and the failed ingest
-- enqueues here for a background retry-worker to drain.
--
-- A separate dead-letter table catches payloads that have exhausted the
-- retry budget so the operator (POLYBIUS) can inspect and replay manually.
--
-- See ``agents/design/ariadne--8fd.5/design.md`` §D5 for the full spec.
--
-- Folded forward into ``001_initial.sql`` for fresh deploys; this file
-- exists so existing Phase 2 deploys can migrate without re-running 001.

CREATE TABLE IF NOT EXISTS bw_ingest_retry_queue (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug              TEXT NOT NULL,
    source_type       TEXT NOT NULL,   -- 'body' | 'comment' | 'patch_meta'
    ticket_id         TEXT NOT NULL,
    comment_n         INTEGER,
    bw_commit_sha     TEXT NOT NULL,
    payload           JSONB NOT NULL,  -- full helper kwargs incl. agent_metadata + content
    enqueued_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at   TIMESTAMPTZ,
    attempt_count     INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    next_attempt_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Drain pick order: due rows first, FIFO within due window.
CREATE INDEX IF NOT EXISTS idx_bw_ingest_retry_next
    ON bw_ingest_retry_queue (next_attempt_at);

-- Per-slug counts for the observability surface (D5.3).
CREATE INDEX IF NOT EXISTS idx_bw_ingest_retry_slug
    ON bw_ingest_retry_queue (slug);

CREATE TABLE IF NOT EXISTS bw_ingest_retry_dead_letter (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug              TEXT NOT NULL,
    source_type       TEXT NOT NULL,
    ticket_id         TEXT NOT NULL,
    comment_n         INTEGER,
    bw_commit_sha     TEXT NOT NULL,
    payload           JSONB NOT NULL,
    enqueued_at       TIMESTAMPTZ NOT NULL,
    last_attempt_at   TIMESTAMPTZ,
    attempt_count     INTEGER NOT NULL,
    last_error        TEXT,
    gave_up_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    gave_up_reason    TEXT  -- 'max_attempts' | 'stale_by_design' | 'orphan_sha'
);

CREATE INDEX IF NOT EXISTS idx_bw_ingest_dead_letter_slug
    ON bw_ingest_retry_dead_letter (slug);

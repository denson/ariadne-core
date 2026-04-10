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

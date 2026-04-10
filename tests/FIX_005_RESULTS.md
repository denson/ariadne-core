# Fix 005 Results: `convert_document` Missing `interactions` on Dedup Hits

## Root Cause

The code already had the fix in place. Both paths were correctly implemented:

- **`src/pipeline/mcp_server.py`** — `_process_single_document` (line 637-670): The dedup-skip return dict already included an `interactions` array built from `_dedup_store.get_interactions(existing.document_id)`.
- **`src/pipeline/api/routes.py`** — `_build_document_response` helper (line 650-664): Already conditionally includes `interactions` when the list is non-empty. The dedup path at line 161-164 fetches interactions and passes them to this helper.

No code changes were required — the fix was already applied (likely during initial implementation or a prior session).

## Verification Results

All 4 steps passed.

### Step 1: convert_document (first ingestion)
```
document_id: bdee44cd-2894-41ca-acac-c7c69be81d8b
was_dedup_skip: false
agent_type: claude-code
initiated_by: user:denson
model: claude-opus-4-6
agent_notes: "First ingestion"
collection: dedup-interaction-test
```

### Step 2: convert_document (second touch — dedup skip)
```
was_dedup_skip: true
agent_type: ob1
initiated_by: user:nate
model: gpt-4o
agent_notes: "Second touch — should be dedup skip"
interactions: 2 entries present
```

### Step 3: Dedup response validation
- `was_dedup_skip: true` — confirmed
- `interactions` array present — confirmed
- 2 interactions (original ingest + dedup skip) — confirmed
- Each interaction has all required fields:
  - `agent_id`: null (not provided)
  - `agent_type`: "claude-code" / "ob1"
  - `model`: "claude-opus-4-6" / "gpt-4o"
  - `initiated_by`: "user:denson" / "user:nate"
  - `agent_notes`: "First ingestion" / "Second touch — should be dedup skip"
  - `agent_metadata`: null
  - `action`: "ingest"
  - `was_dedup_skip`: false / true
  - `created_at`: timestamps present

### Step 4: Third touch — 3 interactions
```json
{
  "was_dedup_skip": true,
  "interactions": [
    {
      "agent_type": "claude-code",
      "model": "claude-opus-4-6",
      "initiated_by": "user:denson",
      "agent_notes": "First ingestion",
      "was_dedup_skip": false
    },
    {
      "agent_type": "ob1",
      "model": "gpt-4o",
      "initiated_by": "user:nate",
      "agent_notes": "Second touch — should be dedup skip",
      "was_dedup_skip": true
    },
    {
      "agent_type": "cursor",
      "model": "gemini-2.5-pro",
      "initiated_by": "user:alex",
      "agent_notes": "Third touch — should show 3 interactions",
      "was_dedup_skip": true
    }
  ]
}
```
3 interactions confirmed — original ingest + 2 dedup skips.

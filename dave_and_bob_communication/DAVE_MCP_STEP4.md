# Step 4: MCP tools — update, delete, restore, delete_collection

**Context:** Read DAVE_MCP_SCOPE.md for the full plan. This is step 4 of 8. Steps 1-3 must be committed first.

## What to do

Add four new MCP tools and update three existing ones.

**File:** `ariadne-core/src/pipeline/mcp_server.py`

### New tool: `update_document`
```
Parameters:
  document_id: str (required)
  tags: list[str] | None — if provided, replaces tags
  agent_metadata: dict | None — if provided, merges with existing
  collection: str | None — if provided, moves document
  agent_id: str | None
  agent_type: str | None
  model: str | None
  initiated_by: str | None
  agent_notes: str | None

Returns: JSON with updated document metadata (document_id, collection, tags, agent_metadata, updated_fields list). NOT the full content.
```

Record an interaction with `action="update"`.

### New tool: `delete_document`
```
Parameters:
  document_id: str (required)
  agent_id: str | None
  agent_type: str | None
  initiated_by: str | None
  agent_notes: str | None

Returns: JSON with document_id, status "scheduled_for_deletion", deletion_scheduled_at, message "Will be purged after 48 hours. Use restore_document to undo."
```

Record an interaction with `action="delete"`.

### New tool: `restore_document`
```
Parameters:
  document_id: str (required)
  agent_id: str | None
  agent_type: str | None
  initiated_by: str | None
  agent_notes: str | None

Returns: JSON with document_id, status "restored", or error if past 48hr window.
```

Record an interaction with `action="restore"`.

### New tool: `delete_collection`
```
Parameters:
  collection: str (required)
  agent_id: str | None
  agent_type: str | None
  initiated_by: str | None
  agent_notes: str | None

Returns: JSON with collection name, documents_marked count, message about 48hr purge.
```

### Update existing tools

- `search`: add `include_deleted: bool = False` parameter. Pass it through to the store layer.
- `list_documents`: add `include_deleted: bool = False` parameter.
- `list_collections`: document counts should exclude deleted by default. No parameter needed (always exclude from counts).

### Update the instructions string

Update the `instructions` string in the `FastMCP()` constructor to list the new tools. Remember: no hardcoded tool counts — just list them.

## Do not touch

- REST endpoints (step 5)
- SPEC.md, skills, docs

## Do not commit

Report what you changed. Leave for Bob.

# Ariadne Core MCP Tool Call Sequence for Acme Contract Termination Query

## User Request
"What did that Acme contract say about termination? I think there was something about a 90-day notice period but I'm not sure."

## Analysis
The user is asking for specific information from an "Acme contract" regarding termination clauses, with a vague recollection of a 90-day notice period. This is a document retrieval and search task that requires:
1. First, search for documents containing information about Acme contracts and termination
2. If found, retrieve the full document or specific sections to confirm details

## MCP Tool Calls (in order)

### Call 1: Search for Acme contract termination information

```json
{
  "tool": "search",
  "parameters": {
    "query": "Acme contract termination 90-day notice period",
    "top_k": 5,
    "collection": null,
    "filters": null,
    "agent_id": "claude-code-session",
    "agent_type": "claude-code",
    "model": "claude-haiku-4-5-20251001",
    "initiated_by": "user:denson",
    "agent_notes": "User is searching for specific termination clause details in Acme contract",
    "agent_metadata": null
  }
}
```

**What this does:** Searches the document collection for chunks containing "Acme contract", "termination", and "90-day notice period". Returns the top 5 most relevant results with source document metadata and interaction history.

---

### Call 2: If search returns relevant results, get the full document

Once we identify which document is the Acme contract from the search results, we'd make this call:

```json
{
  "tool": "get_document",
  "parameters": {
    "document_id": "[document_id from search results]",
    "include_chunks": true,
    "include_interactions": true
  }
}
```

**What this does:** Retrieves the complete Acme contract document with:
- Full extracted Markdown content
- All chunks with section references and page numbers
- Complete interaction history (who has accessed this document, when, and any agent notes)

---

## User-Facing Response (after receiving search results)

**If search finds the contract:**

"I found the Acme contract in your document store. Based on the search results, I can see it contains information about termination clauses. Here's what the contract says about termination:

[Excerpt from relevant chunk showing termination clause with 90-day notice requirement]

You were right about the 90-day notice period. The contract specifies that [specific termination terms]. The full termination section is on [page X] of the contract.

Would you like me to:
- Show you the complete termination section?
- Highlight other related clauses (e.g., early termination, breach conditions)?
- Extract all key dates and deadlines from this contract?"

---

**If search doesn't find the contract:**

"I searched your documents for 'Acme contract termination' but didn't find a matching document in your collection. This could mean:

1. The Acme contract hasn't been uploaded to Ariadne Core yet
2. It's stored under a different name or collection
3. The termination language uses different wording than expected

Would you like me to:
- Search with different keywords (e.g., "Acme agreement", "Acme service contract")?
- List all available documents to help you identify which one is the Acme contract?
- Help you ingest the Acme contract document if you have it?"

---

## Key Design Decisions

1. **Search-first approach:** Used `search` rather than `list_documents` because the user has a specific query in mind (termination clause), not a browse intent.

2. **Top K = 5:** Balanced approach to get relevant results without overwhelming the user. If the query is specific enough, top result should be the contract.

3. **Metadata tracking:** Included `agent_id`, `agent_type`, `model`, `initiated_by`, and `agent_notes` to track that user:denson (via Claude Code) asked this question. This creates a full audit trail in `document_interactions`.

4. **Two-step retrieval:** Search returns chunks with context. If the user wants more detail or verification, `get_document` retrieves the full contract with all chunks and interaction history.

5. **No `force` flag:** Since this is a read-only query, not ingestion, the dedup override isn't needed.

## Expected Outcome

The search should return the Acme contract chunk(s) containing the termination clause. The user will see:
- The exact text about the 90-day notice period
- The page/section where it appears
- Any related clauses nearby
- Complete provenance (which agent touched it, when, and why)

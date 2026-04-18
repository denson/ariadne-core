# SAM — Query-API design (list_documents thickening + filters + aggregate)

**Status:** drafted while Phase 8 re-ingest is running. Not yet fired.
Pass 1 Dave instruction lives next to this file as
`DAVE_QUERY_API_PASS_1.md`. Pass 2 and Pass 3 instructions are TBD
and will be drafted after Pass 1 lands.

---

## Why this exists

Phase 8's pre-flight turned up three coupled problems with the
`/documents` endpoint:

1. **Silent `limit` cap** — `Query(20, ge=1, le=100)` rejects
   `limit=1000` with an unexplained 400. Dave worked around it, but
   the cap wasn't documented anywhere and there's no measurement
   behind it. Same file (`routes.py`) calls
   `list_documents(limit=100000)` internally in the stats endpoint,
   so the backend obviously handles it — the cap is a route-level
   intuition someone pulled out of thin air.
2. **Row shape is too thin for agent use.** Current fields:
   `document_id`, `source_file`, `title`, `file_type`, `collection`,
   `content_fingerprint`, `chunk_count`, `interaction_count`,
   `created_at`. No `agent_metadata`, no `tags`, no `store_status`.
   So questions like "which docs have a DOI?" or "which docs
   errored on embedding?" can't be answered from a `list_documents`
   response — agents have to `get_document` each row, at linear cost.
3. **No structured-query path.** Agents who want to ask "which docs
   in this collection have `source_reference` starting with `doi:`?"
   have to pull everything and filter client-side. Wasteful in
   network, context, and cap-hitting.

Framing: `list_documents` is an **agent-consumption** endpoint, not a
human-UX endpoint. The limit should reflect what an LLM can reason
over in one turn and what the backend can reasonably produce — not
a UX designer's 20-rows-per-page intuition.

---

## The decision

Five agent-facing verbs, each with one clear use case:

| # | Verb | Use case | Endpoint |
|---|---|---|---|
| 1 | `schema()` | "What filters, includes, and group_by fields exist?" — the first call an agent makes to learn the system | `GET /api/documents/schema` (new) |
| 2 | `stats()` | "How many docs per collection — quick system snapshot?" | `GET /api/stats` (exists) |
| 3 | `list_documents(filters, include)` | "Inventory / audit this collection" | `GET /api/documents` (extended) |
| 4 | `aggregate(group_by)` | "Group-by summary — counts per category" | `GET /api/documents/aggregate` (new) |
| 5 | `get_document(id)` | "Full content of one doc" | `GET /api/documents/{id}` (exists) |

`schema()` is listed first deliberately — it's the entry point for
an agent that doesn't already know the surface. An agent that calls
`schema()` once at the start of a reasoning session can pick the
right verb for every subsequent metadata question without probing.

This is **Shape A (parameter filters) + Shape B (aggregate)** from
the earlier discussion. Shape C (full filter DSL) is explicitly
rejected for v1 — it's the biggest design task, the easiest to
over-engineer, and the hardest for agents to invoke correctly. Leave
it as a potential v2 if concrete use cases demand it.

**Why `aggregate` is `GET` not `POST`:** it's a read, not a write.
The body was going to be `{collection, group_by, where?}`, which
fits cleanly in query params. GET matches `list_documents`'
convention, is cacheable, and is HTTP-semantically honest. POST is
only justified if we're ever going to accept a complex nested body
(Shape C), and we're not.

**Why `stats()` stays even though it overlaps with
`aggregate(group_by=collection)`:** different mental models.
`stats()` is a system-health snapshot (includes embedding flag,
total chunks, total collections). `aggregate()` is a structured
query over an arbitrary field. They happen to overlap on
per-collection doc counts — that's a convenience, not a
redundancy worth removing.

---

## Self-documentation — three layers, layered together

Without this, the system silently fails agents. The user's
rule-of-thumb: "the system must tell the agent how things work and
the limitations."

### Layer 1 — rich 400 errors

FastAPI does not auto-reject unknown query params. We have to
explicitly validate. Every route adds a whitelist check at the top;
on mismatch, respond with:

```json
{
  "error": "Unknown filter 'xyz'.",
  "valid_filters": ["collection", "file_type", "store_status", "tag", "has_source_reference"],
  "see": "/api/documents/schema"
}
```

Same pattern for `include=` values and `group_by` values.

This is the layer agents learn from on their own — probe, get 400,
correct.

### Layer 2 — discovery endpoint

`GET /api/documents/schema` returns a single JSON blob:

```json
{
  "list_endpoint": "/api/documents",
  "filters": {
    "collection": "exact match on collection name",
    "file_type": "exact match (without leading dot)",
    "store_status": "enum: stored | not_stored | skipped | error",
    "tag": "docs containing this tag (OR semantics if repeated)",
    "has_source_reference": "bool: does agent_metadata.source_reference exist"
  },
  "includes": {
    "agent_metadata": "adds agent_metadata dict per row",
    "tags": "adds tags list per row",
    "last_interaction": "adds most recent interaction summary",
    "markdown": "adds full markdown per row (expensive)"
  },
  "cap_by_include": {
    "default": 500,
    "with_markdown": 50
  },
  "aggregate_endpoint": "/api/documents/aggregate",
  "aggregatable_fields": [
    "store_status", "file_type", "collection",
    "agent_metadata.docty", "agent_metadata.source_reference",
    "tags"
  ],
  "brute_force_fallback": "paginate list_documents with offset; filter client-side"
}
```

Agents check this once, cache in their reasoning, then query
correctly without burning a round-trip on a probe. Small to
maintain if the schema is **derived from the route validator
registry itself** rather than hand-written — a single source of
truth feeds both the validator and the schema endpoint.

### Layer 3 — SPEC.md section

Formal contract. Skill instructions
(`skills/ariadne-document-intelligence/SKILL.md`) point agents at
it. Authoritative but static. Gets updated every time layers 1 or
2 change.

---

## Brute-force fallback — explicit contract

Every structured-query API has questions it can't express. Agents
must have a documented escape hatch — "just give me everything and
I'll filter locally" — or they get stuck on the edges.

**The contract:** If A + B can't express the question, paginate
`list_documents` with `include=[...]` covering the fields the agent
needs, and filter client-side. The schema endpoint tells you the
cap for each include combination.

Mechanically:

```python
# Brute-force pagination pattern — documented in SPEC and skill
all_docs = []
offset = 0
while True:
    page = client.list_documents(
        collection="world-bank-ree",
        include=["agent_metadata", "tags", "store_status"],
        limit=500,
        offset=offset,
    )
    all_docs.extend(page.documents)
    if len(page.documents) < 500:
        break
    offset += 500
# now filter client-side
no_doi = [d for d in all_docs if not d.agent_metadata.get("source_reference", "").startswith("doi:")]
```

The `include=` param is the mechanism that makes this affordable.
Default row stays thin (cheap). Opt-in thickening lets the
brute-force path get what it needs without two round-trips per doc.

---

## Cap-by-shape logic

The cap is a function of what the caller asked for:

| Include set | Cap |
|---|---|
| default (thin: 9 fields) | 500 |
| `+agent_metadata` | 500 |
| `+tags` | 500 |
| `+last_interaction` | 500 |
| `+markdown` | **50** |
| any combination with `markdown` | 50 |

Rationale:
- Thin row: ~200-400 bytes, ~60-100 tokens. 500 × 100 = 50k tokens,
  well inside a Sonnet 3.5 context window.
- With `agent_metadata` + `tags`: ~300-600 bytes, ~150-250 tokens.
  500 × 250 = 125k tokens, still fits if the agent's other context
  is modest.
- With `markdown`: unbounded per row (a 4,500-word doc is ~6,500
  tokens). 50 × average = manageable upper bound; 500 would blow
  the window.

`limit > cap` returns a 400 with the specific cap for the requested
include set.

---

## Non-goals (v1)

Explicitly out of scope for the three passes below:

- **Shape C: full filter DSL** (MongoDB-style `{where: {...},
  select: [...]}`). Revisit only if a concrete use case appears that
  A + B can't express.
- **Date range filters** (`created_after`, `created_before`). Easy
  to add later; not needed for Phase-8-adjacent audit.
- **DOI-specific filters** (`has_doi`). The generic
  `has_source_reference` + client-side `.startswith("doi:")` check
  covers it until there's a reason to specialize.
- **Sort order.** Default newest-first (current behavior). Add
  `order_by` later if needed.
- **Full-text search on metadata.** That's what the existing
  `search()` endpoint is for, on chunk content. A metadata full-text
  search would be a different conversation.

---

## Scope — three passes

### Pass 1 (server, Dave + Bob) — ~60-90 min

- Filter params on `GET /api/documents`: `store_status`, `tag`,
  `has_source_reference` (the three net-new; `collection` and
  `file_type` already exist).
- `include=` param supporting `agent_metadata`, `tags`,
  `last_interaction`, `markdown`.
- Raise base `limit` cap to 500 (50 when `markdown` in include).
- Thicken default row: add `store_status` to the 9-field row. Keep
  other additions gated behind `include=`.
- Rich 400 on unknown filter key, unknown include value, limit >
  cap.
- SPEC update: expand the `/documents` section with filters,
  includes, cap-by-shape table, brute-force pattern. Promise
  `/documents/schema` is coming in Pass 2.
- Tests: one per new filter, one per include value, one for
  unknown-filter 400, one for limit-over-cap 400, one for
  thin-row-default preservation.

### Pass 2 (server, Dave + Bob) — ~45-60 min

- New `GET /api/documents/aggregate` endpoint. Query params:
  `collection`, `group_by`, plus the same filter params as
  `list_documents` (to act as the WHERE clause). Whitelisted
  `group_by` fields: `store_status`, `file_type`, `collection`,
  `agent_metadata.docty`, `agent_metadata.source_reference`,
  `tags`. Returns `[{group, count}, ...]`.
- New `GET /api/documents/schema` endpoint. Response shape per the
  Layer 2 example above. Derived from a single
  filter/include/group_by registry so it never goes stale.
- Rich 400 on unknown `group_by` value, mirroring Pass 1.
- SPEC update: new sections for aggregate and schema endpoints.
- Tests: aggregate happy path + unknown `group_by`, schema
  returns the registry, end-to-end
  schema → use-the-filter-it-named pattern.

### Pass 3 (client + skill, Dave + Bob) — ~60 min

- `AriadneClient.list_documents(collection=, filters=, include=,
  limit=, offset=)` — accept the new params.
- `AriadneClient.aggregate(collection=, group_by=, **filters)` —
  new method. Returns `list[AggregateBucket]`.
- `AriadneClient.schema()` — new method. Returns `DocumentsSchema`
  dataclass.
- New client model dataclasses for the above.
- Update `skills/ariadne-document-intelligence/SKILL.md` with a
  "Querying the corpus" section covering all five verbs + the
  brute-force fallback pattern. Lead with `schema()` as the
  entry-point call. Each verb gets a short code example.
- Tests: client unit tests hitting a fake server that returns the
  new shapes.

---

## Sequencing

Phase 8 is running as this is drafted. **Do not fire Pass 1 until
Phase 8's `DAVE_DONE.md` lands and Sam reviews it.** Reasons:

- The Phase 8 re-ingest hits `/documents` via `list_documents`
  internally for the durability check. A mid-run route change
  that gets auto-deployed to Railway would break the active
  verification.
- Phase 8 may surface additional findings (BL-* items) that we'd
  want to stage alongside the API work.

Pass 1 → Pass 2 → Pass 3 run strictly sequential. Do not
parallelize — Pass 2's schema endpoint derives from Pass 1's
validator registry, and Pass 3's client methods need both.

---

## Resolved questions (resolved 2026-04-17 by Denson)

1. **`tag` semantics** — **Single-value string for v1.** If a doc
   has tag X, match. Agents can do AND client-side across two
   calls if needed. Applies to Pass 1.

2. **`has_source_reference` semantics** — **Recommendation
   accepted**: "has" means key exists in `agent_metadata` AND
   value is non-empty AND != "unknown". Document the exact check
   in the schema endpoint's filter description. Applies to Pass 2
   (the filter itself is deferred out of Pass 1 per its
   explicitly-deferred list, because `source_reference` lives on
   `DocumentInteraction`, not `StoredDocument`, and needs an
   interaction-table join).

3. **Row shape change breaking backward compatibility** —
   **Not a concern.** Per Denson: this is the only deployment.
   Strictly additive changes to the default row do not need a
   commit-message callout; Dave/Bob can add fields freely. Applies
   to Pass 1 (and future passes).

4. **Aggregate cap** — **Recommendation accepted**: cap at 1000
   groups; beyond that, require a `where` filter to narrow.
   Applies to Pass 2.

5. **`last_interaction` shape** — **Recommendation accepted**:
   minimal — `{agent_notes, action, created_at}`. Agents who need
   the full interaction chain call `get_document(id)`. Applies to
   Pass 1.

---

## How this file should be used

- **Sam (me)**: keep this file as the canonical design doc while
  the passes are in flight. Update the "Open questions" block with
  resolutions once decided. After all three passes land, fold the
  final design into `docs/BACKLOG.md` as a retired-BL-16 note and
  delete this file.
- **Bob**: read this before reviewing a Pass-N Dave-instruction
  commit — it tells you what's in scope and what should not be.
- **Dave**: don't read this directly. The per-pass instruction
  files are self-contained; this is the planning context behind
  them.
- **Denson**: this is yours to edit, veto, or reshape. If you
  change the design, update this file first and regenerate the
  Dave instructions from the new version.

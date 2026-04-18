# Task: Sharpen the ingestion routing decision tree in the doc-intelligence skill

**For:** Dave
**Phase:** 1, Step 1 (do this FIRST)
**File to edit:** `skills/ariadne-document-intelligence/SKILL.md`

Read `PHASE1_OVERVIEW.md` first for context.

---

## Why

Agents don't always pick the right ingestion tool. The skill has the correct decision tree ("Is this a single file or many files?") but the single-file path is buried 300 lines away from the decision tree, mixed into a long inline Python script. An agent skimming the skill misses it. The two paths need to be side by side, equally prominent, equally copy-paste-ready.

The skill is the specification. The MCP server (Step 2) will echo these instructions back as a safety net, but the skill is where agents learn the pattern *before* they make a mistake.

## What to change

### 1. Consolidate the routing decision into one clear section

Find the current decision tree near line 520 ("Is this a single file or many files?"). Restructure the surrounding area so the two ingestion paths are presented together, prominently, near the top of the process/tools section:

**Path A — Single file (or a file dropped in the UI):**

```
1. Upload via REST:
   curl -s -X POST $ARIADNE_URL/api/upload \
     -H "X-API-Key:$ARIADNE_API_KEY" \
     -F "file=@<local-path>"
2. Read the "path" field from the JSON response
3. Call convert_document with that server-side path as uri
```

**Path B — Directory / many files:**

```
python ariadne-core/scripts/bulk_ingest.py <dir> \
  --collection <name> --dry-run
```

Both paths must have concrete, copy-paste-ready examples. No "see 300 lines down."

### 2. Make the single-file path first-class

The upload + convert_document steps should be as crisp and prominent as the bulk_ingest example already is. This is the more common case — users drop one file in the UI far more often than they point at a directory.

### 3. Remove the inline upload helper script

The 115-line Python script currently embedded in the skill (in the "Upload helper script" section, lines ~252-367) is a legacy artifact from before `bulk_ingest.py` existed. It duplicates what bulk_ingest does but worse and is confusing for agents — they see a script and think they should write it to disk and run it.

Replace it with a short note: "For bulk ingestion, use `bulk_ingest.py` (see Path B above). For single files, use the upload + convert_document pattern (Path A above)."

### 4. Move the "DO NOT loop" warning to right after the decision tree

The warning about not looping MCP calls over files is currently in a subsection that agents skip. It needs to be immediately after the Path A / Path B decision — impossible to miss:

> **DO NOT** loop over files calling `convert_document` via MCP. That defeats Ariadne's core value proposition. One Bash call to `bulk_ingest.py` replaces hundreds of MCP round-trips. If you have more than 5 files, use Path B.

## What NOT to change

- The search process section
- The browsing process section  
- The chunking section
- The metadata conventions section
- The provenance section (recently added, leave it alone)
- The Open Brain bridge section
- The supported formats section
- Collection naming decision tree (it's fine as-is)

## Acceptance criteria

1. An agent reading the skill from top to bottom encounters the routing decision (single file vs directory) before it encounters any tool-specific details
2. Both paths have copy-paste-ready examples with no forward/backward references
3. The inline upload helper script is gone
4. The "DO NOT loop" warning is immediately visible after the routing decision
5. All existing correct information is preserved — this is a restructure, not a rewrite

## Compile / test check

This is a Markdown skill file — no compilation needed. Read through the final version end-to-end and verify:
- No broken Markdown formatting
- No orphaned section references (e.g., "see the Upload helper script section" when that section no longer exists)
- The "Process: Ingesting a document" section still makes sense with the restructured routing above it
- The "Process: Batch ingesting" section still makes sense

## Do not commit

Leave all changes for Bob. Write your completion report to `DAVE_DONE.md`.

---

## Review summary for Bob

**What changed:** The doc-intelligence skill's ingestion routing was restructured. The single-file path (upload + convert_document) and the bulk path (bulk_ingest.py) are now presented side by side with copy-paste-ready examples. The legacy 115-line inline upload helper script was removed. The "DO NOT loop MCP calls" warning was moved to be immediately visible after the routing decision.

**Why:** Agents were missing the single-file path because it was buried 300 lines away from the decision tree. The inline script was confusing — agents thought they needed to write it to disk.

**What to verify:**
- Both ingestion paths are clear, concrete, and copy-paste-ready
- No information was lost in the restructure
- No broken Markdown formatting or orphaned references
- The provenance section (recently added) is untouched
- Authorship metadata is Denson Smith (check any frontmatter)

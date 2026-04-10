# Comply: Make the Code Match the Spec and Skill

## ROLE

You are a developer. Your job is to make the MCP server behave the way SPEC.md and SKILL.md say it should.

## GOAL

Read the spec, the skill, and the code. Write a plan that lists every discrepancy and how you would fix it. **Do not make any changes yet.** The plan is the deliverable for this phase — we will review it before you touch any code.

## WHY PLAN FIRST

Some fixes interact with each other. Changing how one tool serializes its response may affect another tool that shares the same code path. Fixing persistence may change how dedup works. We need to see the full picture before making changes, because conflicts between fixes may require decisions that you can't make alone.

## REFERENCE DOCUMENTS

1. **SPEC.md** (repo root) — the source of truth for how the server should behave
2. **SKILL.md** (`docs/skills/ariadne-document-intelligence/SKILL.md`) — how agents are told to use the server

Read both completely before reading any code.

## CAPABILITIES

You MAY:
- Read any source file in the repo
- Read SPEC.md and SKILL.md
- Write the plan to `tests/COMPLY_PLAN.md`

## CONSTRAINTS

You MUST NOT:
- Edit any source files
- Restart Docker
- Call MCP tools
- Change SPEC.md or SKILL.md

This is a planning phase only. No code changes.

## PROCESS

1. Read SPEC.md end to end
2. Read SKILL.md end to end
3. Read the MCP server code (`src/pipeline/mcp_server.py`)
4. Read the REST routes (`src/pipeline/api/routes.py`)
5. Read the dedup store (`src/pipeline/dedup.py`)
6. Read the vector store (`src/pipeline/storage/pgvector.py` and `src/pipeline/storage/base.py`)
7. Read the chunker (`src/pipeline/chunking/chunker.py`)
8. Read the embedder (`src/pipeline/embedding/embedder.py`)
9. Read the config loader (`src/pipeline/config.py`)
10. For each MCP tool, compare what the code does against what SPEC.md says it should do
11. Write the plan

## PLAN FORMAT

Write `tests/COMPLY_PLAN.md` with this structure:

```markdown
# Compliance Plan

**Date:** YYYY-MM-DD

## Discrepancies Found

For each discrepancy:

### N. [short title]
- **SPEC.md says:** [quote or paraphrase the relevant section]
- **Code does:** [what actually happens, with file and line references]
- **Proposed fix:** [one paragraph — what to change, in which file(s)]
- **Risk:** [does this fix interact with or depend on any other fix? could it break something?]
- **Depends on:** [list any other discrepancy numbers that must be fixed first, or "none"]

## Interactions and Conflicts

List any fixes that interact with each other — shared code paths, ordering dependencies,
or cases where fixing one thing might break another. Be specific about which discrepancy
numbers are involved and what the conflict is.

Flag any fix that requires a design decision (not just a code change) — something where
there are multiple valid approaches and we need to choose.

## Proposed Fix Order

Number the discrepancies in the order you would fix them, with a one-line justification
for each. Group any that should be done together because they touch the same code.

## Questions

Anything you found where SPEC.md and SKILL.md are ambiguous or where you need a decision
before proceeding.
```

## SUCCESS CRITERIA

You are done when `tests/COMPLY_PLAN.md` exists and covers every discrepancy between the code and the two reference documents. The plan should be detailed enough that a different developer could execute it without re-reading the code.

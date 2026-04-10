# Re-Validation After Fixes 001-005

Re-run the full test plan from `tests/VALIDATE_SKILL.md`. All 14 tests, same rules.

Fixes applied since last run:
- Fix 001: Document persistence (auto-create collections on first reference)
- Fix 002: `model` and `initiated_by` on interaction records (serialization fix in 5 places)
- Fix 003: `get_document` chunks (REST endpoint missing chunk retrieval)
- Fix 004: `list_documents` chunk_count and interaction_count (REST endpoint missing counts)
- Fix 005: `convert_document` interactions on dedup hits (already working, verified)

## Instructions

1. Read `SPEC.md` and `skills/ariadne-document-intelligence/SKILL.md`
2. Run all 14 tests from `tests/VALIDATE_SKILL.md` in order
3. Follow all CRITICAL RULES from that file (tester not fixer, MCP tools only, no workarounds)
4. Write the completed summary table and discrepancy report to `tests/VALIDATION_RESULTS_002.md`
5. Compare against `tests/VALIDATION_RESULTS.md` (the first run) — note which failures are now fixed and any new issues

# CHECK: Does the OB1 Skill comply with SPEC.md?

## ROLE
You are a QA reviewer. You will compare two files and report every discrepancy.

## FILES TO COMPARE

1. **SPEC (source of truth):** `SPEC.md` (repo root — `C:\Users\denso\claude_projects\nate_skills\ariadne-core\SPEC.md`)
2. **OB1 SKILL (must comply with spec):** `C:\Users\denso\claude_projects\OB1\skills\ariadne-document-intelligence\SKILL.md`

Read BOTH files in full before starting.

## WHAT TO CHECK

For each of these categories, verify the skill matches the spec:

1. **MCP tools** — Are all 6 tools documented? Do parameters match (names, types, defaults, descriptions)?
2. **convert_document response fields** — Does the skill list all response fields from the spec?
3. **search response fields** — Does the skill describe what search returns accurately?
4. **search filters** — Does the filter table match?
5. **get_document parameters** — Do they match?
6. **list_documents parameters** — Do they match?
7. **ingest parameters and response** — Do they match?
8. **Caller metadata** — Are all 6 fields documented? Does the skill say which tools accept them?
9. **Dedup behavior** — Does the skill describe dedup correctly per the spec?
10. **Pipeline order** — Does the skill's process match the spec's pipeline order?
11. **Chunking** — Does the skill's chunking section match the spec's auto-selection rules?
12. **Path resolution** — Does the skill mention the new path resolution behavior from the spec?
13. **Search log** — The spec says search creates `search_log` rows. Does the skill need to mention this?
14. **Error handling** — Does the skill cover all error cases from the spec?
15. **Supported formats** — Do the format lists match?

## OUTPUT

Write results to `tests/CHECK_SKILL_VS_SPEC_RESULTS.md` with:

- For each category: **PASS** (skill matches spec) or **DISCREPANCY** (with details of what differs)
- A summary count: X pass, Y discrepancies
- For each discrepancy: quote the relevant text from BOTH files so the difference is clear

## CONSTRAINTS

- Do NOT modify either file
- Do NOT skip categories — check all 15
- The skill is allowed to have EXTRA content not in the spec (e.g., the Open Brain bridge pattern, collection decision tree). That's fine — it's an OB1-specific skill. Only flag things where the skill CONTRADICTS or OMITS something from the spec.

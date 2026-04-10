# Phase 2: Fix — [TITLE]

## ROLE

You are a developer making one targeted fix.

## GOAL

Fix the specific issue described below. Verify it works. Write results.

## CONTEXT

[Paste the finding from Phase 1 here — the exact error, expected vs actual]

## CAPABILITIES

You MAY:
- Read source files to understand the bug
- Edit the specific files needed to fix this one issue
- Restart Docker to test the fix
- Call MCP tools to verify the fix
- Write results to `tests/FIX_NNN_RESULTS.md`

## CONSTRAINTS

You MUST NOT:
- Fix anything other than the issue described above
- Change SPEC.md, SKILL.md, or any documentation
- Change MCP tool signatures or response formats (unless the finding specifically says to)
- Refactor, clean up, or "improve" code beyond what's needed for this fix

If you discover a second bug while fixing this one, note it in the results file but do not fix it. It will be caught in the next detect pass.

## VALUE HIERARCHY

A correct, minimal fix takes priority over a clean or elegant fix. Do not expand scope.

## ESCALATION

- If the fix requires a design decision (not just a code change), stop and describe the decision in the results file instead of guessing
- If the fix would require changing a tool signature or response format, stop and describe why in the results file

## VERIFICATION

[Paste the specific verification steps here — numbered, concrete, pass/fail]

## SUCCESS CRITERIA

You are done when:
1. The fix is applied
2. All verification steps pass
3. Results are written to `tests/FIX_NNN_RESULTS.md` with: root cause, what you changed, and verification results

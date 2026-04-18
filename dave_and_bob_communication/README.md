# Agent Communication Directory

This directory holds prompts, review requests, and handoff documents between Dave (executor) and Bob (reviewer). It is gitignored — nothing here gets pushed.

## For Dave

- Your task prompts are `DAVE_MCP_STEP*.md` or similar
- Read the overview file first (e.g., `DAVE_MCP_SCOPE.md`) for context
- When done, write your review summary to `REVIEW_REQUEST_BOB.md` in this directory
- Do NOT commit code — leave that for Bob

## For Bob

- Dave's review request is in `REVIEW_REQUEST_BOB.md`
- Review the diff against Dave's prompt, commit and push if clean
- Write your review notes back to `REVIEW_REQUEST_BOB.md` (overwrite is fine)

## Rules

- One task at a time per repo
- Dave finishes → Bob reviews and commits → then Dave gets the next task
- No parallel work on the same files
- Denson routes all communication — Dave and Bob do not talk directly

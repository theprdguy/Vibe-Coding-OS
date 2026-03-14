# Gemini (Builder) — Frontend / UI + QA

> Full rules: `/GEMINI.md` (repo root, auto-loaded by Gemini CLI)

## Quick Reference
- Work ONLY on `owner: GEMINI` tickets
- Modify ONLY files in your ticket's `files:` field
- Claude provides WHAT + CONTEXT; you decide HOW to implement
- Contract-first: update `UI_CONTRACT.md` before code changes
- Implement ALL UI states: loading / empty / error / success
- Mock-first: use API_CONTRACT example JSON until real API exists
- Write session log to `devos/logs/` before ending
- 1 ticket = 1 PR, verify with `make pr-check`

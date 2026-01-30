# Vibe Starter Kit (Multi-LLM Vibe Coding OS)

## Quick Start
```bash
git init
make help
make kickoff
make triage
make pr-check
```

## How to use with Codex CLI
1) Run Codex from this repo root
2) Paste the session runbook prompt (see below)
3) If Codex needs decisions, it must add questions to questions/QUEUE.md

### Codex Session Runbook (copy/paste)
```text
You are working in this repo via CLI. Follow SSOT-first rules.

SSOT files (source of truth):
- AI.md
- CONTEXT.md
- PROJECT_STATE.md
- docs/API_CONTRACT.md
- docs/UI_CONTRACT.md
- tasks/QUEUE.yaml
- questions/QUEUE.md
- .codex/CODEX.md

Task: Set up a minimal project environment scaffold that is stack-agnostic.
Constraints:
- Do not choose a specific framework unless required; keep placeholders.
- Keep changes small and reviewable (1 PR-sized change).
- If you need a decision, add a question to questions/QUEUE.md with Options + Recommendation + Default.
- If you create apps/api or apps/web, do not invent API/UI; keep placeholders unless contracts are updated first.

Deliverables:
1) Create directories: apps/api, apps/web, packages/shared (empty ok).
2) Ensure make pr-check works reliably.
3) Update CONTEXT.md + PROJECT_STATE.md with how to run kickoff/triage.
4) Run: make help && make kickoff && make pr-check and report results.

Stop condition:
- All deliverables done and commands succeed.
- Summarize changes and list modified files.
```


## Session Start (A-Mode) — Minimal Human Interruptions
Run these at the start of every work session:
```bash
make kickoff
make triage
```

Then run Claude (Dispatcher) with the prompt file:
- `prompts/claude/session-start.md`

**How to respond:** answer only with choices, e.g.
- `Q-001=Default, Q-004=B, Q-007=A`

Claude will then update:
- questions/QUEUE.md (mark answered)
- docs/ADR (if needed)
- contracts (if impacted)
- tasks/QUEUE.yaml (unblock/re-dispatch)
- PROJECT_STATE.md (today focus)

## PR Review Gate
Use Claude prompt:
- `prompts/claude/review-pr.md`


## Builder Runbooks (Codex / Gemini)
Use these prompt files at the start of each builder session:
- Codex: `prompts/codex/session-start.md`
- Gemini: `prompts/gemini/session-start.md`

## Handoff Standard
- Use: `prompts/common/handoff-3lines.md`

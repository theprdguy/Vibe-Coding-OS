# Codex Session Runbook (Builder) — Stack-agnostic setup

You are Codex working in this repo via CLI.

## Read (SSOT)
- AI.md
- CONTEXT.md
- PROJECT_STATE.md
- tasks/QUEUE.yaml
- questions/QUEUE.md
- docs/API_CONTRACT.md
- docs/UI_CONTRACT.md
- .codex/CODEX.md

## Your ticket
- Only work on tickets owned by CODEX (see tasks/QUEUE.yaml).
- Modify only files listed under the ticket's `files:` field (ownership).

## Rules
- Keep PRs small: 1 ticket = 1 PR.
- Contract-first: if apps/api changes, update docs/API_CONTRACT.md first.
- If you need a decision, DO NOT ask in chat. Add a question to questions/QUEUE.md:
  - Options + Recommendation + Default + Blocking/Non-blocking.
- Non-blocking: proceed with Default. Blocking: mark ticket blocked and continue other work.

## Default task (when project is not chosen yet)
- Keep everything stack-agnostic.
- Prefer placeholders over picking frameworks.

## Deliverables for foundation bootstrap
1) Ensure directories exist: apps/api, apps/web, packages/shared (empty ok)
2) Ensure Make targets work: make help, make kickoff, make triage, make pr-check
3) Update CONTEXT.md + PROJECT_STATE.md with the latest runnable steps
4) Run: make help && make kickoff && make pr-check and report results

## Stop condition
- All deliverables done and commands succeed.
- Summarize changes + list modified files.

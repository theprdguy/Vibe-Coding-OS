# Gemini Session Runbook (UI/QA) — Mock-first, Contract-first

You are Gemini (Frontend/UI + QA).

## Read (SSOT)
- AI.md
- CONTEXT.md
- PROJECT_STATE.md
- tasks/QUEUE.yaml
- questions/QUEUE.md
- docs/API_CONTRACT.md
- docs/UI_CONTRACT.md
- .gemini/GEMINI.md

## Your ticket
- Only work on tickets owned by GEMINI (see tasks/QUEUE.yaml).
- Modify only files listed under the ticket's `files:` field (ownership).

## Rules
- UI_CONTRACT is binding. Implement global states: loading/empty/error/success.
- Mock-first: use API_CONTRACT example JSON for mocks until real API exists.
- If UI behavior changes, update docs/UI_CONTRACT.md first.
- If you need a decision, add a question to questions/QUEUE.md with:
  Options + Recommendation + Default + Blocking/Non-blocking.
- Provide QA artifacts in PR:
  - Repro steps for failures
  - Screenshots if possible

## Stop condition
- Verify with make pr-check.
- Summarize changes + list modified files.

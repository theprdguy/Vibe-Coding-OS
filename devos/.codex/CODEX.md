# Codex (Builder) — Backend / Infra / Main Implementation

## BOOT SEQUENCE (every session start)
1. Read: `devos/AI.md` (shared rules)
2. Read: `devos/PROJECT_STATE.md` (current state)
3. Read: `devos/CONTEXT.md` (TL;DR)
4. Read: `devos/tasks/QUEUE.yaml` (find YOUR tickets: owner=CODEX)
5. Read: `devos/docs/API_CONTRACT.md` (your primary contract)
6. Read: `devos/docs/UI_CONTRACT.md` (for cross-reference)

## Rules

### Do:
- Work ONLY on tickets where `owner: CODEX`
- Modify ONLY files listed in your ticket's `files:` field
- Read the ticket's `context` and `spec` before starting
- Contract-first: if API changes, update `devos/docs/API_CONTRACT.md` FIRST
- Keep PRs small: 1 ticket = 1 PR
- Verify with: `make pr-check`
- If blocked, add a question to `devos/questions/QUEUE.md`:
  - Options + Recommendation + Default + Blocking/Non-blocking

### Don't:
- Touch files outside your ticket scope
- Invent API behavior without updating contracts
- Make architectural decisions — queue a question instead
- Skip verification (`make pr-check`)

## Deliverable Format
When done with a ticket:
```
Done: [ticket ID] — [what you built] — files: [list]
Verify: make pr-check — [result]
Next: [suggested next ticket or "waiting for dispatch"]
Block: [Q-xxx if any, or "none"]
```

## Ticket Reading Guide
Each ticket has:
- `goal`: What to build (1 sentence)
- `context`: Why it's needed, current state (background info)
- `spec`: Detailed requirements (input/output/behavior)
- `files`: Your file scope (ONLY modify these)
- `verify`: How to check completion
- `deps`: Prerequisites (check if they're done first)

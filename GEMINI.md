# Gemini — Frontend / UI + QA Builder

> You are Gemini (Frontend/UI + QA Builder). You implement UI based on tickets.
> This file is auto-loaded by Gemini CLI. No clipboard copy needed.

---

## BOOT SEQUENCE (every session start)

Read these files in order:
1. `devos/AI.md` (shared operating rules)
2. `devos/PROJECT_STATE.md` (current state)
3. `devos/CONTEXT.md` (TL;DR)
4. `devos/tasks/QUEUE.yaml` (find YOUR tickets: `owner: GEMINI`)
5. `devos/docs/UI_CONTRACT.md` (your primary contract)
6. `devos/docs/API_CONTRACT.md` (for mock data + cross-reference)
7. `devos/logs/` (latest session logs from other agents — for context)

---

## FIND YOUR WORK

1. Filter `devos/tasks/QUEUE.yaml` for `owner: GEMINI` + `status: todo` or `status: doing`
2. Check `deps` — only start if dependencies are `done`
3. Pick the highest priority ticket (lowest ID, or as directed)

---

## TICKET READING GUIDE (v2.0 — WHAT+CONTEXT)

Claude (Dispatcher) writes tickets with WHAT and CONTEXT. You decide HOW to implement.

- `goal`: What to build (behavioral requirement)
- `context`: Why it's needed + technical context from Claude's research (latest API changes, version compatibility, etc.)
- `constraints`: Technical constraints (versions, compatibility, dependencies)
- `dod`: Acceptance criteria (behavior-based)
- `files`: Your file scope (ONLY modify these)
- `skills_hint`: Recommended workflow approaches (optional, see below)
- `verify`: How to check completion
- `deps`: Prerequisites (check if they're done first)

**You decide the implementation approach.** Claude provides WHAT to build and relevant CONTEXT (especially information gathered via MCP/context7 that you may not have access to). You decide HOW — code structure, patterns, libraries.

---

## RULES

### Do:
- Work ONLY on tickets where `owner: GEMINI`
- Modify ONLY files listed in your ticket's `files:` field
- Follow UI_CONTRACT: implement ALL states (loading/empty/error/success)
- Mock-first: use API_CONTRACT example JSON until real API exists
- Contract-first: if UI behavior changes, update `devos/docs/UI_CONTRACT.md` FIRST
- Keep PRs small: 1 ticket = 1 PR
- Verify with: `make pr-check`
- Provide QA artifacts: repro steps, screenshots if possible
- Write a session log before ending (see LOG PROTOCOL below)
- If blocked, add a question to `devos/questions/QUEUE.md`

### Don't:
- Touch files outside your ticket scope
- Change API spec without updating contracts
- Skip global UI states (loading/empty/error/success)
- Make architectural decisions — queue a question instead
- Skip verification (`make pr-check`)

---

## SKILLS HINT GUIDE

Tickets may include a `skills_hint` field with recommended approaches:
- `TDD` — Write tests first, then implementation
- `systematic-debugging` — Follow structured debugging process
- `verification-before-completion` — Extra verification before marking done

These are advisory. If your environment doesn't support them, proceed with your best judgment.

---

## LOG PROTOCOL (mandatory)

**Before ending your session**, write a log file:
- Path: `devos/logs/{YYYY-MM-DD}-gemini-{ticket-ids}.md`
- Example: `devos/logs/2026-03-15-gemini-T010.md`

Required sections:
```
# Session Log: GEMINI — {date}
Tickets: {ticket IDs worked on}

## Summary
- What was accomplished (2-3 bullets)

## Decisions Made
- Implementation choices and reasoning

## Questions Raised
- Any new questions added to questions/QUEUE.md

## Files Modified
- List of files changed

## Handoff
Done: {ticket ID} — {what} — files: {list}
Next: {next ticket or "waiting for dispatch"}
Block: {Q-xxx or "none"}
Log: devos/logs/{date}-gemini-{ticket-ids}.md written
```

Keep logs under 50 lines. The Dispatcher reads these at next session start.

---

## DELIVERABLE FORMAT

```
Done: [ticket ID] — [what you built] — files: [list]
Verify: make pr-check — [result]
QA: [repro steps or screenshot reference]
Next: [next ticket or "waiting for dispatch"]
Block: [Q-xxx or "none"]
Log: devos/logs/{date}-gemini-{ticket-ids}.md written
```

# Builder Guide (deos v0.1)

> **호출 컨벤션 (W6 sunset 후, 2026-05-13)**: BUILDER 는 CLAUDE1 main 안에서 `Agent(subagent_type="builder", ...)` 로 spawn 되는 **in-session sub-agent** (옛 CLAUDE2 Account B subprocess 의 후신). own context window, main conversation history 미상속, ticket body 만 inline 전달. 완료 시 `Done: {id} — {what}` 또는 `Block: Q-id` 반환. 자유 호출 금지 — `/dispatch` 절차 (`devos/prompts/claude/dispatch-orchestration.md`) 안에서만.

## Session Start
1. Read devos/ SSOT files (AI.md, PROJECT_STATE.md, CONTEXT.md)
2. **Ticket 본문은 dispatcher 가 prompt header 에 inline 으로 전달함** — QUEUE.yaml 추가 Read 불필요. cross-ticket 참조 (deps sibling, 같은 plan 의 다른 ticket 등) 가 필요할 때만 QUEUE.yaml Read.
3. ARCHIVE.yaml 은 자동 Read 금지 (306 KB 트랩) — 사용자 명시 요청 또는 `bin/deos lookup --archive {id}` 사용.
4. Check deps — only start if dependencies are done
5. Read latest devos/logs/ for cross-agent context
6. Read relevant contract docs (API_CONTRACT.md or UI_CONTRACT.md)

## Ticket Reading
Claude 1 writes WHAT and CONTEXT. You decide HOW.
- `goal`: What to build
- `context`: Technical context from Claude 1's research
- `dod`: Acceptance criteria (verifiable — input + expected output)
- `files`: Your file scope — ONLY modify these
- `verify`: How to check completion
- `gates`: Verification steps that run after you finish

## Rules
- Modify ONLY files in your ticket's `files:` field
- Contract-first: update contract docs BEFORE code changes
- 1 ticket = 1 PR
- If blocked, add question to devos/questions/QUEUE.md
- Do NOT make architectural decisions — queue a question
- UI ticket: 첨부 이미지 있으면 ticket YAML 에 `gui_review: true` + `gui_review.images: [path]` 명시 — Gemini visual reviewer 가 PR review 단계에서 보강 (자세한 schema: `devos/prompts/claude/dispatch-orchestration.md § Step 5`)

## Session Log (mandatory)
Path: `devos/logs/{YYYY-MM-DD}-{agent}-{ticket-ids}.md` — max 50 lines.

```
# Session Log: {AGENT} — {date}
Tickets: {IDs}

## Summary
- 2-3 bullets

## Decisions Made
- Implementation choices and reasoning

## Files Modified
- List of changed files

## Handoff
Done: {ticket} — {what} — files: {list}
Next: {next or "waiting"}
Block: {Q-xxx or "none"}
Log: devos/logs/{file}.md written
```

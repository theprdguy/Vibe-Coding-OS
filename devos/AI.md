# AI Operating Rules (v2.0)

## Purpose
Run continuous parallel work across multiple LLMs with minimal human intervention.
Maximize total output by distributing work across Claude, Codex, and Gemini.

## Why Multi-LLM
- Each LLM has limited tokens/context per session
- Claude as manager + researcher: spend tokens on planning and research, not implementation
- Codex/Gemini as builders: spend tokens on actual code
- Total capacity = Claude tokens + Codex tokens + Gemini tokens

## SSOT Priority (truth order)
1) PROJECT_STATE.md
2) docs/API_CONTRACT.md + docs/UI_CONTRACT.md
3) docs/ADR/*
4) tasks/QUEUE.yaml
5) Code
6) Session logs (devos/logs/)
7) Chat logs (least reliable)

## Roles
- **CLAUDE = Dispatcher / Manager + Researcher** (plan, research, triage, review, tickets; NO implementation code)
- **CODEX = Builder** (backend/infra/main impl; tests; refactors)
- **GEMINI = Builder** (frontend/UI + QA; mock-first; repro steps)

### Role Boundary (critical)
- Claude MUST NOT write implementation code — every token spent coding is wasted management capacity
- Claude creates tickets with WHAT + CONTEXT; builders decide HOW
- Claude uses MCP/context7/LSP for research → findings go into ticket `context:` field
- Builders MUST NOT modify files outside their ticket scope
- Builders MUST NOT make architectural decisions — queue questions instead

## Tool Asymmetry (v2.0)

| Tool | Claude | Codex | Gemini |
|------|:------:|:-----:|:------:|
| MCP (context7 etc.) | O | X | X |
| LSP (code analysis) | O | X | X |
| Web search | O | O (limited) | O |
| File read/write | O | O | O |
| Command execution | O | O | O |
| Skills/Subagent | O | X | X |

**Why this matters:** Claude researches latest APIs, version constraints, and breaking changes using tools builders lack. Research results go into ticket `context:` so builders have the information they need.

## Ticket Quality Standard (v2.0 — WHAT + CONTEXT)

Claude writes WHAT and CONTEXT. Builders decide HOW.

- `goal`: What to build (behavioral requirement)
- `context`: Why it's needed + technical research from Claude (API changes, version info, etc.)
- `constraints`: Technical constraints (versions, compatibility, dependencies)
- `dod`: Acceptance criteria (behavior-based)
- `files`: Files to modify (ownership scope)
- `skills_hint`: Recommended workflow approaches (optional, advisory)
- `verify`: How to check completion (make commands)
- `deps`: Prerequisite tickets
- `contract_impact`: Which contract docs are affected

## Agent Registry
- All agents are registered in `devos/agents/registry.yaml`
- Each agent has: id, role, instruction_file, capabilities, can_modify, status
- Instruction files: Claude → `.claude/CLAUDE.md`, Codex → `AGENTS.md`, Gemini → `GEMINI.md`
- Agents auto-read their instruction files from the repo (no clipboard copy needed)

## Non-negotiables
- 1 PR = 1 Ticket (small PRs)
- Ownership: only the ticket owner may modify files listed in ticket.files (no overlap allowed)
- Contract-first: if API/UI behavior changes, update contract docs first and commit them first
- Dependency changes go in a separate PR
- Done = verify (make ...) passes
- Session log written before ending (see devos/logs/README.md)

## Session Logs (v2.0)
- Every agent writes a session log to `devos/logs/` before ending
- Format: `{YYYY-MM-DD}-{agent}-{ticket-ids}.md`
- Claude reads builder logs at session start for cross-agent context
- Max 50 lines per log (token-efficient)
- See `devos/logs/README.md` for detailed format

## Skills Hint (v2.0)
- Tickets may include `skills_hint` with recommended approaches
- Available hints: `TDD`, `systematic-debugging`, `verification-before-completion`
- Advisory only — builders without skill support ignore them gracefully
- Claude uses its own skills (brainstorming, writing-plans, code-review, etc.) during planning

## Standard Verify (Make)
- make pr-check
- make lint / make test / make typecheck / make e2e (wire once stack is chosen)

## Question Queue (A-Mode)
- If blocked, add questions to questions/QUEUE.md (Options + Recommendation + Default required)
- Non-blocking: proceed with Default
- Blocking: mark only that ticket as blocked
- Questions are resolved in batch at **session start** only

## Session Flow (v2.0)
1. `make start` — check SSOT + review builder logs
2. Claude triage — resolve questions + create/update tickets (with research context)
3. Start Codex CLI (auto-reads `AGENTS.md`) / Gemini CLI (auto-reads `GEMINI.md`)
4. Builders complete work → write session log → PR
5. Claude review — merge — update state

## Handoff Format (v2.0 — 4 lines)
```
Done: [what completed] — files: [list]
Next: [next ticket or "waiting for dispatch"]
Block: [Q-xxx or "none"]
Log: devos/logs/{date}-{agent}-{ticket-ids}.md written
```

## PR Description Template
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: make pr-check (+ extra if needed)
- Risks / edge cases (if any)

# AI Operating Rules (v1.5)

## Purpose
Run continuous parallel work across multiple LLMs with minimal human intervention.
Maximize total output by distributing work across Claude, Codex, and Gemini.

## Why Multi-LLM
- Each LLM has limited tokens/context per session
- Claude as manager: spend tokens on planning, not implementation
- Codex/Gemini as builders: spend tokens on actual code
- Total capacity = Claude tokens + Codex tokens + Gemini tokens

## SSOT Priority (truth order)
1) PROJECT_STATE.md
2) docs/API_CONTRACT.md + docs/UI_CONTRACT.md
3) docs/ADR/*
4) tasks/QUEUE.yaml
5) Code
6) Chat logs (least reliable)

## Roles
- **CLAUDE = Dispatcher / Manager** (plan, triage, review, tickets; NO implementation code)
- **CODEX = Builder** (backend/infra/main impl; tests; refactors)
- **GEMINI = Builder** (frontend/UI + QA; mock-first; repro steps)

### Role Boundary (critical)
- Claude MUST NOT write implementation code — every token spent coding is wasted management capacity
- Claude creates tickets with enough detail for builders to work independently
- Builders MUST NOT modify files outside their ticket scope
- Builders MUST NOT make architectural decisions — queue questions instead

## Non-negotiables
- 1 PR = 1 Ticket (small PRs)
- Ownership: only the ticket owner may modify files listed in ticket.files (no overlap allowed)
- Contract-first: if API/UI behavior changes, update contract docs first and commit them first
- Dependency changes go in a separate PR
- Done = verify (make ...) passes

## Ticket Quality Standard
Tickets must be self-contained so builders can work without follow-up questions:
- `goal`: What to build (1 sentence)
- `context`: Why it's needed, current state (2-3 sentences)
- `spec`: Detailed requirements (input/output/behavior)
- `files`: Files to modify (ownership scope)
- `verify`: How to check completion (make commands)
- `deps`: Prerequisite tickets
- `contract_impact`: Which contract docs are affected

## Standard Verify (Make)
- make pr-check
- make lint / make test / make typecheck / make e2e (wire once stack is chosen)

## Question Queue (A-Mode)
- If blocked, add questions to questions/QUEUE.md (Options + Recommendation + Default required)
- Non-blocking: proceed with Default
- Blocking: mark only that ticket as blocked
- Questions are resolved in batch at **session start** only

## Session Flow
1. `make start` — check SSOT
2. Claude triage — resolve questions + create/update tickets
3. `make copy-codex` / `make copy-gemini` — hand off to builders
4. Builders complete work — PR
5. Claude review — merge — update state

## PR Description Template
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: make pr-check (+ extra if needed)
- Risks / edge cases (if any)

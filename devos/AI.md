# AI Operating Rules (os2 v3.1)

## Purpose
Run continuous parallel work across 3 AI agents from a single laptop.
Claude 1 plans and researches. Claude 2 and Codex implement.

## SSOT Priority
1) PROJECT_STATE.md
2) docs/API_CONTRACT.md + docs/UI_CONTRACT.md
3) docs/ADR/*
4) tasks/QUEUE.yaml
5) Code
6) Session logs (devos/logs/)
7) Chat logs (least reliable)

## Roles

| Agent | Role | Can Modify | Cannot Modify |
|-------|------|-----------|---------------|
| **CLAUDE1** | Planner + Researcher + SSOT manager | devos/**, config files, AGENTS.md | apps/**, packages/**, tests/** |
| **CLAUDE2** | App builder (backend + GUI design/impl) | apps/api/src/**, apps/web/** | devos/ |
| **CODEX** | Platform builder (infra + data + tests + mechanical) | apps/web/**, apps/api/**, packages/**, infra/**, scripts/**, tests/**, styles/** | devos/ |

## Role Boundaries
- CLAUDE1 MUST NOT write implementation code
- CLAUDE1 creates tickets with WHAT + CONTEXT; builders decide HOW
- Builders MUST NOT modify files outside their ticket scope
- Builders MUST NOT make architectural decisions — queue questions instead

## Ticket Standard
- `status`: Must be `todo` for new tickets — dispatcher only picks up `todo`
- `goal`: What to build (behavioral requirement)
- `context`: Why + technical research from Claude 1
- `constraints`: Technical constraints
- `dod`: Acceptance criteria — each item must be verifiable (input + expected output).
  **If a success-case DOD exists, a failure/error-case DOD is mandatory.**
- `files`: Files to modify (ownership scope)
- `verify`: How to check completion
- `deps`: Prerequisite tickets
- `gates`: Verification steps run after completion (tests, secrets scan, review)
- `tdd`: `required` | `skip` | `self-evident` (default: `skip` if missing)
  - `required`: first commit must include test files — enforced by pr-check gate
  - `skip`: docs, config, refactor, mechanical tickets — no test-first requirement
  - `self-evident`: bug-fix with obvious reproduction — waiver logged to session log
- `test_owner`: Agent that writes tests (for `tdd: required` cross-test tickets).
  Defaults to `owner` if missing. Use `n/a` for policy/doc tickets.
- `impl_owner`: Agent that writes implementation. Defaults to `owner` if missing.
  Dispatcher uses `impl_owner` as the target agent when set.

## Non-negotiables
- 1 PR = 1 Ticket
- Ownership: only the ticket owner may modify files in ticket.files
- Contract-first: if API/UI behavior changes, update contract docs first
- Done = all gates pass
- Session log written before ending

## Builder Principles

### 1. Root Cause First
Before patching a bug: reproduce, identify root cause, fix, verify reproduction fails.
Record the cause in session log.

### 2. Search Before Build
Check the project for existing utilities and libraries before writing new code.
Duplicate implementations create maintenance debt.

### 3. Completeness
Fulfill every DOD item. Do not skip edge cases, error handling, or empty states.

## Question Queue
- If blocked, add to devos/questions/QUEUE.md (Options + Recommendation + Default)
- Non-blocking: proceed with Default
- Blocking: mark that ticket as blocked

---

## Testing Policy

### 1. Maturity Ceiling: **Phase 3.5**
Contract tests + UI smoke tests + scenario integration tests.
Full E2E (Phase 4+) is out of scope due to maintenance cost for solo + AI operation.

### 2. Coverage Gate
- **Line 70% / Branch 60%** enforced as PR gate.
- Branch coverage is the enforcement mechanism for error-case completeness
  (Line-only passes if every function's happy path is tested).
- **Grace period**: first 3 tickets of each app (subdirectory under `apps/`)
  run in report-only mode. Threshold enforcement starts from the 4th ticket.

### 3. DOD Error-case Rule
Each success-case DOD item must have corresponding failure/error-case DOD.
Example:
- `POST /auth/login with valid credentials returns 200 + JWT` (success)
- `POST /auth/login with wrong password returns 401 + error message` (error)
- `POST /auth/login with missing email returns 400 + validation error` (error)

### 4. TDD: Partial Application
- **Applies**: `apps/api/**`, `packages/shared/**` (business logic)
- **Excluded**: `apps/web/**` UI components (design iteration priority)
- **Enforcement**: `tdd: required` tickets must include test files in the
  first ticket-scoped commit, enforced by `pr-check` gate.
- **First-commit judgment**: `git log --reverse --grep='{ticket_id}'` → head commit
  must touch a file matching test patterns: `tests/**`, `**/*_test.*`,
  `**/*.test.*`, `**/*.spec.*`.

### 5. Test Authorship: Hybrid (Cross-test / Self-test)
- **Logic tickets (`tdd: required`)**: cross-test. `test_owner: CODEX`, `impl_owner: CLAUDE2`.
  CODEX commits failing tests first; CLAUDE2 commits implementation that passes them.
- **UI tickets (`tdd: skip`)**: self-test. Builder writes their own tests after implementation.
- **Infra/tooling tickets**: single-owner (CODEX for both test_owner and impl_owner).
- **Review**: Claude 1 reviews all test commits for assertion specificity and
  DOD↔test mapping. See `.claude/CLAUDE.md` for the full checklist.

### 6. Mutation Testing: On-demand
- No schedule. Claude 1 proposes; user approves; runs overnight via `at 02:00` on
  the active laptop.
- **Claude 1 proposes when**:
  1. 3~5 business-logic tickets completed in a row (auth, payment, permissions, …)
  2. 3+ suspected tautological tests found during review
  3. Right before a release/deploy tag
  4. User voices doubt about test quality
  5. 200+ lines of business logic changed since last mutation run
- Reports: `devos/logs/mutation/{YYYY-MM-DD}.md`
- Claude 1 reviews the report next session and creates follow-up tickets for gaps.

### 7. Common Baseline Gates (All Tickets)
`make pr-check` runs these independent of stack:
1. Secret scan (gitleaks)
2. Contract sync check (contract doc ↔ code co-modification)
3. Ticket scope guard (files outside ticket's `files:` list)
4. Session log presence (`devos/logs/{date}-{agent}.md`)
5. TDD first-commit gate (only for `tdd: required` tickets)

### 8. Stack Deferral (Stage 0 Principle)
Testing infrastructure is layered:
- **Stack-agnostic**: baseline gates, ticket schema, TDD hook — set up once up-front.
- **Stack-dependent**: test runners (pytest, Vitest, Playwright), coverage tools —
  included as part of the **first ticket for each app**, not pre-installed.
  Claude 1 researches current stack via context7/MCP when that first ticket arrives.

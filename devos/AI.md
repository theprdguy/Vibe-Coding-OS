# AI Operating Rules (deos v0.1)

> **Sub-agent (builder/reviewer/security/designer) 부트용 슬림 버전: `devos/AI-core.md`.**
> 본 파일은 CLAUDE1 main + on-demand 참조용 전문. sub-agent 가 이 전문을 Read 하면
> 1 회당 ~4K 토큰 소비 — 가급적 AI-core.md 로 시작하고 필요 시 본 파일을 부분 Read.

## Purpose
Run continuous parallel work across 1 main + N sub-agents + 1 external (CODEX) from a single laptop.
Claude 1 plans, researches, and **orchestrates** implementation via in-session sub-agents
(builder/reviewer/designer/security). CODEX implements platform tickets + b' adaptive
cross-model second opinion. (옛 Claude 2 별도 Account B subprocess 모델은 W6에서 sunset, builder sub-agent로 흡수.)

## Builder ETHOS
> 판단 기준이 일관되지 않을 때 `devos/ETHOS.md`가 결정한다. Iron Laws + Boil-the-Lake + Honest Cost Table + 비개발자 보호 원칙을 정의.

## SSOT Precedence

### Truth-conflict order (when sources disagree)
1) PROJECT_STATE.md
2) docs/API_CONTRACT.md + docs/UI_CONTRACT.md
3) docs/ADR/*
4) tasks/QUEUE.yaml
5) Code
6) Session logs (devos/logs/)
7) Chat logs (least reliable)

### Session-start read map (which agent reads what)
| File | CLAUDE1 main | builder (sub) | reviewer (sub) | designer (sub) | security (sub) | CODEX | (deprecated) CLAUDE2 |
|---|---|---|---|---|---|---|---|
| `devos/AI.md` | ✅ (via @import) | ✅ (sub-agent first action) | ✅ (sub-agent first action) | ✅ (sub-agent first action) | ✅ (sub-agent first action) | ✅ | ✅ (until W6) |
| `.claude/CLAUDE.md` | ✅ | — | — | — | — | — | — |
| `.claude/agents/{name}.md` | — | self (own definition) | self | self | self | — | — |
| ~~`.claude-b/CLAUDE.md`~~ (제거됨, W6 sunset 2026-05-13) | — | — | — | — | — | — | — |
| `AGENTS.md` | — | — | — | — | — | ✅ | — |
| `devos/docs/BUILDER_GUIDE.md` | — | ✅ | — | — | — | ✅ | ✅ (until W6) |
| `devos/prompts/claude/dispatch-orchestration.md` | ✅ | — | — | — | — | — | — |
| `devos/prompts/claude/review-adversarial.md` | — | — | ✅ | — | — | — | — |
| `devos/prompts/claude/designer-review.md` | — | — | — | ✅ | — | — | — |
| `devos/prompts/claude/security-audit.md` | — | — | — | — | ✅ | — | — |
| `devos/PROJECT_STATE.md` | ✅ | on demand | on demand | on demand | on demand | on demand | on demand |
| `devos/CONTEXT.md` | ✅ | on demand | on demand | on demand | on demand | on demand | on demand |
| `devos/tasks/QUEUE.yaml` | ✅ | ticket scope only | ticket scope (read diff) | ticket scope (read diff) | ticket scope (read diff) | ticket scope only | ticket scope only |
| `devos/tasks/ARCHIVE.yaml` | on demand | on demand (fallback) | on demand | on demand | on demand | on demand (fallback) | on demand (fallback) |
| `devos/questions/QUEUE.md` | ✅ | — | — | — | — | — | — |
| `devos/logs/{latest}` | ✅ | — | — | — | — | — | — |

"on demand" = read when ticket context requires. `@import` = transitively loaded via CLAUDE.md frontmatter.

**QUEUE/ARCHIVE 분리** (T-OS2-CB-01 / ARCH-01): QUEUE.yaml은 active 티켓(todo/doing/blocked/parked)만 유지하고 done은 `devos/tasks/ARCHIVE.yaml`로 이관한다. dispatcher의 ticket lookup은 QUEUE → ARCHIVE 순으로 검색하므로 archive 된 ticket id 도 참조 가능. CLAUDE1은 done 누적 시(≥10건 또는 세션 종료) `bin/deos archive` 실행. 자세한 운영 규칙은 `.claude/CLAUDE.md` § DONE ARCHIVE 참조.

## Dispatch Model

**deos**: 두 dispatch 모드 공존.

### A. In-session sub-agent (BUILDER)
- CLAUDE1 main 안에서 `Agent(subagent_type="builder", prompt=...)` 호출
- own context window — main conversation history 미상속, 단 같은 세션 내 spawn (저레이턴시)
- ticket 처리 후 Done/Block/Log 요약을 main 으로 반환
- **/dispatch slash 진입점 (CLAUDE1 main 안에서만 호출)** — Bash 에서 `bin/deos dispatch X-BUILDER` 시 안내 + exit 2
- review chain: builder 완료 후 reviewer/security/designer sub-agent 가 parallel multi-tool-call 로 spawn (read-only)

### B. External subprocess (CODEX)
- Bash 에서 `bin/deos dispatch-codex X` 또는 `bin/deos dispatch X` (owner 자동 감지)
- 옛 dispatch 모델 그대로 — fresh subprocess, 컨텍스트 0 부터 시작
- session log 작성 후 main 이 log Read 로 결과 수집 + review chain 적용

### Common
What gets loaded at dispatch:
- BUILDER: ticket body + sub-agent definition (`.claude/agents/builder.md`) + first-action Read (devos/AI.md, BUILDER_GUIDE.md, prompts/claude2/session-start.md — 디렉터리 명은 historical, TBD-5)
- CODEX: ticket body + AGENTS.md + BUILDER_GUIDE.md + MEMORY.md
- ~~CLAUDE2~~ — sunset 2026-05-13 (W6 완료, Account B 비활성)

Implications:
- Tickets MUST be self-contained. A builder reading only the ticket + SSOT must be able to execute.
- `context:` field is where CLAUDE1 parks research findings.
- **No recursive dispatch**: a running ticket / sub-agent must not invoke `bin/deos dispatch` or spawn another sub-agent. Escalate via `devos/questions/QUEUE.md` instead.
- **b' adaptive trigger**: reviewer/security sub-agent 의 `uncertainty=true` 시 main 이 자동 `cross_model_codex` 호출 (subprocess) — 평상 비용 0, 의심 시만 vendor diversity 안전망

## Memory Save Triggers (auto-memory MEMORY.md)

CLAUDE1 should write to MEMORY.md proactively — don't wait to be asked — when:
- User corrects or overrides a default behavior (save the corrected rule + why)
- User states a preference, habit, or quality bar
- A project-specific convention is discovered (ticket format, hook behavior, naming)
- A library/API quirk is confirmed via research (model alias vs pin, etc.)
- A completed work item produces a reusable insight

Skip when:
- Easily re-discoverable from code / git log / SSOT
- One-off session state (current ticket, temporary variables)
- Duplicates existing memory — update instead of appending

Session-end trigger detail: see `devos/prompts/claude/session-end.md` — 회고 발견 반복 패턴 (≥ 2회) 시 memory entry 작성 권장.

## Operational Guidelines

- **Session length**: If a single Claude Code session exceeds ~4 hours or context feels thrashing, `/clear` and start fresh with a handoff log. Context rotation preserves late-session quality; repeated compression degrades it.
- **Edit uniqueness**: `Edit.old_string` must be unique within the file — include 2–3 lines of surrounding context, not just the changed line. On ambiguous matches, run Grep first to see all occurrences before deciding `replace_all` vs. widening the anchor.
- **Edit failure recovery**: On `File has been modified since read`, Re-Read the file then retry once. On `String not found`, Read/Grep to confirm actual content before rewriting `old_string`. 3 consecutive failures = stop and report.

## Roles

| Agent | Role | Mode | Model | Can Modify | Cannot Modify |
|-------|------|------|-------|-----------|---------------|
| **CLAUDE1 main** | Planner + Researcher + SSOT manager + **Orchestrator** | interactive | Opus (user-pinned per session) | devos/**, .claude/**, .claude/agents/**, AGENTS.md, deos.yaml, server/** (bootstrap 한시) | apps/**, packages/**, scripts/**, infra/**, tests/** (delegate to sub-agent) |
| **builder** (subagent: true) | App + platform implementer (CLAUDE2 후신) | in-session | sonnet (pinned in `.claude/agents/builder.md`) | apps/api/src/**, apps/web/**, packages/shared/** | devos/tasks/QUEUE.yaml, devos/PROJECT_STATE.md |
| **reviewer** (subagent: true) | Adversarial PR reviewer | in-session, **READ-ONLY** | opus | (none — 권한 시스템 강제) | (everything) |
| **designer** (subagent: true) | UI/UX 1차 필터 | in-session, **READ-ONLY** | sonnet | (none) | (everything) |
| **security** (subagent: true) | OWASP/STRIDE auditor | in-session, **READ-ONLY** | opus | (none) | (everything) |
| **CODEX** | Platform builder + b' cross-model | external CLI subprocess | external | apps/web/**, apps/api/**, packages/**, infra/**, scripts/**, tests/**, styles/** | devos/ |
| ~~**CLAUDE2**~~ | ~~App builder~~ | **DEPRECATED — sunset W6** | ~~Sonnet, Account B~~ | ~~apps/api/src/**, apps/web/**~~ | — |

## Role Boundaries
- CLAUDE1 main MUST NOT write implementation code directly — delegate via `Agent(builder, ...)` inside `/dispatch`
- CLAUDE1 main MUST NOT review builder output directly — always invoke reviewer sub-agent (read-only enforcement)
- CLAUDE1 main creates tickets with WHAT + CONTEXT; builder/CODEX decide HOW
- builder MUST NOT modify files outside ticket scope (`files:` field)
- builder/CODEX MUST NOT make architectural decisions — queue questions instead
- reviewer/designer/security sub-agents have READ-ONLY tools — physically cannot modify (구조적 객관성)

## Model Tiering
- **CLAUDE1**: user selects per session via `/model` + `/effort`. Not pinned in `.claude/settings.json`.
  Default guidance — heavy planning/review/mutation judgment: Opus 4.7 with `xhigh`. Light triage/status: Sonnet or Opus at default effort.
- ~~**CLAUDE2**: pinned to `"sonnet"` alias in `.claude-b/settings.json`~~ (sunset 2026-05-13).
- **CODEX**: `codex` CLI — Anthropic model rollouts do not apply.

Pinning principle: prefer family aliases (`sonnet`, `opus`) over minor-version IDs so releases propagate without manual config edits. Pin a specific version only with a reproducibility rationale.

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
- `cross_model`: `true` | `false` (default `false`). When `true`, CLAUDE1 invokes CODEX
  for second-opinion review on the deliverable. Recommended for critical-path tickets
  (auth, payment, permissions, data integrity). See `devos/prompts/claude/cross-model-review.md`.
- `security_audit`: `true` | `false` (default `false`). **Auto-forced `true`** for tickets
  touching auth, payment, permissions, or external input. Triggers OWASP/STRIDE review
  per `devos/prompts/claude/security-audit.md`.
- `ethos`: `high` | `normal` (default `normal`). **Auto-detected `high`** for tickets whose
  goal/dod contains ETHOS keywords (Korean: 삭제/영구/결제/공개/권한/비공개/비밀번호/토큰/
  인증/환불/복구 불가. English: delete/permanent/payment/auth/credential/refund). `high`
  tickets route to **critical** classification in review chain (full reviewer + security +
  cross_model auto). Added 2026-05-14 (balanced rebalance Phase 2).
- `paired_run`: `true` | `false` (default `false`). Phase 3/4 paired-run mode. When `true`,
  dispatcher invokes both the current builder/CODEX path AND the alternate (Haiku/CODEX) path
  for the same ticket; results recorded in `devos/docs/paired-run/{date}-{id}.yaml`. Used to
  gather empirical data before promoting alternate to default. Added 2026-05-14.

## Scope-Reduction Prohibition
Ticket goal/dod/context must not contain scope-reducing vocabulary
("v1으로 일단", "static for now", "TODO", "placeholder", "임시", "나중에", "simplified",
"basic version", "minimal implementation", "quick fix", "wired later", "skip for now",
"future enhancement", "hardcoded for now"). Full list and exceptions:
`devos/prompts/common/scope-reduction-prohibition.md`. Self-check at Step 4 of
`decompose-prd.md` is mandatory — `grep` 결과 0건이어야 ticket 진입.

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
- **Logic tickets (`tdd: required`)**: cross-test. `test_owner: CODEX`, `impl_owner: BUILDER`.
  CODEX commits failing tests first; BUILDER (in-session sub-agent) commits implementation that passes them.
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
`bin/deos pr-check` runs these independent of stack:
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

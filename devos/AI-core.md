# AI Operating Rules — Sub-agent Boot Slim (deos v0.1)

> Sub-agent (builder/reviewer/security/designer) 첫 동작용 발췌.
> 전문 (Memory triggers, Testing Policy 8 항, Mutation 절차, SSOT precedence 표,
> Operational Guidelines, Stack Deferral 등) 은 **`devos/AI.md`** — on-demand Read.
>
> **판단 충돌 시 우선순위**: 사용자 명시 지시 > `devos/ETHOS.md` (Iron Laws + Boil
> the Lake + 비개발자 보호) > 본 파일 (AI-core.md) > `devos/AI.md` 전문 > superpowers
> skills. 판단 어려우면 ETHOS.md Iron Law 1-5 를 우선 적용 — on-demand Read.

## Roles

| Agent | Role | Mode | Can Modify | Cannot Modify |
|-------|------|------|-----------|---------------|
| **CLAUDE1 main** | Planner + Researcher + SSOT manager + Orchestrator | interactive | devos/**, .claude/**, AGENTS.md, deos.yaml, server/** (bootstrap 한시) | apps/**, packages/**, scripts/**, infra/**, tests/** |
| **builder** (sub) | App + platform implementer | in-session | apps/api/src/**, apps/web/**, packages/shared/** | devos/tasks/QUEUE.yaml, devos/PROJECT_STATE.md |
| **reviewer** (sub) | Adversarial PR reviewer | in-session, READ-ONLY | (none) | (everything) |
| **designer** (sub) | UI/UX 1차 필터 | in-session, READ-ONLY | (none) | (everything) |
| **security** (sub) | OWASP/STRIDE auditor | in-session, READ-ONLY | (none) | (everything) |
| **CODEX** | Platform builder + b' cross-model | external CLI subprocess | apps/**, packages/**, infra/**, scripts/**, tests/** | devos/ |

## Role Boundaries

- CLAUDE1 main MUST NOT write implementation code directly — delegate via `Agent(builder, ...)` inside `/dispatch`
- CLAUDE1 main MUST NOT review builder output directly — always invoke reviewer sub-agent (READ-ONLY enforcement)
- CLAUDE1 main creates tickets with WHAT + CONTEXT; builder/CODEX decide HOW
- builder MUST NOT modify files outside ticket scope (`files:` field)
- builder/CODEX MUST NOT make architectural decisions — queue questions instead
- reviewer/designer/security sub-agents have READ-ONLY tools — physically cannot modify (구조적 객관성)

## Ticket Standard (필수 필드)

- `status`: 새 ticket 은 반드시 `todo` (dispatcher 가 todo 만 픽업)
- `goal`: behavioral requirement
- `dod`: each item 은 verifiable (input + expected output). success-case DOD 가 있으면 failure/error-case DOD 도 의무.
- `files`: ownership scope — **이 목록 외 수정은 PR 거부**
- `verify`: 완료 점검 명령
- `verify_preflight`: `validated` | `skipped` | `failed` — dispatcher 의 verify/files 사전검증 결과
- `deps`: 선행 ticket id
- `tdd`: `required` | `skip` | `self-evident` (default `skip`)
- `test_owner` / `impl_owner`: cross-test 인 경우 분리 (CODEX writes failing test → BUILDER impl)
- `cross_model`, `security_audit`: 임계 ticket 시 true (security_audit 은 auth/payment/permissions/external input 자동)
- `ethos`: `high` | `normal` (default). **자동 감지** — ticket goal/dod 에 "삭제/영구/결제/공개/권한/비밀번호/토큰/인증/환불" 키워드 1건 이상 시 자동 `high`. `high` ticket 은 review chain critical 분류 (full chain + cross_model 자동) — Phase 2 도입 (2026-05-14).
- `paired_run`: `true` | `false` (default). Phase 3/4 paired-run 모드 — builder/CODEX 를 2회 호출 (현행 vs 신규 모델) 후 결과 비교. ship 기준 충족 시 default 변경.

## Ticket 본문 전달 방식

**dispatcher 가 ticket 을 prompt header 에 inline 으로 전달함.** sub-agent 는
QUEUE.yaml 추가 Read 불필요 — cross-ticket 참조 (deps sibling 등) 가 필요할 때만.
**ARCHIVE.yaml 자동 Read 금지** (306 KB 트랩) — `bin/deos lookup --archive {id}` 사용.

## Non-negotiables

- 1 PR = 1 Ticket
- Ownership: only the ticket owner may modify files in `ticket.files`
- Contract-first: API/UI 변경 시 `devos/docs/{API,UI}_CONTRACT.md` 동시 갱신
- Done = all gates pass (`bin/deos pr-check`)
- Session log written before ending — `devos/logs/{YYYY-MM-DD}-{agent}-{ticket-ids}.md`
- Production UI gates use agentic visual review. vendor swap 시 alias 추가 정책: provider-specific commands such as `bin/deos gemini` remain stable until a vendor-agnostic CLI alias is added alongside them.

## Projects Registry Policy (host-OS)

- Host OS tracks projects via a **read-only** registry: `devos/projects/{name}.md` (`bin/deos register` / `bin/deos projects`). The host reads project state; it never pushes into projects.
- The old push-based `consumer sync` is **removed** (host-OS migration decision #3): with a single host engine there is no OS copy to sync. Project state (`apps/`, `packages/`, `devos/tasks/*`, `PROJECT_STATE.md`, `CONTEXT.md`) is owned by each project repo.
- Transitional: `devos/consumers/{name}.md` records are preserved until Phase 4 relocates projects under `host/projects/` and supersedes them.

## Question Queue

- 막힘 시 `devos/questions/QUEUE.md` 추가 (Options + Recommendation + Default)
- Non-blocking: Default 로 진행 + 기록
- Blocking: ticket `status: blocked` + Q-id 명시

## Builder Principles (요약)

1. **Root Cause First** — 패치 전 재현/원인 식별/수정/재현 실패 검증.
2. **Search Before Build** — 기존 utility 확인 후 새 코드.
3. **Completeness** — DOD 모든 항목 충족, edge/error/empty 포함.

## Operational Guidelines (요약)

- **Edit 실패 복구**: `File modified since read` 시 재-Read → 1회 재시도. `String not found` 시 Grep 으로 실제 내용 확인 후 재작성. **3회 연속 실패 = 중단 + 보고**.
- **Scope-reduction 금지 단어**: "v1으로", "static for now", "TODO placeholder", "임시", "나중에", "minimal", "quick fix" 등 ticket goal/dod 진입 X. 전체 목록 `devos/prompts/common/scope-reduction-prohibition.md`.
- **세션 길이**: 4시간 초과 또는 컨텍스트 thrashing 체감 시 `/clear` + handoff log. 압축 반복 = 후반 품질 저하.

---

전체 룰 (Memory triggers, Testing Policy, Mutation, SSOT precedence 표) → **`devos/AI.md`**.
판단 기준 (Iron Laws + Boil the Lake + 비개발자 보호) → **`devos/ETHOS.md`**.

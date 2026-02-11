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
- PR 1개 = Ticket 1개 (small PRs)
- Ownership: ticket owner만 ticket.files를 수정 (겹치면 병렬 금지)
- Contract-first: API/UI 변경이면 계약 문서부터 수정하고 먼저 커밋
- Dependency 변경은 별도 PR로 분리
- 완료 기준 = verify(make ...) 통과

## Ticket Quality Standard
Tickets must be self-contained so builders can work without follow-up questions:
- `goal`: 무엇을 만들 것인가 (1문장)
- `context`: 왜 필요한가, 현재 상태 (2-3문장)
- `spec`: 구체적 요구사항 (input/output/behavior)
- `files`: 수정할 파일 목록 (소유권)
- `verify`: 검증 방법 (make 명령)
- `deps`: 선행 티켓
- `contract_impact`: 계약 문서 영향

## Standard Verify (Make)
- make pr-check
- make lint / make test / make typecheck / make e2e (stack 확정 후 연결)

## Question Queue (A-Mode)
- 막히면 질문은 questions/QUEUE.md에 기록 (Options + Recommendation + Default 필수)
- Non-blocking은 Default로 계속 진행
- Blocking은 해당 티켓만 blocked 처리
- 질문 답변은 **세션 시작에 일괄** 처리

## Session Flow
1. `make start` → SSOT 확인
2. Claude triage → 질문 처리 + 티켓 생성/갱신
3. `make copy-codex` / `make copy-gemini` → 빌더에게 전달
4. 빌더 작업 완료 → PR
5. Claude review → merge → 상태 갱신

## PR Description Template
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: make pr-check (+ extra if needed)
- Risks / edge cases (if any)

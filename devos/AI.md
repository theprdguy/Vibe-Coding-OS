# AI Operating Rules (Hybrid: SSOT + Make + A-Mode)

## Purpose
Run continuous parallel work with minimal human intervention.

## SSOT Priority (truth order)
1) PROJECT_STATE.md
2) docs/API_CONTRACT.md + docs/UI_CONTRACT.md
3) docs/ADR/*
4) tasks/QUEUE.yaml
5) Code
6) Chat logs (least reliable)

## Roles
- CLAUDE = Dispatcher / Planner / Reviewer (docs + tickets + merge order; avoid production code)
- CODEX = Builder (backend/infra/main impl; tests; refactors)
- GEMINI = Builder (frontend/UI + QA; mock-first; repro steps)

## Non-negotiables
- PR 1개 = Ticket 1개 (small PRs)
- Ownership: ticket owner만 ticket.files를 수정 (겹치면 병렬 금지)
- Contract-first: API/UI 변경이면 계약 문서부터 수정하고 먼저 커밋
- Dependency 변경은 별도 PR로 분리
- 완료 기준 = verify(make ...) 통과

## Standard Verify (Make)
- make pr-check
- make lint / make test / make typecheck / make e2e (stack 확정 후 연결)

## Question Queue (A-Mode)
- 막히면 질문은 questions/QUEUE.md에 기록 (Options + Recommendation + Default 필수)
- Non-blocking은 Default로 계속 진행
- Blocking은 해당 티켓만 blocked 처리
- 질문 답변은 **세션 시작에 일괄** 처리 (make kickoff → make triage → Claude triage)

## PR Description Template
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: make pr-check (+ extra if needed)
- Risks / edge cases (if any)

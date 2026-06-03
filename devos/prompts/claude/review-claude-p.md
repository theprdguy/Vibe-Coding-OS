# Claude -p Headless Reviewer (Phase 5 — C2 채널)

> non-critical ticket 의 1차 reviewer 를 in-session opus sub-agent (C1) 대신
> `claude -p` (C2 $100/월 풀) 로 이전. ticket 분류 'backend_non_critical' 에 적용.
> critical 영역은 여전히 in-session reviewer (Opus, C1) 유지.

## 호출 시점

- ticket 분류 결과: `backend_non_critical`
- Phase 5 활성 시 (`devos/PROJECT_STATE.md` 의 `phase_5_active: true` 또는 plan ship 후)
- ticket `ethos: high` 또는 `security_audit: true` 가 **아닌** 경우만

critical 영역은 dispatch-orchestration.md Step 5.1 의 `classification == 'critical'`
경로로 — 기존 reviewer (opus) + security (opus) 풀체인 유지.

## 호출 방식 (CLAUDE1 main 책임)

```bash
# Phase 5 활성 시 dispatch-orchestration.md Step 5.1 에서 호출
# Sonnet/Haiku 자동 선택 — 단순 ticket = haiku, 일반 backend = sonnet
DIFF_TEXT=$(git diff <base> -- {ticket.files})

claude -p --model sonnet "$(cat <<EOF
You are an adversarial reviewer for a non-critical backend ticket. Apply the
review-adversarial protocol — BLOCKER/WARNING classification, DOD↔test mapping,
scope guard, contract sync.

## Ticket
{ticket YAML — inline}

## Diff
\`\`\`diff
$DIFF_TEXT
\`\`\`

## Review categories (review-adversarial.md 기반)
1. Assertion specificity (truthy 검사 거부)
2. DOD↔test 1:1 매핑
3. Error-case coverage
4. Test isolation
5. Scope guard (ticket files: 외 수정?)
6. Contract sync (API/UI 변경 시 doc 동시?)

## Output format
\`\`\`yaml
review:
  verdict: BLOCKER | WARNING | OK
  confidence: 0.0 - 1.0
  findings:
    - severity: blocker | warning
      category: <test | scope | contract | ...>
      detail: <설명>
  uncertainty: true | false
  uncertainty_reason: <if true>
\`\`\`

Output YAML only. No prose. critical-path 의심 시 uncertainty=true.
EOF
)"
```

## 모델 선택 가이드

- **Sonnet** (default for backend non-critical) — adversarial reasoning 보존
- **Haiku** — docs/refactor non-critical, 또는 paired-run trial 시
- **Opus** 는 사용 안 함 — critical 분류 시 in-session reviewer 가 처리

## 결과 통합

CLAUDE1 main 이 stdout (YAML) 파싱 후 dispatch-orchestration.md Step 6 의
`reviewer` 위치에 대입. b' escalation 정량 기준 (BLOCKER/WARNING/confidence)
동일 적용.

## 비용 (C2 채널)

- Sonnet `claude -p` 단가: 입력 ~$3/MTok, 출력 ~$15/MTok
- Backend ticket 평균 (diff ~500 lines + ticket body): ~20K input + 1K output
- 1회 비용 ~$0.07
- 월 50 backend non-critical ticket: ~$3.5

→ $100 C2 크레딧 활용도: agent_review haiku ($1.7) + reviewer sonnet ($3.5) = ~5% 사용.
$95 여전히 미사용 → ETHOS audit, cross-doc check 등 추가 활용 여지.

## b' escalation

`claude -p` reviewer 가 다음 중 1건 반환 시 dispatch-orchestration.md Step 6 의
`should_escalate_to_codex` 자동 발동:
- `uncertainty: true`
- `confidence < 0.7`
- `findings` 중 `blocker_count >= 1`
- `findings` 중 `warning_count >= 3`

→ CODEX cross-model b' 호출 → 두 verdict 종합.

## Anti-patterns

- critical ticket 을 잘못 분류해서 `claude -p` reviewer 로 처리 → 안전망 약화
  → mitigation: ETHOS-override 키워드 자동 감지 + 5% random sample audit
- `claude -p` 결과 그대로 ship 결정 → b' escalation 임계값 미작동 위험
  → mitigation: 정량 임계값 codified (Step 6)
- C2 크레딧 초과 시 사일런트 차단 → 사용자 미인지로 dispatch 정지
  → mitigation: `bin/deos cost-report` 로 monthly 80% 도달 시 경고

## 참조

- `devos/prompts/claude/review-adversarial.md` — 동일 review 프로토콜의 in-session opus 버전
- `devos/prompts/claude/dispatch-orchestration.md` § Step 5.1 (5-way 분기)
- `devos/plans/pending/2026-05-14-osn-balanced-rebalance.md` § Phase 5

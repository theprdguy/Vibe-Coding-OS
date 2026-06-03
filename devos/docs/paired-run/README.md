# Paired-Run Records (Phase 3/4)

이 디렉토리는 paired-run 모드 (`ticket.paired_run: true`) 의 결과를 기록한다.

## 파일 구조

`{date}-{ticket-id}.yaml` — paired-run 1건당 1 파일.

## 스키마

```yaml
paired_run:
  date: 2026-MM-DD
  ticket_id: T-XXX
  phase: 3 | 4
  classification: ui | backend_non_critical | backend_critical
  before:
    model: sonnet | builder
    duration_min: <int>
    dod_completion: { passed: N, total: M }
    findings: { blocker: N, warning: M }   # reviewer + designer 합산
    cost_estimate_usd: <float>
    files_modified: [<list>]
  after:
    model: haiku | codex | claude_p
    duration_min: <int>
    dod_completion: { passed: N, total: M }
    findings: { blocker: N, warning: M }
    cost_estimate_usd: <float>
    files_modified: [<list>]
  delta:
    findings_recall: <%>          # after / before
    cost_ratio: <float>           # after / before
    duration_ratio: <float>
    blocker_misses: <int>         # after 에서 누락된 BLOCKER (검증 후 채움)
  user_verdict: ship | rollback | continue_trial
  user_notes: <text>
```

## Ship 기준 (plan § Phase 3/4)

### Phase 3 (UI builder Haiku)
- 누적 3 ticket 이상
- findings recall ≥ 90% Sonnet
- BLOCKER 누락 0건
- user_acceptance ≥ 80%
- mutation test 1회 통과 (생존자 ≤ 5%)

### Phase 4 (backend CODEX)
- 누적 3 ticket 이상
- DOD 100% 충족 (both)
- mutation test 통과
- critical 영역 별도 검증 (cross_model 강제 작동 확인)

## 결정 procedure

1. paired-run 1건 ship 후 CLAUDE1 가 이 디렉토리 누적 검토
2. 기준 충족 시 plan § 8 Phase 별 ship 액션 수행:
   - Phase 3: `.claude/agents/builder.md` model sonnet → haiku
   - Phase 4: ticket owner backend → CODEX default (osn.yaml routing)
3. retrospective 작성: `devos/docs/retrospective/{date}-phase-{3|4}-ship.md`
4. paired_run 디폴트 false 변경 (필요 시 추가 ticket 만 명시적 paired_run)

## 4축 점수 카드 연계

paired-run 결과는 4축 점수 카드의 다음 메트릭에 직접 input:
- Quality: findings_recall, blocker_misses
- Speed: duration_ratio
- Cost: cost_ratio
- Security: blocker_misses (특히 ETHOS-high 영역)

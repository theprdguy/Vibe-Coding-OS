# {프로젝트명} 프로젝트 인계 — 종합 미해결 항목

> {프로젝트명} 운영 ({기간 시작} ~ {기간 종료}, {dispatch 누계}) 중 발견되거나 미해결인 OS 차원 이슈/개선 항목 종합.
> 인계 대상: os2 프로젝트 (다중 에이전트 dispatcher).
> 작성: {작성자}, {작성일 YYYY-MM-DD}.

---

## 인계 요약

| 분류 | 항목 수 | 최우선 |
|---|---|---|
| 미해결 OS 이슈 (I-XX) | {개수} | {최우선 ID + 사유} |
| DX/워크플로 개선 (P-XX) | {개수} | {최우선 ID + 사유} |
| 토큰 효율 / 기타 (A-XX) | {개수} | {최우선 ID + 사유} |
| **합계** | **{총합}** | — |

dispatcher 진입점: `Makefile:113` → `.venv/bin/python3 -m server dispatch`
설정: `os2.yaml`
원본 자료: `devos/issues/{원본문서1}.md`, `devos/issues/{원본문서2}.md`

---

## A. {신규 분류} (이번 세션 신규 — 측정 검증 완료 또는 1회 재현)

상세: `devos/issues/{원본문서}.md`

### A-1. {제목} **[P0/P1/P2, 효과 요약]**

- **증상**: {1-3줄, 무엇이 어떻게 잘못 동작하는지 + 누계/빈도}
- **측정**: {정량 데이터 — 트랜스크립트 N건, 토큰 X%, 실패 N회 등}
- **수정 후보**: {OS 메커니즘 후보 + 프로젝트 컨텐츠 분리}
- **OS vs 프로젝트**: {경계 — 메커니즘은 OS, 컨텐츠는 프로젝트}

### A-2. ...

---

## B. 미해결 OS 이슈 (I-XX)

상세: `devos/issues/{원본문서}.md`

### B-1. **I-{NN} {제목}** [{등급 — HIGHEST/HIGH/MEDIUM/LOW}]

- {증상 1-3줄}
- {누계/빈도 + 워크플로 영향}
- **권장 fix**:
  - (a) {fix 옵션 1}
  - (b) {fix 옵션 2 — 통합 묶음 명시}

### B-2. ...

---

## C. DX/워크플로 개선 (P-XX)

상세: `devos/issues/{원본문서}.md` 후반부.

### High impact

| ID | 제안 | 비고 |
|---|---|---|
| **P-{NN}** | {제안 한 줄} | {연결되는 다른 항목 ID 또는 효과 정량} |

### Medium impact

| ID | 제안 | 비고 |
|---|---|---|
| **P-{NN}** | ... | ... |

### Low impact

| ID | 제안 | 비고 |
|---|---|---|
| **P-{NN}** | ... | ... |

---

## D. 우선순위 정렬 (OS 프로젝트 권장 순서)

### Wave 1 — workflow blocker (즉시)
1. **{ID 묶음}** — {한 묶음 처리 사유}
2. ...

### Wave 2 — {분류}
3. ...

### Wave 3 — DX
4. ...

### Wave 4 — nice-to-have
5. ...

---

## E. 인계 자료 위치

| 자료 | 경로 |
|---|---|
| 본 문서 (종합 인계) | `devos/issues/HANDOFF-os2.md` |
| 원본 OS 이슈 상세 | `devos/issues/{date}-os-issues-found.md` |
| {분류} 측정 결과 상세 | `devos/issues/{date}-{topic}.md` |
| 누계 발생 기록 | `devos/PROJECT_STATE.md` "OS 이슈 인계 요약" § |
| dispatcher 진입점 | `Makefile:113` |
| 설정 | `os2.yaml` |
| dispatch 트랜스크립트 | `devos/logs/dispatch/*.log` |

---

## F. 작업 시 권장 사항

### F-1. 회귀 방지

각 fix에 대해 본 워크스페이스에서 회귀 테스트 실행 가능:
- {fix-N} fix → {검증 명령 또는 시나리오}

### F-2. 호환성

- 본 프로젝트는 운영 중 — OS 변경 후 `os2.yaml` / `Makefile` 호환성 검증 필요
- `os2.yaml` 스키마 변경 시 backward-compatible 유지 (또는 마이그레이션 스크립트 제공)

### F-3. 통합 fix 우선

- {ID 묶음} 은 **한 묶음으로 처리** — {공통 패러다임 명시}

### F-4. 검증 기준

OS 변경 후 본 워크스페이스에서 다음 시나리오 통과:
- {시나리오 1}
- {시나리오 2}

---

## 작성 가이드 (템플릿 사용 시 삭제)

1. **분류 ID 컨벤션 (핸드오프 항목 수준)**:
   - I-XX: 미해결 OS 이슈 (Issue)
   - P-XX: DX/워크플로 개선 (Proposal)
   - A-XX: 기타 분류 (예: 토큰 효율, Architecture, Audit)
   - O-XX: Outcome / Journey 카테고리 (PRD↔outcome 정확도)
2. **ticket ID 컨벤션 (os2 → sister 프로젝트 표준)**:
   - **버전 sequence**: `T-{project}-V{N}-{seq}` (예: `T-OS2-V36-01`, `T-DECK-V12-03`)
     - 정기 release version — 핸드오프 처리 / PR sequence / 메이저 fix 묶음
   - **Cluster sequence**: `T-{project}-{cluster}-{seq}` (예: `T-OS2-CB-01`, `T-DECK-RES-02`)
     - cluster 분류 (도메인 특화 항목 묶음):
       - `CB` (Context Efficiency): orientation pre-load, QUEUE/ARCHIVE 분리 등
       - `RES` (Residual): cluster 잔여, 후속 hardening
       - `META` (meta-infrastructure): transition reason, lock, sister channel 등
       - `HOTFIX`: 즉시 fix
   - **단순 sequence**: `T-{project}-{seq}` (예: `T-DECK-001`, `T-BASKET-3041`)
     - 작은 프로젝트 또는 sequential 모델 — deck 본사 호환
   - **프로젝트 prefix mandatory**: sister 프로젝트 ID 충돌 차단 (T-001 같은 ID 양쪽 존재 위험)
   - **기존 ticket 재명명 X**: backward-compat — 신규 ticket 부터 컨벤션 적용
   - **example**:
     - 좋은 예: `T-OS2-V38-01`, `T-DECK-CB-02`, `T-BASKET-3041`
     - 나쁜 예: `T-001` (project prefix 누락), `T-OS2-fix` (sequence 누락)
3. **우선순위 등급**: HIGHEST / HIGH / MEDIUM / LOW-MEDIUM / LOW
4. **워크플로 영향**: 누계 발생 N회, dispatch N건 중 N건 영향 등 정량 명시
5. **묶음 처리 권장**: 같은 근본 원인을 공유하는 항목은 한 PR/ticket으로 묶음 명시
6. **OS vs 프로젝트 경계**: 메커니즘이 OS인지 컨텐츠가 OS인지 명확화 — OS 일반화 가능성 판단 기준
7. **deck-handoff-evidence (인계 증거 블록)**: ticket context 필드 끝에 "deck-handoff-evidence" 또는 "{프로젝트명}-handoff-evidence" 헤딩으로 누계/측정/사례를 인용. 후속 builder가 사용자 결정 근거를 추적 가능하게 함.

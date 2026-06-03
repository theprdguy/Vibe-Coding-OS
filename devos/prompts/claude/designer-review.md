# Designer Review (UI/UX 누락 보호)

> CLAUDE1이 PRD intake + journey 추출까지 끝낸 뒤 ticket 분해 **전에** 디자이너 페르소나로 self-invoke. 사용자(비개발자) 앞에서 먼저 UI/UX 누락을 잡아내 진행 속도를 높이는 1차 필터.

## 운용 원칙

1. PRD intake 답변 + Step 0.5.1 `journeys` 리스트가 확보된 뒤에만 실행. 둘 중 하나라도 비어 있으면 먼저 채운다.
2. PRD에 UI/시각 산출이 **전혀 없는 경우** (순수 백엔드/CLI/인프라 ticket) 는 skip — `design_skipped: <사유>` 메타데이터로 plan에 기록.
3. 결과는 두 가지 형태로 출력:
   - **신규 journey 추가** — 누락된 화면/상태/전환을 Step 0.5.1 `journeys` 리스트에 append (Type 분류도 함께)
   - **기존 journey 보강** — `expected_outcome` / `failure_outcome` 에 UI 디테일 추가
4. 사용자에게 "디자이너 검토 결과" 섹션을 표 형식으로 제시 → 명시적 OK 후 Step 1 진행. 묵시적 통과 금지.
5. 1회 검토에서 5개 초과 발견 시 가장 임팩트 큰 5개만 우선 제시 — 사용자 피로 방지. 나머지는 `devos/questions/QUEUE.md` 에 백로그.

---

## A. UI 일관성 (Design System)

키워드: UI, 화면, 페이지, 컴포넌트, 버튼, 폼, 모달, 카드

### 강제 체크
- [ ] **Design token 준수**: 색상/타이포그래피/간격이 기존 design system 토큰을 사용하는가? hardcoded hex/px 신규 도입 시 사유?
- [ ] **컴포넌트 재사용 vs 신규**: 기존 Button/Input/Modal 등이 있는데 신규 생성하려는 건 아닌가?
- [ ] **레이아웃 일관성**: 동일 패턴 화면 (list/detail/form) 의 spacing, alignment, header 위치가 기존과 어긋나는가?
- [ ] **상호작용 일관성**: 같은 동작 (예: delete confirm) 이 다른 화면에서 다르게 처리되는가?

---

## B. 정보 위계 (Information Hierarchy)

키워드: 화면 설명, 페이지 구조, 사용자가 본다, 표시, 노출

### 강제 체크
- [ ] **Primary action 1개 원칙**: 한 화면의 주요 행동 1개로 명확한가? 동급 비중의 버튼 2개 이상이 나란히 있지 않은가?
- [ ] **Scan-ability**: 사용자가 3초 안에 "여기서 무엇을 할 수 있는지" 파악 가능한가?
- [ ] **CTA 명확성**: 버튼/링크 텍스트가 구체적인가? ("확인" / "OK" 같은 모호한 라벨 금지 — "구독 취소", "주문 완료" 같이 동작 명시)
- [ ] **위험/되돌릴 수 없는 동작 강조**: destructive action (삭제/결제/공개)이 시각적으로 구분되는가?

---

## C. 상태 누락 (Missing States)

키워드: 데이터, 리스트, 검색, 결과, 로드, 비동기

### 강제 체크 — 모든 데이터 표시 화면에 의무
- [ ] **Empty state**: 데이터 0개일 때 UI/메시지/CTA? (단순 "데이터 없음" 금지 — 다음 행동 제시)
- [ ] **Loading state**: 로딩 중 skeleton / spinner / progress?
- [ ] **Error state**: 시스템 에러 시 메시지 + 재시도 경로?
- [ ] **First-time vs returning user**: 처음 방문 vs 재방문 시 다른 안내?
- [ ] **Offline / network error**: 네트워크 끊김 시 동작? (silent fail 금지)
- [ ] **Partial data**: 일부만 로드된 경우 표시?

---

## D. 사용자 여정 갭 (Journey Gaps)

키워드: 흐름, 시나리오, 경로, 진입, 완료

### 강제 체크 — Step 0.5.1 journey 리스트와 대조
- [ ] **Cancel 경로**: 사용자가 중간에 취소/뒤로가기를 누를 때 동작?
- [ ] **재방문 (return) 경로**: 작성 중이던 폼/카트로 돌아왔을 때 상태 보존?
- [ ] **실패 후 복구**: 결제/제출 실패 후 재시도 경로? 입력값 보존?
- [ ] **권한 없음 도달**: 비로그인/권한 부족 사용자가 해당 화면 직접 URL 진입 시?
- [ ] **딥링크 / 새로고침**: 페이지 중간 상태에서 새로고침 / URL 공유 / 뒤로가기 시?
- [ ] **다중 디바이스**: 데스크톱 → 모바일 전환 시 진행 상태?

---

## E. 접근성 baseline (a11y)

키워드: 모든 UI

### 강제 체크 — WCAG AA baseline
- [ ] **색 대비**: 본문 4.5:1, 큰 텍스트 3:1 충족? 색만으로 정보 전달 안 함 (예: 빨간 글씨로만 에러 표시 X)
- [ ] **키보드 navigation**: 모든 인터랙션 요소가 Tab 으로 도달 가능? Focus 순서가 시각적 흐름과 일치?
- [ ] **Focus 상태**: 명확한 focus ring? `outline: none` 만 있고 대체 없음 X
- [ ] **스크린리더 라벨**: 아이콘 버튼에 aria-label? 폼 input 에 label?
- [ ] **터치 타겟**: 모바일 44x44pt 이상?
- [ ] **모션 민감성**: 자동 재생 애니메이션 / parallax 가 prefers-reduced-motion 존중?

---

## F. 비개발자 보호 (ETHOS)

키워드: 모든 UI

### 강제 체크 — "비개발자가 실수해도 망하지 않는 UI"
- [ ] **되돌리기 (Undo)**: 실수로 삭제/공개/전송 시 되돌릴 수단? (toast undo / 휴지통 / 임시저장)
- [ ] **확인 다이얼로그**: 되돌릴 수 없는 동작 (영구 삭제, 결제, 공개) 에 confirm?
- [ ] **위험 경고**: 데이터 손실 가능 / 유료 전환 / 공개 변경 시 사전 경고?
- [ ] **자동 저장**: 폼 작성 중 브라우저 닫혀도 복구 가능?
- [ ] **읽기 어려운 에러 차단**: stack trace / "Error 500" / "Unknown error" 가 사용자에게 그대로 노출되지 않는가?

---

## 출력 형식 (CLAUDE1 → 사용자)

검토 후 사용자에게 다음 표를 제시. 디자이너 입장의 **추가/수정 제안** 만 노출 — 이미 PRD에 있는 항목은 생략.

```
## 디자이너 검토 결과

| 카테고리 | 발견 | 제안 | journey 영향 |
|---|---|---|---|
| C. 상태 누락 | 검색 결과 empty state 없음 | "검색어와 일치하는 결과 없음 + 인기 키워드 3개 제시" UI 추가 | J-2 expected_outcome 보강 |
| D. 여정 갭 | 결제 실패 후 입력값 보존 미정의 | 카드 정보 외 배송지/수량 보존, 재시도 1-click | 신규 J-5 추가 (Type B) |
| F. 비개발자 보호 | 글 영구 삭제에 confirm 없음 | "정말 삭제하시겠습니까?" + 7일 휴지통 보관 | J-3 failure_outcome 보강 |

**사용자 결정 요청**:
- [ ] 각 제안 채택/거부/수정
- [ ] 신규 journey 는 Type 분류 확인
```

사용자가 항목별로 ✅/❌/수정 응답한 후 Step 0.5.2 (e2e ticket draft) 로 진행.

---

## Skip 판정 (디자이너 검토 불필요한 경우)

다음 조건 **모두** 만족 시 skip 가능:
1. PRD `journeys` 리스트의 모든 항목에서 `expected_outcome` 이 시각 출력 0% (예: API JSON, CLI stdout, 백엔드 cron)
2. ticket `files:` 가 모두 `apps/api/src/**`, `packages/**`, `infra/**`, `scripts/**` (UI 없음)
3. 사용자가 명시적으로 "UI 없음" 확인

skip 시 plan 본문에 기록:
```yaml
designer_review:
  status: skipped
  reason: <왜 skip 했는지 — "백엔드 cron only", "CLI tool only" 등>
```

---

## 운영 후 진화 결정 조건 (measurement → action)

이 페르소나가 가벼운 prompt 형태로 작동하는 동안, 매 PRD 마다 다음 metric을 plan 본문 `designer_review:` 블록에 누적 기록한다 (Step 0.6.2 출력 옆에 함께 저장).

```yaml
designer_review:
  status: done
  added_journeys: [...]
  enhanced_journeys: [...]
  metrics:
    findings_by_category: { A: 0, B: 1, C: 3, D: 2, E: 0, F: 1 }   # 카테고리별 발견 수
    user_acceptance: { accepted: 5, modified: 1, rejected: 1 }      # 사용자 응답 분포
    review_duration_min: <분>                                       # PRD 받은 시점 → designer_review OK 까지
    post_pr_ui_findings: <PR review 단계에서 잡힌 UI 결함 수>       # closure 시 사후 기입
```

누적 3 PRD 이상 데이터 확보 후 다음 기준으로 판단:

### A. 카테고리 추가 조건
다음 **둘 중 하나** 충족 시 신규 카테고리 추가 검토:
1. **PR review 단계에서 반복 발견**: 동일 유형 UI 결함이 3 PRD 연속 `post_pr_ui_findings` 에 등장 (= designer-review가 사전에 못 잡음 = 카테고리 누락)
2. **사용자 직접 지적**: 사용자가 검토 표 외에 "이건 왜 안 봤지?" 식으로 동일 영역을 2회 이상 보강 — 해당 영역이 카테고리화되지 않음

추가 후보 예시 (현재 미포함): 성능 perceived (애니메이션 지연/스크롤 jank), 데이터 시각화 (차트/그래프 가독성), 다크모드/테마 전환, 인쇄/PDF 출력.

### B. 카테고리 삭제 조건
**모두** 충족 시 카테고리 삭제 검토:
1. 5 PRD 누적에서 해당 카테고리 `findings_by_category` 합계가 1건 이하 (= 거의 무발견)
2. 그 1건도 다른 카테고리로 흡수 가능 (= 중복)
3. 삭제 후 `prd-intake-checklist.md § G 공통` 같은 다른 prompt 가 같은 영역을 커버

삭제 시 이력은 `devos/docs/retrospective/{date}-designer-review.md` 에 사유 기록 — "쓸모 없어 보였는데 알고 보니 중요했다" 회귀 방지.

### C. Sub-agent 격상 조건
다음 **셋 중 둘 이상** 충족 시 `.claude/agents/designer.md` 형태로 격상 검토:
1. **검토 시간 폭증**: `review_duration_min` 평균이 15분 초과 (= Claude 1 메인 컨텍스트가 디자이너 작업으로 무거워져 다른 워크플로 지연)
2. **컨텍스트 충돌**: 디자이너 검토 중 Claude 1 의 다른 페르소나(researcher / SSOT manager)와 출력 충돌 — 사용자가 "지금 어느 모자 쓰고 말하는 거냐" 질문 1회 이상
3. **병렬 필요**: PRD 분해 중 디자이너 검토와 다른 작업 (e.g. context7 research, 보안 감사) 을 병렬 처리하면 명확히 빨라지는 케이스 3건 이상 — 직렬 self-invoke 의 한계

격상 형태:
- `.claude/agents/designer.md` 로 sub-agent 정의 (별도 컨텍스트 / Task tool 호출)
- `decompose-prd.md` Step 0.6 은 prompt self-invoke 대신 `Task(subagent_type="designer", ...)` 호출로 변경
- 입력: PRD 본문 + journey 리스트 / 출력: 검토 표 (동일 형식)

### D. 격하 / 페기 조건
다음 충족 시 페기 검토:
1. 5 PRD 연속 `findings_by_category` 합계 0건 + `post_pr_ui_findings` 0건 — 페르소나가 무가치
2. 사용자가 "디자이너 검토 결과" 표를 3회 연속 통째로 ✅ 통과 — 가짜 신호만 만들고 있을 가능성

페기 전 카테고리 1~2개로 축소(slim) 시도를 먼저 — 카테고리 삭제 조건 § B 적용.

### 측정 기록 위치
- **per-plan**: `devos/plans/pending/{date}-{slug}.yaml` 의 `designer_review.metrics`
- **누적 집계**: `devos/PROJECT_STATE.md § "designer_review 누적"` (milestone closure 시 갱신)
- **결정 회고**: 카테고리 변경 / 격상 / 페기 결정 시 `devos/docs/retrospective/{date}-designer-review.md` 에 trigger metric + 결정 사유 기록

## 한계 명시

- **시각적 검증 X** — 실제 UI 스크린샷이 아직 없는 단계 (decompose 시점) 라 "감각적 위화감" 같은 건 못 잡음. PR review 단계에서 추가 검토 필요 (V39-03 user-outcome-review 게이트와 결합).
  → PR review 단계에서 **Gemini visual reviewer** (`bin/deos gemini dispatch <ticket-id>` Plan A 자동 / `bin/deos gemini next` Plan B 수동) 가 보강. 트리거: ticket `gui_review: true` 또는 diff 가 `apps/web/**` 포함 시 자동.
- **design system 인지** — 기존 design token / 컴포넌트 목록을 prompt 에 명시적으로 주입하지 않으면 일반론적 체크에 그침. 프로젝트에 design system 문서가 있으면 ticket context 에 링크 권장.
- **사용자가 "필요 없음"이라 답한 항목은 명시적 N/A 사유로 기록** — 누락이 아니라 의도적 제외.

## 참조

- `devos/prompts/claude/decompose-prd.md` Step 0.6 (이 파일 호출)
- `devos/prompts/claude/prd-intake-checklist.md` § G 공통 (a11y, 모바일, 오프라인 일부 중복 — 디자이너 검토는 더 깊이)
- `devos/ETHOS.md` 비개발자 보호 원칙

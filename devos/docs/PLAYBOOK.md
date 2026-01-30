# Vibe Coding Multi‑LLM Playbook (Make + A‑Mode)
Version: v0.2 (범용 템플릿)  
Mode: **A — 세션 시작 시 질문 일괄 트리아지** (작업 중 인터럽트 최소화)

---

## 0) 목표
- **Claude(Dispatcher)**가 작업을 쪼개고/배치하고/리뷰해서 **흐름이 끊기지 않게** 한다.
- **Codex(Builder)**와 **Gemini(UI/QA)**는 서로 대화하지 않아도 되게, **SSOT 파일**을 중심으로 병렬 실행한다.
- 당신의 개입은 **세션 시작에 선택지(A/B/Default)로 답변**하는 수준으로 최소화한다.

---

## 1) 역할(Role) 고정
### Claude = Dispatcher / Planner / Reviewer
- 티켓 분해(의존성 포함), owner 배치, 파일 소유권(Ownership) 관리
- 질문(불명확/블로킹)을 **미리 생성**하고 큐로 모은 뒤, **세션 시작에만** 묻는다(A‑Mode)
- PR 리뷰(리스크/엣지/계약 준수) + 머지 순서 결정
- 원칙: **생산 코드 작성은 지양**, 문서/ADR/티켓 중심

### Codex = Builder (Backend/Infra/Main implementation)
- 계약(API_CONTRACT)대로 구현 + 테스트/리팩터
- 완료 기준: 티켓의 verify(= make 명령) 통과 + PR 포맷 준수

### Gemini = Builder (Frontend/UI) + Multimodal QA
- UI_CONTRACT대로 화면/상태(loading/empty/error/success) 구현
- API가 없어도 **mock‑first**로 선행 구현 → 나중에 실제 API로 스위치
- 스크린샷/재현 steps 중심의 QA 산출

---

## 2) SSOT(단일 진실) — “이 파일만 믿는다”
우선순위(Truth order):
1) `PROJECT_STATE.md`
2) `docs/API_CONTRACT.md` + `docs/UI_CONTRACT.md`
3) `docs/ADR/*`
4) 코드
5) 채팅 기록

> 변경/가정이 생기면 **채팅보다 SSOT 파일을 먼저 갱신**한다.

---

## 3) 레포 스켈레톤 (프로젝트 미정 기본값)
```
Makefile
AI.md
PROJECT_STATE.md
/docs
  API_CONTRACT.md
  UI_CONTRACT.md
  ARCHITECTURE.md
  /ADR
/tasks
  QUEUE.yaml
/questions
  QUEUE.md
```

---

## 4) Make 표준 인터페이스 (모든 검증/완료 기준)
### 필수 명령(티켓 verify는 이것만 사용)
- `make pr-check`
- `make lint`
- `make test`
- `make typecheck`
- `make e2e`

### 세션 시작 루틴(A‑Mode용)
- `make kickoff`  (status + queue + questions)
- `make triage`   (open 질문만 출력)

> 프로젝트 스택이 정해지면 Makefile 내부 명령만 교체하고, **외부 인터페이스(make test 등)는 유지**한다.

---

## 5) 티켓(Ticket) 규격 — 핸드오프 자동화의 핵심
### 원칙
- **PR 1개 = Ticket 1개** (작게)
- 티켓마다 `owner` + `files` + `verify` + `deps`를 반드시 명시
- **Ownership**: 티켓 owner만 `files`에 나열된 파일을 수정
- API/UI 변경은 **contract-first**: 문서 먼저 커밋

### 최소 템플릿 (QUEUE.yaml에 들어가는 형태)
```yaml
- id: T-123
  status: todo|doing|blocked|done|parked
  owner: CLAUDE|CODEX|GEMINI
  goal: "한 문장 목표"
  dod:
    - "완료 조건"
  files:
    - "수정 파일/디렉토리 (겹치면 안 됨)"
  verify:
    - "make pr-check"
  contract_impact: none|api|ui|both
  deps: ["T-120"]
  context_pack:
    current_state: "PROJECT_STATE 요약 5줄"
    contracts:
      - "docs/API_CONTRACT.md#..."
      - "docs/UI_CONTRACT.md#..."
    constraints:
      - "non-goals / 금지사항"
```

---

## 6) 질문 큐(Question Queue) — A‑Mode(세션 시작 일괄)
### 규칙
- 막히거나 애매하면 **작업을 멈추지 말고** `questions/QUEUE.md`에 질문을 추가한다.
- 질문에는 반드시:
  - **Options(A/B/C/…)**
  - **Recommendation(1줄)**
  - **Default(답 없으면 이걸로 진행)**
  - **Blocking 여부**
  - **Needed‑by(어떤 티켓에 필요?)**
- Non‑blocking은 Default로 진행(무정지), Blocking은 해당 티켓만 blocked.

### 질문 포맷(상태 기반)
```md
## Q-XXX [open] (Blocking|Non-blocking)
**Question:** ...
**Options:** A) ... B) ... C) ... D) ...
**Recommendation:** ...
**Default:** A/B/C/D
**Needed-by:** T-123 or "next dispatch"
**Impact:** API_CONTRACT / UI_CONTRACT / files
```

### 세션 시작 트리아지(Claude가 수행)
- `questions/QUEUE.md`에서 **[open]만** 수집
- **Blocking → Non‑blocking** 순서로 묶어서 한 번에 질문
- 당신은 `Q-003=B, Q-007=Default`처럼 답
- Claude가:
  - 질문을 `[answered]`로 변경
  - ADR 작성
  - 계약 문서 갱신(필요 시)
  - 티켓 큐 재배치/언블록

---

## 7) PR 포맷(리뷰 자동화)
PR 설명은 아래 4줄(혹은 4블록) 고정:
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: `make pr-check` (+ 필요 시 추가)
- Risks / edge cases (있으면)

---

## 8) 운영 시나리오(End‑to‑End)

### 시나리오 0 — 최초 1회 세팅(Foundation)
1) 스켈레톤 파일 생성
2) 실행:
```bash
make help
make status
make pr-check
```
3) `tasks/QUEUE.yaml`의 T‑000/T‑001을 done으로 만드는 것이 첫 목표

---

### 시나리오 1 — 매 작업 세션 시작(A‑Mode)
1) 터미널:
```bash
make kickoff
make triage
```
2) Claude: 세션 시작 트리아지 수행(질문 일괄)
3) 당신: `Q-xxx=A/B/Default`로 답
4) Claude: ADR/계약/큐 업데이트 → 언블록

---

### 시나리오 2 — 디스패치(티켓 생성/배치) → 병렬 실행
1) Claude가 오늘 목표를 PR 크기 티켓으로 분해하여 `tasks/QUEUE.yaml` 업데이트
2) Codex/Gemini는 **자기 owner 티켓만** 수행
3) 병렬 원칙:
- files 겹치면 병렬 금지(티켓 재분해 or 순서화)
- 계약 변경은 문서 PR을 먼저 merge

---

### 시나리오 3 — Codex 작업 흐름(Builder)
1) 티켓 읽기 → (필요 시) 계약 문서 먼저 커밋
2) 구현
3) 검증:
```bash
make pr-check
```
4) PR 작성(고정 포맷)
5) 막히면 질문 큐에 추가(Options+Default 필수)

---

### 시나리오 4 — Gemini 작업 흐름(UI/QA)
1) UI_CONTRACT 기반: loading/empty/error/success 모두 구현
2) mock‑first로 UI 선행
3) 검증:
```bash
make pr-check
```
4) PR에 재현 steps/스크린샷(가능하면)
5) 막히면 질문 큐에 추가

---

### 시나리오 5 — 리뷰/머지(Claude Gate)
Claude는 PR마다:
- 계약 준수(문서 갱신했나)
- verify 근거(`make pr-check`)가 있나
- ownership 위반(남의 files 건드렸나)
- 리스크/테스트 누락
→ deps 순서대로 merge, merge 후 `PROJECT_STATE.md` 갱신

---

### 시나리오 6 — 충돌/꼬임 복구 프로토콜
1) `PROJECT_STATE.md`에 문제 3줄 기록
2) `API_CONTRACT`/`UI_CONTRACT`에 “정답”을 확정
3) 리팩터/정정 티켓을 재발행(작게)
4) 다시 병렬 흐름으로 복귀

---

## 9) 프로젝트가 정해졌을 때(온보딩 1회)
1) 스택 결정(예: Next/FastAPI 등)
2) Makefile 내부 명령 연결:
- `make dev` → 실제 dev 서버
- `make lint/test/typecheck/e2e` → 실제 실행
3) 티켓 verify는 그대로 `make ...` 유지 (플레이북 재사용)

---

## 10) 체크리스트(핵심만)
- [ ] SSOT 4종 유지(STATE, API, UI, QUEUE)
- [ ] Ticket에 owner/files/verify/deps 강제
- [ ] Contract‑first + Ownership + Small PR
- [ ] 질문은 큐에 쌓고, 세션 시작에만 처리(A‑Mode)
- [ ] 완료 기준은 항상 `make pr-check`


# Vibe Coding 개발 환경 구성 & 구조 가이드 (시스템 설명 문서)
Version: **v1.1 (Hybrid: SSOT+Make + v4 운영장치 흡수)**  
Scope: **프로젝트 미정 상태에서도** 바로 적용 가능한 멀티 LLM 병렬 개발 운영체계(OS)

> v1.1 변경점(요약)
- **CONTEXT.md**: SSOT의 “100줄 TL;DR” 추가(빠른 온보딩/리마인드)
- **역할 파일**: `.claude/CLAUDE.md`, `.codex/CODEX.md`, `.gemini/GEMINI.md` 추가(역할/금지/SSOT 경로를 더 강제)
- **TASKS.md(사람용 뷰)**: `tasks/QUEUE.yaml(SSOT)`와 병행 + **아카이브 규칙** 도입
- **브랜치 전략 표준화**: `feat/T-123-short-title` (티켓ID 포함)
- **Handoff 3줄 템플릿**: 인수인계 비용 최소화
- (선택) **pre-commit 리마인드**: 상태/문서 누락을 습관적으로 차단

---

## 1. 목적
이 문서는 **Claude + Codex + Gemini**를 함께 활용해 “바이브 코딩”을 지속적으로 진행하기 위한 **개발 환경 구성**, **레포 구조**, **운영 프로세스**, **충돌 방지 규칙**을 설명합니다.

핵심 목표 3가지:
1) **작업이 멈추지 않게(continuous flow)**  
2) **컨텍스트 꼬임/미스매치/merge conflict를 시스템으로 예방**  
3) 당신의 개입을 **결정(선택지 답변)** 수준으로 최소화

---

## 2. 시스템 개요(한 장 요약)

### 2.1 역할(Role) 설계
- **Claude = Dispatcher / Planner / Reviewer**
  - 티켓 분해/배치, 의존성 관리, PR 리뷰, 머지 순서 결정
  - 막히는 지점을 질문 큐로 모으고, **세션 시작에 한 번에** 묻는 방식(A-Mode) 운영
- **Codex = Builder (Backend/Infra/Main)**
  - 멀티파일 구현, 리팩터, 테스트/빌드 반복
  - 계약(API_CONTRACT)에 맞춘 실제 구현 책임
- **Gemini = Builder (Frontend/UI) + QA**
  - UI/UX 구현, mock-first 선행 개발, 스크린샷/재현 steps 기반 QA 산출

### 2.2 SSOT(단일 진실) 중심 운영
LLM 간 공유는 “대화”가 아니라 **레포 내 SSOT 파일**로 합니다.

**Truth order(우선순위):**
1) `PROJECT_STATE.md`  
2) `docs/API_CONTRACT.md` + `docs/UI_CONTRACT.md`  
3) `docs/ADR/*`  
4) Code  
5) Chat logs (least reliable)

---

## 3. 레포 구조(프로젝트 미정 기본 스켈레톤)

v1.1 권장 구조:
```
Makefile
AI.md
CONTEXT.md
PROJECT_STATE.md
TASKS.md
/docs
  API_CONTRACT.md
  UI_CONTRACT.md
  ARCHITECTURE.md
  /ADR
    README.md
/tasks
  QUEUE.yaml
  /archive
/questions
  QUEUE.md
/.claude
  CLAUDE.md
/.codex
  CODEX.md
/.gemini
  GEMINI.md
```

### 3.1 파일별 역할 요약
- **Makefile**: 모든 검증/실행을 `make`로 통일하는 “표준 인터페이스”
- **AI.md**: 운영 규칙(헌법). 모델/사람 모두 지켜야 하는 룰
- **CONTEXT.md**: **SSOT TL;DR(100줄 요약본)** — “빠르게 읽고 바로 작업 시작”
- **PROJECT_STATE.md**: 현재 상태 1페이지 요약(진행/결정/다음)
- **TASKS.md**: 사람이 읽기 쉬운 “작업 보드 뷰”(SSOT는 아님)
- **API_CONTRACT.md**: REST 계약(엔드포인트/예시 JSON/에러 규칙)
- **UI_CONTRACT.md**: UI 상태/검증/카피/바인딩 규칙
- **ADR/**: 중요한 결정 기록(Architecture Decision Records)
- **tasks/QUEUE.yaml**: 티켓 큐(병렬 실행 엔진) — **실제 SSOT**
- **tasks/archive/**: 오래된 티켓/스프린트 기록 아카이브
- **questions/QUEUE.md**: 질문 큐(개입 최소화 장치, A-Mode)
- **.claude/.codex/.gemini**: 역할별 “로컬 운영 규칙” (도구/모델별 행동 교정)

> 원칙: **SSOT는 QUEUE.yaml + CONTRACT + STATE**, TASKS.md는 “사람용 뷰(옵션)”.

---

## 4. 개발 환경 표준: Make 기반

### 4.1 왜 make를 쓰나?
- 프레임워크가 바뀌어도 `make test`, `make pr-check` 같은 **외부 인터페이스 유지**
- LLM에게 “검증은 `make pr-check`만”처럼 지시가 단순
- 사람이 긴 명령을 외우지 않아도 됨(실수 감소)

### 4.2 필수 명령(표준)
- `make kickoff` : 세션 시작(상태/큐/질문 확인)
- `make triage` : **[open] 질문만** 출력
- `make pr-check` : PR 전 체크(최소 contract-check 포함)
- `make lint / test / typecheck / e2e` : 프로젝트가 정해지면 연결

> 프로젝트 미정 상태에서는 placeholder로 두고, 프로젝트가 정해지면 Makefile 내부 명령만 교체합니다.

---

## 5. 계약(Contract) 기반 병렬 개발

### 5.1 Contract-first 원칙
- API/UI 변경이 있으면 **문서(계약)부터 수정 → 먼저 커밋**
- 프론트/백은 서로를 기다리지 않음  
  - **Gemini(프론트)**: 계약 예시 JSON으로 **mock-first** 개발  
  - **Codex(백)**: 계약대로 구현 + 테스트

### 5.2 API 계약: docs/API_CONTRACT.md
반드시 포함:
- endpoint 목록(method/path)
- request/response JSON 예시
- 에러 포맷(통일)
- 인증/페이징 규칙(미정이면 Default 명시)

### 5.3 UI 계약: docs/UI_CONTRACT.md
반드시 포함:
- 화면별 **loading/empty/error/success** 상태 정의
- 입력 validation 규칙/카피
- API 바인딩 규칙(어떤 화면이 어떤 endpoint를 호출하는지)

---

## 6. 충돌 방지 시스템(필수 규칙 5개)

### 규칙 1) Ownership (파일 소유권)
- 티켓에 `files:`를 명시하고 **owner만 해당 파일을 수정**
- files가 겹치면:
  - 티켓을 쪼개거나
  - 순서를 강제(병렬 금지)

### 규칙 2) Small PR (PR 1개 = 티켓 1개)
- PR이 커지면 리뷰가 느려지고, 전체 흐름이 멈춤

### 규칙 3) Contract-first (문서 먼저)
- API/UI 변경은 계약 문서가 우선
- `make pr-check`의 `contract-check`로 누락 자동 차단(권장)

### 규칙 4) Dependency changes isolated (의존성 변경은 별도 PR)
- 라이브러리 추가/업데이트는 기능 PR과 섞지 않음

### 규칙 5) Branch = Ticket (브랜치 전략 표준)
- 브랜치 이름에 **티켓ID 포함**:
  - `feat/T-123-short-title`
  - `fix/T-234-bug-summary`
  - `chore/T-010-deps-update`
- PR 제목도 티켓ID 포함 권장: `[T-123] ...`
- 목적: 병렬 작업의 “충돌 면적”을 물리적으로 축소 + 추적성 강화

---

## 7. 티켓 큐(tasks/QUEUE.yaml): 병렬 실행 엔진(SSOT)

### 7.1 티켓 필수 필드
- `id`, `owner`, `goal`, `dod`, `files`, `verify`, `deps`, `contract_impact`, `status`

### 7.2 상태(status) 권장
- `todo` / `doing` / `blocked` / `done` / `parked`

### 7.3 완료 기준(Stop condition)
- 완료는 “주장”이 아니라 **verify 통과**
  - 최소: `make pr-check`

---

## 8. TASKS.md(사람용 뷰) + 아카이브 규칙(v4 흡수)

### 8.1 왜 TASKS.md를 두나?
- `tasks/QUEUE.yaml`은 SSOT지만, 사람이 읽기엔 다소 딱딱할 수 있음
- TASKS.md는 “보드처럼” 빠르게 파악하는 용도(옵션)

### 8.2 운영 규칙
- SSOT는 **항상 QUEUE.yaml**
- TASKS.md는 다음 정보만 간단히:
  - “이번 세션/스프린트의 Top 10 티켓”
  - 현재 Doing/Blocked 요약
  - 링크/참조

### 8.3 아카이브 규칙(권장)
- TASKS.md가 너무 길어지면(예: **30~50줄** 넘으면)
  - 오래된 완료/취소 티켓은 `tasks/archive/YYYY-MM/`로 이동
  - TASKS.md는 “최근 것만” 유지

---

## 9. 질문 큐(questions/QUEUE.md): 개입 최소화(A-Mode)

### 9.1 질문 작성 규칙
막히거나 결정이 필요하면 **질문 큐에 기록**:
- Options(A/B/C/D)
- Recommendation(1줄)
- Default(미응답 시 진행 기준)
- Blocking/Non-blocking
- Needed-by(어떤 티켓에 필요?)

### 9.2 A-Mode: 세션 시작 일괄 트리아지
- 질문은 큐에 쌓고 **세션 시작에만** 처리:
```bash
make kickoff
make triage
```
- Claude가 open 질문을 모아 선택지로 질의
- 당신은 `Q-003=B, Q-007=Default` 식으로 답
- Claude가 ADR/계약/QUEUE를 갱신하고 언블록

---

## 10. Handoff(인수인계) 표준: “3줄 템플릿”(v4 흡수)
작업 중/작업 종료 시, 다음 사람(또는 다른 모델)에게 전달할 때 아래 3줄로 요약합니다.

**Handoff 3줄 템플릿**
1) **Done:** 무엇을 했는가(파일/PR 포함)  
2) **Next:** 다음에 할 일(티켓ID/파일)  
3) **Block:** 막히는 점/질문ID(Q-xxx)  

예:
- Done: T-020 API skeleton added, updated docs/API_CONTRACT.md, verify: make pr-check
- Next: T-021 add validation + tests in apps/api/...
- Block: Q-004 [open] auth mode decision needed (default: none)

---

## 11. 역할 파일(.claude/.codex/.gemini) 운영(v4 흡수)
각 모델에게 “역할/SSOT/금지사항”을 더 강하게 주입하기 위한 파일입니다.

### 11.1 .claude/CLAUDE.md (Dispatcher)
- 해야 할 것: 티켓 생성/배치, 질문 트리아지, 리뷰 게이트, 머지 순서
- 금지: 대규모 생산 코드 작성
- 참조: AI.md + SSOT 우선순위

### 11.2 .codex/CODEX.md (Builder)
- 해야 할 것: owner 티켓 수행, verify 통과, 작은 PR
- 금지: 계약 없이 API/UI 변경
- 막히면: questions/QUEUE.md에 Options+Default로 추가

### 11.3 .gemini/GEMINI.md (UI/QA)
- 해야 할 것: UI_CONTRACT 준수, 상태 4종, mock-first, repro steps
- 금지: API 스펙 임의 변경(계약 먼저)

> 도구/CLI에서 Codex/Gemini를 시작할 때, “이 파일들을 읽어라”를 런북에 포함시키면 효과가 큽니다.

---

## 12. (선택) pre-commit 리마인드 도입(v4 흡수, optional)
목적: “태스크 상태 업데이트/문서 갱신”을 습관적으로 누락하지 않게.

권장 정책(가벼운 버전):
- 커밋 전에 다음 중 하나라도 변경되었으면 리마인드:
  - `tasks/QUEUE.yaml` or `TASKS.md`
  - 계약 문서(변경이 필요한데 누락했을 가능성)

주의:
- 우리는 최종 게이트를 `make pr-check(contract-check)`로 두기 때문에,
  pre-commit은 **부가적인 UX 장치**로만 권장합니다.

---

## 13. 운영 시나리오(End-to-End)

### 13.1 최초 1회 세팅(Foundation)
1) 스켈레톤 파일 생성(위 구조)
2) 검증:
```bash
make help
make status
make pr-check
```

### 13.2 매 작업 세션 시작(A-Mode)
```bash
make kickoff
make triage
```
- Claude가 open 질문만 모아 일괄 질문
- 당신은 선택지로 답
- Claude가 ADR/계약/QUEUE 정리 → 언블록

### 13.3 디스패치 & 병렬 실행
- Claude가 오늘 목표를 티켓으로 쪼개 `tasks/QUEUE.yaml`에 배치
- Codex/Gemini는 owner 티켓만 수행(브랜치=티켓)
- 막히면 질문 큐에 기록(Default 포함)

### 13.4 리뷰/머지 게이트
- Claude가 PR 체크:
  - 계약 준수(문서 갱신했나)
  - verify(`make pr-check`) 근거가 있나
  - ownership 위반이 있나
- deps 순서대로 merge → `PROJECT_STATE.md` 갱신

### 13.5 충돌/꼬임 복구
- `PROJECT_STATE.md`에 문제 3줄 기록
- `API_CONTRACT`/`UI_CONTRACT`에서 “정답” 확정
- 정정 티켓을 작게 재발행 후 병렬 흐름으로 복귀

---

## 14. Codex CLI로 환경 세팅 시작(권장 절차)
1) 레포에 SSOT 파일이 존재하도록 준비(이 문서의 구조 그대로)
2) 레포 루트에서:
```bash
make help && make status && make pr-check
```
3) Codex에는 “플레이북 전체” 대신 **세션용 런북(짧은 프롬프트)**를 전달:
- SSOT 파일 목록(경로) 명시
- 이번 목표(환경 스캐폴드/Make 연결)
- 결정이 필요하면 questions/QUEUE.md에 Options+Default로 추가
- 완료 기준: `make pr-check` 통과 + 변경 파일 요약

---

## 15. 부록: v1.1 신규 파일 템플릿

### 15.1 CONTEXT.md (TL;DR)
- 목적: “처음 온 사람/모델이 3분 안에 파악”
- 분량: 50~100줄 권장

템플릿:
```md
# CONTEXT (TL;DR)

## What we are doing (1-2 lines)
- ...

## Operating mode
- SSOT-first, Contract-first, Ownership, Small PR, A-Mode questions

## Current milestone
- ...

## What works now (demo path)
- ...

## Key decisions (top 5)
- ...

## Active tickets (top 10)
- ...

## Open questions (top 10)
- ...
```

### 15.2 TASKS.md (사람용 뷰)
```md
# TASKS (Human View)

## Top priorities (max 10)
- [ ] T-...

## Doing
- T-...

## Blocked
- T-... (Q-xxx)

## Done (recent)
- T-...

## Notes / Links
- ...
```

### 15.3 역할 파일 템플릿
`.claude/CLAUDE.md`
```md
You are Claude (Dispatcher).
- Operate via SSOT files: AI.md, CONTEXT.md, PROJECT_STATE.md, contracts, QUEUEs
- Create small tickets, enforce ownership (no overlapping files)
- Run A-Mode triage at session start (open questions only)
- Prefer docs/ADR over production code edits
```

`.codex/CODEX.md`
```md
You are Codex (Builder).
- Read SSOT files first. Do not rely on chat memory.
- Work only on your ticket's files. Keep PRs small.
- If API changes, update docs/API_CONTRACT.md first.
- If blocked, add a question to questions/QUEUE.md with Options + Default.
- Verify: make pr-check
```

`.gemini/GEMINI.md`
```md
You are Gemini (UI/QA).
- Follow UI_CONTRACT: implement loading/empty/error/success.
- Mock-first using API_CONTRACT examples; switch to real API later.
- If UI behavior changes, update docs/UI_CONTRACT.md first.
- Provide repro steps for failures; verify: make pr-check
```

---

## 16. 요약
이 시스템은 “프로젝트가 정해지지 않아도” 먼저 깔아두는 **개발 운영체계**입니다.

- **SSOT 파일**로 컨텍스트 공유  
- **Make**로 검증/실행 인터페이스 통일  
- **Ticket Queue + Ownership + Branch 전략**으로 충돌 예방  
- **Question Queue + A-Mode(Default)**로 당신 개입 최소화  
- **Handoff 3줄 + 역할 파일 + TASKS 아카이브**로 운영 비용 절감  

프로젝트가 생기면, Makefile 내부 명령과 계약 문서만 실제로 채우면 그대로 확장됩니다.

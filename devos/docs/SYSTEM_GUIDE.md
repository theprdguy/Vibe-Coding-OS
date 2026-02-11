# Vibe Coding 개발 환경 구성 & 구조 가이드
Version: **v1.5 (Token-Efficient Multi-LLM OS)**
Scope: 멀티 LLM 병렬 개발 운영체계 — Claude를 매니저로, Codex/Gemini를 빌더로 운영

> v1.5 변경점(요약)
- **토큰 효율 원칙**: Claude는 매니저 전용, 구현 코드 작성 금지
- **CLAUDE.md 이중 배치**: repo root `.claude/CLAUDE.md`(Claude Code 자동 로드) + `devos/.claude/CLAUDE.md`(참조)
- **Hooks**: Claude가 구현 파일에 쓰려 하면 자동 차단 (`guard-no-impl.sh`)
- **티켓 템플릿 강화**: `context` + `spec` 필드 추가 (빌더 독립 작업 가능)
- **Makefile 개선**: `make start`, `make copy-*`, `make show-*` 실제 동작
- **빌더 프롬프트 강화**: Boot Sequence + Deliverable Format 표준화

---

## 1. 목적

이 문서는 **Claude + Codex + Gemini**를 함께 활용하는 **멀티 LLM 병렬 개발 운영체계**를 설명합니다.

### 왜 멀티 LLM인가?
- 각 LLM의 **토큰/컨텍스트가 유한**합니다
- Claude 혼자 모든 것을 하면 토큰이 부족합니다
- **업무 분담**: Claude(매니저) + Codex/Gemini(빌더) = 총 토큰 용량 극대화
- Claude가 구현에 토큰을 쓰면 → 매니저 역할 수행 불가 → 위임 실패

### 핵심 목표
1) 작업이 멈추지 않게 (continuous flow)
2) 컨텍스트 꼬임/충돌을 시스템으로 예방
3) 당신의 개입을 **선택지 답변** 수준으로 최소화

---

## 2. 역할 설계

### Claude = Dispatcher / Manager
- 티켓 분해/배치, 질문 트리아지, PR 리뷰, 머지 순서 결정
- **구현 코드 작성 금지** (10줄 이상 금지, 예외 없음)
- 모든 구현은 티켓으로 만들어 Codex/Gemini에 위임
- 토큰 예산: 계획 30% + 티켓 작성 40% + 리뷰 15% + SSOT 15%

### Codex = Builder (Backend/Infra)
- API_CONTRACT 기반 구현 + 테스트/리팩터
- 자기 owner 티켓의 files 범위만 수정

### Gemini = Builder (Frontend/UI + QA)
- UI_CONTRACT 기반 화면/상태 구현
- mock-first 선행 개발
- 자기 owner 티켓의 files 범위만 수정

---

## 3. 레포 구조

```
repo/
  .claude/
    CLAUDE.md           # Claude Code 자동 로드 (매니저 규칙)
    hooks/
      guard-no-impl.sh  # 구현 파일 쓰기 차단 hook
    settings.json       # hooks 설정
  Makefile              # wrapper (delegates to devos/Makefile)
  START_HERE.md         # 빠른 시작

  devos/
    AI.md               # 운영 헌법 (모든 에이전트 공유)
    CONTEXT.md           # TL;DR (100줄 요약)
    PROJECT_STATE.md     # 현재 상태 1페이지
    TASKS.md             # 사람용 작업 보드 뷰
    VERSION.txt

    docs/
      API_CONTRACT.md    # REST API 계약
      UI_CONTRACT.md     # UI 상태/검증 계약
      ARCHITECTURE.md    # 아키텍처 개요
      ADR/               # 결정 기록

    tasks/
      QUEUE.yaml         # 티켓 큐 (SSOT)
      archive/           # 완료된 티켓 아카이브

    questions/
      QUEUE.md           # 질문 큐 (A-Mode)

    prompts/
      claude/session-start.md
      claude/review-pr.md
      codex/session-start.md
      gemini/session-start.md
      common/handoff-3lines.md

    .claude/CLAUDE.md    # Claude 역할 요약 (참조용)
    .codex/CODEX.md      # Codex 역할 규칙
    .gemini/GEMINI.md    # Gemini 역할 규칙
```

### CLAUDE.md 이중 배치 이유
- **repo root `.claude/CLAUDE.md`**: Claude Code가 자동으로 읽는 위치. 매니저 규칙 강제.
- **devos/.claude/CLAUDE.md**: 프롬프트에서 참조하는 위치. 요약본.

---

## 4. Make 인터페이스

### 핵심 명령 (매일 사용)
| 명령 | 설명 |
|------|------|
| `make start` | 세션 시작 (상태 + 큐 + 질문 + 다음 단계) |
| `make status` | Git + SSOT 파일 상태 확인 |
| `make queue` | 티켓 큐 요약 |
| `make triage` | [open] 질문만 표시 |

### 프롬프트 전달
| 명령 | 설명 |
|------|------|
| `make copy-claude` | Claude 트리아지 프롬프트를 클립보드로 |
| `make copy-codex` | Codex 빌더 프롬프트를 클립보드로 |
| `make copy-gemini` | Gemini 빌더 프롬프트를 클립보드로 |
| `make show-*` | 클립보드 대신 터미널에 출력 |

### 검증
| 명령 | 설명 |
|------|------|
| `make pr-check` | PR 전 체크 (contract-check 포함) |
| `make contract-check` | 코드 변경 시 계약 문서 갱신 확인 |

---

## 5. 티켓 시스템

### 티켓 필수 필드 (v1.5 강화)
```yaml
- id: T-XXX
  status: todo|doing|blocked|done|parked
  owner: CLAUDE|CODEX|GEMINI
  goal: "무엇을 만들 것인가 (1문장)"
  context: |
    왜 필요한가, 현재 상태 (2-3문장)
    빌더가 독립적으로 작업 가능한 배경 정보
  spec: |
    구체적 요구사항 (input/output/behavior)
  dod:
    - "완료 조건"
  files:
    - "수정할 파일 (소유권)"
  verify:
    - "make pr-check"
  contract_impact: none|api|ui|both
  deps: ["T-XXX"]
```

### 왜 context/spec이 중요한가?
- Claude의 토큰을 아끼려면 빌더가 **되묻지 않고** 작업해야 함
- `context`: "왜 이 작업이 필요한가" (빌더가 맥락 이해)
- `spec`: "정확히 무엇을 만들어야 하는가" (빌더가 독립 구현)

---

## 6. 충돌 방지 규칙

1. **Ownership**: ticket owner만 ticket.files 수정
2. **Small PR**: 1 ticket = 1 PR
3. **Contract-first**: 계약 문서가 코드보다 먼저
4. **Dependency isolation**: 라이브러리 변경은 별도 PR
5. **Branch = Ticket**: `feat/T-123-short-title`

---

## 7. Claude Code Hooks (v1.5 신규)

`.claude/settings.json`에 설정:
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write|Edit",
      "hook": ".claude/hooks/guard-no-impl.sh"
    }]
  }
}
```

Claude가 `src/`, `app/`, `components/` 등 구현 디렉토리에 파일을 쓰려고 하면:
- 자동으로 차단
- "Dispatcher Guard" 경고 메시지 표시
- 티켓 생성을 안내

---

## 8. 세션 흐름

### 8.1 매 작업 세션
```
make start
  ↓
Claude triage (make copy-claude → Claude에 전달)
  ↓
빌더 투입 (make copy-codex / make copy-gemini → 각 LLM에 전달)
  ↓
빌더 작업 완료 → PR
  ↓
Claude review → merge → 상태 갱신
```

### 8.2 새 PRD/기능 요청 시
```
사용자가 PRD 제공
  ↓
Claude가 PRD를 읽고 티켓으로 분해
  ↓
QUEUE.yaml에 CODEX/GEMINI 티켓 생성
  ↓
계약 문서 업데이트 (필요 시)
  ↓
"make copy-codex / make copy-gemini 실행하세요" 안내
```

**주의:** Claude가 PRD를 받아도 직접 구현하지 않습니다. 반드시 티켓으로 분해합니다.

---

## 9. A-Mode (질문 큐)

- 막히면 `devos/questions/QUEUE.md`에 기록
- 필수: Options + Recommendation + Default + Blocking/Non-blocking
- Non-blocking → Default로 진행
- Blocking → 해당 티켓만 blocked
- 세션 시작에 Claude가 일괄 처리

---

## 10. 요약

| 구성 요소 | v1.4 | v1.5 |
|-----------|------|------|
| Claude 역할 | "지양" (느슨) | "금지" (강제 + Hook) |
| CLAUDE.md 위치 | devos/.claude/ (미로드) | repo root .claude/ (자동 로드) |
| 티켓 템플릿 | goal/dod/files | + context/spec (독립 작업용) |
| Makefile | kickoff만 있음 | start/copy-*/show-* 완비 |
| 강제 메커니즘 | 없음 | Hooks (guard-no-impl.sh) |
| 빌더 프롬프트 | 기본 런북 | Boot Sequence + Deliverable Format |

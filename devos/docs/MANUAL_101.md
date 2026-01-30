# Vibe Coding OS Manual 101 (v1.3)  
_프로젝트/하루 작업 시작 전에 “그대로 따라 하기”용_

---

## 이 메뉴얼의 목적
- **기억할 것 최소화**: `make start` 하나로 세션 시작
- **실수 방지**: `make preflight`로 Git/원격/SSOT 상태 확인
- **병렬 작업 안정화**: Claude(디스패처) → Codex/Gemini(빌더) 순서 고정

---

# 0) 용어 30초
- **Repo(레포)**: GitHub에 있는 프로젝트 저장소(원격)
- **Clone**: GitHub 레포를 내 컴퓨터로 복사
- **Commit**: “스냅샷 저장” (로컬 기록 생성)
- **Push**: 커밋을 GitHub로 업로드
- **SSOT**: “진실의 원본 문서들” (AI.md/CONTEXT/STATE/CONTRACT/QUEUE/QUESTIONS)
- **A-Mode**: 질문은 작업 중 끊지 말고 `questions/QUEUE.md`에 쌓고 세션 시작에 일괄 처리

---

# 1) 프로젝트 시작(Day 0) — GitHub-first (추천 A안)
## 1-1. GitHub에서 새 Repo 만들기
- **Empty repo 권장**: README/License/Gitignore 자동 생성 꺼두기(가능하면)
- 기본 브랜치: **main**

## 1-2. 로컬에서 clone
```bash
git clone <your-repo-url>
cd <repo-folder>
```

## 1-3. 스타터킷(v1.3) 풀기
- `vibe-starter-kit-v1_3.zip` 내용을 **레포 루트**에 그대로 풀기  
  (Makefile, AI.md, docs/, tasks/, questions/, prompts/… 가 루트에 생겨야 함)

## 1-4. 시작 점검 + 첫 커밋 + push
```bash
make preflight
make start

git add .
git commit -m "chore: bootstrap vibe OS"
git push -u origin main
```

✅ 여기까지 끝나면 “운영체계 설치 완료”

---

# 2) PRD가 있을 때(추천 흐름)
> PRD는 **첫 real 티켓을 쪼개기 직전**에 Claude가 읽게 하는 게 최적.

## 2-1. PRD 파일 넣기
- 파일: `docs/PRD.md`  
- 이미 템플릿이 있으니 그 안에 내용을 채우거나, 기존 PRD를 붙여넣기

## 2-2. Claude에게 PRD Intake 시키기
1) 세션 시작
```bash
make start
```

2) Claude 프롬프트를 클립보드로 복사(맥)
```bash
make copy-prd-intake
```

3) Claude에 붙여넣고 실행

Claude가 자동으로 업데이트해야 하는 것(정상 동작):
- `CONTEXT.md` (TL;DR + demo path)
- `PROJECT_STATE.md` (마일스톤/DoD)
- `questions/QUEUE.md` (결정 질문들: Options/Default 포함)
- `docs/API_CONTRACT.md`, `docs/UI_CONTRACT.md` (최소 계약)
- `tasks/QUEUE.yaml` (첫 real 티켓 디스패치)

---

# 3) 매일 작업 시작(Daily Start) — “이것만 기억”
## 3-1. 오늘 세션 시작
```bash
make start
```

출력된 **Dashboard**를 보고:
- Open questions(최대 5개)
- Top tickets
- 다음 실행 프롬프트(Claude/Codex/Gemini)

## 3-2. Claude(디스패처) 세션-start 트리아지
```bash
make copy-claude
```
- Claude에 붙여넣기
- 당신은 **선택지만 답하기**  
  예: `Q-001=Default, Q-004=B`

Claude가 해야 할 일:
- `questions/QUEUE.md`에서 답변 처리([answered])
- 필요한 경우 ADR/Contracts/Tasks/STATE 업데이트
- 오늘 할 티켓 재정렬/언블록

## 3-3. 빌더 시작(병렬)
### Codex (백엔드/메인/리팩터)
```bash
make copy-codex
```

### Gemini (프론트/UI/QA)
```bash
make copy-gemini
```

---

# 4) 작업 중 규칙(헷갈리면 여기만)
## 4-1. “막히면” 채팅으로 묻지 말고 질문 큐
- 질문은 항상 `questions/QUEUE.md`
- 꼭 포함:
  - Options (A/B/C/D)
  - Recommendation (추천)
  - Default (기본값)
  - Blocking/Non-blocking

질문 템플릿 추가(자동):
```bash
make new-question
```

## 4-2. 티켓 단위(1 Ticket = 1 PR)
- 티켓 생성 템플릿:
```bash
make new-ticket
```
- 티켓에는 `files:` 범위를 좁게 잡기(충돌 방지)

## 4-3. 계약 우선(Contract-first)
- `apps/api/**`가 바뀌면 → `docs/API_CONTRACT.md` 먼저/같이
- `apps/web/**`가 바뀌면 → `docs/UI_CONTRACT.md` 먼저/같이

---

# 5) PR 올리기 전 체크(최소)
```bash
make pr-check
```

PR 템플릿은 이미 포함:
- `.github/PULL_REQUEST_TEMPLATE.md`

Claude PR 리뷰 프롬프트:
```bash
make copy-pr-review
```

---

# 6) 자주 나는 실수 5가지(체크리스트)
- [ ] 스타터킷을 **레포 루트가 아닌 다른 폴더**에 풀었다  
- [ ] **첫 커밋 없이** 작업부터 시작했다(체크가 무력화됨)  
- [ ] SSOT가 **다른 레포/다른 경로**에 있고 `../` 경로로 티켓을 가리킨다(권장X)  
- [ ] 계약(API/UI) 바꾸면서 contract 문서를 안 고쳤다  
- [ ] 질문을 채팅으로 하고 `questions/QUEUE.md`에 안 남겼다  

---

# 7) 오늘 “최단 루틴”만 다시(치트시트)
```bash
make start
make copy-claude      # Claude triage 실행
# (선택) PRD 있으면
make copy-prd-intake  # Claude PRD intake 실행

make copy-codex       # Codex 시작
make copy-gemini      # Gemini 시작

make pr-check         # PR 전 최소 게이트
```

---

## 도움말
- 다음 안내를 보고 싶으면:
```bash
make help
```

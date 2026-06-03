# CLAUDE1 Session-End (회고 + bookkeeping)

> 본 프로토콜은 세션 종료 직전에 1회 실행한다. 회고 누락률 통제 + memory entry trigger + bookkeeping 자동화가 목적이다.
> meation chain 14 회고 v1→v2 보강률 117% 사건을 메커니즘으로 차단한다.

## Step 1: 회고 작성

`devos/logs/{YYYY-MM-DD}-claude1.md` (또는 `{date}-session-end-claude1-chain{N}.md` for chain-단위 log) 에 회고를 작성한다.

회고 헤더에 다음 metadata 라인을 의무 기록한다:

```yaml
date: YYYY-MM-DD
chain: N
tickets_shipped: [T-..., T-...]
revision_delta: <metric only — gate 아님>
```

- **revision_delta** 는 회고 v1 항목 수 vs 최종 항목 수의 변화율 (%). gate / pass-fail 판정 용도가 **아니다** — 정량 추적만. 자가 검증 압력을 만들기 위한 시그널.

## Step 2: Self-question checklist (의무)

회고 v1 작성 후, 다음 8 카테고리를 **모두** 자문한다. 각 카테고리당 "빠진 항목 없는가?" 를 1줄 이상 답변한다 (없으면 "없음" 명시).

1. **user-AI 협업 마찰** — 사용자가 같은 지시를 반복했거나, 내가 사용자 의도를 잘못 해석한 사례
2. **DB / data 위험 패턴** — schema drift, 마이그레이션 누락, 데이터 손실 risk
3. **dev 환경 운영 이슈** — token TTL, redirect loop, port 충돌, 환경변수 누락
4. **잔재 파일 / .gitignore** — 임시 파일, sentinel, working-tree 잔재, .gitignore 누락
5. **Wave 분기 / PM 결정 deferred** — 미해결 PM 결정, deferred ticket, 의존 unblock 누락
6. **memory system 활용** — 이번 chain 에서 발견한 반복 패턴이 memory entry 자격이 되는가?
7. **vendor 정보 검증** — 사용자 제공 / WebSearch / third-party 정보를 직접 binary `--help` 로 검증했는가?
8. **보안** — 평문 secret 노출, API key, OAuth flow, OWASP 신호

self-question 항목을 회고 본문에 별도 섹션 `## Self-question (8 categories)` 으로 포함한다. v2 보강 시 추가된 항목은 v1 에 누락되었던 것이므로 revision_delta 에 반영된다.

## Step 2.5: OS-feedback capture (INBOX) — 마찰을 증발시키지 말 것

이번 세션(또는 이번 세션이 검토한 하위 프로젝트 작업)에서 **OS-레벨 마찰**을 만났으면 `devos/os-feedback/INBOX.md` 에 append 한다. 이게 "제품 마찰 → OS 개선" 운영 모델의 capture 지점이다 — 채팅에서 한 번 말하고 끝나면 다음 세션 CLAUDE1 은 모른다.

OS-레벨 마찰의 예 (제품 버그가 아니라 *엔진/도리/운영* 결함):
- 게이트가 잘못 통과/차단 (false-pass / false-block), 명령이 잘못된 레포·경로를 봄
- 호스트가 제공해야 할 것을 프로젝트가 로컬 해킹으로 때움 (예: agent 주입 갭 → 심링크 결합)
- 도리↔코드 드리프트, 명명 부채, 미사용 기계, 빈 스캐폴딩 발견
- 프로젝트 add/remove·de-vendor·스키마 마이그레이션에서의 수동/마찰 지점

기록 방법: 어느 프로젝트 세션에서든 `deos feedback "..."`, 또는 호스트에서 직접 `- {ISO-ts} [origin] (SEV) {1줄} [status: open]` 한 줄. **한 줄=한 항목** (count_feedback 가 `- ` 줄을 셈). 제품 기능 결함은 INBOX 아님 → 해당 프로젝트 QUEUE.

## Step 3: Memory entry trigger (강제 write 아님)

다음 조건 시 `~/.claude/projects/.../memory/feedback_*.md` 또는 동등 위치에 memory entry **작성을 권장**한다 (강제 write 는 아님):

- **회고 발견 반복 패턴 (≥ 2회)** — 동일 패턴이 본 chain 또는 직전 chain 에서 2회 이상 발생한 경우
- 사용자가 명시적으로 기억 요청
- 새로 발견한 vendor / library / API quirk

memory write 자체는 사용자 의도 영역. CLAUDE1 은 trigger 만 명시하고 실행은 자가 판단.

## Step 4: Bookkeeping — bin/deos archive

세션 종료 직전 QUEUE.yaml 에 `status: done` ticket 이 1건 이상 존재하면 `bin/deos archive` 를 자동 호출한다. 토큰 누적 방지.

```bash
bin/deos archive
```

조건: done ≥ 1. 없으면 skip.

## Step 5: Report back (session-end format)

```
── Session Summary ──
date: YYYY-MM-DD
chain: N
revision_delta: <metric>

── Shipped ──
- T-XXX (owner): <1줄 outcome>

── Self-question Findings ──
- [카테고리]: <발견 항목 or "없음">

── Memory Triggers ──
- <발견한 반복 패턴 권장 항목, 없으면 "없음">

── Next ──
- [chain N+1 dispatch hint, blocker]

── Archive ──
- bin/deos archive 실행 결과 (skipped if done=0)
```

## CRITICAL REMINDERS

- self-question 8 카테고리는 의무. "없음" 도 명시 답변.
- revision_delta 는 metric only — gate 로 사용 금지.
- memory entry 는 trigger 명시까지만. 강제 write 금지.
- bin/deos archive 는 done ≥ 1 시 자동.

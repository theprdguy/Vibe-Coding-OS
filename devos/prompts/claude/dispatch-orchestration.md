# Dispatch Orchestration (CLAUDE1 main)

> CLAUDE1 main thread 가 `/dispatch T={id}` invocation 을 받았을 때 따라야 할
> deterministic 7-step 절차. orchestration 일관성 보장.

## Invocation 패턴

사용자가 main 세션에서:
- `/dispatch T=T-OSN-X` (slash 형식)
- `T-OSN-X 의 /dispatch 절차 시작` (자연어 형식)
- `dispatch T-OSN-X` (간략)

위 셋 중 하나로 명시. 어느 패턴이든 main 은 본 문서의 Step 1~7 을 정확히 따른다.

**모호한 invocation 거부**: "실행해", "해줘", "진행" 단독은 거부 — ticket id 명시 요청.

---

## Step 1 — Ticket lookup + pre-flight

```bash
bin/deos lookup {id}      # canonical entrypoint; lookup 은 QUEUE→ARCHIVE fallback. (T= prefix 금지: 순수 ticket id)
```

반환: ticket JSON (또는 not_found error). pre-flight 검사:
- `status == 'todo'` 인지 (아니면 거부 — 옛 룰 존중)
- `deps:` 모두 status=done 인지 (의존성 미해결 시 deps 별 status 출력 + Q-id)
- `files:` overlap 검사 (현 phase 직렬 builder 라 무관 — Future enhancement)

실패 시: status=blocked + 명확한 에러 출력 + 종료.

## Step 1.5 — Ticket preflight policy

dispatcher 는 agent 실행 전에 ticket scope sanity 를 검증한다. P0 검증 범위는
`files:` 경로 존재성 (`NEW:` prefix 는 신규 파일 marker 로 허용) 과 `verify:` 첫
token 이 PATH 또는 repo binary 로 존재하는지에 한정한다. 실패 시 ticket 은
`blocked` 로 전환되고 reason 이 stderr 에 출력된다. 결과는 ticket 의
`verify_preflight: validated|skipped|failed` 로 audit 가능해야 한다.

## Step 2 — Owner 라우팅

```
ticket.owner === ?
  ├─ BUILDER → Step 3a
  ├─ CODEX   → Step 3b
  ├─ CLAUDE1 → Step 3c
  ├─ CLAUDE2 → deprecated owner; reject and migrate ticket owner to BUILDER
  └─ 기타 / 알 수 없음 → exit 1 + "unknown owner: {value}"
```

## Step 3 — Owner-specific dispatch

Step 2 의 owner 라우팅 결과에 따라 Step 3a / 3b / 3c 중 하나만 실행.

### Step 3 prelude — BOOT_INLINE 블럭 (모든 sub-agent 공통)

CLAUDE1 main 은 Step 3a/3b/3c 진입 직전에 **`devos/AI-core.md` 를 1 회 Read**
한 뒤 그 본문을 prompt 의 `<<INLINE devos/AI-core.md>>` placeholder 자리에
`<BOOT_INLINE>...</BOOT_INLINE>` 블럭으로 치환한다. 이렇게 하면 sub-agent
spawn 시 별도 Read tool round-trip 없이 부트 룰을 즉시 보유한다 (per-spawn
tool wrapper ~200-400 토큰 절감 × N sub-agent).

치환 책임자: **CLAUDE1 main** (단일 source `devos/AI-core.md` drift 방지).
sub-agent.md 는 BOOT_INLINE 블럭이 prompt 에 있으면 AI-core.md Read 를
생략하고, 없으면 fallback 으로 직접 Read 한다.

### Step 3a — BUILDER dispatch (in-session sub-agent)

```
Agent(
  subagent_type="builder",
  prompt="""
  Ticket: {id}
  {ticket body — goal/context/constraints/dod/files/verify/gates 전체 inline 전달}

  <BOOT_INLINE>
  <<INLINE devos/AI-core.md>>
  </BOOT_INLINE>

  첫 동작 (의무): devos/prompts/claude2/session-start.md,
  devos/docs/BUILDER_GUIDE.md Read 후 작업 시작.
  (BOOT_INLINE 블럭이 위에 있으므로 AI-core.md 별도 Read 생략.)
  완료 시 'Done: {id} — {what} — files: {list}' 또는 'Block: {Q-id}' 반환.
  """
)
```

builder sub-agent 는 own context window 로 작업 → Done/Block/Log 반환.
**main 은 sub-agent 결과를 직접 review 금지 (Rule 7) — Step 4~6 의 reviewer chain 으로 처리.**

### Step 3b — CODEX dispatch (subprocess)

```bash
bin/deos dispatch-codex {id}
```

옛 codex CLI subprocess 흐름 그대로. 종료 후:
- `devos/logs/{date}-codex-{id}.md` Read 로 작업 결과 확인
- exit code != 0 → status=blocked + Q-id

### Step 3c — CLAUDE1 직접 처리

policy/SSOT doc ticket (devos/, .claude/, AGENTS.md, osn.yaml compatibility config, root docs scope). <!-- osn.yaml: compatibility filename — preserved verbatim -->
main 이 직접 실행 — 옛 룰 그대로. session log 는 `devos/logs/{date}-claude1.md`
한 파일에 누적.

## Step 4 — pr-check gate

```bash
T={id} bin/deos pr-check
```

옛 gate (secret scan, contract sync, scope guard, session log 존재) 그대로 실행.
실패 시: status=blocked + 출력 메시지 + 종료.

## Step 5 — Review chain (5-way 분기, 2026-05-14 balanced rebalance)

ticket 유형별 분기 — 매 ticket 무조건 3-spawn 폐기. Step 3 prelude 와 동일하게
**각 prompt 에 `<BOOT_INLINE>` 블럭으로 AI-core.md 본문 치환**.

### Step 5.0 — ticket classification (CLAUDE1 main 책임)

```python
# 0) ETHOS-override 자동 감지 — 키워드 1건 이상 시 ticket.ethos = 'high'
ETHOS_KEYWORDS = [
    "삭제", "영구", "결제", "공개", "권한", "비공개",
    "비밀번호", "토큰", "인증", "환불", "복구 불가",
    "delete", "permanent", "payment", "auth", "credential", "refund",
]
if any(kw in (ticket.goal + ' ' + ' '.join(ticket.dod)) for kw in ETHOS_KEYWORDS):
    ticket.ethos = 'high'   # 명시되지 않았으면 자동

# 1) ticket 분류 — 우선순위 순
if ticket.security_audit == True or ticket.ethos == 'high':
    classification = 'critical'
elif any('apps/web/' in f for f in ticket.files):
    classification = 'ui'
elif any(f.startswith(('apps/api/', 'packages/', 'server/')) for f in ticket.files):
    classification = 'backend_non_critical'
elif all(f.startswith(('devos/', '.claude/', 'docs/')) for f in ticket.files):
    classification = 'docs_refactor'
else:
    classification = 'backend_non_critical'   # 보수적 default

# 2) 5% random sample — 평소 skip 되는 경로도 검증 (보안 안전망)
import random
if random.random() < 0.05 and classification in ('ui', 'backend_non_critical', 'docs_refactor'):
    classification = 'critical'   # 5% 확률로 full chain
    audit_sample = True
```

### Step 5.1 — 분기 별 review chain

```python
if classification == 'critical':
    # Full chain — auth/payment/permissions/external_input + ETHOS-high + 5% sample
    Agent(reviewer, prompt="ticket {id} diff. branch/PR: {ref}\n<BOOT_INLINE>...</BOOT_INLINE>")
    Agent(security, prompt="ticket {id} security audit — files: {list}\n<BOOT_INLINE>...</BOOT_INLINE>")
    if any('apps/web/' in f for f in ticket.files):
        Agent(designer, prompt="ticket {id} UI 검토\n<BOOT_INLINE>...</BOOT_INLINE>")

elif classification == 'ui':
    # designer + builder self-review (Sonnet UX reasoning 보존, security skip)
    Agent(designer, prompt="ticket {id} UI 검토 — files: {list}\n<BOOT_INLINE>...</BOOT_INLINE>")
    # builder self-review: builder.md 의 verification-before-completion 절차로 처리

elif classification == 'backend_non_critical':
    # CODEX 1차 reviewer (C0) — Phase 5 활성 시 / Phase 5 비활성 시 claude -p (C2)
    # Phase 5 진입 전: Opus reviewer + 4축 점수 카드 기록
    Agent(reviewer, prompt="ticket {id} diff\n<BOOT_INLINE>...</BOOT_INLINE>")
    # Phase 5 활성 시 (devos/PROJECT_STATE.md 의 phase_5_active 플래그):
    #   claude_p_review(ticket_id)   # C2 채널 — bin/deos review --headless

elif classification == 'docs_refactor':
    # self-verify only — sub-agent spawn 없음
    pass   # main 의 pr-check gate 만 의존

# Gemini visual reviewer (별도 채널 — UI ticket 자동)
if ticket.get('gui_review') == True or any('apps/web/' in f for f in ticket.files):
    bash("bin/deos gemini dispatch {id}")   # Plan A 자동
```

read-only sub-agent 들이라 충돌 X. 모두 결과 schema (verdict / findings /
uncertainty / confidence) 반환.

**Ticket schema 확장**:
- `gui_review: true|false` — UI 변경 ticket 명시 (디폴트 자동 감지)
- `gui_review_required: true|false` — true 시 fail-closed
- `gui_review.images: [path]` — 첨부 PNG
- **`ethos: 'high' | 'normal' (default)`** — high 시 무조건 critical 분류
- **`paired_run: true | false`** — Phase 3/4 paired-run 발동 (Step 5.3 참조)

### Step 5.2 — 분기 audit 기록 (operational)

매 dispatch 후 `devos/logs/dispatch-classification.jsonl` (append-only) 에 1줄:
```json
{"date":"2026-MM-DD","id":"T-XXX","classification":"<5-way>","audit_sample":<bool>,
 "files":[...],"ethos":"<level>","spawn_count":<N>}
```

이 로그가 4축 점수 카드의 분류 정확성 검증 input — random 5% sample 결과 와 평소
경로 결과 비교용.

### Step 5.3 — paired-run mode (Phase 3/4 active 시)

ticket `paired_run: true` 또는 `devos/PROJECT_STATE.md` 의 `paired_run.phase_3` /
`paired_run.phase_4` 활성 시 — builder/CODEX 호출을 **2회** 실행:

```python
if classification == 'ui' and paired_run_phase_3_active:
    # current: builder Sonnet (default)
    result_a = Agent(builder, prompt="...")   # sonnet
    # alt: builder Haiku
    result_b = Agent(builder_haiku, prompt="...")   # haiku — .claude/agents/builder-haiku.md (Phase 3 신규)
    record_paired_run(ticket, result_a, result_b)   # devos/docs/paired-run/{date}-{id}.yaml

elif classification == 'backend_non_critical' and paired_run_phase_4_active:
    result_a = Agent(builder, prompt="...")              # sonnet — 현행
    result_b = bash("bin/deos dispatch-codex {id}")       # CODEX — alt
    record_paired_run(ticket, result_a, result_b)
```

paired-run ship 기준 (plan § Phase 3/4):
- Phase 3: findings recall ≥ 90% Sonnet, BLOCKER 누락 0, 3 ticket 평균 user_acceptance ≥ 80%
- Phase 4: DOD 100% 충족, mutation test 1회 통과 (생존자 ≤ 5%)

## Step 6 — Fan-in + b' adaptive trigger (정량화 — 2026-05-14)

각 sub-agent 결과 파싱 (YAML 블록):
```python
reviewer = parse_yaml(reviewer_output)
security = parse_yaml(security_output) if security_called else None
designer_findings = parse_yaml(designer_output) if designer_called else None
```

**b' (adaptive CODEX cross-model) 트리거 — 정량 기준 (정성 'uncertainty=true' 폐기)**:

```python
def should_escalate_to_codex(reviewer, security, ticket) -> bool:
    """
    2026-05-14 balanced rebalance — 정성 → 정량.
    어느 조건 1건이라도 만족 시 CODEX cross-model 발동.
    """
    if ticket.get('cross_model') == True:                    # 명시 요청
        return True
    if ticket.get('security_audit') == True:                 # auth/payment/...
        return True
    if ticket.get('ethos') == 'high':                        # ETHOS-override
        return True
    if reviewer.get('confidence', 1.0) < 0.7:                # reviewer 자체 불확실
        return True
    blocker_count = sum(1 for f in reviewer.get('findings', []) if f.severity == 'blocker')
    warning_count = sum(1 for f in reviewer.get('findings', []) if f.severity == 'warning')
    if blocker_count >= 1:                                   # BLOCKER 있음 → 2차 검증
        return True
    if warning_count >= 3:                                   # WARNING 누적 ↑
        return True
    if security and security.get('findings', []):            # security finding 1건 이상
        return True
    if reviewer.get('uncertainty') == True:                  # legacy 호환
        return True
    return False

if should_escalate_to_codex(reviewer, security, ticket):
    codex_verdict = bash(f"bin/deos cross-model-codex {ticket.id} --reason='{reason}'")
    # CODEX 60s timeout. timeout 시 reviewer 단독 verdict + 'b_fallback' WARNING.
else:
    codex_verdict = None
```

verdict 통합 (BLOCKER 우선):
```python
verdicts = [v for v in [reviewer, security, codex_verdict] if v]
if any(v.verdict == 'BLOCKER' for v in verdicts):
    final = 'BLOCKER'
elif any(v.verdict == 'WARNING' for v in verdicts):
    final = 'WARNING'
else:
    final = 'OK'
```

**b' fallback rate 추적**: `devos/logs/dispatch-classification.jsonl` 에 escalated
필드 추가. 4축 점수 카드의 `b_prime_escalation_rate` 메트릭 — Phase 5 시점에 10-25%
정상, < 10% = 임계값 보수적 (조정 필요), > 25% = 비용 절감 무효 (분류 정확성 문제).

## Step 7 — 최종 처리 + 표준 결과 헤더 (2026-05-14)

```
if final == 'BLOCKER':
    ticket.status = 'blocked'
    devos/questions/QUEUE.md 에 Q-id + 사유 기록
    QUEUE.yaml 에 _transition_reason / _actor / _ts 추가
elif final in ('WARNING', 'OK'):
    ticket.status = 'done'
    session log 작성: devos/logs/{date}-orchestrator-{id}.md
        (BUILDER 결과 요약 + reviewer/security/designer verdict + b' 발동 여부)
    QUEUE.yaml status update
```

**표준 결과 헤더 (사용자 인지 부담 흡수)** — 모든 dispatch 결과는 다음 형식으로 사용자에게 출력:

```
T-OSN-X {done|blocked} — path: {ui|backend_non_critical|backend_critical|docs_refactor|critical-via-5%}
  build: {sonnet|haiku|CODEX|claude_p}
  review: {reviewer(opus)|designer(sonnet)|CODEX-1차|claude_p(C2)|self-verify} — {BLOCKER:N WARNING:M OK}
  b': {skip|escalated → CODEX:{verdict}|fallback(timeout)}
  paired_run: {none|phase_3:builder_haiku|phase_4:codex} — recall {%}
  verdict: {MERGE OK|BLOCK + Q-XXX|WARNING — see log}
  files: [...]
  log: devos/logs/{date}-orchestrator-{id}.md
```

이 헤더가 없으면 사용자가 매번 "어느 path 였지? 어느 모델이 build/review 했지?" 물어봐야
함 — 균형안의 인지 부담 영구 drag 완화 메커니즘.

세션 종료 직전 `done >= 1` 시: `bin/deos archive` 1회.

---

## Failure modes 요약

| 단계 | 실패 | 처리 |
|---|---|---|
| Step 1 lookup | ticket not found | exit 1 + 에러 메시지 |
| Step 1 pre-flight | deps 미해결 | status=blocked + deps 별 출력 |
| Step 3a sub-agent | builder timeout / Block 반환 | status=blocked + Q-id |
| Step 3b CODEX | subprocess fail | status=blocked + stderr 출력 |
| Step 4 pr-check | gate fail | status=blocked + 실패 gate 출력 |
| Step 5 sub-agent | reviewer/security/designer timeout | WARNING 기록, 나머지 결과로 진행 (graceful) |
| Step 6 b' | CODEX timeout | reviewer 단독 verdict + 'b' fallback' WARNING |
| Step 7 status | QUEUE.yaml write fail | 에러 + Q-id (사용자 수동 복구 필요) |

---

## Anti-patterns

- main 이 builder 결과를 직접 OK 판정 (Rule 7 위반 — 항상 reviewer 호출)
- `/dispatch` 밖에서 builder Agent 직접 호출 (Rule 8 위반)
- ticket 없이 builder 즉석 호출 (Rule 2 위반)
- reviewer.uncertainty 무시 (b' 안전망 무력화)
- pr-check 건너뜀 (옛 hook 우회)

---

## 참조

- `.claude/CLAUDE.md` § ORCHESTRATOR ROLE
- `devos/AI.md` § Roles + Dispatch Model
- `devos/agents/registry.yaml` — sub-agent 메타
- `.claude/agents/{builder,reviewer,designer,security}.md` — sub-agent 정의

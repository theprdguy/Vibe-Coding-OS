# CLAUDE1 PRD → Tickets

You receive a PRD / spec / feature request. Decompose, don't execute.

> ETHOS: 비개발자 보호 + Boil the Lake. 단축본 ticket 금지. 누락 없이 완전 분해.

## Step 0: PRD intake checklist (의무)

PRD를 받으면 **decompose 전에** `devos/prompts/claude/prd-intake-checklist.md`를 따라 도메인별 누락 항목을 사용자에게 질문한다. happy path만 적힌 PRD를 그대로 분해 금지.

- 키워드 스캔 → 해당 도메인 섹션 적용 (Auth/Payment/Input/Upload/External API/Permissions/공통)
- 한 번에 5개 이하로 묶어 질문
- 답변을 PRD 부록 또는 `devos/questions/QUEUE.md`에 기록
- 사용자가 "필요 없음"이라 답한 항목은 *명시적 N/A 사유*로 기록

## Step 0.5: User journey 추출 + 자동 e2e ticket draft (의무)

PRD intake checklist 답변까지 확보된 후, ticket 분해 **전에** 다음을 수행:

### 0.5.1 User journey 추출

PRD 본문에서 사용자가 직접 인지/조작/확인하는 시점·전환·결과를 **줄 단위**로 발췌하여 `journeys` 리스트로 작성한다. 도메인 추상화 (UI/CLI/API/모바일/하드웨어 무관 동일 형식):

```yaml
journeys:
  - id: J-1
    actor: <end-user role>
    trigger: <시작 행위 1줄 — "버튼 클릭" / "POST /x" / "CLI 실행" / "앱 시작">
    expected_outcome: <사용자가 직접 보는/받는 결과 — "리스트에 카드가 추가된다" / "JSON {ok:true} 반환" / "stdout `done` 출력">
    failure_outcome: <실패 시 사용자가 보는 결과 — "에러 토스트 표시" / "401 + message" / "stderr `not found` + exit 1">
    type_hint: A | B | C   # 아래 분류 § 참조
```

추출 원칙:
- happy path **+** failure path 둘 다 — failure_outcome 누락 시 Type B 결함 잠복.
- "사용자가 직접 보는 결과" 가 비어 있으면 (내부 상태만 변경) journey 가 아님 — 일반 ticket 으로 처리.
- 모호하면 `devos/questions/QUEUE.md` 에 추가, journey 확정 후 진행.

### 0.5.2 자동 e2e ticket draft 변환

각 journey 1건 → e2e ticket 1건 draft 자동 생성. **단순 OK prompt 거부** — 사용자가 draft 본문을 시각적으로 검토할 수 있는 형식으로 작성.

draft 형식 (자동 채움):
```yaml
- id: T-{PROJECT}-V{N}-e2e-{seq}
  status: todo
  owner: BUILDER | CODEX
  goal: |
    e2e: {trigger} → {expected_outcome} (J-{n})
  context: |
    user journey J-{n} ({actor}) — PRD §{줄번호} 발췌.
    Type {A|B} 분류 — Type A: V39-01 단독 예방, Type B: screenshot_tool 게이트 필수.
  dod:
  - <success: trigger 실행 → expected_outcome 관찰 가능 (도메인별 수단)>
  - <failure: invalid trigger → failure_outcome 관찰 가능>
  files:
  - <e2e 검증이 닿는 시각적 출력 산출 경로 — UI 컴포넌트 / CLI 진입점 / API endpoint>
  verify: |
    <도메인 도구 — playwright/detox/maestro/curl/stdout diff 등>
  deps: [<implementation ticket id 들>]
  gates:
  - scan-secrets
  - pr-check
  - user-outcome-review   # screenshot_tool 설정 시 (V39-03)
  screenshot_tool: playwright | detox | maestro | simctl | eas_preview | n/a
  device_target: web | ios_sim | android_emu | physical | n/a
  type_class: A | B
```

### 0.5.3 사용자 시각적 검증 게이트

draft 묶음을 사용자에게 제시하여 검토받는다. 단순 "Approve?" 가 아닌 **journey ↔ draft 표** 형식:

```
| J-id | trigger | expected_outcome | draft ticket | type_class | 검토 |
|---|---|---|---|---|---|
| J-1 | … | … | T-XXX-e2e-01 | A | ☐ |
| J-2 | … | … | T-XXX-e2e-02 | B | ☐ |
```

사용자가 추가/삭제/병합/Type 재분류를 지시할 수 있도록 draft 본문 그대로 노출. 묵시적 OK 금지 — 사용자 명시적 응답 후 Step 0.6 로 진행.

### 0.5.4 Type A/B/C 결함 분류 § (basket cross-validation 산출)

PRD intake 와 journey 추출 시 결함이 어느 Type 인지 사전 분류 — 게이트 결합 여부 판정 기준.

| Type | 정의 | 사례 | 예방 메커니즘 |
|---|---|---|---|
| **A** | user journey 시점/전환/외관 가정 누락 | "Stay 누적 끝점 user journey 가정 누락", "FAB 텍스트 시각 가독성 미검증", "분류 완료 후 화면 상태 가정 누락" | **Step 0.5 + 3.5 단독 예방 (~10%)** |
| **B** | 아키텍처/데이터/프레임워크 동작 결함 | "linkStore 상태관리 결함", "og:image 상대 경로 케이스 누락", "RN FlatList key 갱신 미흡" | **Step 0.5 + V39-03 user-outcome-review 게이트 결합 필수 (~7%)** |
| **C** | 사업 결정 변경 / UX 의사결정 reversal | "fxtwitter 도입 → 제거 → 재도입" | **OS 적용 제외 — milestone closure ticket § '의도적 변경' 별도 분류 (over-engineering 방지)** |

분류 기록 위치:
- e2e ticket `type_class` 필드 (A/B 만, C 는 OS ticket 아님)
- milestone closure 회고에 Type 분포 기록 (`devos/docs/retrospective/{date}-{milestone}.md` § "Type 분포")

## Step 0.6: Designer review (UI/UX 1차 필터, 의무)

journey 확정 (Step 0.5.3 사용자 OK) 직후, ticket 분해 **전에** `devos/prompts/claude/designer-review.md` 를 따라 디자이너 페르소나로 self-invoke. 비개발자 사용자 앞에서 먼저 UI/UX 누락을 잡아내 진행 속도를 높이는 1차 필터.

### 0.6.1 검토 범위
designer-review.md 의 6개 카테고리 (A. UI 일관성 / B. 정보 위계 / C. 상태 누락 / D. 여정 갭 / E. 접근성 / F. 비개발자 보호) 를 PRD + journey 리스트에 대해 적용.

### 0.6.2 산출물
- **신규 journey 추가**: 누락된 화면/상태/전환을 Step 0.5.1 `journeys` 리스트에 append + Type 분류
- **기존 journey 보강**: `expected_outcome` / `failure_outcome` 에 UI 디테일 추가
- **사용자 검토 표**: designer-review.md § "출력 형식" 의 표 형식으로 사용자에게 제시

1회 검토에서 5개 초과 발견 시 임팩트 큰 5개만 우선 제시. 나머지는 `devos/questions/QUEUE.md` 백로그.

### 0.6.3 Skip 조건
PRD `journeys` 리스트 전체가 시각 출력 0% (백엔드 cron / API JSON / CLI stdout only) 이고 모든 ticket `files:` 가 UI 없는 경로 (`apps/api/src/**`, `packages/**`, `infra/**`, `scripts/**`) 인 경우 skip.

skip 시 plan 본문에 기록:
```yaml
designer_review:
  status: skipped
  reason: <왜 skip — 예: "백엔드 cron only">
```

수행 시:
```yaml
designer_review:
  status: done
  added_journeys: [J-N, J-N+1]    # 신규 추가된 journey id
  enhanced_journeys: [J-1, J-3]   # outcome 보강된 journey id
  deferred: <devos/questions/QUEUE.md 백로그 항목 수>
```

### 0.6.4 사용자 명시적 OK 후 진행
designer-review.md § "출력 형식" 표에 사용자가 항목별 ✅/❌/수정 응답 → journey 리스트 갱신 → Step 1 로 진행. 묵시적 통과 금지.

## Step 1: Understand scope
- Read the PRD fully (intake 답변 포함). List unknowns.
- Research unknowns via `context7` (library APIs, breaking changes, version compat).
- If ambiguous → add to `devos/questions/QUEUE.md` with options + recommendation + default. Do NOT guess critical decisions.

## Step 2: Partition by owner
- **BUILDER** (app + platform implementer, in-session sub-agent — 옛 CLAUDE2 의 후신): `apps/api/src/**`, `apps/web/**` — backend business logic, GUI, components
- **CODEX** (platform, external CLI): `packages/**`, `infra/**`, `scripts/**`, `tests/**` — infra, tests, mechanical edits
- Cross-test logic ticket: `test_owner: CODEX`, `impl_owner: BUILDER`
- 옛 CLAUDE2 owner 표기는 deprecated (sunset W6 of osn-claude2-sunset plan) — historical 컨텍스트 외 사용 X
- UI ticket 검토 시 designer sub-agent 자동 호출 (`.claude/agents/designer.md`) — Step 0.6 의 self-invoke 가 sub-agent 호출로 진화

## Step 2.5: Mode 분류 (의무)

PRD 분해로 나오는 **모든 ticket 은 `mode` 필수** (`exploration` | `productization` | `production`).
즉석/잡 ticket (PRD 분해 외 직접 filing) 은 면제 — 이 의무는 **분해 산출물에만** 적용한다.
근거: mode 는 "판단 보조 + 속도 조절기" 다. 분해 시점에 각 ticket 의 무게(엄격함)를 결정해
두면, 이후 게이트가 그 무게대로 동작한다 (`docs/policy/MODE_GATE_MATRIX.md`).

### 2.5.1 분류 신호표 (신호 → mode)

| 신호 | mode |
|---|---|
| 프로토타입 / UX 스케치 / 기술 probe / discovery — 버려도 되는 학습용, 사용자 outcome 미확정, "일단 되는지 보자" | **exploration** |
| 유망한 exploration 결과를 production-ready 요구사항·리스크·owner·files·gates·DOD 로 정리 (대개 CLAUDE1/PM 소유, 코드 산출 적음) | **productization** |
| 코드베이스에 남아 미래 작업을 지탱하는 제품 변경 — 사용자 outcome 확정, work_type/risk/policy 명확 | **production** |

추가 강제 신호:
- `work_type: ui` + 실제 사용자 노출 + outcome 확정 → **production** (visual review 강제 트리거)
- auth / payment / permissions / external input 접촉 → **production** (`security_audit` 자동)
- 적격 판정 기준: **production 은 ssot 가 필수필드를 강제**한다 — `user_outcome`, `risk_level`,
  `work_type`, `policy_class`, `dod`, `files` 를 *지금 채울 수 있는가*로 판정. 못 채우면 아직
  exploration/productization 단계다 (`server/ssot.py:_validate_policy_fields`).

### 2.5.2 비-production ticket 의 게이트 (report-only)

- exploration / productization ticket 도 **test/review 게이트를 빼지 말고 그대로 붙인다.**
- 이 게이트들은 `T-OS3-MODE-GATE-POSTURE` 이후 **report-only** 로 동작한다 — 실행되어 결과는
  세션 로그에 `[REPORTED]` 로 남지만 실패해도 ticket 을 막지 않는다 (속도 유지 + 신호 보존).
- **secrets 게이트는 mode 불문 항상 blocking (안전 바닥)** — 어느 mode 든 붙인다. 프로토타입
  이라도 키 유출은 유출이다.
- production ticket 의 게이트는 모두 blocking (현행) — secrets + review 존재가 강제된다.

### 2.5.3 승격 추적 (보조)

exploration → productization → production 으로 ticket 이 파생되면, 신규 ticket 에
`descends_from: <원-ticket-id>` 를 적어 여정을 추적한다 (`T-OS3-MODE-DESCENDS-FROM`).
옵셔널 — 파생 관계가 있을 때만.

## Step 3: Write each ticket

**Ticket ID 명명 컨벤션 (mandatory)**:
- **버전 sequence**: `T-{PROJECT}-V{N}-{seq}` (예: `T-OS2-V36-01`)
  - 정기 release version — 핸드오프 처리 / PR sequence / 메이저 fix 묶음
- **Cluster sequence**: `T-{PROJECT}-{CLUSTER}-{seq}` (예: `T-OS2-CB-01`, `T-OS2-RES-02`)
  - cluster: `CB`(Context Efficiency), `RES`(Residual), `META`(meta-infrastructure), `HOTFIX`
- **단순 sequence**: `T-{PROJECT}-{seq}` (예: `T-DECK-001`)
  - 작은 프로젝트 / sequential 모델 / deck 본사 호환
- **프로젝트 prefix mandatory** — sister 프로젝트 (deck/basket/bbn/Vibe-Coding-OS) ID 충돌 차단
- **기존 ticket 재명명 X** — backward-compat, 신규 ticket 부터 컨벤션 적용
- **example**: `T-OS2-V38-01` ✅ / `T-001` ❌ (prefix 누락) / `T-OS2-fix` ❌ (sequence 누락)

Required fields (see `devos/AI.md` Ticket Standard):
```yaml
- id: T-XXX
  status: todo              # MUST be todo — dispatcher skips others
  owner: BUILDER | CODEX     # 옛 CLAUDE2 deprecated
  mode: exploration | productization | production   # 의무 (Step 2.5) — 분해 산출 ticket
  descends_from: T-YYY      # optional — 승격 추적 (Step 2.5.3)
  goal: <behavioral requirement, 1 sentence>
  context: |
    <why + your research findings — make ticket self-contained>
  constraints:
    - <tech constraint>
  dod:
    - <success case: input → expected output>
    - <error case: input → expected error>   # mandatory if success case exists
  files:
    - <exclusive modification scope>
  verify: |
    <how to check — commands, URLs, gates>
  deps: [T-YYY]
  gates:
    - scan-secrets
    - pr-check
  tdd: required | skip | self-evident
  test_owner: CODEX | BUILDER | n/a
  impl_owner: BUILDER | CODEX
  cross_model: false        # true for critical path (auth/payment/permissions)
  security_audit: false     # auto-true for auth/payment/permissions/external-input
  skills_hint: [skill-name] # optional, see SKILLS INTEGRATION
```

**신규 디렉토리 규칙**: ticket의 `files`에 새 최상위 디렉토리 (`apps/X/`, `packages/X/`, `infra/X/` 등 — 기존에 없던 경로) 가 포함되면 **동일 wave에 `T-XXX-test-infra` ticket을 자동 추가**한다. 해당 ticket의 DOD: (a) 테스트 러너 설정 파일 (`pytest.ini` / `jest.config` 등 — 디렉토리의 언어/스택에 맞춰), (b) fixture 1개 (최소 conftest.py 또는 setup helper), (c) "1+1=2" 수준의 dummy test 1건이 통과. 목표는 사후 추가 (T-033a 형태) 패턴 박멸 — 신규 디렉토리는 첫 ticket 시점부터 test 인프라가 함께 dispatch 되어야 한다.

## Step 3.5: e2e ticket mandatory + journey 매핑 검증 (의무)

Step 3 ticket 작성 후, save 직전에 다음을 검증:

### 3.5.1 e2e ticket coverage

Step 0.5.1 에서 추출한 모든 journey 가 최소 1개 e2e ticket 으로 매핑되어 있는지 확인:

```yaml
journey_coverage:
  - J-1 → [T-XXX-e2e-01]
  - J-2 → [T-XXX-e2e-02, T-XXX-e2e-03]   # 1 journey → N tickets 허용
  - J-3 → []                              # ❌ 누락 — plan approve 거부
```

미매핑 journey 발견 시:
1. 해당 journey 가 별도 e2e ticket 불필요한 사유 (구현 ticket DOD 에 흡수 등) 를 plan 본문 § "journey-mapping-rationale" 에 명시.
2. 사유 부재 시 e2e ticket 추가하거나 journey 자체를 PRD 에서 제거 (사용자 확인 필요).

### 3.5.2 Type A 분류 강제

`type_class: A` 인 e2e ticket 은 다음 조건 자동 강제:
- `gates:` 에 `user-outcome-review` 포함 X (Type A 는 V39-01 단독 예방).
- `verify:` 에 journey trigger → expected_outcome 직접 검증 명령 명시.
- `deps:` 에 implementation ticket 명시 (e2e 가 implementation 보다 먼저 done 될 수 없음).

`type_class: B` 인 e2e ticket 은 다음 조건 자동 강제:
- `gates:` 에 `user-outcome-review` 포함 (V39-03 게이트 결합 필수).
- `screenshot_tool` 또는 동등 검증 도구 (stdout diff / curl diff 등) 명시.
- `device_target` 명시 (UI 영역만, 비-UI 는 n/a).

### 3.5.3 e2e ↔ implementation 의존성 검증

각 e2e ticket 의 `deps:` 에 명시된 implementation ticket 이 동일 plan 또는 이전 plan 에 존재하는지 확인. 누락 시 plan approve 거부.

## Step 4: Self-check before save (의무)

Save 직전 자가 검사:

1. **금지어 검사** (`devos/prompts/common/scope-reduction-prohibition.md`):
   ```bash
   grep -E -i "v1 로|TODO|FIXME|XXX|placeholder|static for now|나중에|임시|추후|simplified|basic version|minimal implementation|quick fix|wired later|skip for now|future enhancement|hardcoded for now" devos/plans/pending/{date}-{slug}.yaml
   ```
   결과 0건이어야 함. 발견 시 ticket 자체 수정.

2. **DOD pair 검사**: 모든 success-case dod에 매칭되는 error-case dod 존재 확인.

3. **security_audit 자동 강제**: 인증/결제/권한/외부 입력 ticket은 `security_audit: true` 강제.

4. **cross_model 권장 검사**: critical path(auth/payment/permissions/data integrity) ticket은 `cross_model: true` 권장.

5. **e2e ticket coverage 검사** (Step 3.5.1 산출): journey 미매핑 0건이어야 함. 발견 시 plan 본문 § "journey-mapping-rationale" 에 사유 명시 또는 e2e ticket 추가.

6. **Type 강제 검사** (Step 3.5.2 산출):
   - `type_class: A` ticket: `gates:` 에 `user-outcome-review` 미포함 ✓
   - `type_class: B` ticket: `gates:` 에 `user-outcome-review` 포함 ✓ + `screenshot_tool` 또는 동등 도구 명시 ✓
   - 위반 시 ticket 자체 수정.

7. **designer_review 메타데이터 검사** (Step 0.6 산출): plan 본문에 `designer_review:` 블록이 있는지 확인. `status: done` 또는 `status: skipped + reason` 둘 중 하나여야 함. 누락 시 plan approve 거부.

8. **mode 분류 검사** (Step 2.5 산출): 분해 산출 **모든 ticket 에 `mode` 존재**. `mode: production` ticket 은 `user_outcome` / `risk_level` / `work_type` / `policy_class` / `dod` / `files` 필수필드 구비 + `secrets`(또는 `scan-secrets`) & `agent-review` 게이트 존재. 비-production ticket 도 test/review 게이트를 빼지 않음(report-only 동작). 누락 시 ticket 자체 수정.

## Step 4.5: 효과 측정 metric (의무)

plan 본문에 다음 metric § 추가 — milestone closure 시 정량 비교 기준:

```yaml
effectiveness_metrics:
  baseline:
    follow_up_ticket_ratio: <milestone N-1 마감 후 후속 ticket 비율 — 분모: 본 milestone 분량, 분자: 마감 후 추가된 후속 ticket 수>
    type_distribution: { A: <%>, B: <%>, C: <%> }
  target:
    follow_up_ticket_ratio: <목표 — 일반적으로 baseline 의 50% 이하>
    type_a_prevention_rate: ">= 80%"   # Step 0.5 + 3.5 로 Type A 예방
    type_b_prevention_rate: ">= 70%"   # Step 0.5 + V39-03 결합 시
  measurement:
    closure_retro: <devos/docs/retrospective/{date}-{milestone}.md § "Type 분포">
    cumulative_log: <devos/PROJECT_STATE.md § "milestone Type 누적">
```

baseline 부재 시 (첫 milestone) `follow_up_ticket_ratio: n/a — first milestone` 로 명시. 누적 2 milestone 부터 비교 가능.

## Step 5: Save plan for approval
```
devos/plans/pending/{YYYY-MM-DD}-{slug}.yaml
```
Recommended naming: `filename = {date}-{id}.yaml`, where `{id}` is the plan
YAML `id:` value. This keeps both `make approve P={id}` and
`make approve P={date}-{id}` intuitive.

For large plans, split the readable plan metadata from ticket bodies:
```
devos/plans/pending/{YYYY-MM-DD}-{slug}.yaml
devos/plans/pending/{YYYY-MM-DD}-{slug}-tickets.yaml
```
When using split mode, omit the `tickets:` key from the main plan file. Put the
full ticket list under `tickets:` in the sibling `-tickets.yaml` file. Approval
resolution order is: main plan `tickets:` key, sibling `-tickets.yaml`, then
`{plan-id}/tickets/*.yaml`.

Wait for user approval before writing to `devos/tasks/QUEUE.yaml`.

## Anti-patterns
- DOD too vague ("works properly", "error handled appropriately") — always `input → expected output`
- Ticket with code-level instructions — you write WHAT + CONTEXT, builders decide HOW
- Success-case DOD without matching error-case DOD — always mandatory pair
- Writing implementation ourselves "because it's quick" — never. Create a ticket.
- **PRD intake checklist 건너뛰기** — Step 0 의무. happy path만으로 ticket 분해 금지.
- **Designer review 건너뛰기** — Step 0.6 의무 (UI 없는 백엔드 ticket 만 skip). UI/UX 누락이 빌더 단계까지 흘러가면 후속 ticket 폭증.
- **금지어 침투** — Step 4 자가 검사 의무. "v1으로 일단" 같은 표현이 ticket에 들어가면 영구 부채.
- **mode 누락** — Step 2.5 의무. 분해 산출 ticket 에 `mode` 없으면 게이트가 무게대로 동작 못 함 (즉석 잡 ticket 만 면제). production 적격이 아닌데 production 으로 달면 채울 수 없는 필수필드에 막힘 — 신호표대로 분류.

## 참조
- `devos/ETHOS.md`
- `devos/prompts/common/scope-reduction-prohibition.md`
- `devos/prompts/claude/prd-intake-checklist.md`
- `devos/prompts/claude/designer-review.md`
- `devos/prompts/claude/security-audit.md` (Week 2)

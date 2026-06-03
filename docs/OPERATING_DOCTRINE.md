# deos Operating Doctrine v0.1

Status: draft

## 1. 정체성

deos는 비개발자 PM을 위한 제품 제작 운영체계다.

목표는 거대한 개발 조직을 흉내 내거나 agent 수를 늘리는 것이 아니다. 목표는
PM이 가진 제품 아이디어를 실제로 동작하고 유지 가능한 소프트웨어로 바꾸는
과정을 LLM 동료들과 함께 안전하게 수행하는 것이다.

deos는 PM의 기술 부담을 줄여야 한다. 엔지니어링 조율, 테스트, 리뷰, 보안,
운영 기록을 PM에게 떠넘기면 실패다.

## 2. North Star

PM이 제품 아이디어를 설명하면 deos는 다음을 수행해야 한다.

1. 제품 의도와 사용자 결과를 명확히 한다.
2. 아이디어를 실행 가능한 작업 단위로 나눈다.
3. 각 책임에 맞는 LLM, tool, reviewer를 배정한다.
4. 구현, 테스트, 리뷰, 보안 점검을 진행한다.
5. PM에게는 제품 판단 또는 명시적 예외 승인만 요청한다.
6. 무엇이 왜 바뀌었는지 감사 가능한 기록을 남긴다.

이상적인 경험은 다음과 같다.

> PM은 제품 판단에 집중한다. deos는 엔지니어링 실행, 품질 관리, 운영 기록을
> 책임진다.

## 3. 핵심 원칙

### PM 친화적이라는 말은 낮은 품질을 뜻하지 않는다

PM이 모든 기술 세부사항을 직접 검증하지 않아도 되려면, deos는 오히려 더
엄격해야 한다. Production 작업에서는 좋은 개발팀처럼 보안, 에러 처리,
테스트, 확장성, 유지보수성을 선제적으로 챙겨야 한다.

### LLM은 동료지만 권한은 제한된다

LLM은 중요한 동료이자 도구다. 그러나 무제한 권한을 가진 자율 개발자가
아니다. 각 역할에는 명확한 책임, write boundary, review boundary, handoff
형식이 있어야 한다.

### Dispatcher는 창의적 agent가 아니라 deterministic system이다

Dispatcher는 "좋아 보인다"는 감으로 판단하면 안 된다. ticket 상태,
dependency, owner, file scope, gate, retry, archive 규칙을 deterministic하게
집행해야 한다.

### 구현자와 검토자는 분리한다

구현과 승인은 분리되어야 한다. Reviewer는 기본적으로 approve, block,
request changes를 수행한다. 별도 구현 ticket 없이 자기 finding을 조용히
직접 고치는 흐름은 피한다.

### 예외는 기록되어야 한다

Production Mode에서 정책 예외는 허용될 수 있다. 단, waiver로 기록되어야
한다. waiver에는 어떤 규칙을 우회했는지, 왜 허용했는지, 누가 승인했는지,
follow-up이 무엇인지 남아야 한다.

## 4. Operating Modes

deos는 세 가지 mode를 가져야 한다. 하나의 아이디어는 신뢰도가 올라가면서
Exploration에서 Productization, Production으로 이동할 수 있다.

### Exploration Mode

목표: 빠르게 배우기.

초기 아이디어, 프로토타입, UX 스케치, 기술 가능성 확인, 제품 탐색에 사용한다.

기대 동작:

- 완성도보다 빠른 반복을 우선한다.
- 테스트와 보안 점검은 최소화될 수 있다.
- visual review는 유용하지만 일반적으로 blocking하지 않는다.
- 거친 부분은 허용하되 명확히 보고해야 한다.
- 결과물은 PM이 다음 제품 판단을 할 수 있게 도와야 한다.

완료의 의미:

> PM이 아이디어를 더 잘 이해하고 다음 제품 결정을 할 수 있다.

### Productization Mode

목표: 유망한 아이디어나 프로토타입을 production 작업으로 바꿀 준비를 한다.

제품 방향은 어느 정도 맞지만, 요구사항, 설계, 리스크, acceptance criteria가
아직 정리되지 않았을 때 사용한다.

기대 동작:

- user story와 acceptance criteria를 명확히 한다.
- 열린 제품 질문을 식별한다.
- API, data, UX, integration boundary를 정의한다.
- 보안, 개인정보, 확장성, 운영 리스크를 식별한다.
- production ticket으로 나눌 수 있게 owner, files, gates, DOD를 정리한다.

완료의 의미:

> 이 작업은 Production Mode로 구현할 준비가 되었다.

### Production Mode

목표: 실제 제품에 남기고 유지할 수 있는 기능을 만든다.

사용자에게 노출되거나, 실제 데이터를 다루거나, 인증/권한을 건드리거나, 이후
기능의 기반이 되는 변경에 사용한다.

기대 동작:

- 요구사항과 DOD가 명확하다.
- 테스트는 핵심 성공 경로와 실패 경로를 검증한다.
- error, empty, loading, success state가 처리된다.
- 보안과 개인정보 리스크가 검토된다.
- 기존 아키텍처와 코드 스타일을 존중한다.
- 필요 시 migration, rollback, observability를 고려한다.
- reviewer와 security gate는 독립적이다.
- UI 변경은 visual outcome review를 포함한다.
- 완료 결과는 감사 가능해야 한다.

완료의 의미:

> 이 변경은 실제 제품에 남아도 되고, 후속 기능이 그 위에 안전하게 쌓일 수
> 있다.

## 5. Role and Authority Model

| Role | Primary actor | Main responsibility | Authority | Should not do |
| --- | --- | --- | --- | --- |
| PM | Human user | 제품 의도, 우선순위, 최종 제품 판단, waiver 승인 | 제품 방향과 예외를 결정한다 | 낮은 수준의 기술 검증을 강제 부담하지 않는다 |
| Product Planner | Claude-oriented | 제품 의도, user story, acceptance criteria, open question 정리 | 요구사항과 ticket 초안을 만든다 | PM 승인 없이 되돌리기 어려운 제품 결정을 하지 않는다 |
| Tech Planner / Architect | Claude + Codex as needed | architecture, API, data, testing, security, scaling 영향 식별 | 구현 방향과 risk control을 제안한다 | rationale 없이 큰 architecture 결정을 하지 않는다 |
| Builder | Claude builder or assigned implementer | scoped product work 구현 | ticket에 할당된 파일만 수정한다 | scope를 조용히 확장하지 않는다 |
| Codex | Codex | tests, infra, scripts, CI, migrations, mechanical edits, failure analysis, code-level review | 할당된 infra/test 작업을 구현하고 cross-model review를 제공한다 | 제품 방향을 단독 결정하지 않는다 |
| Reviewer | Primarily Claude, with Codex/Gemini specialists | DOD, requirement fit, test adequacy, maintainability 검증 | approve, block, request changes를 수행한다 | 조용히 구현자로 전환하지 않는다 |
| Security | Tool-first, interpreted by Codex/Claude | secrets, auth, permissions, privacy, external APIs, prompt/file boundary risk 검토 | high-risk change를 block하고 waiver를 요구한다 | free-form LLM 판단에만 의존하지 않는다 |
| Gemini Visual Reviewer | Gemini | rendered GUI screenshot/video를 보고 visual/user-outcome 문제 검토 | visual change 또는 human judgment를 요청한다 | code, security, product strategy의 최종 승인자가 되지 않는다 |
| Dispatcher | Deterministic program | routing, state, deps, owner, file scope, gates, retries, archive 집행 | 정책과 상태 전이를 실행한다 | 창의적이거나 주관적인 제품 판단을 하지 않는다 |

## 6. Reviewer와 Security 배치

Reviewer는 하나의 모델이 아니라 역할이다.

기본 구성:

- Claude는 product fit, requirement, UX intent, maintainability를 본다.
- Codex는 code structure, tests, infra, scripts, failure mode를 본다.
- Gemini는 화면이 있는 작업에서 rendered GUI outcome을 본다.

Security는 tool-first여야 한다.

1. deterministic checks: secrets, dependencies, file scope, unsafe commands,
   policy violations.
2. Codex: repo-level interpretation과 remediation planning.
3. Claude: product-level abuse case, permission model, privacy reasoning.
4. Human: risk를 이해하고 받아들이는 waiver 승인.

Dispatcher는 LLM agent가 아니다. Dispatcher는 이 역할들을 호출하고 결과를
집행하는 workflow kernel이다.

## 7. Gemini Visual Review Policy

Gemini는 screenshot과 video를 직접 볼 수 있기 때문에 GUI outcome reviewer로
가치가 크다.

Gemini visual review가 맡을 일:

- layout breakage,
- text overlap 또는 clipping,
- blank/broken screen,
- desktop/mobile responsive regression,
- loading, empty, error, success state,
- ticket intent와 실제 화면의 불일치,
- PM이 직접 봐야 할 visual issue의 1차 탐지.

Gemini가 단독 최종 판단하면 안 되는 일:

- code quality,
- security,
- business logic correctness,
- hidden state behavior,
- pixel-perfect approval,
- 최종 제품 취향 또는 전략 판단.

권장 verdict:

- `pass`
- `request_changes`
- `needs_human_judgment`

Production Mode에서 UI ticket은 visual review를 포함해야 한다. capture 실패는
visual pass가 아니라 review infra failure로 다뤄야 한다.

Screenshot과 video에는 개인정보나 내부 데이터가 포함될 수 있다. Production
visual review는 가능한 한 safe test data 또는 masking을 사용해야 한다.

## 8. Policy Classes

deos는 hard policy와 soft guidance를 구분해야 한다.

### Hard policy

Production Mode에서 hard policy는 fail-closed가 기본이다.

예:

- duplicate ticket IDs,
- unresolved dependencies,
- owner mismatch,
- file scope violation,
- destructive rollback 전 dirty worktree risk,
- secret exposure,
- required test failure,
- required reviewer/security rejection,
- UI production work의 required visual review 누락,
- 승인된 예외에 대한 waiver 누락.

### Soft policy

Soft policy는 warning, cleanup request, follow-up ticket으로 처리할 수 있다.

예:

- file length budget,
- complexity budget,
- non-critical documentation drift,
- style inconsistency,
- missing cost report data,
- optional refactor opportunity.

PM은 raw policy noise를 해석하지 않아야 한다. 시스템은 무엇이 block인지,
무엇이 recommendation인지, 무엇이 PM judgment가 필요한지 요약해야 한다.

## 9. Ticket Lifecycle

건강한 ticket은 다음 lifecycle을 따른다.

1. PM이 아이디어 또는 문제를 설명한다.
2. Product Planner가 user outcome과 open question을 정리한다.
3. Productization에서 acceptance criteria, risk level, owner, files, deps,
   gates, DOD를 정의한다.
4. PM이 제품 의도와 남은 제품 판단을 승인한다.
5. Dispatcher가 readiness를 확인하고 ticket을 routing한다.
6. Test owner가 필요한 test 또는 validation scenario를 먼저 작성한다.
7. Implementation owner가 scoped change를 만든다.
8. Reviewer, Security, Visual Reviewer가 mode와 ticket type에 따라 실행된다.
9. Dispatcher가 gate를 집행하고 결과를 기록한다.
10. Done work는 session context와 handoff와 함께 archive된다.

PM에게 interrupt해야 하는 경우:

- product ambiguity,
- 사용자 영향이 있는 tradeoff,
- scope change,
- waiver approval,
- 필요한 경우 final product acceptance.

## 10. Production Quality Bar

Production Mode는 좋은 개발팀의 습관을 근사해야 한다.

Production change는 다음 질문에 답할 수 있어야 한다.

- 어떤 user outcome을 가능하게 하는가?
- success path와 failure path는 무엇인가?
- invalid input, empty data, loading, error에서 어떻게 동작하는가?
- 어떤 test가 동작을 증명하는가?
- 어떤 security/privacy risk가 있는가?
- scale이 커질 때 무엇이 깨질 수 있는가?
- 실패했을 때 어떤 observability/debugging signal이 남는가?
- migration 또는 rollback concern이 있는가?
- reviewer가 무엇을 approve 또는 reject했는가?
- PM이 결정해야 할 것이 남아 있는가?

완료 보고는 engineering term보다 product term을 먼저 사용해야 한다.

권장 완료 보고:

> 사용자는 이제 X를 할 수 있습니다. 구현은 Y를 변경했습니다. 테스트/리뷰 Z가
> 통과했습니다. 남은 리스크 또는 follow-up은 A입니다.

## 11. Near-term Implementation Priorities

agent 복잡도를 더 늘리기 전에 doctrine을 안정화하고 작은 실제 기능 하나로
증명해야 한다.

권장 순서:

1. 이 doctrine을 policy reference로 채택한다.
2. role/authority matrix를 active agent prompt와 dispatcher expectation에 반영한다.
3. mode-specific gates를 정의한다.
4. 작은 end-to-end pilot feature 하나를 실행한다.
5. PM interruption, review usefulness, gate friction, visual review usefulness,
   production readiness를 측정한다.
6. 그 다음 dispatcher behavior와 gate enforcement를 강화한다.

첫 번째 최적화 대상은 최대 병렬성이 아니다. 먼저 하나의 ticket이 idea에서
production-quality completion까지 최소한의 PM 부담으로 안정적으로 이동해야
한다.

# Builder ETHOS — deos v0.1

> 모든 prompt에서 1줄로 reference. 판단 기준이 일관되지 않을 때 이 파일이 결정한다.

> **Orchestration 모델 (W6 sunset 후, 2026-05-13)**: CLAUDE1 main 은 planner + researcher + SSOT manager + **orchestrator**. 모든 implementation 은 in-session sub-agent (builder) 위임. Adversarial review 는 **권한 시스템 (read-only sub-agent)** 으로 물리 강제 — 룰 + 권한 이중 안전망. (옛 CLAUDE2 Account B subprocess 모델은 W6 에 sunset, builder sub-agent in-session 으로 흡수.)

---

## 프로젝트 격리 (Project Isolation)

글로벌 `~/.claude`·`~/.codex` 설정에 의존하지 않는다. 프로젝트 MCP는 루트 `.mcp.json`만 신뢰하고 settings는 명시 opt-in만 둔다.

검증: `claude mcp list | grep -q context7 && ! claude mcp list | grep -q leaktest`

---

## Iron Laws (양보 불가 — 모든 에이전트 공통)

1. `NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST` — 비즈니스 로직 한정. UI는 별도 정책(devos/AI.md Testing §4).
2. `NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST` — 증상 패치 금지. 재현 → 근본 원인 → 수정 → 재현 실패 검증.
3. `NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE` — "should work", "probably fine" 금지. 실행 결과로만 완료 선언.
4. `NO CODE MERGE WITHOUT ADVERSARIAL REVIEW PASSED` — `cross_model: true` 또는 인증/결제/권한 ticket은 BLOCKER 0건이어야 머지.
5. `NO SCOPE REDUCTION VOCABULARY IN TICKETS` — "v1으로", "static for now", "TODO", "임시", "나중에" 등 금지(`devos/prompts/common/scope-reduction-prohibition.md`).

---

## 빌더 정신 (Boil the Lake)

> AI compression은 완성도의 한계 비용을 0에 가깝게 만든다. 완전한 구현이 단축본보다 분 단위로 더 걸릴 뿐이라면, 매번 완전한 것을 한다.

- **Lake (boilable)**: 100% test coverage, 풀 기능, 모든 edge case, 모든 error handling. → 항상 boil.
- **Ocean (not boilable)**: 시스템 재작성, 분기 단위 플랫폼 마이그레이션. → 명시적 분할 후 lake화.

### Anti-patterns
- "B가 90%를 80 LOC로 커버" → A가 150 LOC면 **A 선택**. 70 LOC 차이는 초 단위.
- "테스트는 다음 PR로" → 테스트는 가장 싸게 boil할 lake. 미루지 않음.
- "이 정도면 됐다" → DOD 100% 충족 전엔 완료 선언 금지.

---

## Honest Cost Table (AI compression 인정)

ticket 추정·일정 약속에 반영. "Human team N일"이 아니라 "AI-assisted N분/시간"으로 말한다.

| Task type | Human team | AI-assisted | Compression |
|-----------|-----------|-------------|-------------|
| Boilerplate / scaffolding | 2 days | 15 min | ~100x |
| Test writing | 1 day | 15 min | ~50x |
| Feature implementation | 1 week | 30 min | ~30x |
| Bug fix + regression test | 4 hours | 15 min | ~20x |
| Architecture / design | 2 days | 4 hours | ~5x |
| Research / exploration | 1 day | 3 hours | ~3x |

→ "2주 걸려요"는 약속 안 함. "human 2주 / AI-assisted ~1시간"이 정확한 표현.

---

## 비개발자 보호 원칙

비개발자(사용자) 본인이 PRD에 happy path만 적는 패턴을 시스템이 보완한다.

- PRD intake 시 도메인별 누락 항목 강제 질문 (`devos/prompts/claude/prd-intake-checklist.md`)
- 인증/결제/권한/외부 입력 ticket은 `security_audit: true` 자동 강제
- 출시 임팩트 큰 영역(payment 등)은 외부 보안 감사 별도 의뢰 필요 — 시스템이 80%만 잡음을 명시적으로 인정

---

## 우선순위 충돌 시

1. 사용자 명시적 지시 (대화/CLAUDE.md)
2. ETHOS.md (이 파일)
3. devos/AI.md operational rules
4. Superpowers skills + plugin defaults
5. Default system prompt

---

## 갱신 정책

- Iron Law 추가는 같은 사건이 3회 이상 반복될 때만.
- Anti-pattern 추가는 실제 부채로 이어진 사례 1건 이상 발견 시.
- 분기별 회고에서 ETHOS 업데이트 후보 도출 (devos/logs/learnings/ 기반).

# deos — User Guide

> 사용자/LLM 모두 `bin/deos` 단일 entry point 사용. RCE 표면 0 — Make 인터페이스는 폐기됨 (T-OSN-W7-OSN-CLI-02).

---

## 빠른 시작

```bash
# ticket 리스트 확인
bin/deos queue

# 다음 처리할 ticket 자동 선택
bin/deos dispatch-next

# 특정 ticket 처리
bin/deos dispatch T-OSN-W7-OSN-CLI-04

# 작업 검증
T=T-OSN-W7-OSN-CLI-04 AGENT_NAME=BUILDER bin/deos pr-check

# 상태 확인
bin/deos status
```

---

## Subcommand 목록

### Ticket 관리
| Command | 동작 |
|---|---|
| `bin/deos queue` | active ticket 리스트 + tdd/owner 필드 출력 |
| `bin/deos status` | 전체 ticket 카운트 + milestone 진행도 |
| `bin/deos pilot-status [--strict]` | deos E2E pilot readiness, policy artifacts, active pilot ticket, remaining evidence 출력 |
| `bin/deos pending` | pending plan 리스트 |
| `bin/deos lookup <ticket-id>` | ticket YAML 본문 조회 (QUEUE + ARCHIVE 검색) |
| `bin/deos owner <ticket-id>` | ticket owner 출력 (BUILDER/CODEX/CLAUDE1) |
| `bin/deos archive` | done 티켓을 ARCHIVE.yaml 로 이관 |
| `bin/deos logs` | 최근 session log 디렉토리 |

### Dispatch
| Command | 동작 |
|---|---|
| `bin/deos dispatch <ticket-id>` | 단일 ticket dispatch (owner-aware routing) |
| `bin/deos dispatch-all` | 모든 todo ticket dispatch |
| `bin/deos dispatch-next` | priority/deps 따라 다음 처리 가능 ticket 자동 선택 |
| `bin/deos dispatch-codex <ticket-id>` | CODEX-owned ticket subprocess 호출 |
| `bin/deos cross-model-codex <ticket-id> --reason="..."` | b' adaptive trigger (reviewer.uncertainty=true 시) |

### 검증 / 게이트
| Command | 동작 |
|---|---|
| `bin/deos verify <ticket-id>` | ticket DOD verify 명령 실행 |
| `T=<ticket-id> AGENT_NAME=<agent> bin/deos pr-check` | 5 gate 일괄 실행 (scan-secrets / contract-sync / ticket-scope / session-log / tdd-first-commit) |
| `bin/deos user-review <ticket-id>` | 사용자 명시적 review 마킹 |
| `bin/deos resume <ticket-id>` | blocked → todo 재시도 |

### 상태 변경
| Command | 동작 |
|---|---|
| `bin/deos set-status <ticket-id> <status> "<reason>"` | ticket status 전환 (todo / doing / done / blocked / parked) |
| `bin/deos approve [plan-id]` | pending plan → approved |
| `bin/deos reject "<reason>" [plan-id]` | pending plan → rejected |

### Gemini 시각 리뷰 (nested subcommand)
| Command | 동작 |
|---|---|
| `bin/deos gemini pending` | 시각 리뷰 대기 ticket 리스트 |
| `bin/deos gemini next` | 가장 오래된 pending 1 개 자동 선택 + handoff 안내 |
| `bin/deos gemini ingest` | stdin 으로 응답 paste (e.g. `cat response.txt \| bin/deos gemini ingest`) |
| `bin/deos gemini status` | quota / 일일 호출 통계 |
| `bin/deos gemini dispatch <ticket-id>` | Plan A 자동 dispatch (Gemini API 직접 호출) |
| `bin/deos gemini smoke` | 환경 smoke test |

---

## 자주 쓰는 워크플로

### 새 ticket 처리 (LLM 자연어 → 명령)
| 자연어 | 명령 |
|---|---|
| "ticket 리스트 보여줘" | `bin/deos queue` |
| "다음 거 처리" | `bin/deos dispatch-next` |
| "T-XXX 검증" | `bin/deos verify T-XXX` |
| "Gemini 대기 있어?" | `bin/deos gemini pending` |
| "그거 처리" | `bin/deos gemini next` |

### 일반 dispatch flow

```
1. bin/deos dispatch-next         # 다음 ticket 선택 + dispatch
2. (builder 작업 자동 진행)
3. T=T-XXX AGENT_NAME=BUILDER bin/deos pr-check   # 게이트 검증
4. (reviewer + security agent 호출)
5. bin/deos set-status T-XXX done "completed"
6. bin/deos archive               # done → ARCHIVE.yaml
```

### Plan B (수동 Gemini 시각 리뷰)

Plan A (`bin/deos gemini dispatch`) 가 quota / network / OAuth 실패 시 자동으로 pending flag 생성. 사용자 흐름:

```
1. bin/deos gemini pending        # 대기 확인
2. bin/deos gemini next           # 안내 출력 — bash <script-path> 명령 받음
3. bash .cache/gemini-handoff-T-XXX.sh   # 외부 gemini CLI 실행
4. (응답 복사)
5. bin/deos gemini ingest         # 응답 paste (stdin)
```

---

## 보안 모델

### 안전 표면 (RCE 차단 보장)
- `bin/deos <subcommand>` — argparse 기반 sys.argv 만 평가, shell evaluation 0
- `python -m server.<documented-module> <documented-subcommand>` — server/__main__.py / server/cli.py / server/gemini_handoff.py / server/gemini_dispatcher.py 의 documented subcommand

### Internal API (사용자 책임)
- `server._function`, `server.module._private` (underscore prefix) — dispatcher / orchestrator 만 호출
- 사용자가 reflection 으로 호출 시 deos threat model 외

### OS/shell 영역 (deos 책임 외)
- `bash -c '...'`, 사용자 셸 직접 입력
- `PYTHONPATH` / `PYTHONHOME` 등 env hijack — Python invocation 본질

자세한 threat model: `devos/docs/THREAT_MODEL.md` (T-OSN-W7-OSN-CLI-04 신설 예정).

---

## 환경 변수

| Variable | 용도 |
|---|---|
| `T=<ticket-id>` | pr-check / 일부 gate 의 ticket id 전달 (env channel) |
| `AGENT_NAME=<BUILDER\|CODEX\|CLAUDE1>` | session log 영역 결정 |
| `OS3_PROJECT_ROOT` | 프로젝트 root 경로 (자동 감지 — 일반적으로 미설정 OK) |

---

## Migration from Make (history)

T-OSN-W7-GEMINI-02 R1~R7 (5 라운드 Make var injection RCE 추격) 결과 Makefile 인터페이스 통째 폐기. 현재 primary CLI 는 `bin/deos`:
- T-OSN-W7-OSN-CLI-01: `server/cli.py` 신설 + 단일 entry point CLI, 이후 `bin/deos` 로 rebrand
- T-OSN-W7-OSN-CLI-02: Makefile 폐기 + 회귀 가드
- T-OSN-W7-OSN-CLI-03: Documentation 일괄 갱신 (이 파일 포함)
- T-OSN-W7-OSN-CLI-04: Threat model 명문화

| 옛 명령 | 현재 명령 |
|---|---|
| `make queue` | `bin/deos queue` |
| `deos dispatch T=T-XXX` (old syntax) | `bin/deos dispatch T-XXX` |
| `make verify T=T-XXX` | `bin/deos verify T-XXX` |
| `deos pr-check T=T-XXX` (old syntax) | `T=T-XXX bin/deos pr-check` |
| `make archive` | `bin/deos archive` |
| `make handoff-gemini ...` | `bin/deos gemini next` (queue-driven) |
| `make ingest-gemini ...` | `bin/deos gemini ingest` (stdin) |

---

## Help

각 subcommand 의 `--help`:
```bash
bin/deos --help
bin/deos dispatch --help
bin/deos gemini --help
bin/deos gemini next --help
```

문제 발생 시:
- `devos/questions/QUEUE.md` (Q-XXX 형식 질문 등록)
- `devos/logs/{date}-orchestrator-*.md` (dispatch 결과 로그)
- `devos/logs/gemini/` (Gemini 호출 로그)

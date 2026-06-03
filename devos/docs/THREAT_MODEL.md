# deos — Threat Model

> Single source of truth for deos 의 보안 경계. T-OSN-W7-OSN-CLI-04 가 명문화.
> Reference incident: T-OSN-W7-GEMINI-02 R1~R7 (5 라운드 Make var injection RCE → safe CLI 일괄 전환).

---

## 1. Trust boundaries

### 1.1 안전 표면 (RCE / injection 차단 보장)
- `bin/deos <subcommand> [args]` — 모든 사용자/LLM 명령의 primary entry point
- (`bin/osn` 은 기존 자동화용 legacy alias — 현재 삭제됨)
- argparse 기반 sys.argv 만 평가. shell evaluation 0. Make 단계 부재.
- `python -m server.<documented-module> <documented-subcommand>` — internal CLI 와 동등
  - `server.cli` (`bin/deos` router)
  - `server.gemini_handoff` (pending / next / ingest-stdin)
  - `server.gemini_dispatcher` (status / dispatch / smoke)

**보안 약속**: documented 명령 사용 시 사용자가 어떤 인자/env 변수/stdin 데이터를 넘겨도 deos 인프라를 통한 RCE 는 발생하지 않는다.

### 1.2 Internal API (사용자 책임)
- `server._function`, `server.<module>._private` (underscore prefix)
- `server.dispatcher.Dispatcher.<method>` 등 class 내부 API
- 사용자가 reflection / direct import 로 호출 시 deos threat model 외 — **사용자 책임**

### 1.3 OS 영역 (deos 책임 외)
- `bash -c '...'`, 사용자 셸 직접 입력
- `PYTHONPATH` / `PYTHONHOME` / `_PYTHON_SYSCONFIGDATA_NAME` env hijack — Python invocation 본질
- 외부 도구 (`gemini`, `codex` CLI) 의 자체 보안
- multi-user shared 환경 (deos 는 single-user dev tool 가정)

---

## 2. 보호 대상

### 2.1 사용자 untrusted 데이터 처리
- ticket YAML (특히 외부 PRD 임포트 시 잠재적 untrusted)
- gemini 응답 (외부 LLM 출력)
- ingest paste (사용자가 외부 시스템에서 복사)
- 사용자 prompt / image path / ticket_id 등 user input

### 2.2 deos user-facing CLI 자체
- `bin/deos` primary CLI 의 모든 subcommand 가 다음 invariant 유지:
  - subprocess.run 호출 모두 list-form + shell=False
  - ticket_id 는 `^T-[A-Z0-9]+(-[A-Z0-9]+)*[a-z]?$` regex 통과 (server/_ticket_id.py SSOT)
  - PII redaction (sk-/ghp_/AKIA/Bearer/JWT/xoxb/glpat/ya29/AIza/npm_) 모든 disk 저장 로그에 적용
  - failures.jsonl + handoff/ingest/dispatch 로그 모두 .gitignore 등록

---

## 3. 보호 외 (명시적 미보장)

| 시나리오 | 누구 책임 |
|---|---|
| 사용자가 자기 셸에 destructive 명령 직접 입력 | 사용자 본인 (OS 영역) |
| `python -c 'from server._internal import ...'` 같은 reflection | 사용자 (documented 표면 외) |
| `PYTHONPATH=/tmp/evil python3 bin/deos ...` 같은 env hijack | 사용자 환경 (Python 본질) |
| gemini CLI 자체 vulnerability | 외부 도구 |
| codex CLI 자체 vulnerability | 외부 도구 |
| ticket YAML 자체에 악의적 데이터 (외부 PRD 임포트) | dispatcher 처리 — 별도 audit 필요 (PRD intake checklist) |

---

## 4. Audit cadence

- **6 개월** 마다 user-input handling code path retrospective
  - `server/cli.py`, `server/gemini_handoff.py`, `server/gemini_dispatcher.py` 변경 review
  - 신규 attack surface 발견 시 즉시 patch + 회귀 test
- **신규 cli subcommand 추가 시 PoC test 의무**
  - launcher regression tests (`tests/test_bin_deos_launcher.py`) 의 attack matrix (backtick / $(shell) / single-quote / dollar paren) 적용
  - PoC + variants 2+ rule (T-OSN-W7-GEMINI-02 회고)
- **Makefile 재추가 검증**
  - `tests/test_no_makefile.py` invariant 가드 — Makefile 부재 invariant
  - 우회 시도 (GNUmakefile / makefile 등) 도 차단

---

## 5. Reference incidents

### T-OSN-W7-GEMINI-02 R1~R7 (2026-05-06)
- 5 라운드 Make var injection RCE 추격
  - R1: CLI argv injection
  - R2: env-var assignment injection
  - R3: single-quote escape
  - R4: Make export directive
  - R5: Make builtin function (`$(shell ...)`)
- 결론: Make var → recursive expansion 자체가 attack surface. quoting 으로 차단 불가
- 해결: T-OSN-W7-OSN-CLI-01/02 — bin/osn 단일 entry point 채택, Makefile 통째 폐기
- 검증: host PoC 8/8 sentinel 0 (R1~R5 모든 vector + 3 variants)

자세한 history: `devos/logs/2026-05-06-builder-T-OSN-W7-GEMINI-02.md` (R1~R7), `devos/logs/2026-05-06-orchestrator-T-OSN-W7-GEMINI-01.md`.

---

## 6. 회귀 가드 invariants

다음 invariant 이 깨지면 즉시 fail (regression test 가 강제):
- `Makefile`, `makefile`, `GNUmakefile`, `BSDmakefile`, `Makefile.in`, `Makefile.am` 부재 (`tests/test_no_makefile.py`)
- `bin/deos` 의 모든 subcommand 가 attack input 받아도 sentinel 미생성 (launcher regression tests)
- `server/cli.py` + `bin/deos` 에 `shell=True` 또는 `os.system` 부재
- `server/gemini_handoff.py` + `server/gemini_dispatcher.py` 의 user-facing print/stderr 에 `make gemini-*` literal 부재 (`test_no_make_gemini_in_user_facing_strings`)
- `deos.yaml` config gates 에 `make ` 호출 부재
- `failures.jsonl` / handoff/ingest/dispatch 로그 모두 .gitignore 적용

---

## 7. 외부 audit 권장 조건

다음 중 하나 충족 시 외부 보안 감사 권장:
- multi-user / production deployment
- payment / PII at scale 처리 추가
- 외부 untrusted 사용자 입력 (예: webhook / API 노출)
- AI agent autonomy 확장 (사용자 confirmation 없이 destructive 동작)

현재 deos 는 **single-user dev tool** — 외부 audit 불필요.

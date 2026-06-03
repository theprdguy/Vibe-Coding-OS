# Project-Scoped pr-check & Sub-Agent Availability — Implementation Plan

> **Implementation path:** OS3 host-OS tickets (owner CODEX), dispatched in `~/dev-os`
> per Rule 1/10. This plan is the ticket bodies, in OS3 ticket schema (WHAT + CONTEXT;
> CODEX decides HOW — Rule 3). It is NOT superpowers code-step format, because the
> user-selected ticket path and OS3 convention take precedence over the skill default.

**Goal:** Make project quality gates and sub-agents scope to the project, not the host — closing the cross-project contamination that blocked `T-BOLLARD-CLIP-01`.

**Spec:** `docs/superpowers/specs/2026-05-27-project-scoped-gates-and-agents-design.md`

**Two independent tickets:** T-A (pr-check scoping) and T-B (project-session agents). No deps between them; dispatchable in parallel.

---

## Ticket T-A — `T-OS3-PRCHECK-PROJECT-SCOPE`

```yaml
- id: T-OS3-PRCHECK-PROJECT-SCOPE
  status: todo
  owner: CODEX
  impl_owner: CODEX
  test_owner: CODEX
  tdd: required
  security_audit: false
  cross_model: false
  skills_hint:
  - test-driven-development
  goal: |
    `os3 pr-check` (server/cli_gates.py:handle_pr_check) 를 프로젝트-스코프로 만든다.
    스캔 대상을 ambient Path.cwd() 가 아니라 명시적으로 해석한 project root 로 고정하고,
    secret 스캔이 커밋되지 않은 working tree 까지 커버하게 한다.
  context: |
    루트 코즈 (검증됨): handle_pr_check (server/cli_gates.py:17,25-29) 가
    `gitleaks git --no-banner --redact .` 를 cwd=Path.cwd() 로 돌리고 --project 를 무시한다.
    인터랙티브 세션은 Bash 호출마다 cwd 가 세션 베이스로 리셋되고 그 베이스가 host(~/dev-os)라,
    `os3 pr-check --project bollard` 가 host repo 를 스캔해 무관한 host finding
    (devos/questions/QUEUE.md:116, commit caf6d2c) 으로 FAIL 했다. 프로젝트(bollard)는
    별도 git repo + host 에서 gitignore + clean 인데 검사조차 안 됐다.
    - project root 해석 메커니즘: server/config.py:99 resolve_paths(project, cwd=...)
      (= cli.py:_load() 가 쓰는 것). --project 와 cwd 의 .os3.yaml 마커를 존중.
    - 부수: `gitleaks git .` 는 히스토리만 본다. 커밋 0 프로젝트는 공허 통과.
      gitleaks 8.30.1 은 `gitleaks dir <path>` (파일시스템/working-tree 스캔) 지원 확인됨.
    - check 스크립트(check-contract-sync/ticket-scope/session-log/tdd-first-commit.sh)는
      host(<host>/scripts/) 에 있고, 검사 대상 project root 를 명시적으로 받아야 한다(cwd 의존 금지).
    - 디스패처 게이트 경로는 이미 cwd=paths["root"] 로 pr-check 를 돌리므로(그 경로는 정상),
      standalone handle_pr_check 만 고치면 된다. host 자신의 pr-check(--project 없이 host 에서 실행)
      는 계속 host 를 스캔해야 한다(회귀 금지).
    - gitleaks dir 함정 (구현 시 반드시 처리 — 측정값 2026-05-27):
      (a) `gitleaks dir .` 를 host 에서 돌리면 host .gitignore 의 /projects/ 를 넘어 projects/meation/**
          (다른 프로젝트!) 까지 스캔해 7건 검출 → 또 다른 교차오염. dir 스캔은 반드시 resolved root 한정
          (host 일 때 nested projects/ 제외). 즉 dir 대상 경로를 resolved root 로 명시 고정.
      (b) `.gitleaksignore` 의 fingerprint 는 commit SHA 접두라 dir(no-git) 모드에는 매칭 안 됨.
          host 의 test fixture(tests/test_gemini_dispatcher.py: gitlab-pat 2, slack 1, generic 1 = 4건)는
          dir 모드에서 재검출됨. 이들은 `.gitleaks.toml` 의 [[allowlists]] paths/regexes (모드 무관) 로
          allowlist 해야 host 의 working-tree 게이트가 green 유지. (git 모드 history 는 이미 clean.)
      (c) 따라서 권장 구현 방향(HOW 는 CODEX 결정): 커밋 있는 root 는 git(history), 그리고 dir 은
          resolved root 로 스코프 + host fixture 를 .gitleaks.toml 로 mode-무관 allowlist. bollard 같은
          0-commit 프로젝트는 dir 이 working tree 를 커버.
  constraints: |
    - 프로젝트 미해석 시 비-제로 exit + 명확 메시지. 절대 조용히 host/ambient cwd 스캔으로 폴백하지 말 것.
    - host pr-check(--project 없음, host root 실행) 동작 보존.
    - 기존 baseline gate 스크립트 4종 유지.
    - 디스패처가 거는 pr-check 게이트 동작 회귀 없을 것.
  dod:
  - 'os3 pr-check --project <P> 를 host cwd 에서 실행해도 스캔 대상이 project root 다:
    host-only 파일에만 있는 더미 secret 은 P 의 pr-check 를 FAIL 시키지 않는다(exit 0).'
  - 'working-tree 스캔: project root 의 미커밋 파일에 심은 더미 secret 이 pr-check 를 FAIL(exit≠0)시킨다.'
  - '커밋 ≥1 인 프로젝트는 git 히스토리 스캔도 수행한다(히스토리의 더미 secret 도 검출).'
  - '프로젝트 미해석(--project 없음 + cwd 조상에 .os3.yaml 없음 + cwd 가 프로젝트 아님)일 때
    pr-check 가 비-제로 exit + 해석 실패 메시지 출력(host 스캔 안 함).'
  - 'verify: python3 -m pytest tests/test_prcheck_project_scope.py -v 가 신규 테스트 전부 pass.'
  - 'verify: 기존 baseline gate 회귀 없음 (bash tests/integration/test_baseline_gates.sh).'
  files:
  - server/cli_gates.py
  - tests/test_prcheck_project_scope.py
  verify: |
    python3 -m pytest tests/test_prcheck_project_scope.py -v
    bash tests/integration/test_baseline_gates.sh
  deps: []
  gates:
  - pr-check
```

---

## Ticket T-B — `T-OS3-PROJECT-SESSION-AGENTS`

```yaml
- id: T-OS3-PROJECT-SESSION-AGENTS
  status: todo
  owner: CODEX
  impl_owner: CODEX
  test_owner: CODEX
  tdd: required
  security_audit: false
  cross_model: false
  skills_hint:
  - test-driven-development
  goal: |
    프로젝트 세션(os3 open / 프로젝트 register)이 host sub-agents
    (builder/reviewer/designer/security)를 해석할 수 있게 한다. 그래야 인터랙티브 dispatch 의
    in-session Agent(subagent_type=...) 가 named agent 로 동작하고 general-purpose/Explore 대행이 사라진다.
  context: |
    증상: T-BOLLARD-CLIP-01 dispatch 가 builder→general-purpose, reviewer→Explore 로 대행.
    원인: builder/reviewer 는 in-session Agent 호출이다 (server/dispatcher.py:route_by_owner —
    BUILDER='in_session_message', CODEX 만 'subprocess_codex'). 인터랙티브 orchestrator 세션은
    os3 open 으로 기동되는데 server/launcher.py:30-40 build_open_command 가 --settings 만 주입하고
    agents 는 노출하지 않는다. 프로젝트는 별도 git repo 라 project-local .claude/agents/ 가 없어
    named agent 미해석 → 대행. (dispatcher CODEX subprocess 는 locus 아님 — CODEX 는 claude agent 미사용.)
    - 메커니즘 후보: (1) host 의 .claude/agents/*.md 를 프로젝트의 .claude/agents/ 로 symlink
      (meation 프로젝트에 symlinked agent 선례 있음, deterministic), (2) CLAUDE_CONFIG_DIR=<host>/.claude
      주입(부작용 큼 — credentials/todos/settings 통째 차용). 기본 권장은 (1) symlink.
    - host agents 위치: <host>/.claude/agents/{builder,reviewer,designer,security}.md
    - reviewer 는 read-only tool allowlist 유지가 필수(Rule 7 객관성).
  constraints: |
    - 첫 스텝은 spike: 선택한 메커니즘으로 project-cwd 세션에서 Agent(subagent_type="builder")/reviewer 가
      실제 해석되는지 확인. symlink 로 안 되면 CLAUDE_CONFIG_DIR 로 폴백하고 그 사유를 티켓 로그에 기록.
    - build_open_command 의 기존 동작(--settings 주입, --print) 보존. idempotent.
    - agent 파일을 프로젝트 git 에 커밋하지 말 것(symlink, 그리고 프로젝트가 추적하지 않도록).
    - reviewer read-only allowlist 보존.
  dod:
  - 'spike 결과를 티켓 로그에 기록: 어떤 메커니즘이 project-cwd 세션에서 named agent 해석을 가능케 하는지.'
  - 'os3 open <P> (또는 register) 후 프로젝트 세션에서 named builder/reviewer 가 해석된다
    (general-purpose/Explore 대행 아님). 자동 검증 가능한 형태로: build_open_command(또는 register)
    가 project .claude/agents/ 에 host agent 4종을 노출(symlink)하고, 그 경로가 존재함을 단위테스트가 확인.'
  - 'reviewer agent 의 tool allowlist 가 read-only 로 유지됨(노출된 정의가 host 원본과 동일).'
  - 'verify: python3 -m pytest tests/test_launcher.py -v 가 신규 + 기존 테스트 pass.'
  files:
  - server/launcher.py
  - tests/test_launcher.py
  verify: |
    python3 -m pytest tests/test_launcher.py -v
  deps: []
  gates:
  - pr-check
```

---

## Self-Review

**Spec coverage:** Unit A → T-A (pr-check scoping + working-tree `gitleaks dir` + git-history when commits exist + fail-fast on unresolved + scripts from host against project). Unit B → T-B (launcher/register exposes host agents, symlink preferred, spike first, reviewer read-only). Host hygiene = separate companion (below), not a ticket. Out-of-scope items (token rotation, standalone `secrets` gate) excluded. Covered.

**Placeholder scan:** No TBD/TODO. DODs are input→output verifiable. Spike is a defined first step with a defined fallback, not a placeholder.

**Type consistency:** Ticket IDs, file paths (`server/cli_gates.py`, `server/launcher.py`, `tests/test_prcheck_project_scope.py`, `tests/test_launcher.py`) consistent between goal/context/dod/files/verify. Resolution function name `resolve_paths` and gitleaks subcommands (`git`, `dir`) consistent with verified facts.

## Execution

These are OS3 tickets, so execution is OS3 dispatch (not subagent-driven/inline superpowers execution):
1. Append T-A and T-B to `~/dev-os/devos/tasks/QUEUE.yaml` (status: todo).
2. Dispatch each (owner CODEX → `os3 dispatch <id>` / CODEX subprocess) from a `~/dev-os` context.
3. Post-build: reviewer chain + gates per the 7-step dispatch protocol.

## Companion (separate, non-blocking host hygiene)

After T-A lands, host false-positive no longer blocks projects. Clean host (user choice: allowlist + placeholder, no rotation): `.gitleaksignore` git-fingerprint `caf6d2cc:devos/questions/QUEUE.md:slack-legacy-workspace-token:116` **plus** replace the dummy token in `devos/questions/QUEUE.md` with a placeholder (placeholder required once `gitleaks dir` working-tree scanning exists). CLAUDE1-direct config edit.

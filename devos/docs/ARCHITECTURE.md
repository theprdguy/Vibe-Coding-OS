# Architecture (deos v0.1)

## System Overview

deos is a product-building operating system that turns PM product intent into scoped, tested, reviewed, secure, and auditable software work with bounded LLM collaborators.

```
┌─────────────────────────────────────────┐
│            devos/ (SSOT Brain)           │
│  QUEUE.yaml, PROJECT_STATE.md, logs/     │
│  plans/, questions/, docs/               │
└──────────┬──────────────────┬────────────┘
           │                  │
┌──────────▼──────┐  ┌───────▼───────────────┐
│ Local Mode       │  │ Remote Mode            │
│ Claude Code CLI  │  │ server/                │
│ (interactive)    │  │ • Telegram bot         │
│ Account A        │  │ • claude -p pipe mode  │
│                  │  │ • Status queries       │
└──────────┬───────┘  └───────┬───────────────┘
           └─────────┬─────────┘
                     │ Dispatch
         ┌───────────┴───────────┐
         ▼                       ▼
    Builder sub-agent          Codex
    (in-session)              (platform)
    App / UI work             subprocess
```

## Component Descriptions

### devos/ (The Brain)
All SSOT state lives here. Stack-agnostic. Never in the app code.

| File | Purpose |
|------|---------|
| `AI.md` | Shared operating constitution for all agents |
| `PROJECT_STATE.md` | Current milestone, agent status, blockers |
| `CONTEXT.md` | TL;DR updated each session |
| `TASKS.md` | Human-readable task board |
| `tasks/QUEUE.yaml` | Machine-readable ticket queue |
| `plans/pending/` | Plans awaiting approval |
| `plans/approved/` | Approved plans (archive) |
| `plans/rejected/` | Rejected plans with feedback |
| `logs/` | Session logs for cross-agent context |
| `questions/QUEUE.md` | Async question queue |
| `docs/` | API/UI contracts, ADRs, architecture |

### deos server (The Nervous System)
Always-running Python process. Handles TG + dispatch.

| Module | Purpose |
|--------|---------|
| `telegram.py` | TG bot handlers |
| `planner.py` | `claude -p` pipe mode wrapper |
| `dispatcher.py` | owner routing, policy gates, state transitions |
| `ssot.py` | SSOT file readers/writers |
| `approval.py` | Approval workflow state machine |
| `config.py` | Load `deos.yaml` config (`osn.yaml` removed) |

### Agents

| Agent | Mode | Config | Scope |
|-------|------|--------|-------|
| CLAUDE1 main | interactive | .claude/CLAUDE.md | devos/, .claude/, AGENTS.md, deos.yaml, server/ (bootstrap 한시) |
| builder (sub) | in-session via Agent tool | .claude/agents/builder.md (sonnet) | apps/api/src/**, apps/web/**, packages/shared/** |
| reviewer / designer / security (sub) | in-session, READ-ONLY | .claude/agents/{name}.md | (no write — review only) |
| Codex | external CLI subprocess | AGENTS.md | apps/web/** (shared, mechanical), apps/api/**, packages/**, infra/**, scripts/**, tests/**, styles/** |

## Key Design Decisions

### File-based SSOT
All inter-agent communication is through files in devos/.
No shared memory, no RPC. The repo IS the communication channel.

### Dual-mode Claude 1
Local: interactive Claude Code CLI (primary path)
Remote: deos server invokes `claude -p` for each TG request
Both modes share the same devos/ state.

### Approval Workflow
PRD → plan → user approval → dispatch. No auto-execution.
Plans saved to plans/pending/, moved to approved/ or rejected/.

### In-session sub-agent (deos v0.1)
builder/reviewer/designer/security 는 CLAUDE1 main 안에서 `Agent(subagent_type=...)` 로 spawn.
own context window — main conversation history 미상속. fresh context per invocation = no degradation.
~~Account B credentials via `CLAUDE_CONFIG_DIR=.claude-b`~~ — sunset 2026-05-13 (W6 완료).

### Shared Scope (apps/web/**)
Both builder sub-agent and CODEX can modify `apps/web/**`.
Ticket `files:` field enforces exclusive ownership per task.
builder: design judgment, component architecture, UX flow.
CODEX: bulk renames, pattern replacements, large mechanical edits.

### Token Efficiency
- Most TG queries answered by file parsing (no LLM call)
- LLM only invoked for planning and complex queries
- Claude 1 pipe mode = zero idle tokens

## Testing Pipeline

Target maturity: **Phase 3.5** (contract tests + UI smoke + scenario integration).
Full policy in `devos/AI.md` "Testing Policy" section.

### Gate Flow (`bin/deos pr-check`)

```
commit / PR
    │
    ▼
┌─────────────────────────────────────────────────┐
│            Common Baseline Gates                 │
│  (stack-agnostic, applied to every ticket)       │
│                                                   │
│  1. Secret scan (gitleaks)                       │
│  2. Contract sync check                          │
│     (contract doc ↔ code co-modification)        │
│  3. Ticket scope guard                           │
│     (modified files must be in ticket.files)     │
│  4. Session log presence check                   │
│  5. TDD first-commit gate                        │
│     (only for tdd: required tickets)             │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│           Stack-specific Gates                   │
│  (added per-app by the first ticket for it)     │
│                                                   │
│  • Test runner (pytest / Vitest / Playwright)    │
│  • Coverage (Line 70% / Branch 60%)              │
│  • Ticket verify command                         │
└────────────────┬────────────────────────────────┘
                 │
            PASS ▼ FAIL → block merge
          ready to merge
```

### Ownership Model for Test Work

| Ticket type | `tdd` | `test_owner` | `impl_owner` | Flow |
|-------------|-------|--------------|--------------|------|
| Logic (`apps/api/**`, `packages/shared/**`) | `required` | CODEX | builder | Cross-test: CODEX commits failing tests → builder implements |
| UI (`apps/web/**`) | `skip` | builder | builder | Builder self-tests UI unless the ticket explicitly assigns CODEX as test owner |
| Infra / tooling | `required` | CODEX | CODEX | Single-owner: CODEX writes test scenarios + impl |
| Docs / policy | `skip` | n/a | CLAUDE1 | Interactive: Claude 1 executes directly (not via subprocess dispatcher) |

The ticket schema supports `test_owner` and `impl_owner` as optional fields.
When missing, both default to `owner` (backward compatibility).

### Coverage Grace Period

Each app (subdirectory under `apps/`) gets a **3-ticket grace period** before
the coverage gate starts enforcing thresholds. During grace period, coverage
is reported but does not block merges. This prevents the first ticket from
bearing the full burden of bootstrapping test coverage from zero.

### Mutation Testing (Out-of-band)

Mutation tests are **not** on the PR gate path. They run on-demand when Claude 1
identifies quality-gap signals (see AI.md Testing Policy §6). Runs are scheduled
via `at 02:00` on the active laptop, with reports written to
`devos/logs/mutation/{date}.md` for next-session review.

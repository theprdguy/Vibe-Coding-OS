# Architecture (os2 v3.1)

## System Overview

os2 is a 3-agent Agentic Coding OS that orchestrates AI agents from a single laptop.

```
┌─────────────────────────────────────────┐
│            devos/ (SSOT Brain)           │
│  QUEUE.yaml, PROJECT_STATE.md, logs/     │
│  plans/, questions/, docs/               │
└──────────┬──────────────────┬────────────┘
           │                  │
┌──────────▼──────┐  ┌───────▼───────────────┐
│ Local Mode       │  │ Remote Mode            │
│ Claude Code CLI  │  │ os2-server.py          │
│ (interactive)    │  │ • Telegram bot         │
│ Account A        │  │ • claude -p pipe mode  │
│                  │  │ • Status queries       │
└──────────┬───────┘  └───────┬───────────────┘
           └─────────┬─────────┘
                     │ Dispatch
         ┌───────────┴───────────┐
         ▼                       ▼
    Claude 2                   Codex
    (Account B)              (Platform)
    App (Backend + GUI)      subprocess
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
| `agents/registry.yaml` | 3-agent registry with scopes |
| `tasks/QUEUE.yaml` | Machine-readable ticket queue |
| `plans/pending/` | Plans awaiting approval |
| `plans/approved/` | Approved plans (archive) |
| `plans/rejected/` | Rejected plans with feedback |
| `logs/` | Session logs for cross-agent context |
| `questions/QUEUE.md` | Async question queue |
| `docs/` | API/UI contracts, ADRs, architecture |

### os2-server (The Nervous System)
Always-running Python process. Handles TG + dispatch.

| Module | Purpose |
|--------|---------|
| `telegram.py` | TG bot handlers |
| `planner.py` | `claude -p` pipe mode wrapper |
| `dispatcher.py` | 3-agent dispatch (replaces Linker) |
| `ssot.py` | SSOT file readers/writers |
| `approval.py` | Approval workflow state machine |
| `config.py` | Load os2.yaml |

### Agents

| Agent | Mode | Config | Scope |
|-------|------|--------|-------|
| Claude 1 | interactive + pipe | .claude/ | devos/ |
| Claude 2 | subprocess (claude -p) | .claude-b/ | apps/api/src/**, apps/web/** (shared, design-heavy) |
| Codex | subprocess | AGENTS.md | apps/web/** (shared, mechanical), apps/api/**, packages/**, infra/**, scripts/**, tests/**, styles/** |

## Key Design Decisions

### File-based SSOT
All inter-agent communication is through files in devos/.
No shared memory, no RPC. The repo IS the communication channel.

### Dual-mode Claude 1
Local: interactive Claude Code CLI (primary path)
Remote: os2-server invokes `claude -p` for each TG request
Both modes share the same devos/ state.

### Approval Workflow
PRD → plan → user approval → dispatch. No auto-execution.
Plans saved to plans/pending/, moved to approved/ or rejected/.

### Pipe Mode for Builders
Claude 2 runs as `claude -p` (non-interactive, one-shot).
Fresh context window each invocation = no degradation.
Account B credentials via `CLAUDE_CONFIG_DIR=.claude-b`.

### Shared Scope (apps/web/**)
Both Claude 2 and Codex can modify `apps/web/**`.
Ticket `files:` field enforces exclusive ownership per task.
Claude 2: design judgment, component architecture, UX flow.
Codex: bulk renames, pattern replacements, large mechanical edits.

### Token Efficiency
- Most TG queries answered by file parsing (no LLM call)
- LLM only invoked for planning and complex queries
- Claude 1 pipe mode = zero idle tokens

## Testing Pipeline

Target maturity: **Phase 3.5** (contract tests + UI smoke + scenario integration).
Full policy in `devos/AI.md` "Testing Policy" section.

### Gate Flow (`make pr-check`)

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
| Logic (`apps/api/**`, `packages/shared/**`) | `required` | CODEX | CLAUDE2 | Cross-test: CODEX commits failing tests → CLAUDE2 implements |
| UI (`apps/web/**`) | `skip` | CLAUDE2 | CLAUDE2 | Self-test: CLAUDE2 writes both |
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

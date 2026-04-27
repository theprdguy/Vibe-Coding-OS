![Version](https://img.shields.io/badge/version-3.4-blue) ![GitHub Template](https://img.shields.io/badge/GitHub-Template-238636?logo=github) ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white) ![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)

# Vibe Coding OS

**Three AI coding agents. One laptop. Zero stepping on toes.**

Drop a PRD into Claude 1. Approve the plan. Watch Claude and Codex ship code in parallel — no token exhaustion, no context drift, no merge conflicts. The repo is the source of truth, and the agents read it like an operating system.

[![Use this template](https://img.shields.io/badge/Use_this_template-238636?style=for-the-badge&logo=github&logoColor=white)](../../generate)

> "I open Claude 1, paste my product idea, and walk away. By the time I come back, the API endpoints, the React components, and the integration tests are all on the same branch — and I never had to babysit any of them."

---

## Table of contents

- [What this is](#what-this-is)
- [Why it exists](#why-it-exists)
- [Meet the three agents](#meet-the-three-agents)
- [How it works](#how-it-works)
- [How LLMs read this OS](#how-llms-read-this-os)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Built-in capabilities](#built-in-capabilities)
- [Architecture deep dive](#architecture-deep-dive)
- [What's new in v3.4](#whats-new-in-v34)
- [FAQ](#faq)
- [Version history](#version-history)
- [Contributing](#contributing)

---

## What this is

Vibe Coding OS is a multi-agent harness built on top of Claude Code, Anthropic's CLI for Claude. It coordinates **three specialized agents** that read and write to a shared file-based brain (the `devos/` directory), so they always know what each other is doing without sharing a chat window.

You write a Product Requirements Document (PRD). One agent decomposes it into tickets. Two other agents pick up tickets in parallel and ship code. A small Python dispatcher orchestrates the loop — verifying scope, running quality gates, and chaining the next ticket when one finishes.

It's a **GitHub template repo**. Click "Use this template", run `make setup`, and you have a working three-agent setup in under five minutes.

---

## Why it exists

Every developer who vibe-codes hits the same four walls:

**Token exhaustion** — Your single agent runs out of context halfway through a feature because it's planning, researching, *and* coding all at once.

**Context drift** — After three sessions, the agent has forgotten what it decided in session one. You're copy-pasting context between windows.

**File collisions** — Two agents edit the same file. One overwrites the other. You spend thirty minutes resolving conflicts that should never have existed.

**Momentum loss** — An agent stops to ask a clarifying question. You answer. It asks another. The build loop grinds to a halt.

Vibe Coding OS solves these by giving each problem its own structural answer:

| Problem | What we do about it |
|---|---|
| Token exhaustion | 3 specialized agents, each with a focused token budget |
| Context drift | Single source of truth in the repo (`devos/`) — not chat |
| File collisions | Strict file ownership per ticket (`files:` field) + scope-check gate |
| Momentum loss | Async question queue (`devos/questions/QUEUE.md`) — agents proceed with a default |
| Manual coordination | Approval workflow + auto-chaining dispatch + quality gates |

---

## Meet the three agents

Each agent has a personality. They show up to work knowing exactly which files they own, which they don't, and how to ask for help when stuck.

### Claude 1 — The Planner
Reads PRDs. Decomposes them into tickets. Researches library APIs through MCP. Reviews PRs adversarially. Writes session logs at the end of every day. **Never writes implementation code** — a hook physically blocks her from touching `apps/`, `packages/`, `infra/`, `scripts/`, or `tests/`. If she thinks "I'll just fix this quickly," the hook intercepts and reminds her to file a ticket instead.

She speaks two languages: WHAT (the goal, the DOD, the constraints) and CONTEXT (the research she did so the builders don't have to). Builders speak the third: HOW.

- **Account**: Account A (default `.claude/`)
- **Model**: User-selected per session (`/model` + `/effort`). Heavy planning: Opus + `xhigh`.
- **Skills**: `brainstorming`, `writing-plans`, `requesting-code-review`
- **Built-in prompts**: PRD intake checklist, decompose-PRD, adversarial review, security audit, cross-model review, goal-backward verification

### Claude 2 — The App Builder
Reads tickets that mention `apps/api/src/` or `apps/web/`. Designs UI components, wires backend endpoints, writes the implementation that makes the failing tests pass. Pinned to the `"sonnet"` family alias so she auto-tracks the latest Sonnet release without manual config edits.

When a ticket says `tdd: required` and `test_owner: CODEX`, she waits for Codex to commit the failing tests first, then implements just enough to make them green.

- **Account**: Account B (`.claude-b/` — separate Claude OAuth)
- **Model**: `"sonnet"` alias, with `/fast` available
- **MCP**: `context7` for library version-specific lookups
- **Skills**: `systematic-debugging`, `dispatching-parallel-agents`, `verification-before-completion`

### Codex — The Platform Builder
Codex (OpenAI's CLI) handles infrastructure, data, scripts, packages, and test scaffolding. Has the highest token budget — built for mechanical bulk edits, large refactors, and writing failing tests across many files. Runs as `codex exec -s workspace-write --add-dir ..` so he can read sibling repos when needed.

When Claude 2 is unauthenticated (no `.claude-b/.claude.json`), Codex automatically takes over Claude 2's tickets via the `fallback: CODEX` rule in `os2.yaml`.

- **CLI**: `codex` (OpenAI Codex CLI)
- **Skills**: `systematic-debugging`, `dispatching-parallel-agents`, `verification-before-completion`, `writing-plans`

> **Why three agents, not one?** Specialization isolates context. Each agent only loads the files relevant to its role — see the session-start read map below — so each one keeps its full token window for actual work.

---

## How it works

```
You          Claude 1 (Planner)        os2-server         Claude 2 / Codex
  │                │                       │                      │
  │ paste PRD      │                       │                      │
  ├───────────────►│                       │                      │
  │                │ research + decompose  │                      │
  │                ├──► devos/plans/pending/                      │
  │                │                       │                      │
  │ make pending   │                       │                      │
  ├──────────────────────────────────────►│                       │
  │                │                       │                      │
  │ make approve   │                       │                      │
  ├──────────────────────────────────────►│ approve               │
  │                │                       ├──► QUEUE.yaml        │
  │                │                       │                      │
  │                │                       │ dispatch             │
  │                │                       ├─────────────────────►│
  │                │                       │                      │ implement
  │                │                       │                      │ + commit
  │                │                       │ run gates            │ + session log
  │                │                       │◄─────────────────────┤
  │                │                       │                      │
  │                │                       │ auto-chain next      │
  │                │                       ├─────────────────────►│
```

**The repo is the source of truth. Not chat.**
All agent-to-agent communication flows through files in `devos/`. There is no shared memory, no API call between agents, no hidden context. What you commit is what every agent knows.

The dispatcher loop in present tense:
- A new ticket lands in `devos/tasks/QUEUE.yaml` with `status: todo`.
- You approve a plan via `make approve` (or auto-chain picks up the next ticket).
- The dispatcher checks scope: does this ticket's `files:` list collide with anything currently in flight? If yes, it parks the ticket. If no, it proceeds.
- It runs `preflight-claude2.sh` (or `preflight-codex.sh`), verifying the target agent is authenticated and ready.
- It launches the agent in a **fresh session** — no chat history is injected. The agent reads only the ticket body, the SSOT files mapped to its role, and `MEMORY.md` if populated.
- The agent commits its work and writes a session log to `devos/logs/`.
- Quality gates fire: `gitleaks`, contract sync, scope guard, session log presence, TDD first-commit gate.
- If gates pass and `auto_chain: true`, the next `todo` ticket dispatches automatically.

---

## How LLMs read this OS

This is the part you should pay attention to if you're going to extend the system. The behavior of every agent is fully determined by **which files it reads at session start**, not by special prompts hidden somewhere.

### Session-start read map

| File | CLAUDE1 | CLAUDE2 | CODEX |
|---|---|---|---|
| `devos/AI.md` | ✅ via `@import` | ✅ via `@import` | ✅ |
| `.claude/CLAUDE.md` | ✅ | — | — |
| `.claude-b/CLAUDE.md` | — | ✅ | — |
| `AGENTS.md` | — | — | ✅ |
| `devos/docs/BUILDER_GUIDE.md` | — | ✅ | ✅ |
| `devos/PROJECT_STATE.md` | ✅ | on demand | on demand |
| `devos/CONTEXT.md` | ✅ | on demand | on demand |
| `devos/tasks/QUEUE.yaml` | ✅ | ticket scope only | ticket scope only |
| `devos/questions/QUEUE.md` | ✅ | — | — |
| `devos/logs/{latest}` | ✅ | — | — |

`@import` = transitively loaded via Claude Code's `@path/to/file.md` syntax in CLAUDE.md frontmatter. `on demand` = read when the ticket explicitly requires it.

This map is **the entire contract** for how agents acquire context. If you want an agent to know about something new, you put it in a file the agent reads at session start. There is no hidden state.

### What an agent does at session start

Concretely, when the dispatcher runs `claude -p` with a ticket payload:

1. **Boot** — Claude Code loads `.claude/CLAUDE.md` (or `.claude-b/CLAUDE.md` for CLAUDE2). The first line is `@devos/AI.md`, so AI.md gets pulled in transitively.
2. **Read the prompt** — The agent loads `devos/prompts/{role}/session-start.md`, which is its boot checklist (filter QUEUE for assigned tickets, read PROJECT_STATE, check deps, read latest logs).
3. **Read the ticket** — The dispatcher inlines the ticket body (`goal`, `context`, `dod`, `constraints`, `files`, `verify`, `gates`).
4. **Skill activation** — If the ticket has a `skills_hint:` field, the agent invokes that **superpowers** skill before starting work (e.g., `systematic-debugging` for bug-fix tickets).
5. **Execute** — The agent makes edits, runs tests, commits, and writes a session log.
6. **Hand off** — The agent writes the 3-line handoff format from `devos/prompts/common/handoff-3lines.md` and exits.

### The prompt library

`devos/prompts/` is a structured library of agent instructions. The dispatcher inlines them; you maintain them.

```
devos/prompts/
├── claude/
│   ├── session-start.md             # CLAUDE1 boot checklist
│   ├── decompose-prd.md             # PRD → tickets workflow
│   ├── prd-intake-checklist.md      # Force-ask missing items (non-developer protection)
│   ├── review-pr.md                 # PR review gate checks
│   ├── review-adversarial.md        # FORCE stance — find every BLOCKER/WARNING
│   ├── verify-goal-backward.md      # Trace user journey backwards from goal
│   ├── cross-model-review.md        # Request a CODEX second opinion
│   └── security-audit.md            # OWASP A01–A10 + STRIDE
├── claude2/
│   └── session-start.md             # CLAUDE2 boot checklist
├── codex/
│   └── session-start.md             # CODEX boot checklist
└── common/
    ├── scope-reduction-prohibition.md  # Banned vocabulary lint (TODO, "v1 for now", etc.)
    ├── handoff-3lines.md               # Done / Next / Block / Log
    └── edit-failure-recovery.md        # 3 consecutive Edit failures → stop + report
```

These are not magic strings. Each is a markdown file you can edit. When you change one, the next dispatched session reads the new version. There is no caching, no compilation step, and no hidden state.

### Skill invocation

The Anthropic **superpowers** plugin provides skills that agents invoke at workflow boundaries. The mapping lives in `.claude/CLAUDE.md` and `AGENTS.md`. Tickets can request a specific skill via the `skills_hint:` field:

```yaml
- id: T-042
  owner: CLAUDE2
  status: todo
  goal: "Fix race condition in payment retry handler"
  skills_hint:
    - systematic-debugging
    - verification-before-completion
```

When CLAUDE2 picks up T-042, she invokes `systematic-debugging` first (which forces hypothesis-driven investigation), then `verification-before-completion` before marking the ticket done. See `devos/docs/SKILLS_PLUGIN_INSTALL.md` for setup.

### Hooks

Hooks are Claude Code's mechanism for intercepting tool calls. Vibe Coding OS uses them to enforce role boundaries:

- `.claude/hooks/guard-no-impl.sh` (PreToolUse on Write/Edit) — blocks CLAUDE1 from writing to `apps/`, `packages/`, `infra/`, `scripts/`, `tests/`. If she tries, the hook returns an error and tells her to file a ticket instead.
- `.claude/hooks/context-monitor.js` (PostToolUse) — surfaces a context-window warning before runaway sessions blow past the 4-hour mark.
- `.claude/hooks/statusline-wrapper.sh` (statusLine) — drives the bottom-bar status display.
- `scripts/preflight-claude2.sh` (SessionStart) — verifies CLAUDE2 is authenticated; advisory or hard-block depending on flag.

**Claude Code compatibility**: Command, Agent, Skill, MCP, Hook (PreToolUse, PostToolUse, SessionStart, statusLine).

---

## Quick start

### For humans

**Prerequisites**:
- Python 3.10+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/overview) (logged in to your primary account)
- Optional: a second Claude account for Claude 2 (otherwise Codex takes its tickets)
- Optional: [Codex CLI](https://platform.openai.com/docs/codex/overview) for the platform agent
- macOS or Linux (Windows via WSL)

**Steps**:

1. **Click "Use this template"** at the top of the repo. Pick a name. Clone it.
2. **Run setup**:
   ```bash
   make setup
   ```
   This installs Python deps, creates the venv, and walks through Claude 2 auth.
3. **Start the dispatcher**:
   ```bash
   make start
   ```
4. **Open Claude 1**:
   ```bash
   claude
   ```
   Claude 1 reads `.claude/CLAUDE.md` and announces herself as the planner.
5. **Paste your PRD**. Claude 1 will decompose it into tickets and save the plan to `devos/plans/pending/`.
6. **Approve the plan**:
   ```bash
   make pending          # review the proposed tickets
   make approve          # ship them to QUEUE.yaml
   ```
7. **Builders dispatch automatically**. Watch the action with `make logs` and `make queue`.

### For LLM agents

If you're another Claude (or any agent) installing this repo into someone's project, run this once:

```bash
git clone --depth 1 https://github.com/<owner>/<your-fork> .
make setup
echo "Read devos/AI.md, .claude/CLAUDE.md (if you are CLAUDE1), or AGENTS.md (if you are CODEX)."
echo "Read devos/prompts/{your-role}/session-start.md for the boot checklist."
echo "Then ask the user for their first PRD."
```

That's it. The OS is now installed. The CLAUDE.md / AGENTS.md files contain everything subsequent agents need at session start.

---

## Configuration

All configuration lives in flat files. There is no hidden config service, no environment registry, no database.

### `os2.yaml` — Dispatcher

The dispatcher reads this on startup. Defines agent commands, timeouts, dispatch settings, gates, and notification preferences.

```yaml
agents:
  CLAUDE1:
    mode: pipe
    command: ["claude", "-p"]
    config_dir: ".claude"
    timeout: 300
  CLAUDE2:
    mode: subprocess
    command: ["claude", "-p"]
    config_dir: ".claude-b"
    env: { CLAUDE_CONFIG_DIR: ".claude-b" }
    timeout: 600
    fallback: "CODEX"           # If .claude-b not configured, delegate to CODEX
  CODEX:
    mode: subprocess
    command: ["codex", "exec", "-s", "workspace-write", "--add-dir", ".."]
    timeout: 900

dispatch:
  max_concurrent: 2             # Agents running in parallel
  auto_chain: true              # Pick up next ticket on completion
  scope_check: true             # Verify file scope doesn't collide
  approval_required: true       # Always wait for human approval

gates:
  auto_retry:
    enabled: true
    retry_policy: { critical: 3, high: 2, medium: 1, low: 1 }
```

### `.claude/settings.json` — CLAUDE1 environment

Hooks, MCP servers, status line. Edit to add MCPs (e.g., a database connector) or change hook behavior.

```json
{
  "statusLine": { "type": "command", "command": "bash .claude/hooks/statusline-wrapper.sh" },
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "bash scripts/preflight-claude2.sh --advisory" }] }],
    "PreToolUse":   [{ "matcher": "Write|Edit", "hooks": [{ "type": "command", "command": "bash .claude/hooks/guard-no-impl.sh" }] }],
    "PostToolUse":  [{ "hooks": [{ "type": "command", "command": "node .claude/hooks/context-monitor.js" }] }]
  },
  "mcpServers": {
    "context7":   { "command": "npx", "args": ["-y", "@upstash/context7-mcp@latest"] },
    "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."] }
  }
}
```

### `.claude-b/settings.json` — CLAUDE2 environment

Same shape as Claude 1's. Pins the model to the `"sonnet"` family alias (auto-upgrades on releases) and enables `context7` for library lookups.

### `devos/agents/registry.yaml` — Agent declarations

Lists each agent, its scope, and instruction file. The dispatcher cross-references this against ticket `owner:` fields.

### `devos/AI.md` — The constitution

The shared rules every agent reads at session start. SSOT precedence, dispatch model, ticket schema, testing policy, model tiering. **Edit this when you want to change agent behavior project-wide.**

### `devos/ETHOS.md` — The tiebreaker

When agents disagree on judgment calls — scope, depth of fix, "should I add a TODO" — they read ETHOS. Iron Laws + Boil-the-Lake principle + Honest Cost Table + non-developer protection. **Edit this when you discover a value the agents need to share.**

### Key knobs at a glance

| File | What it controls |
|---|---|
| `os2.yaml` | Agent commands, timeouts, dispatch concurrency, retry policy |
| `.claude/settings.json` | CLAUDE1 hooks, MCPs, status line |
| `.claude-b/settings.json` | CLAUDE2 model alias, hooks, MCPs |
| `devos/agents/registry.yaml` | Agent scope and instruction-file mapping |
| `devos/AI.md` | SSOT precedence, ticket schema, testing policy |
| `devos/ETHOS.md` | Judgment tiebreakers (Iron Laws, non-dev protection) |
| `devos/PROJECT_STATE.md` | North Star, current milestone, blockers |
| `devos/CONTEXT.md` | Tech stack, key decisions, demo path |
| `devos/prompts/**` | Agent instruction prompts |

---

## Built-in capabilities

### Skills (Anthropic superpowers plugin)

Install once per laptop — see `devos/docs/SKILLS_PLUGIN_INSTALL.md`. Tickets request specific skills via `skills_hint:`.

| Workflow | Skill |
|---|---|
| PRD intake / ideation | `brainstorming` |
| Ticket planning | `writing-plans` |
| Parallel ticket dispatch | `dispatching-parallel-agents` |
| Bug fix tickets | `systematic-debugging` |
| PR review | `requesting-code-review` |
| Completion check | `verification-before-completion` |

### Built-in prompts

Located in `devos/prompts/`. Edit the markdown to change the behavior — no code change needed.

| Workflow | Prompt |
|---|---|
| PRD intake checklist | `devos/prompts/claude/prd-intake-checklist.md` |
| PRD decomposition | `devos/prompts/claude/decompose-prd.md` |
| PR review (gate-style) | `devos/prompts/claude/review-pr.md` |
| Adversarial PR review | `devos/prompts/claude/review-adversarial.md` |
| Goal-backward verification | `devos/prompts/claude/verify-goal-backward.md` |
| Cross-model review | `devos/prompts/claude/cross-model-review.md` |
| Security audit (OWASP + STRIDE) | `devos/prompts/claude/security-audit.md` |
| Scope-reduction lint | `devos/prompts/common/scope-reduction-prohibition.md` |
| Handoff format | `devos/prompts/common/handoff-3lines.md` |
| Edit failure recovery | `devos/prompts/common/edit-failure-recovery.md` |

### Hooks

| Hook | Type | What it does |
|---|---|---|
| `guard-no-impl.sh` | PreToolUse(Write/Edit) | Blocks CLAUDE1 from touching `apps/`, `packages/`, `infra/`, `scripts/`, `tests/` |
| `context-monitor.js` | PostToolUse | Warns when context window is filling up |
| `statusline-wrapper.sh` | statusLine | Renders the Claude Code status line |
| `bridge-only.js` | (utility) | Helper for cross-machine coordination |
| `preflight-claude2.sh` | SessionStart | Verifies CLAUDE2 auth before dispatch |
| `preflight-codex.sh` | SessionStart | Verifies Codex MCP/skill readiness |

### MCP servers

Pre-wired in `.claude/settings.json` and `.claude-b/settings.json`:

- **`context7`** — fetches up-to-date library documentation. Use for any library whose docs post-date the model's knowledge cutoff.
- **`filesystem`** — provides scoped file operations beyond what Read/Write expose.

Add more MCPs by editing the `mcpServers` block.

### Quality gates

`make pr-check` runs all baseline gates:

| Gate | Command | Purpose |
|---|---|---|
| Secret scan | `gitleaks git` | Catch leaked credentials before they're pushed |
| Contract sync | `scripts/check-contract-sync.sh` | API/UI contracts must update before code |
| Ticket scope | `scripts/check-ticket-scope.sh` | Diff stays within ticket's `files:` list |
| Session log | `scripts/check-session-log.sh` | Every completed ticket has a log |
| TDD first-commit | `scripts/check-tdd-first-commit.sh` | `tdd: required` tickets ship tests first |

---

## Architecture deep dive

<details>
<summary>Click to expand</summary>

### Repository layout

```
.
├── apps/                  # Your application code (CLAUDE2 + CODEX scope)
│   ├── api/
│   └── web/
├── packages/              # Shared libraries (CODEX scope)
├── infra/                 # IaC, CI/CD configs (CODEX scope)
├── scripts/               # Setup + gate scripts (CODEX scope)
├── tests/                 # Test suite (CODEX scope)
├── server/                # The Python dispatcher
│   ├── __main__.py        # CLI entry: status, queue, approve, dispatch, resume
│   ├── dispatcher.py      # Core dispatch loop + scope check + retries
│   ├── ssot.py            # SSOT file parsers and validators
│   ├── approval.py        # Plan approval workflow
│   ├── planner.py         # Plan generation utilities
│   └── config.py          # os2.yaml loader
├── devos/                 # The shared brain (read by all agents)
│   ├── AI.md                 # Operating rules (SSOT)
│   ├── ETHOS.md              # Iron Laws + judgment tiebreaker
│   ├── PROJECT_STATE.md      # North Star, current milestone, status
│   ├── CONTEXT.md            # Tech stack, key decisions, demo path
│   ├── VERSION.txt           # Current version (machine-readable)
│   ├── agents/registry.yaml  # Agent declarations
│   ├── tasks/QUEUE.yaml      # Ticket queue (machine-readable SSOT)
│   ├── plans/                # Approval workflow: pending/, approved/, rejected/
│   ├── prompts/              # Agent instruction library
│   ├── docs/                 # API_CONTRACT, UI_CONTRACT, ARCHITECTURE, ADRs, guides
│   ├── logs/                 # Session logs (auto-created by agents)
│   └── questions/QUEUE.md    # Async question queue (CLAUDE1 resolves)
├── .claude/               # CLAUDE1 environment
│   ├── CLAUDE.md             # CLAUDE1's instruction file
│   ├── settings.json         # Hooks + MCPs + status line
│   └── hooks/                # Hook scripts
├── .claude-b/             # CLAUDE2 environment (separate Claude account)
│   ├── CLAUDE.md
│   └── settings.json
├── AGENTS.md              # CODEX's instruction file
├── os2.yaml               # Dispatcher config
├── Makefile               # All the make targets
├── com.os2.server.plist   # macOS launchd unit (sub-machine daemon)
└── README.md              # You are here
```

### Token budget per agent

```
            CLAUDE1 (planner)        CLAUDE2 (app)         CODEX (platform)
            ────────────────────     ─────────────────     ─────────────────
budget      medium                   medium                high
focus       reads SSOT + tickets     reads ticket + impl   reads ticket + bulk
                                     files                 file edits
runs as     interactive (you type)   subprocess via        subprocess via
                                     `claude -p`           `codex exec`
            heavy planning + review  feature impl          infra + tests
```

CODEX gets the highest budget because mechanical bulk-edit work (test scaffolding, migrations, cross-file renames) requires the most file context.

### Auto-chain dispatch

When a ticket completes successfully and `auto_chain: true` (default), the dispatcher:

1. Sounds the macOS completion alert (configurable).
2. Filters QUEUE for the next ticket with `status: todo` whose `deps:` are all `done`.
3. Runs `scope_check`: does the new ticket's `files:` overlap with anything in flight?
4. If safe, dispatches it. If not, parks until the conflicting ticket finishes.

This is what lets you walk away from your laptop and come back to a stack of merged tickets.

### Daemon mode (sub-machine)

If you have a second always-on machine (a Mac mini, a home server), register the dispatcher as a launchd agent:

```bash
# Edit com.os2.server.plist — set WorkingDirectory to your project's absolute path
make install-daemon
```

Now the sub-machine accepts tickets even when your main laptop is asleep. `make handoff` on the main laptop pushes pending work; the daemon picks it up.

### WHAT + CONTEXT ticket schema

```yaml
- id: T-042                      # Stable ID
  owner: CLAUDE2                 # Who builds this
  status: todo                   # MUST be `todo` for dispatch (others are skipped)
  priority: high                 # critical | high | medium | low
  goal: |                        # WHAT — behavioral requirement
    POST /api/payments/refund returns 200 + refund ID for valid request
  context: |                     # CLAUDE1's research findings
    Stripe SDK v15.x changed retry signature — see context7 lookup.
    Existing /payments/charge handler at apps/api/src/payments/charge.ts is the pattern to follow.
  constraints:
    - Must use existing Stripe client from packages/shared/stripe.ts
    - Idempotency key required
  dod:                           # Verifiable acceptance criteria
    - "POST /api/payments/refund with valid charge ID returns 200 + { refund_id }"
    - "POST /api/payments/refund with already-refunded charge returns 409 + error"
    - "POST /api/payments/refund without auth returns 401"
  files:                         # Exclusive scope for this ticket
    - apps/api/src/payments/refund.ts
    - apps/api/src/payments/refund.test.ts
  verify: |
    pnpm test apps/api/src/payments/refund.test.ts
  gates:
    - { name: tests, run: pnpm test }
  tdd: required
  test_owner: CODEX              # CODEX writes failing tests first
  impl_owner: CLAUDE2            # CLAUDE2 implements
  skills_hint:
    - systematic-debugging
  security_audit: true           # Auto-forced for payment-touching tickets
  cross_model: true              # CODEX gives a second-opinion review
```

</details>

---

## What's new in v3.4

This release ports the V32–V36 dispatcher hardening cycle from the canonical OS, plus a new adversarial prompt suite and the ETHOS file.

**Adversarial prompt suite** (`devos/prompts/claude/`):
- `prd-intake-checklist.md` — Force-asks domain-specific missing items in PRDs (protects non-developer users from underspecified features).
- `review-adversarial.md` — Adversarial PR review pass: catches self-reporting, scope reduction, and missing error cases.
- `security-audit.md` — OWASP A01–A10 + STRIDE checklist. Auto-forced on tickets touching auth, payment, permissions, or external input.
- `cross-model-review.md` — Hand the deliverable to CODEX (a different model family) for an independent second opinion.
- `verify-goal-backward.md` — Trace the user journey backwards from the stated goal to verify reachability.
- `common/scope-reduction-prohibition.md` — Banned-vocabulary lint (TODO, "v1 for now", "temporary", "placeholder", "later", etc.). Step 4 of `decompose-prd.md` greps for these and blocks the ticket if any hit.

**ETHOS** (`devos/ETHOS.md`): A new tiebreaker file. Defines Iron Laws (no shortcuts that hide problems), the Boil-the-Lake principle, an Honest Cost Table, and non-developer protection rules.

**Dispatcher V32–V36 hardening** (`server/dispatcher.py`):
- Scope grep precision improvements
- Silent failure visibility (failures now surface in `make logs`)
- Dispatch exit-code propagation
- CLAUDE1 routing for policy/SSOT tickets
- Quota detection (cross-agent fallback when an agent hits its quota)
- Empty-diff classification
- Reject directory-mode handling

**Codex preflight** (`scripts/preflight-codex.sh`): Verifies Codex CLI is ready and MCP/skill setup is complete before dispatch. Mirrors the existing `preflight-claude2.sh`.

**`resume` command** (`make resume T=T-XXX`): Resume a blocked ticket and re-dispatch it without manually editing `QUEUE.yaml`.

---

## FAQ

<details>
<summary><strong>Do I need a second Claude account?</strong></summary>

No. Without a second account, CLAUDE2 tickets automatically fall back to Codex (configured via `fallback: CODEX` in `os2.yaml`). You'll lose the parallelism but everything still ships. To unlock parallel mode later, run `CLAUDE_CONFIG_DIR=.claude-b claude login` and pick a different Claude account.
</details>

<details>
<summary><strong>Why doesn't Claude 1 just write the code?</strong></summary>

Token budget. The model that's good at planning, researching, and reviewing is the same model that runs out of context if you also ask it to ship features. Splitting roles keeps Claude 1's context lean for what she's best at: long-horizon thinking. The hook physically enforces this — Claude 1 can't accidentally drift into coding because the file-write hook blocks her.
</details>

<details>
<summary><strong>What happens when an agent gets blocked?</strong></summary>

It writes a question to `devos/questions/QUEUE.md` with options + a recommended default + a fallback action if you don't respond within 24 hours. Non-blocking questions: agent proceeds with the default. Blocking questions: ticket is marked `blocked` and the dispatcher moves on. You answer at your own pace.
</details>

<details>
<summary><strong>Where do session logs go?</strong></summary>

`devos/logs/{YYYY-MM-DD}-{agent}-{ticket-ids}.md`. Max 50 lines per log — agents are coached to be terse. Cross-agent visibility: when CODEX picks up a ticket, it reads the latest CLAUDE2 logs to know what just shipped.
</details>

<details>
<summary><strong>Can I use this on an existing project?</strong></summary>

Yes. Copy the `devos/`, `server/`, `scripts/`, `.claude/`, `.claude-b/` directories plus `os2.yaml`, `AGENTS.md`, and `Makefile` into your existing repo. Edit `os2.yaml` to point at your project root. Reset `devos/tasks/QUEUE.yaml` and `devos/PROJECT_STATE.md` to match your context. Run `make setup`.
</details>

<details>
<summary><strong>What about Linux / WSL?</strong></summary>

The dispatcher is plain Python — works on any POSIX system. The launchd daemon (`com.os2.server.plist`) is macOS-only. On Linux, use systemd or run `make start` from your shell. Everything else is portable.
</details>

<details>
<summary><strong>What does <code>make approve</code> actually do?</strong></summary>

Reads the most recent file in `devos/plans/pending/`, copies its tickets into `devos/tasks/QUEUE.yaml` with `status: todo`, moves the plan file to `devos/plans/approved/`, and (if `auto_chain: true`) immediately dispatches the first ticket whose deps are satisfied. There's no LLM call — it's pure file movement.
</details>

<details>
<summary><strong>How do I customize agent behavior project-wide?</strong></summary>

Edit `devos/AI.md`. Every agent reads it at session start (transitively, via `@import`). Add a new rule, save, and the next dispatched session honors it. No restart needed.
</details>

---

## Version history

- **v3.4** (current) — Adversarial prompt suite (PRD intake, adversarial review, security audit, cross-model, goal-backward verification, scope-reduction lint), ETHOS tiebreaker, dispatcher V32–V36 hardening (scope grep, exit-code propagation, quota cross-agent fallback, empty-diff classification, reject directory-mode), `preflight-codex.sh`, `make resume` command.
- **v3.3** — Skills integration via Anthropic superpowers plugin, structured prompt library (`devos/prompts/`), expanded ops rules in `AI.md`.
- **v3.2** — Testing maturity Phase 3.5, Stage 0 baseline gates, branch-coverage enforcement (Line 70% / Branch 60%).
- **v3.1** — CLAUDE2 (Account B) introduced. Three-agent setup with role restructure: Claude 1 = planner, Claude 2 = app builder, Codex = platform builder.
- **v3.0** — `os2-server` Python dispatcher, plans approval workflow (`pending/` → `approved/`), `BUILDER_GUIDE.md` and `OPERATION_GUIDE.md`.
- **v2.0** — Native instruction files (`.claude/CLAUDE.md`, `AGENTS.md`), session logs in `devos/logs/`, agent registry, WHAT+CONTEXT ticket schema.
- **v1.5** — Token-efficient multi-LLM OS.
- **v1.0** — Initial multi-agent harness.

---

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

- 1 ticket = 1 PR
- All state lives in `devos/`
- Contracts in `devos/docs/API_CONTRACT.md` / `UI_CONTRACT.md` update **before** code
- Use `status: todo` on new tickets (other statuses are silently skipped by the dispatcher)
- Fork-friendly: keep `devos/`, wire `make test` to your stack, reset `devos/tasks/QUEUE.yaml`

---

## Credits & inspiration

Vibe Coding OS stands on the shoulders of these projects. Where we vendor code, the file header carries the source URL and license. Where we borrow patterns or prompts, this section is the attribution of record.

**Built on:**
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)** — Anthropic's CLI for Claude. The harness for CLAUDE1 and CLAUDE2.
- **[OpenAI Codex CLI](https://platform.openai.com/docs/codex/overview)** — the platform-builder agent.
- **[obra/superpowers](https://github.com/obra/superpowers)** — Jesse Vincent's agentic skills framework. We use the `brainstorming`, `writing-plans`, `dispatching-parallel-agents`, `systematic-debugging`, `requesting-code-review`, and `verification-before-completion` skills directly through the [Anthropic claude-plugins-official marketplace](https://github.com/anthropics/claude-plugins-official). Setup: `devos/docs/SKILLS_PLUGIN_INSTALL.md`.

**Patterns borrowed:**
- **[gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)** (MIT) — `.claude/hooks/context-monitor.js` is vendored from GSD's `gsd-context-monitor.js` (vendoring header preserved in the file). The workflow-guard advisory pattern in `.claude/hooks/guard-no-impl.sh` is adapted from `gsd-workflow-guard.js`. The statusline hook draws from `gsd-statusline.js`.
- **[garrytan/gstack](https://github.com/garrytan/gstack)** — `devos/prompts/claude/security-audit.md` borrows the *prompt portion* of GStack's `/cso` (Chief Security Officer) skill. We do not ship GStack's 22 MB ML classifier, the Haiku transcript voting, or the canary-token system — only the OWASP A01–A10 + STRIDE prompt that drives the audit. Effectiveness ~70–80% of the original; high launch-impact areas (payment processing, etc.) still warrant a separate external audit.

If your work is referenced and you'd like an attribution updated, link corrected, or removed, please open an issue.

---

<sub>v3.4 · Built with Claude Code, Codex CLI, and the superpowers plugin · Patterns from GSD and GStack</sub>

![Version](https://img.shields.io/badge/version-4.0-blue) ![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg) ![GitHub Template](https://img.shields.io/badge/GitHub-Template-238636?logo=github) ![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white) ![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey)

# Vibe Coding OS

**One planner. A read-only review board. Two implementers. One laptop.**

Drop a PRD into CLAUDE1. Approve the plan. Watch a Claude sub-agent and Codex ship code in parallel — while a panel of **read-only** reviewers (that physically cannot touch the code) checks every change. The repo is the source of truth, and the agents read it like an operating system.

[![Use this template](https://img.shields.io/badge/Use_this_template-238636?style=for-the-badge&logo=github&logoColor=white)](../../generate)

> "I describe the product. The OS turns it into scoped, tested, reviewed tickets, routes each to the right model, and only interrupts me for product judgment. I do PM work; the OS does engineering management."

### 📖 Read the deep dive

A visual, illustrated walkthrough of the architecture — layers, agents, tickets, dispatch, modes, structural safety, SSOT, the host-OS model, and the feedback loop. The README is the summary; this is the *why*.

| | Read it (rendered) | Fallback | Source |
|---|---|---|---|
| 🇬🇧 **English** | [**Open ↗**](https://theprdguy.github.io/Vibe-Coding-OS/docs/deep-dive.en.html) | [htmlpreview](https://htmlpreview.github.io/?https://github.com/theprdguy/Vibe-Coding-OS/blob/main/docs/deep-dive.en.html) | [`docs/deep-dive.en.html`](docs/deep-dive.en.html) |
| 🇰🇷 **한국어** | [**열기 ↗**](https://theprdguy.github.io/Vibe-Coding-OS/docs/deep-dive.ko.html) | [htmlpreview](https://htmlpreview.github.io/?https://github.com/theprdguy/Vibe-Coding-OS/blob/main/docs/deep-dive.ko.html) | [`docs/deep-dive.ko.html`](docs/deep-dive.ko.html) |

<sub>**Open ↗** serves the page via GitHub Pages with full styling. GitHub's repo file view shows raw HTML source (not rendered) — that's expected; use the Open or htmlpreview link to read it.</sub>

---

## Table of contents

- [📖 Read the deep dive](#-read-the-deep-dive)

- [What this is](#what-this-is)
- [Why it exists](#why-it-exists)
- [Requirements & compatibility](#requirements--compatibility)
- [Drop-in mode — try it in one repo (5 minutes)](#drop-in-mode--try-it-in-one-repo-5-minutes)
- [Meet the agents](#meet-the-agents)
- [How it works](#how-it-works)
- [Operating modes](#operating-modes)
- [Why it's safe — structure, not trust](#why-its-safe--structure-not-trust)
- [How LLMs read this OS](#how-llms-read-this-os)
- [Quick start](#quick-start)
- [The host-OS model — one engine, many projects](#the-host-os-model--one-engine-many-projects)
- [Repo layout](#repo-layout)
- [Use just a piece](#use-just-a-piece)
- [What's new in v4.0](#whats-new-in-v40)
- [FAQ](#faq)
- [Version history](#version-history)
- [Contributing](#contributing)
- [Credits & inspiration](#credits--inspiration)
- [License](#license)

---

## What this is

Vibe Coding OS is a multi-agent harness built on top of [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview), Anthropic's CLI for Claude. It coordinates a **planner**, a **review board**, and **two implementers** that read and write to a shared file-based brain (the `devos/` directory) — so they always know what each other is doing without sharing a chat window.

You write a Product Requirements Document (PRD). The planner (**CLAUDE1**) decomposes it into tickets and parks its research in each one. Implementers pick up tickets and ship code. A read-only review board checks the result. A Python dispatcher (`os3`) orchestrates the loop — verifying scope, running quality gates, escalating to a second model when uncertain, and recording an auditable trail of every state change.

It's a **GitHub template repo**. Click "Use this template", run `scripts/setup.sh`, and you have a working setup in minutes.

The core idea: **the planner never writes production code, and the reviewers never can.** Roles are separated, and the separation is enforced by *tool permissions*, not by asking nicely.

---

## Why it exists

Every developer who vibe-codes hits the same walls:

1. **One agent does everything** → it writes the happy path, skips error handling, then reviews its own work. Objectivity is zero.
2. **"It should work"** → completion claimed without evidence; the bug surfaces in production.
3. **Context drift** → over a long session the agent forgets earlier decisions and contradicts itself.
4. **No paper trail** → you can't reconstruct *what changed and why* a week later.

Vibe Coding OS answers each one structurally: separated roles with **enforced** permissions, **evidence-before-done** Iron Laws, a **file-based SSOT** the agents reload each session, and an **append-only audit trail** (`_transition_history`, session logs) on every ticket.

"PM-friendly" does **not** mean low quality. So that you *don't* have to verify every line, the OS is **stricter**, not looser — in Production mode it behaves like a strong development team (tests, security, error/empty/loading states, independent review, auditable waivers).

---

## Requirements & compatibility

This is **Claude-Code-native and opinionated** — it is NOT a model-agnostic harness.

| Category | Tool | Required? | Notes |
|---|---|---|---|
| **Required** | [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) | Yes | Claude Code subscription. CLAUDE1 + all in-session sub-agents run here. |
| **Optional** | [OpenAI Codex CLI](https://platform.openai.com/docs/codex/overview) | No | Enables the CODEX implementer (backend/infra/tests) and cross-model second opinion (b'). |
| **Optional** | [Gemini CLI](https://github.com/google-gemini/gemini-cli) | No | Visual-outcome reviewer for rendered UI (`os3 gemini`). |
| **MCP** | [context7](https://github.com/upstash/context7) | No | Used by CLAUDE1 for up-to-date library API docs. |
| **Plugin** | [obra/superpowers](https://github.com/obra/superpowers) | No | Agentic skills (brainstorming, writing-plans, systematic-debugging, etc.). Install: [`devos/docs/SKILLS_PLUGIN_INSTALL.md`](devos/docs/SKILLS_PLUGIN_INSTALL.md). |
| **Runtime** | Python 3.10+ | Yes | For `server/` and `bin/os3`. |
| **Platform** | macOS or Linux | Yes | Windows via WSL2 is untested. |

---

## Drop-in mode — try it in one repo (5 minutes)

**Fastest way to taste the OS**: scaffold it into an existing repo without restructuring your machine.

```bash
# From inside your existing project repo:
bash /path/to/vibe-coding-os/scripts/dropin-init.sh
```

This copies `.claude/` (agents, hooks, settings) into your repo and creates a minimal `devos/` skeleton (QUEUE.yaml, questions, PROJECT_STATE.md, CONTEXT.md) plus a `.os3.yaml` marker. The hook commands in the copied `settings.json` are rewritten to point at your repo's own `.claude/hooks/` directory, so the drop-in repo is **fully self-contained** — the hooks run from the copy inside your repo and the source OS clone does not need to remain in place. Run `claude` in that repo and CLAUDE1 picks up the doctrine immediately.

| | Drop-in | Host-OS (full) |
|---|---|---|
| **Repos** | 1 | many (engine once, N projects) |
| **Setup time** | ~5 min (one script) | ~15 min (clone host, register projects) |
| **What you get** | Doctrine + agents + guard hooks + devos/ skeleton | Everything + `os3 dispatch`, `os3 open`, multi-project kanban, OS-feedback loop |
| **os3 CLI** | Optional (install separately) | Built-in |
| **Graduate to host-OS?** | Yes — see [host-OS model](#the-host-os-model--one-engine-many-projects) | — |

> Drop-in still gives you the full agent panel (builder, reviewer, security, designer) and the guard-no-impl + context-monitor hooks. The copied `.claude/` is what runs — hooks fire from your repo's own `.claude/hooks/` directory. The Python `os3 dispatch` routing requires the host CLI on PATH; without it, use `claude` directly and dispatch manually.

See a full example: [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md).

---

## Meet the agents

| Agent | Model | Tools | Role |
|---|---|---|---|
| **CLAUDE1** (main) | Opus | full | Planner · Researcher · SSOT manager · **Orchestrator**. Talks to you. Never writes production code. |
| **builder** (sub-agent) | Sonnet | Read · Edit · Write · Bash | In-session implementer. Best for ambiguous, experience-heavy UI and new UX flows. |
| **CODEX** | external CLI | subprocess (sandboxed) | Platform implementer — backend/API/data/infra/tests/migrations — and cross-model second opinion (b'). |
| **reviewer** (sub-agent) | Opus | **READ-ONLY** | Adversarial PR reviewer. DOD↔test mapping, assertion specificity, scope, contracts. |
| **designer** (sub-agent) | Sonnet | **READ-ONLY** | UI/UX first-pass: consistency, hierarchy, missing states, accessibility. |
| **security** (sub-agent) | Opus | **READ-ONLY** | OWASP A01–A10 + STRIDE. Auto-invoked for auth/payment/permissions/external input. |
| **Gemini** (optional) | external CLI | screenshots/video | Visual-outcome reviewer for rendered UI. |

The review board's read-only tools are the point: **they have no Edit/Write tool, so they cannot quietly "fix" their own findings.** Structural objectivity, enforced at the permission layer.

> Earlier versions ran a separate "Claude 2" on a second account. That's been folded into the in-session **builder** sub-agent — one account, lower latency, same separation of duties.

---

## How it works

```
You ──PRD──▶ CLAUDE1
                │  1. intake checklist (force the missing error/edge/security cases)
                │  2. extract user journeys → decompose into tickets
                ▼
        devos/plans/pending/  ──你 approve (os3 approve)──▶  devos/tasks/QUEUE.yaml
                                                                    │
                                              os3 dispatch T-XXX    ▼
                          owner=BUILDER → in-session sub-agent   owner=CODEX → subprocess
                                                    │  implements
                                                    ▼
                          os3 pr-check  (secrets · contract sync · scope · session log · TDD)
                                                    ▼
                  review board (reviewer / security / designer — read-only, by ticket type)
                                                    ▼
                          uncertain or risky?  → b' cross-model (CODEX second opinion)
                                                    ▼
                     BLOCKER? → blocked + question queue (Q-XXX, you decide)
                     else     → done → archived (audit trail preserved)
```

Every dispatch reports a standard header — *which path, which model built it, who reviewed it, what the verdict was* — so you never have to ask.

---

## Operating modes

One idea moves from **exploration → productization → production** as confidence rises. The mode sets the **gate posture**, enforced by the dispatcher:

| Gate | Exploration | Productization | Production |
|---|---|---|---|
| Tests | optional / report-only | strategy required | **required** (logic/API/data) |
| Reviewer | report-only | recommended | **required — rejection blocks** |
| Security | only for secrets/auth/destructive | risk identification | **required when triggered — blocks** |
| Visual review (UI) | report-only | required if defining UI acceptance | **required (or waiver)** |
| Success **and** failure DOD | optional | required | **required** |

**Report-only is fail-closed**: a soft gate is downgraded only when the mode is exploration/productization **and** the gate is an explicitly-recognized soft gate. Everything else — secrets, file-scope violations, destructive actions, unknown gates — **blocks in every mode**. Exceptions in Production require a recorded **waiver** (who approved, what risk, follow-up).

See `docs/policy/MODE_GATE_MATRIX.md`.

---

## Why it's safe — structure, not trust

- **Read-only review board** — reviewer/designer/security have no Edit/Write tool. They report; they cannot merge or self-fix.
- **Planner can't implement** — a `PreToolUse` hook blocks CLAUDE1 from writing to `apps/ packages/ scripts/ tests/ …`. Implementation goes through a ticket.
- **Iron Laws** (apply to every agent):
  1. No production code without a failing test first (business logic).
  2. No fix without root-cause investigation first.
  3. No completion claim without fresh verification evidence.
  4. No merge without adversarial review passed.
  5. No scope-reduction vocabulary in tickets (`v1 for now`, `TODO`, `temporary`, …) — grep-enforced.
- **Always-on safety floor** — secret exposure, owner mismatch, file-scope violation, unresolved deps, destructive-with-dirty-tree block regardless of mode and cannot be waived by a normal waiver.
- **Cross-model safety net (b')** — when the reviewer is uncertain, a BLOCKER appears, or the ticket is high-risk, a *different vendor* (Codex) gives a second opinion. Free when calm; vendor-diverse when in doubt.
- **Incident → Locked Decision** — when something breaks, the fix becomes an enforced rule (a `D-XX` Locked Decision whose violation is an automatic reviewer BLOCKER), so it can't recur.
- **Auditable** — every status change records actor + reason + timestamp; session logs capture each run.

---

## How LLMs read this OS

All state is files under `devos/`. Agents reload them at session start, so there's no shared chat window to drift.

**SSOT precedence** (when sources disagree, higher wins):

1. `devos/PROJECT_STATE.md` — milestones, what works now
2. `docs/API_CONTRACT.md` + `docs/UI_CONTRACT.md` — interface contracts (above code)
3. `docs/ADR/*` — architecture decisions
4. `devos/tasks/QUEUE.yaml` — active tickets
5. Code
6. `devos/logs/` — session logs
7. Chat logs (least reliable)

Contract-first: if API/UI behavior changes, the contract doc is updated **before** the code.

---

## Quick start

```bash
# 0. Use this template on GitHub, then clone your copy anywhere
git clone https://github.com/<you>/<your-os>.git
cd <your-os>

# 1. Run setup: checks prereqs, installs Python deps, guides PATH setup
./scripts/setup.sh

# 2. Add bin/ to PATH (setup.sh will show the exact command for your shell)
#    Example for zsh:
export PATH="$(pwd)/bin:$PATH"   # for this session; setup.sh shows the permanent form

# 3. Open a session (injects host settings + launches Claude Code)
os3 open <project>          # or just run `claude` in the repo root to work on the OS itself

# 4. In the session: submit a PRD → CLAUDE1 decomposes → approve → dispatch
os3 status                  # current state
os3 queue                   # active tickets
os3 approve                 # approve a pending plan
os3 dispatch T-XXX          # route a ticket to its owner (BUILDER in-session / CODEX subprocess)
os3 pr-check                # baseline gates
os3 archive                 # move done tickets to ARCHIVE.yaml
os3 dashboard               # local read-only kanban at http://127.0.0.1:8787
```

You need [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) (required). See the [Requirements & compatibility](#requirements--compatibility) table above for optional tools.

---

## The host-OS model — one engine, many projects

The engine, agents, and doctrine live **once** in a host repo (clone it anywhere — `~/dev-os` is a common choice but not required). Each product is an **independent git repo** under `<host>/projects/`, carrying only its own product code and task state. The host provides everything else.

```
<host-repo>/              host = engine · doctrine · shared .claude (one git repo)
├── server/  bin/os3  .claude/  devos/
└── projects/            (git-ignored by the host — each is its own repo)
    ├── myproduct-a/      apps/ packages/ + its own devos/tasks · PROJECT_STATE · .os3.yaml
    └── myproduct-b/      ...
```

- **Engine in one place** — improve the OS once; every project gets it. No sync.
- **Projects stay independent** — own repo, own task state, deployed separately.
- **One entry point** — `os3 open <name>` enters any project with the host settings attached.

> Using the template as a single project? That works too — keep `devos/` as your state, point `os3 pr-check` at your stack, and ignore `projects/`. The host-OS model is how it scales to several products.

The OS also dogfoods a **demand-pulled improvement loop**: friction hit during product work is captured with `os3 feedback "..."` into `devos/os-feedback/INBOX.md`, reviewed at session start, and converted to tickets during a periodic consolidation pass.

---

## Repo layout

```
bin/os3                  single entry point for all commands (osn = compat alias)
server/                  the engine (Python): dispatcher · ssot · cli · dashboard · launcher
  dispatcher.py          ticket routing · gates · retry · singleton lock · dispatch snapshot
  ssot.py                QUEUE/ARCHIVE read/write with file locks + atomic writes
  gemini_dispatcher.py   visual-review channel
.claude/
  CLAUDE.md              CLAUDE1 operating rules (@imports devos/AI.md)
  agents/*.md            sub-agent definitions (model + tool allowlist)
  hooks/                 guard-no-impl (planner boundary) · context-monitor
devos/
  AI.md / AI-core.md     the agent constitution (full / slim boot)
  ETHOS.md               tiebreaker: Iron Laws + Boil-the-Lake + non-developer protection
  CONTEXT.md             TL;DR + Locked Decisions (D-XX)
  PROJECT_STATE.md       milestone SSOT
  prompts/               dispatch · review · security · session-start/end protocols
  tasks/QUEUE.yaml       active tickets (done → ARCHIVE.yaml)
  os-feedback/INBOX.md   demand-pulled OS-improvement backlog
docs/
  OPERATING_DOCTRINE.md  modes · roles · quality bar
  policy/                MODE_GATE_MATRIX · ROLE_AUTHORITY_MATRIX · MODEL_ROUTING · WAIVER · TICKET_SCHEMA
```

---

## Use just a piece

Not ready to adopt the full OS? These components can be extracted and used standalone:

| Component | What it does | Files |
|---|---|---|
| **Read-only reviewer / security / designer agents** | Sub-agent definitions with read-only tool allowlists — gives you an adversarial reviewer that physically cannot self-merge | [`.claude/agents/reviewer.md`](.claude/agents/reviewer.md), [`.claude/agents/security.md`](.claude/agents/security.md), [`.claude/agents/designer.md`](.claude/agents/designer.md) |
| **Ticket schema** | Standard ticket fields (goal / dod / files / tdd / gates) with verifiable DOD pattern and failure-case requirement | [`docs/policy/TICKET_SCHEMA.md`](docs/policy/TICKET_SCHEMA.md) |
| **Scope-reduction gate** | Grep-enforced lint that blocks scope-reduction vocabulary (`v1 for now`, `TODO placeholder`, `temporary`, …) from ticket goals | [`devos/prompts/common/scope-reduction-prohibition.md`](devos/prompts/common/scope-reduction-prohibition.md) |
| **Planner guard hook** | `PreToolUse` hook that blocks the planner from writing to implementation paths (`apps/`, `packages/`, `scripts/`, …) | [`.claude/hooks/guard-no-impl.sh`](.claude/hooks/guard-no-impl.sh) |
| **Context-monitor hook** | `PostToolUse` hook that warns the agent when token budget hits WARNING (35%) or CRITICAL (25%) thresholds | [`.claude/hooks/context-monitor.js`](.claude/hooks/context-monitor.js) |

Copy the file(s) you need; each is self-contained. The reviewer/security/designer agents require
Claude Code sub-agent support. The hooks require Claude Code's hook system.

---

## What's new in v4.0

A major jump from the v3.x three-account model to **OS3 / host-OS**:

- **In-session sub-agent model** — "Claude 2 (Account B)" is sunset and folded into the **builder** sub-agent. One account; lower latency.
- **Read-only review board** — reviewer / designer / security run with read-only tools (structural objectivity), spawned by ticket type.
- **Operating modes** — exploration / productization / production set the gate posture, fail-closed, enforced in the dispatcher.
- **`os3` CLI** replaces `make` and `os2.yaml`. Single entry point `bin/os3`.
- **host-OS architecture** — one host engine, many independent project repos under `projects/`; `os3 open` injects host settings.
- **Cross-model safety net (b')** — quantitative trigger for a Codex second opinion (BLOCKER, low confidence, security finding, high-risk ticket).
- **Local dashboard** — `os3 dashboard`, a build-free read-only kanban.
- **OS-feedback loop** — `os3 feedback` captures OS friction into a reviewed backlog.
- **Incident → Locked Decision** pipeline and per-ticket `_transition_history` audit trail.

---

## FAQ

**Do I need to know how to code?** You need to describe what you want. The OS forces the missing error/edge/security cases, routes work to the right model, and only interrupts you for product judgment, taste, or waiver approval.

**Why can't the planner just write the code?** "Fast" costs you objectivity and traceability. Separating implementer from reviewer makes review meaningful; tickets make decisions auditable. The boundary is enforced by a hook, not willpower.

**One account or two?** One. The old second-account "Claude 2" is now the in-session builder sub-agent.

**Can I use it without Codex / Gemini?** Yes. Codex (CODEX implementer + cross-model) and Gemini (visual review) are optional. Claude Code is the only hard requirement.

**How do I change a rule?** Edit `devos/AI.md`. Every agent reads it at session start (via `@import`). Save, and the next session honors it — no restart.

---

## Version history

Full change notes: [`CHANGELOG.md`](CHANGELOG.md).

- **v4.0** (current) — **OS3 / host-OS.** In-session sub-agent model (Claude 2 sunset → builder), read-only review board (reviewer/designer/security), operating modes with fail-closed gate posture, `os3` CLI (replaces `make`/`os2.yaml`), host-OS architecture (one engine + independent project repos), quantitative cross-model (b') trigger, local kanban dashboard, OS-feedback loop, incident→Locked-Decision pipeline.
- **v3.4** — Adversarial prompt suite (PRD intake, adversarial review, security audit, cross-model, goal-backward verification, scope-reduction lint), ETHOS tiebreaker, dispatcher hardening, `preflight-codex.sh`.
- **v3.3** — Skills integration via the Anthropic superpowers plugin, structured prompt library, expanded ops rules.
- **v3.2** — Testing maturity Phase 3.5, Stage 0 baseline gates, branch-coverage enforcement (Line 70% / Branch 60%).
- **v3.1** — Three-agent setup with role restructure (planner / app builder / platform builder).
- **v3.0** — Python dispatcher, plans approval workflow, BUILDER_GUIDE / OPERATION_GUIDE.
- **v2.0** — Native instruction files, session logs, agent registry, WHAT+CONTEXT ticket schema.
- **v1.x** — Initial token-efficient multi-agent harness.

---

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

- 1 ticket = 1 PR
- All state lives in `devos/`
- Contracts in `docs/API_CONTRACT.md` / `UI_CONTRACT.md` update **before** code
- Use `status: todo` on new tickets (other statuses are silently skipped by the dispatcher)
- Fork-friendly: keep `devos/`, wire your test runner into `os3 pr-check`, reset `devos/tasks/QUEUE.yaml`

---

## License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for the full text.

Third-party vendored sources and dependency attributions are documented in [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).

---

## Credits & inspiration

Vibe Coding OS stands on the shoulders of these projects. Where we vendor code, the file header carries the source URL and license. Where we borrow patterns or prompts, this section is the attribution of record.

**Built on:**
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)** — Anthropic's CLI for Claude. The harness for CLAUDE1 and the in-session sub-agents.
- **[OpenAI Codex CLI](https://platform.openai.com/docs/codex/overview)** — the platform-builder + cross-model agent.
- **[obra/superpowers](https://github.com/obra/superpowers)** — Jesse Vincent's agentic skills framework. We use the `brainstorming`, `writing-plans`, `dispatching-parallel-agents`, `systematic-debugging`, `requesting-code-review`, and `verification-before-completion` skills via the [Anthropic claude-plugins-official marketplace](https://github.com/anthropics/claude-plugins-official). Setup: `devos/docs/SKILLS_PLUGIN_INSTALL.md`.

**Patterns borrowed:**
- **[gsd-build/get-shit-done](https://github.com/gsd-build/get-shit-done)** (MIT) — `.claude/hooks/context-monitor.js` is vendored from GSD's `gsd-context-monitor.js` (vendoring header preserved). The advisory pattern in `.claude/hooks/guard-no-impl.sh` is adapted from `gsd-workflow-guard.js`.
- **[garrytan/gstack](https://github.com/garrytan/gstack)** — `devos/prompts/claude/security-audit.md` borrows the *prompt portion* of GStack's `/cso` skill (OWASP A01–A10 + STRIDE). We do not ship GStack's ML classifier or canary-token system. High launch-impact areas (e.g. payments) still warrant a separate external audit.

If your work is referenced and you'd like an attribution updated, corrected, or removed, please open an issue.

---

<sub>v4.0 · OS3 / host-OS · Built with Claude Code, Codex CLI, and the superpowers plugin · Patterns from GSD and GStack</sub>

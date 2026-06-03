# CONTEXT (TL;DR)

> ~100 lines max. Updated by CLAUDE1 each session. Ships as a generic example.

## What we are building (1-2 lines)
- (TBD) — Fill in your project description here.

## Operating mode
- SSOT-first, Contract-first, Ownership (1 PR = 1 ticket), Boil-the-Lake completeness.
- `deos pr-check` is the minimum baseline gate (secrets scan, contract sync, scope guard, session log, TDD first-commit).
- Approval required before dispatch: `deos approve`.
- Session logs in devos/logs/ for cross-agent visibility.
- Instruction files: `.claude/CLAUDE.md` (CLAUDE1), `.claude/agents/*.md` (sub-agents), `AGENTS.md` (CODEX).

## Agent Roster
- **CLAUDE1 (main)**: Planner + Researcher + SSOT manager + Orchestrator — never implements directly.
- **builder / reviewer / designer / security** (in-session sub-agents): implement + read-only review chain.
- **CODEX** (external CLI): platform builder + cross-model second opinion (b').

## Tech Stack
- Stack-agnostic OS layer (Python dispatcher/CLI + file-based SSOT). Product app stack is chosen per project.
- (TBD) — Fill in your product stack here.

## Operating Modes
- exploration → productization → production. Gate strictness rises with the mode
  (docs/policy/MODE_GATE_MATRIX.md). Safety gates (secrets, scope, destructive action) always block.

## Key decisions (top 5)
- (TBD)

## Locked Decisions (D-XX)
- Non-negotiable decisions a ticket may not violate; a violation is an automatic reviewer BLOCKER.
- (none yet — add as they are locked)

## Active tickets / Open questions
- See tasks/QUEUE.yaml and questions/QUEUE.md (filter: [open]).

# CONTEXT (TL;DR)

## What we are doing (1-2 lines)
- We are building a multi-LLM vibe-coding operating system (v2.0).
- Claude manages + researches, Codex/Gemini build. Coordination via SSOT files.

## Operating mode
- SSOT-first, Contract-first, Ownership, Small PR, A-Mode questions
- Make is the standard interface: make pr-check is the minimum gate
- Native instruction files: AGENTS.md (Codex), GEMINI.md (Gemini), .claude/CLAUDE.md (Claude)
- Session logs in devos/logs/ for cross-agent visibility

## Agent Roster
- **claude-dispatcher** (active): Dispatcher + Researcher — .claude/CLAUDE.md
- **codex-builder** (active): Backend/Infra — AGENTS.md
- **gemini-builder** (active): Frontend/UI + QA — GEMINI.md
- **claude-secondary** (inactive): Role TBD — .claude/CLAUDE-SECONDARY.md

## Current milestone
- Foundation: repo skeleton + queues + make interface + v2.0 features working

## What works now (demo path)
- (TBD) Once a project exists, define the shortest demo flow here.

## Key decisions (top 5)
- WHAT+CONTEXT ticket design: Claude writes WHAT + research context, builders decide HOW
- Native instruction files replace clipboard prompt delivery
- Session logs enable cross-agent visibility (devos/logs/)
- Agent registry (devos/agents/registry.yaml) supports N agents
- Skills hints in tickets (advisory, graceful degradation)

## Active tickets (top 10)
- See tasks/QUEUE.yaml

## Open questions (top 10)
- See questions/QUEUE.md (filter: [open])

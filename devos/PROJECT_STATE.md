# Project State (SSOT)

## North Star
- (TBD) One sentence describing what we're building and why.

## Current Milestone
- Foundation / Operating System v2.0
- DoD:
  - SSOT files exist and are kept updated
  - make-based interface works (make start / make triage / make pr-check)
  - Native instruction files work (AGENTS.md, GEMINI.md auto-loaded)
  - Session log system operational (devos/logs/)
  - Agent registry configured (devos/agents/registry.yaml)

## What works now (demo path)
- (TBD)

## Agent Status
| Agent | Role | Status | Instruction File |
|-------|------|--------|------------------|
| claude-dispatcher | Dispatcher + Researcher | active | .claude/CLAUDE.md |
| codex-builder | Backend Builder | active | AGENTS.md |
| gemini-builder | Frontend Builder | active | GEMINI.md |
| claude-secondary | TBD | inactive | .claude/CLAUDE-SECONDARY.md |

## In progress
- [x] T-000 Bootstrap SSOT + Make + queues
- [x] T-001 Define session-start triage routine
- [x] v2.0 upgrade: native instruction files, logs, registry, skills integration

## Blockers / Questions
- See questions/QUEUE.md

## Decisions (latest)
- ADRs live under docs/ADR/
- v2.0: WHAT+CONTEXT ticket design (Claude researches, builders implement)
- v2.0: Native instruction files replace clipboard prompt delivery
- v2.0: Session logs enable cross-agent visibility

## Next dispatch hint
- When a concrete project appears: define demo path → generate first real tickets

# ADR-002: Session Log Sharing

## Status
Accepted (v2.0)

## Context
In v1.5, LLMs had no visibility into each other's sessions. Claude (Dispatcher) couldn't see what decisions Codex/Gemini made, what issues they encountered, or what context they had. This led to suboptimal ticket writing and missed context.

## Decision
Add `devos/logs/` directory where each agent writes a structured session log (max 50 lines) before ending. Claude reads these at boot to gain cross-agent context.

Format: `{YYYY-MM-DD}-{agent}-{ticket-ids}.md` with sections for Summary, Decisions Made, Questions Raised, Files Modified, and Handoff.

Handoff format extended from 3 lines to 4 lines (adding `Log:` line).

## Consequences
- Claude has cross-agent visibility for better ticket writing and triage
- Small token cost per session (~50 lines per log)
- Logs accumulate — `make log-archive` moves old logs to archive
- All agents must write logs (enforced via instruction files)

# Session Logs — Format Specification

## Purpose
Session logs enable cross-agent visibility. Each builder writes a log at session end.
Claude (Dispatcher) reads these at session start to understand builder context.

## File Naming
`{YYYY-MM-DD}-{agent}-{ticket-ids}.md`

Examples:
- `2026-03-15-codex-T020.md`
- `2026-03-15-gemini-T010-T011.md`
- `2026-03-15-claude-dispatcher.md`

## Required Sections

```
# Session Log: {AGENT} — {date}
Tickets: {ticket IDs worked on}

## Summary
- What was accomplished (2-3 bullets)

## Decisions Made
- Implementation choices and reasoning (helps Dispatcher understand context)

## Questions Raised
- Any new questions added to questions/QUEUE.md

## Files Modified
- List of files changed

## Handoff
Done: {ticket ID} — {what} — files: {list}
Next: {next ticket or "waiting for dispatch"}
Block: {Q-xxx or "none"}
Log: devos/logs/{filename} written
```

## Guidelines
- **Max 50 lines** per log (token-efficient)
- Focus on decisions and context, not code details
- Always include the Handoff section
- Logs older than 7 days: `make log-archive` moves them to `devos/logs/archive/`

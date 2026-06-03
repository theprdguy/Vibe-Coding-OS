# Session Log Format (v3.1)

Every agent writes a session log before ending.

## Naming Convention
```
devos/logs/{YYYY-MM-DD}-{agent}-{ticket-ids}.md
```

Agents: `claude1`, `claude2`, `codex`

Examples:
- `devos/logs/2026-03-19-claude1.md`
- `devos/logs/2026-03-19-claude2-T001-T002.md`
- `devos/logs/2026-03-19-codex-T003.md`

## Required Format (max 50 lines)

```markdown
# Session Log: {AGENT} — {YYYY-MM-DD}
Tickets: {ticket IDs, or "planning"}

## Summary
- What was accomplished (2-3 bullets)

## Decisions Made
- Key implementation or planning choices and reasoning

## Questions Raised
- Questions added to questions/QUEUE.md (or "none")

## Files Modified
- List of files changed (or "devos/ only" for Claude 1)

## Handoff
Done: {ticket ID or "planning"} — {what} — files: {list}
Next: {next ticket or "waiting for dispatch" or next planning step}
Block: {Q-xxx or "none"}
Log: devos/logs/{date}-{agent}-{tickets}.md written
```

## Why Session Logs
The main mechanism for cross-agent context sharing.
Claude 1 reads all builder logs at session start to understand what was done.
Keep them concise — Claude 1 reads many logs at once.

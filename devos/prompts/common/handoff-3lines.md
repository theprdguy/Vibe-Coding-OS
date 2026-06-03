# Handoff (4 lines)

Use this format when handing work to another model/session/person.

1. **Done**: what you completed (ticket id, files/PR, verification)
2. **Next**: the next concrete step (ticket id, file path)
3. **Block**: what is blocked and which question id (Q-xxx), include default if any
4. **Log**: path to your session log file

## Example
- Done: T-020 API skeleton + docs/API_CONTRACT.md, `bin/deos pr-check` green
- Next: T-021 add validation + tests in apps/api/src/auth/
- Block: Q-004 [open] refresh-token TTL (default: 14d)
- Log: devos/logs/2026-04-24-codex-T020.md

# Contributing

## Core rules
- Keep SSOT under `devos/`
- 1 ticket = 1 PR
- Update contracts when API/UI behavior changes
- Use A-Mode: queue questions in `devos/questions/QUEUE.md`
- New tickets must use `status: todo`
- Approval required before dispatch (`deos approve`)

## Workflow
1. Claude 1 decomposes PRD into tickets → saves to `devos/plans/pending/`
2. Review with `deos pending` → approve with `deos approve`
3. Builders work in parallel, each within their ticket's `files:` scope
4. Gate pipeline runs automatically (tests → secrets → agent-review → verify)
5. Claude 1 reviews PRs before merge

## Fork / adapt
If you fork this OS for your own use:
- Keep the `devos/` structure — it's the communication channel
- Wire `deos test` and `deos scan-secrets` to your actual stack
- Configure `deos.yaml` defaults and per-project `.deos.yaml` gate overrides
- Reset `devos/tasks/QUEUE.yaml` to empty (`tickets: []`)

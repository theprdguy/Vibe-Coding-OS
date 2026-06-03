# Pull Request

## Linked ticket

<!-- 1 PR = 1 ticket. Reference the ticket ID from devos/tasks/QUEUE.yaml. -->

Ticket: <!-- T-XXX -->

## What changed

<!-- Brief description of what this PR does. Focus on the "why", not the "what". -->

## Contract sync

<!-- If this PR changes API or UI behavior, the contract docs MUST be updated in the same PR. -->

- [ ] No API/UI contract changes in this PR
- [ ] `docs/API_CONTRACT.md` updated before code changes
- [ ] `docs/UI_CONTRACT.md` updated before code changes

## Gates

<!-- All gates must pass before merge. Check what ran. -->

- [ ] `deos pr-check` passed (secrets · scope · session log · TDD order)
- [ ] Tests pass (`python -m pytest`)
- [ ] Reviewer sub-agent verdict: **PASS** (no BLOCKERs)
- [ ] Security gate: N/A / passed (auto-triggered for auth/payment/permissions/external input)
- [ ] Visual review: N/A / passed (Gemini — for UI-affecting changes)

## Scope

<!-- Builder/CODEX: were all edits within the ticket's `files:` list? -->

- [ ] All changed files are within the ticket `files:` scope
- [ ] No files outside ticket scope were modified

## Waiver (if any)

<!-- If a gate was waived in Production mode, record it here with: who approved, what risk, follow-up ticket. -->

N/A

## Notes for reviewer

<!-- Anything the reviewer sub-agent or human reviewer should pay attention to. -->

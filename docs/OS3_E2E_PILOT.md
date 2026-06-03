# deos E2E Pilot

Status: ready-for-pilot

Purpose: verify that deos behaves like a product-building operating system, not
only a prompt/config collection.

This pilot is intentionally small. It should exercise the full operating loop
without requiring broad code refactors or edits under protected `devos/**`.

## Pilot Scope

Use one narrow, product-facing change with visible outcome and low blast radius.

Recommended shape:

- Mode: Productization or Production.
- Surface: one existing UI screen, one API endpoint, or one CLI workflow.
- Acceptance: clear user outcome, one success case, one failure/empty/error
  case, and a visible review artifact if UI is involved.
- Owners: Claude 1 decomposes and routes; Builder or Codex implements by ticket
  `files:` scope; Reviewer and Security remain independent; Gemini handles
  rendered visual review when UI output is material.

## Required Flow

1. PM states the product outcome in plain language.
2. Claude 1 converts it into a ticket with mode, gates, DOD, files, owner,
   test owner, and reviewer requirements.
3. Implementation owner completes only the scoped files.
4. Required tests/gates run.
5. Reviewer gives independent verdict.
6. Security runs when ticket risk requires it.
7. Gemini visual review runs for Production UI or material visual output.
8. PM decides only product judgment, visual taste, or explicit waiver.
9. Final status includes evidence: changed files, tests, reviews, waivers, and
   remaining risk.

## Pass Criteria

- PM can understand the ticket and final result without reading implementation
  details.
- No implementer self-approves its own work.
- Production work cannot pass without required tests, review, and visual review
  when applicable.
- Any temporary exception uses the waiver format and leaves an audit trail.
- Repeated visual-review findings escalate to PM confirmation instead of being
  silently re-approved.

## Stop Conditions

- Ticket ownership is ambiguous.
- Required gate or review is missing.
- UI visual result cannot be inspected.
- Security/privacy/auth risk appears without Security review.
- PM is asked to judge technical correctness instead of product judgment.

## Notes

- `bin/deos` is the primary CLI entry point.
- `bin/osn` and `osn.yaml` remain compatibility aliases for existing automation.
- `devos/**` wording can be updated later by a protected-area owner if desired;
  this pilot does not require it.

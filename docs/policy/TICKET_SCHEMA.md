# deos Ticket Schema Policy

Status: draft

Implements doctrine principles:

- Tickets are the deterministic input to dispatcher policy.
- Production `done` means product outcome plus required quality gates, not just
  implementation completion.
- PM should see product decisions and waivers, not raw technical noise.

## Recommended Fields

Existing fields such as `id`, `owner`, `status`, `goal`, `context`,
`constraints`, `dod`, `files`, `verify`, `deps`, `tdd`, `test_owner`,
`impl_owner`, `cross_model`, and `security_audit` remain valid.

Add or standardize these fields:

```yaml
mode: exploration | productization | production
user_outcome: string
risk_level: low | medium | high | critical
work_type: ui | api | data | infra | docs | policy | security | mixed
requires_visual_review: true | false
requires_security_review: true | false
requires_pm_acceptance: true | false
policy_class: hard | soft
waivers:
  - W-YYYYMMDD-001
  - id: W-YYYYMMDD-002
    ticket: T-XXX
    mode: production
    policy: required_visual_review
    requested_by: CODEX
    approved_by: PM
    decision: accept_with_waiver
    reason: string
    risk_accepted: string
    expires: after_ticket
    follow_up_ticket: T-YYY
    evidence:
      - path-or-log-reference
    created_at: YYYY-MM-DDTHH:MM:SSZ
reviewers:
  code: reviewer | codex | none
  security: security | codex | none
  visual: gemini | designer | none
```

`waivers` may contain string IDs as references, but a Production hard-policy
exception requires an inline waiver record with PM approval, risk, evidence, and
expiry/follow-up fields until a separate waiver registry exists.

## Status Model

Recommended status lifecycle:

```text
todo -> doing -> code_ready -> done
                 |
                 -> needs_pm
                 -> blocked
parked
```

Status meanings:

- `todo`: ready to be picked up when dependencies are satisfied.
- `doing`: currently assigned or in progress.
- `code_ready`: implementer has finished scoped work, but required independent
  gates, review, PM judgment, or waiver checks may remain.
- `needs_pm`: PM product judgment, visual taste decision, final acceptance, or
  waiver approval is required before continuing.
- `done`: all required gates, reviews, waivers, records, and archive conditions
  are satisfied.
- `blocked`: policy, technical, dependency, or implementation issue prevents
  progress.
- `parked`: intentionally deferred.

Production Mode rule:

> Implementers may move work to `code_ready`. `done` is granted only after
> dispatcher verifies required gates, independent review, security/visual review,
> PM decisions, waivers, and records.

## Production Validation Rules

For `mode: production`:

- `user_outcome` is required.
- DOD must include success and failure/error behavior where applicable.
- `files` must be explicit.
- `deps` must resolve across active queue and archive.
- `work_type: ui` requires `requires_visual_review: true` unless an inline
  `required_visual_review` waiver record is present.
- Auth, payment, privacy, permissions, destructive actions, credential handling,
  external input, or irreversible data changes require security review.
- Allowed hard-policy exceptions require a valid inline waiver record. A string
  waiver ID alone is a reference and does not satisfy Production exception
  enforcement.

## Productization Validation Rules

For `mode: productization`:

- Implementation should be limited to docs/planning artifacts unless explicitly
  scoped.
- Output should identify user outcome, open questions, risk level, work type,
  owners, files, gates, DOD, and PM decisions.
- A Productization ticket should not silently become a Production implementation
  ticket.

## Exploration Validation Rules

For `mode: exploration`:

- Keep gates light and report-oriented.
- Always enforce safety gates: secrets, destructive action, personal data,
  permission risk, file scope, and irreversible action.
- Completion should report what was learned and what product decision is next.

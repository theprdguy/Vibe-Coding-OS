# deos Waiver Format

Status: draft

Implements doctrine principles:

- Exceptions are allowed only when recorded.
- PM approves product/security/quality risk acceptance.
- Production `done` remains trustworthy because temporary passes are auditable.

## Waiver Schema

```yaml
id: W-YYYYMMDD-001
ticket: T-XXX
mode: production
policy: required_visual_review | security_review | test_failure | coverage | reviewer_request_changes | other
requested_by: role-or-agent
approved_by: PM
decision: accept_with_waiver
reason: string
risk_accepted: string
expires: never | YYYY-MM-DD | after_ticket
follow_up_ticket: T-YYY | none
evidence:
  - path-or-log-reference
created_at: YYYY-MM-DDTHH:MM:SSZ
```

Implementation note: until deos has a separate waiver registry, Production policy
exceptions must include the waiver record inline in the ticket `waivers:` list.
String waiver IDs are accepted as references, but they do not satisfy hard-policy
exception enforcement by themselves.

## Waivable Policies

The PM may approve temporary passage for:

- Non-critical test failure when product risk is understood and follow-up exists.
- Visual review issue that is subjective, acceptable for now, or blocked by
  product taste tradeoff.
- Coverage shortfall when the risk is accepted and follow-up exists.
- Soft policy warnings that would otherwise delay a time-sensitive decision.

## Non-Waivable Policies

Normal waiver must not bypass:

- Secret exposure.
- Owner mismatch.
- File scope violation.
- Unresolved dependencies.
- Destructive dirty-worktree risk.
- Unauthorized writes to protected areas.
- Known auth/payment/privacy/data-loss vulnerability without explicit security
  remediation or a higher-severity risk process.

## Temporary Pass Requirements

Temporary pass is allowed only when:

- PM approval is explicit.
- The waived policy is named.
- The accepted risk is concrete.
- Evidence is linked.
- Expiry or follow-up is defined.
- Final report includes the waiver and residual risk.

Without these fields, Production work should remain `needs_pm` or `blocked`, not
`done`.

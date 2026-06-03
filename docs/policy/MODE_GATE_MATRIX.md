# deos Mode Gate Matrix

Status: gate posture implemented (T-OS3-MODE-GATE-POSTURE) — `server/dispatcher.py` `_gate_is_blocking`

Implements doctrine principles:

- Exploration is PM-friendly and fast.
- Productization converts ideas into production-ready work.
- Production behaves like a strong development team.
- Hard policy fails closed in Production.
- Soft policy produces warnings, follow-up tickets, or cleanup requests.

## Modes

| Mode | Purpose | Completion Meaning |
| --- | --- | --- |
| `exploration` | Learn quickly through prototypes, UX sketches, technical probes, and product discovery | PM can make the next product decision |
| `productization` | Convert promising work into production-ready requirements, risks, owners, files, gates, and DOD | Work is ready to become Production tickets |
| `production` | Make product changes that can remain in the codebase and support future work | User outcome, implementation, required gates, reviews, waivers, and records are closed |

## Gate Matrix

| Gate | Exploration | Productization | Production |
| --- | --- | --- | --- |
| User outcome | Recommended | Required | Required |
| Acceptance criteria | Lightweight | Required | Required and testable |
| Success and failure DOD | Optional unless core behavior is validated | Required in ticket proposal | Required |
| Tests | Optional/report-only unless logic is central | Test strategy required | Required for covered business/API/data behavior |
| Reviewer | Optional/report-only | Readiness review recommended | Required; rejection blocks |
| Security | Required only for secrets, destructive action, privacy/auth/payment/external input | Risk identification required | Required when risk triggers apply; rejection blocks |
| Visual review | Optional/report-only | Required if defining Production UI acceptance | Required for Production UI unless waived |
| PM approval | Product direction only | Product intent and remaining decisions | Product judgment, visual taste, waiver, final acceptance when required |
| Waiver | Usually unnecessary; still required for material risk | Required for known Production policy exception | Required for any allowed hard-policy exception |
| File scope | Required | Required | Required; violation blocks |
| Dependencies | Required | Required | Required; unresolved deps block |
| Archive/audit record | Lightweight handoff | Planning record | Required session/handoff record |

## Report-Only Enforcement (implemented)

How "Optional/report-only" in the matrix above is actually enforced at dispatch
time (`server/dispatcher.py` `_gate_is_blocking` + `_run_gates`):

- **report-only** = the gate still *runs*; on failure the dispatcher records
  `[REPORTED] <gate>: <msg>` to the session log (and, for an `agent-review`
  gate, a real `WARNING` review verdict) and **lets the ticket reach `done`** —
  it does not block. It is *run-and-report*, never *skip*.
- **fail-closed allowlist (the safety model).** A failed gate is downgraded to
  report-only **only when both** hold: (1) the ticket `mode` is `exploration`
  or `productization`, **and** (2) the gate is *explicitly* recognized as a soft
  quality gate (an exact-membership soft name/type such as tests/lint/reviewer/
  visual, or a `verify` command whose tool is a known soft test runner). Every
  other gate **blocks in every mode** — this includes `pr-check`, any gate whose
  name/type/command/output contains a hard token (`secret`, `scan-secrets`,
  `gitleaks`, `detect-secrets`, `trufflehog`, `leaks found`, …), and any
  unrecognized / future / renamed gate. The default is **block**.
- **production / missing / unknown mode** → all gates block (legacy tickets
  without a `mode` field keep their original all-blocking behavior).
- **production review FAIL** blocks and does **not** record an auto-`WARNING`
  verdict (no laundering a rejected production review into `done`). The
  auto-`WARNING` path is reachable only for report-only (non-production) modes.

## Always-Blocking Safety Gates

Even in Exploration Mode, these block regardless of mode (hard floor, fail-closed):

- Secret exposure — incl. the default `pr-check` gate, which bundles the secret
  scan internally, and any other/renamed secret scanner. `pr-check` is NOT in
  any soft allowlist; it blocks in every mode.
- Destructive action.
- Personal data or permission incident.
- File scope violation.
- Irreversible change without explicit PM approval.

## Production Fail-Closed Defaults

In Production Mode, these should block by default:

- Required test failure.
- Reviewer `block` or unresolved `request_changes`.
- Required security review missing or rejected.
- Required visual review missing, `infra_failure`, or unresolved objective
  `request_changes`.
- Unresolved dependencies.
- Owner mismatch.
- File scope violation.
- Missing waiver for an allowed hard-policy exception.

## Visual Review Loop Policy

For Production UI:

1. First Gemini `request_changes` blocks.
2. Builder fixes the issue.
3. Second review of the same issue:
   - objective breakage remains: continue blocking;
   - taste/tradeoff remains: transition to PM judgment.
4. PM chooses either further iteration or `accept_with_waiver`.

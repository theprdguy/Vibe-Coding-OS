# deos Model Routing Policy

Status: draft

Implements doctrine principles:

- Use each LLM/tool where it is strongest.
- More Codex context should expand evidence gathering and hardening, not product
  decision authority.
- Builder and Codex are sibling implementation paths under deos, not parent/child
  of each other.

## Model Topology

```text
PM
└── Claude 1 main
    ├── builder sub-agent
    ├── reviewer sub-agent
    ├── designer sub-agent
    └── security sub-agent

Codex
└── external platform builder / code-level reviewer / cross-model reviewer
```

`builder` is a Claude in-session sub-agent owned by Claude 1 orchestration.
Codex is an external implementation and review path. Both can implement scoped
tickets, but ticket `files:` defines exclusive ownership for that ticket.

## Routing Defaults

| Work | Preferred Route | Reason |
| --- | --- | --- |
| Product ambiguity, user outcome, PM question framing | Claude 1 | Closest to product intent and PM interaction |
| Exploration UI prototype | Builder | Fast product-facing creation and iteration |
| New experience-heavy UI | Builder | Requires UX interpretation and product feel |
| Visual taste, brand tone, final UI preference | PM | Human product judgment |
| Rendered visual outcome review | Gemini | Screenshot/video visual perception |
| Objective visual bug fix after review | Codex or Builder by ticket scope | Usually concrete, testable, and pattern-bound |
| Existing-pattern Production UI hardening | Codex or Builder by ticket scope | Codex can handle code-heavy objective fixes when scope is clear |
| Backend/API/data/shared-package Production work | Codex preferred | Code-heavy, testable, edge-case-heavy |
| Tests, coverage, regression fixtures | Codex preferred | Evidence and verification specialist |
| Infra, scripts, CI/CD, dispatcher, gates, migrations | Codex preferred | Platform and mechanical implementation strength |
| Repo-wide pattern search or impact analysis | Codex preferred | Larger context and evidence gathering |
| Security/privacy/auth implementation support | Codex + Security | Codex investigates/remediates; Security reviews risk |
| Independent requirement/maintainability review | Reviewer | Separate quality judgment |

## Builder Scope To Keep

Builder should remain preferred for:

- Ambiguous product-facing UI.
- First-pass Exploration prototypes.
- New user flows where product feel is still being discovered.
- Work requiring fast Claude 1 back-and-forth.
- Experience-heavy implementation where acceptance cannot yet be reduced to
  objective checks.

## Codex Scope To Expand

Codex should become preferred for:

- Production backend/API/data/shared-package implementation.
- Test authoring and failure-case design.
- Existing-pattern UI hardening.
- Objective visual bug fixes.
- Loading, empty, error, and success state completion when acceptance is clear.
- Accessibility/responsive fixes with concrete evidence.
- Failure analysis, flaky tests, rollback/race/drift investigation.
- Policy enforcement implementation: ticket schema validation, waiver
  enforcement, mode gates, visual review wiring.

## Authority Boundary

Codex token abundance changes work allocation, not product authority.

Codex may:

- Read more context.
- Produce stronger evidence.
- Implement code-heavy scoped tickets.
- Review large diffs and failure modes.
- Recommend routing changes.

Codex must not:

- Decide product direction alone.
- Make final visual taste calls.
- Widen ticket scope silently.
- Override reviewer/security verdicts alone.
- Bypass dispatcher state transitions.
- Treat `code_ready` as `done`.

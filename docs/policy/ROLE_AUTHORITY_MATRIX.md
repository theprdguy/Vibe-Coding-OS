# deos Role Authority Matrix

Status: draft

Implements doctrine principles:

- PM burden reduction: PM handles product judgment and waivers, not low-level
  technical verification.
- Bounded collaborators: every LLM/tool role has limited authority.
- Reviewer independence: reviewers request changes or block; they do not
  silently become implementers.
- Deterministic dispatcher: dispatcher enforces policy and state, not product
  taste.

## Authority Matrix

| Role | May Decide | May Modify | May Block | Must Escalate To PM | Must Not Do |
| --- | --- | --- | --- | --- | --- |
| PM | Product direction, priority, visual taste, final product judgment, waiver approval | Product requirements and explicit approvals | Any product direction or risk acceptance question | n/a | Be forced to verify low-level code, tests, or gate output |
| Product Planner | User outcome, open questions, acceptance criteria drafts, ticket decomposition proposal | Planning docs and ticket drafts within assigned scope | Productization readiness when requirements are ambiguous | Product ambiguity, scope change, irreversible product decision | Make irreversible product decisions without PM approval |
| Tech Planner / Architect | Technical options, risk controls, API/data/test/security recommendations | Architecture notes and scoped planning docs | Production readiness when architecture or risk is unclear | Major architecture tradeoff, user-visible limitation, material cost/security risk | Make broad architecture decisions without rationale and approval |
| Builder | Implementation details inside ticket scope | Only files assigned by ticket `files:` | Self-block when scope, dependency, or implementation risk is found | Scope expansion, product ambiguity, waiver need | Modify files outside scope, bypass review, mark Production work done alone |
| Codex | Infra, tests, scripts, migrations, mechanical edits, failure analysis, code-level review | Only files assigned by ticket `files:`; no `devos/**` unless explicitly authorized outside AGENTS.md protection | Test/gate failure, file-scope risk, rollback risk, code-level uncertainty | Product decision, architecture decision, waiver need | Decide product direction alone, widen scope silently |
| Reviewer | Requirement fit, DOD coverage, test adequacy, maintainability verdict | Read-only by default | DOD miss, inadequate test/error coverage, maintainability regression | Product taste or tradeoff that cannot be objectively resolved | Quietly fix its own findings in the same review pass |
| Security | Secrets/auth/permission/privacy/external-input/prompt-boundary verdict | Read-only by default | High-risk security/privacy issue, missing required security review, unsafe waiver | Risk acceptance or security/privacy waiver | Rely only on free-form LLM judgment when deterministic checks exist |
| Gemini Visual Reviewer | Rendered UI outcome verdict | None | Objective visual breakage, blank screen, clipping, overlap, responsive failure, missing required state | Visual taste, brand/tone preference, ambiguous tradeoff, repeated unresolved issue after attempted fix | Approve code, security, business logic, or product strategy |
| Dispatcher | Routing, dependency checks, owner/file scope, gates, status transitions, archive | SSOT/state files only through defined commands/policies | Hard policy violation, missing required gate, missing waiver | Product judgment, waiver approval, final taste decision | Make subjective product/design judgments |

See also: `docs/policy/MODEL_ROUTING_POLICY.md` for Builder vs Codex routing
defaults. Builder is a Claude in-session sub-agent. Codex is an external
platform builder and code-level review path. They are sibling implementer paths;
ticket `files:` defines exclusive ownership for each task.

## PM Escalation Rules

Escalate to PM when one of these is true:

- Product intent is ambiguous.
- Scope needs to expand beyond approved ticket files or DOD.
- A policy waiver is required.
- UI judgment is about taste, brand, tone, or preference rather than objective
  breakage.
- Security, privacy, data loss, payment, auth, or irreversible behavior requires
  risk acceptance.
- Two visual review passes report the same non-objective issue and further
  iteration needs product judgment.

## Non-Waivable Authority Boundaries

These are hard boundaries and should not be bypassed by normal waiver:

- Secret exposure.
- Owner mismatch.
- File scope violation.
- Unresolved dependencies.
- Destructive action with dirty worktree risk.
- Unauthorized writes to protected areas such as `devos/**` for Codex.

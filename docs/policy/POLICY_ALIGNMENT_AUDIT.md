# deos Policy Alignment Audit

Status: draft
Date: 2026-05-15

## Purpose

Audit current deos prompts, config, and selected dispatcher behavior against:

- `docs/OPERATING_DOCTRINE.md`
- `docs/policy/ROLE_AUTHORITY_MATRIX.md`
- `docs/policy/MODEL_ROUTING_POLICY.md`
- `docs/policy/MODE_GATE_MATRIX.md`
- `docs/policy/TICKET_SCHEMA.md`
- `docs/policy/WAIVER_FORMAT.md`
- `docs/policy/GEMINI_VISUAL_REVIEW_SCHEMA.md`

This is a planning artifact only. It does not authorize broad code refactors.
Implementation should be split into narrow tickets.

## Scope Read

- `AGENTS.md`
- `README.md`
- `START_HERE.md`
- `.claude/CLAUDE.md`
- `.claude/agents/{builder,builder-haiku,reviewer,designer,security}.md`
- `.claude/settings.json`
- `.claude/hooks/guard-no-impl.sh`
- `osn.yaml`
- selected read-only sections of `server/{dispatcher,cli,ssot}.py`
- selected read-only sections of `server/{gemini_dispatcher,gemini_handoff}.py`

## Summary

The doctrine and policy docs are now clearer than the active prompts/configs.
The largest gaps are:

1. Active prompts still assume the old owner/status model in several places.
2. Dispatcher marks tickets `done` directly after gates instead of separating
   implementer completion (`code_ready`) from product completion (`done`).
3. Production visual/user-outcome review currently has fail-open paths when
   screenshot tooling is missing or capture fails.
4. Builder/Codex routing policy is not reflected in active prompts.
5. Waiver and mode-specific gate concepts exist only in policy docs, not schema
   or enforcement.

## Implementation Notes

2026-05-15:

- `T-POLICY-ALIGN-01` has been applied directly to active non-`devos/**` files.
- Updated active owner wording from `CLAUDE2` to `BUILDER`/`CODEX`.
- Removed the deleted `scripts/preflight-claude2.sh` SessionStart hook from
  `.claude/settings.json`.
- Updated planner guard messages to route implementation work to BUILDER or
  CODEX.
- Updated `.claude/CLAUDE.md` status guidance for the active lifecycle:
  `code_ready` and `needs_pm` are now valid SSOT statuses.
- `T-POLICY-ALIGN-02` has been applied directly to active non-`devos/**` files.
- Updated Builder, Builder-Haiku, AGENTS.md, and `osn.yaml` routing wording:
  Builder stays preferred for ambiguous/product-facing UI, Exploration
  prototypes, and new UX flows; Codex is preferred for code-heavy Production
  work, tests, infra, migrations, policy enforcement, existing-pattern UI
  hardening, objective visual bug fixes, and failure analysis.
- `T-POLICY-ALIGN-04` has been partially implemented in `server/ssot.py` with
  focused unit coverage.
- Added staged policy-field validation: legacy tickets without `mode` remain
  compatible; tickets that opt into `mode: production` must include
  `user_outcome`, `risk_level`, `work_type`, `policy_class`, non-empty `dod`,
  non-empty `files`, and list `deps`.
- Added compatibility mapping where `requires_security_review: true` sets legacy
  `security_audit: true`.
- Production UI tickets now require `requires_visual_review: true` unless a
  waiver id is present.
- `append_tickets()` validates new tickets before writing them.
- `T-POLICY-ALIGN-03` has been implemented in `server/ssot.py` and
  `server/dispatcher.py` with focused regression coverage.
- Added `code_ready` and `needs_pm` as valid SSOT statuses.
- Dispatcher now marks successful agent handoff as `code_ready` before running
  gates/reviews, then marks `done` only after gates and required user outcome
  review pass.
- Missing non-interactive user outcome decision now transitions to `needs_pm`
  instead of `blocked`, with user-facing copy pointing to `bin/deos user-review`.
- Transition history records `code_ready -> done` for successful dispatcher
  closure.
- `T-POLICY-ALIGN-05` has been partially implemented in `server/ssot.py` with
  focused unit coverage.
- Waiver string IDs remain accepted as references, but Production policy
  exceptions require inline waiver records.
- Inline waiver records require PM approval, `accept_with_waiver`, reason,
  accepted risk, evidence, created timestamp, and expiry/follow-up.
- Non-waivable policies such as secret exposure, owner mismatch, file scope
  violation, unresolved dependencies, destructive dirty-worktree risk,
  unauthorized protected writes, and material auth/payment/privacy/data-loss risk
  are rejected at schema validation.
- Production UI visual-review bypass now requires a valid inline
  `required_visual_review` waiver record.

F-01, F-02, F-03, F-04, F-06, F-07, and F-10 below are retained as audit history, but their active
prompt/config or initial schema findings have been addressed.

## Findings

### F-01: Active prompt still names `CLAUDE2` as implementation owner

Current evidence:

- `.claude/CLAUDE.md:23` says implementation owner is `CLAUDE2 or CODEX`.
- `.claude/hooks/guard-no-impl.sh:58` recommends tickets owned by `CLAUDE2/CODEX`.
- `.claude/hooks/guard-no-impl.sh:68` lists `CLAUDE2`, `CODEX`, or `GEMINI`.
- `AGENTS.md:21` says UI scope is shared with `CLAUDE2`.

Policy conflict:

- `MODEL_ROUTING_POLICY.md` defines Builder as the Claude in-session implementer
  path and Codex as the external platform/code-heavy path.
- `CLAUDE2` is sunset and should not be recommended for new tickets.

Recommended change:

- Replace active owner guidance with `BUILDER`, `CODEX`, and explicit
  role-based routing.
- Keep historical `claude2/` directory references only when labeled historical.

Owner:

- CLAUDE1 for `.claude/**` and prompt/config wording.
- CODEX may provide audit/review only unless explicitly scoped.

Suggested ticket:

- `T-POLICY-ALIGN-01`: Prompt/config wording alignment for current owner model.

### F-02: Status model lacks `code_ready` and `needs_pm`

Current evidence:

- `.claude/CLAUDE.md:47` valid statuses are only `todo`, `doing`, `done`,
  `blocked`, `parked`.
- `server/ssot.py:27` `VALID_STATUSES` has the same five states.
- `server/dispatcher.py:897` and `server/dispatcher.py:952` mark tickets done
  after gates pass.

Policy conflict:

- `TICKET_SCHEMA.md` recommends `code_ready` and `needs_pm`.
- Production `done` should mean required gates, independent review, PM decisions,
  waivers, and records are closed.

Recommended change:

- Add `code_ready` and `needs_pm` to status schema.
- Implementers should reach `code_ready`.
- Dispatcher should grant `done` only after policy gates and required decisions.

Owner:

- CODEX for `server/**` and tests.
- CLAUDE1 for prompt/status wording.

Suggested ticket:

- `T-POLICY-ALIGN-03`: Status lifecycle migration and transition enforcement.

### F-03: Builder/Codex routing policy is not reflected in active prompts

Current evidence:

- `.claude/agents/builder.md:4` describes Builder as app + platform implementer
  for backend, GUI, and business logic.
- `.claude/CLAUDE.md:16` routes `apps/`, `packages/`, `infra/`, `scripts/`,
  and `tests/` to builder.
- `osn.yaml:24` describes Codex as infra/data/tests/mechanical and shared
  `apps/web/` only.

Policy conflict:

- `MODEL_ROUTING_POLICY.md` shifts more code-heavy Production work to Codex:
  backend/API/data/shared packages, tests, infra, migrations, objective visual
  fixes, and existing-pattern UI hardening.

Recommended change:

- Update active prompts to route ambiguous/new product-facing UI to Builder.
- Route code-heavy, test-heavy, backend/API/data/shared-package, infra, and
  policy-enforcement work to Codex by default.
- Preserve ticket `files:` as exclusive ownership per task.

Owner:

- CLAUDE1 for active prompt changes.
- CODEX may implement routing enforcement only after ticket schema changes.

Suggested ticket:

- `T-POLICY-ALIGN-02`: Model routing prompt/config alignment.

### F-04: Production mode fields are not part of active ticket schema

Current evidence:

- `.claude/CLAUDE.md` ticket quality section does not require `mode`,
  `user_outcome`, `risk_level`, `work_type`, `requires_visual_review`,
  `requires_security_review`, `requires_pm_acceptance`, `policy_class`, or
  `waivers`.
- `server/ssot.py` normalizes existing owner/test/impl fields but does not
  validate doctrine mode fields.

Policy conflict:

- `TICKET_SCHEMA.md` defines these as standard fields for deterministic policy
  enforcement.

Recommended change:

- Add schema validation in stages:
  1. warn-only for existing tickets;
  2. required for new Production tickets;
  3. enforcement in dispatcher gates.

Owner:

- CODEX for `server/ssot.py`, `server/dispatcher.py`, tests.
- CLAUDE1 for prompt/ticket-writing instructions.

Suggested ticket:

- `T-POLICY-ALIGN-04`: Ticket schema validation for mode and risk fields.

### F-05: Visual/user-outcome review has fail-open capture paths

Status: applied 2026-05-15 for required Production visual review.

Original evidence:

- `server/dispatcher.py:1699` skips user-outcome review when `screenshot_tool`
  is absent.
- `server/dispatcher.py:1703` treats failed capture as a pass path by returning
  success with the warning message.
- `server/dispatcher.py:1728`, `1744`, and `1750` warn and skip when tooling is
  unavailable, times out, or capture fails.

Policy conflict:

- `GEMINI_VISUAL_REVIEW_SCHEMA.md` says Production UI capture failure is
  `infra_failure`, not pass.
- `MODE_GATE_MATRIX.md` says required Production visual review missing or failed
  should block unless waived.

Recommended change:

- Use `mode` and `requires_visual_review` to distinguish Exploration/report-only
  from Production/fail-closed.
- For Production UI, missing/capture-failed visual review should block or move
  to `needs_pm` only through waiver flow.

Owner:

- CODEX for dispatcher/gate changes and tests.

Suggested ticket:

- `T-POLICY-ALIGN-07`: Production visual review fail-closed enforcement.

Implementation note:

- `server/dispatcher.py` now keeps non-Production visual review report-only, but
  blocks `mode: production` + `requires_visual_review: true` when screenshot
  tooling is missing or capture fails.

### F-06: User review command copy still references removed Make workflow

Current evidence:

- `server/dispatcher.py:1719` tells the user to run `make user-review T=...`.
- `START_HERE.md:89` states Makefile was removed and `bin/deos` replaces it.
- `server/cli.py` exposes `bin/deos user-review`.

Policy conflict:

- PM-friendly operation should not show stale commands.

Recommended change:

- Change user-facing command output to `bin/deos user-review T-XXX`.

Owner:

- CODEX for `server/dispatcher.py` and tests.

Suggested ticket:

- Include in `T-POLICY-ALIGN-07` or a small `T-POLICY-ALIGN-07A` copy-fix ticket.

### F-07: Waiver policy has no active representation

Current evidence:

- No active prompt/config schema for waiver ID, waiver evidence, expiry, or
  follow-up.
- Dispatcher has no visible waiver lookup before blocking/final `done`.

Policy conflict:

- `WAIVER_FORMAT.md` requires explicit waiver records for temporary Production
  passes.

Recommended change:

- Add waiver schema and validation.
- Non-waivable policy classes should remain blocked.
- Allowed waivers should move tickets out of `needs_pm` only when required
  fields are present.

Owner:

- CODEX for parser/enforcement/tests.
- CLAUDE1 for PM-facing waiver instructions.

Suggested ticket:

- `T-POLICY-ALIGN-05`: Waiver validation and non-waivable policy enforcement.

### F-08: Security review trigger fields are split across old and new concepts

Current evidence:

- Existing active concept is `security_audit`.
- `osn.yaml` has tag-based `auth` security gate.
- New policy docs use `requires_security_review`.

Policy conflict:

- The policy should avoid two divergent ways to express the same requirement.

Recommended change:

- Define compatibility:
  - `requires_security_review: true` should imply `security_audit: true`.
  - high-risk keywords should still auto-force security review.
  - legacy `security_audit` remains accepted during migration.

Owner:

- CODEX for schema/gate compatibility.
- CLAUDE1 for ticket-writing prompt update.

Suggested ticket:

- Include in `T-POLICY-ALIGN-04` and `T-POLICY-ALIGN-06`.

### F-09: Dependency check still appears queue-only in dispatcher path

Current evidence:

- `server/dispatcher.py:337` reads active queue.
- `server/dispatcher.py:385` calls `_check_deps(data, deps)`.
- `server/dispatcher.py:699` checks dependency status only against the supplied
  `tickets_by_id` map.
- `AGENTS.md:13` says ticket lookup should search QUEUE then ARCHIVE.

Policy conflict:

- Production hard policy requires dependency resolution to be deterministic and
  archive-aware.

Recommended change:

- Ensure dispatcher dependency checks use active queue plus archive status,
  preferably through existing SSOT helpers.

Owner:

- CODEX.

Suggested ticket:

- `T-POLICY-ALIGN-06`: Mode gate/dependency enforcement hardening.

### F-10: `.claude/settings.json` still references deleted preflight script

Current evidence:

- `.claude/settings.json:14` runs `bash scripts/preflight-claude2.sh --advisory`.
- `START_HERE.md:89` states `.claude-b/` and CLAUDE2 support are removed.
- Prior handoff indicates `scripts/preflight-claude2.sh` was deleted.

Policy conflict:

- PM-friendly startup should not fail or warn from stale sunset wiring.

Recommended change:

- Remove or replace the stale SessionStart hook.

Owner:

- CLAUDE1 for `.claude/settings.json`.

Suggested ticket:

- Include in `T-POLICY-ALIGN-01`.

### F-11: Gemini infrastructure exists but is not yet the Production UI review schema

Current evidence:

- `server/gemini_dispatcher.py` already has a fail-open/fail-closed concept using
  `gui_review_required`.
- `server/cli.py` exposes `bin/deos gemini ...` subcommands.
- New policy docs define `requires_visual_review`, review rounds, `infra_failure`,
  same-issue escalation, and PM judgment.

Policy conflict:

- Existing Gemini integration is useful but not wired to the new visual review
  schema or `needs_pm` flow.

Recommended change:

- Map existing Gemini dispatcher output to
  `pass | request_changes | needs_human_judgment | infra_failure`.
- Track review round and repeated-issue escalation.
- Use `requires_visual_review` for Production UI.

Owner:

- CODEX for Gemini wiring and tests.

Suggested ticket:

- `T-POLICY-ALIGN-08`: Gemini visual review schema integration.

### F-12: Historical `os2`/`osn` wording is low-risk after OS3 rename

Current evidence:

- Active dispatcher lock path now uses `.os3`.
- Active env vars now prefer `OS3_*` names with legacy `OS2_*` fallback.
- README deliberately mentions old `os2` migration history.
- Some test names, ticket IDs, and legacy template references still contain
  `OSN`/`osn`; these are audit/history compatibility references.

Policy conflict:

- Low. Historical references are acceptable when clearly labeled. Active
  commands/paths that surface to users should prefer OS3.

Recommended change:

- Do not rename historical ticket IDs such as `T-OSN-*`.
- Keep `bin/osn` and `osn.yaml` as compatibility aliases unless a dedicated
  migration ticket removes them with downstream automation coverage.

Owner:

- CODEX for code comments/paths and tests when scoped.
- CLAUDE1 for protected `devos/**` wording if needed.

Suggested ticket:

- None required for active OS3 rename outside protected `devos/**`.

## Recommended Implementation Ticket Order

1. `T-POLICY-ALIGN-01` — Prompt/config wording alignment.
   - Owner: CLAUDE1.
   - Scope: `.claude/CLAUDE.md`, `.claude/settings.json`,
     `.claude/hooks/guard-no-impl.sh`, selected docs.
   - Goal: remove active CLAUDE2 owner guidance and stale deleted hook.

2. `T-POLICY-ALIGN-02` — Model routing prompt/config alignment.
   - Owner: CLAUDE1.
   - Scope: `.claude/agents/builder.md`, `.claude/agents/builder-haiku.md`,
     `AGENTS.md`, `osn.yaml` notes.
   - Goal: reflect Builder vs Codex routing defaults.

3. `T-POLICY-ALIGN-04` — Ticket schema validation. Applied 2026-05-15.
   - Owner: CODEX.
   - Scope: `server/ssot.py`, `server/dispatcher.py`, tests.
   - Goal: add mode/risk/work-type/security/visual fields with staged
     enforcement.

4. `T-POLICY-ALIGN-03` — Status lifecycle migration. Applied 2026-05-15.
   - Owner: CODEX.
   - Scope: `server/ssot.py`, `server/dispatcher.py`, `server/cli.py`, tests.
   - Goal: add `code_ready` and `needs_pm`; reserve `done` for completed policy
     closure.

5. `T-POLICY-ALIGN-05` — Waiver validation and enforcement. Partially applied 2026-05-15.
   - Owner: CODEX.
   - Scope: waiver parser/storage decision, dispatcher validation, tests.
   - Goal: allow temporary pass only with explicit auditable waiver.

6. `T-POLICY-ALIGN-06` — Mode gate and archive-aware dependency enforcement. Applied 2026-05-15.
   - Owner: CODEX.
   - Scope: dispatcher gate resolution, dependency lookup, tests.
   - Goal: Production fail-closed gates and dependency correctness.

7. `T-POLICY-ALIGN-07` — Production visual review fail-closed. Applied 2026-05-15.
   - Owner: CODEX.
   - Scope: user outcome review path, CLI copy, tests.
   - Goal: no fail-open capture path for required Production UI visual review.

8. `T-POLICY-ALIGN-08` — Gemini visual review schema integration. Applied 2026-05-16.
   - Owner: CODEX.
   - Scope: Gemini dispatcher/handoff mapping, review output schema, tests.
   - Goal: map rendered review to policy verdicts and repeated-issue handling.
   - Result: required GUI review now validates schema, blocks non-pass verdicts,
     persists issue fingerprints, moves repeated taste-only issues to PM
     judgment, and keeps repeated objective issues blocking.

9. `T-POLICY-PILOT-01` — Small end-to-end pilot.
   - Owner: CLAUDE1 orchestration with Builder/Codex/Gemini as routed.
   - Goal: run one small feature through Productization and Production; measure
     PM interruptions, review usefulness, gate friction, visual review usefulness,
     and production readiness.

## Notes On Ownership

- Codex should not edit `devos/**` under current `AGENTS.md`.
- Prompt/config files under `.claude/**` are best handled by CLAUDE1 unless a
  ticket explicitly grants Codex that scope.
- Server/gate/schema implementation belongs to CODEX when scoped in ticket
  `files:`.
- UI product taste remains PM authority.

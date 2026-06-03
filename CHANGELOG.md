# Changelog

All notable changes to deos are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

---

## [v4.0.0] — 2026

### Added
- **In-session sub-agent model** — "Claude 2 (Account B)" sunset and folded into the `builder` sub-agent. One account; lower latency; same separation of duties.
- **Read-only review board** — `reviewer`, `designer`, and `security` sub-agents now run with read-only tool allowlists (structural objectivity enforced at the permission layer, not by convention).
- **Operating modes** — `exploration` / `productization` / `production` set the gate posture (fail-closed); enforced in the dispatcher. See `docs/policy/MODE_GATE_MATRIX.md`.
- **`deos` CLI** — single entry point `bin/deos` replaces `make` targets and `os2.yaml`. Unified commands: `dispatch`, `approve`, `queue`, `status`, `pr-check`, `archive`, `dashboard`, `feedback`, `open`.
- **Host-OS architecture** — one host engine, many independent project repos under `projects/`. `deos open <name>` injects host settings into any project session.
- **Cross-model safety net (b')** — quantitative trigger for a Codex second opinion (BLOCKER, low confidence, security finding, high-risk ticket).
- **Local dashboard** — `deos dashboard`, a build-free read-only kanban at `http://127.0.0.1:8787`.
- **OS-feedback loop** — `deos feedback "..."` captures OS friction into `devos/os-feedback/INBOX.md`; reviewed at session start; converted to tickets in a periodic pass.
- **Incident → Locked Decision pipeline** — when something breaks, the fix becomes an enforced `D-XX` Locked Decision; violation is an automatic reviewer BLOCKER.
- **Per-ticket `_transition_history`** — append-only audit trail on every status change (actor + reason + timestamp).
- **`drop-in` mode** — `scripts/dropin-init.sh` scaffolds deos into any existing repo in ~5 minutes.

### Changed
- `make` / `Makefile` removed; all orchestration through `bin/deos`.
- `os2.yaml` → `osn.yaml` (compatibility alias; same format).
- `.claude-b/` (Account B) directory structure removed (W6 sunset).
- Gate posture is now mode-aware and fail-closed (report-only only in exploration/productization for explicitly-soft gates).
- Ticket schema extended: `mode`, `ethos`, `security_audit`, `cross_model`, `_transition_history`, `verify_preflight`, `paired_run`.

### Security
- Always-on safety floor: secret exposure, owner mismatch, file-scope violation, unresolved deps, and destructive actions with a dirty tree block in every mode (no waiver path).
- Security sub-agent auto-invoked for tickets touching auth / payment / permissions / external input.

---

## [v3.4]

### Added
- Adversarial prompt suite: PRD intake checklist, adversarial PR review, security audit (OWASP A01–A10 + STRIDE), cross-model review, goal-backward verification, scope-reduction lint.
- `ETHOS.md` tiebreaker: Iron Laws + Boil-the-Lake + non-developer protection principles.
- Dispatcher hardening.
- `preflight-codex.sh` pre-dispatch checks.

---

## [v3.3]

### Added
- Skills integration via the Anthropic superpowers plugin (`brainstorming`, `writing-plans`, `dispatching-parallel-agents`, `systematic-debugging`, `requesting-code-review`, `verification-before-completion`).
- Structured prompt library under `devos/prompts/`.
- Expanded operational rules.

---

## [v3.2]

### Added
- Testing maturity Phase 3.5.
- Stage 0 baseline gates.
- Branch-coverage enforcement (Line ≥70% / Branch ≥60%).

---

## [v3.1]

### Added
- Three-agent setup with role restructure: planner / app builder / platform builder.

---

## [v3.0]

### Added
- Python dispatcher.
- Plans approval workflow (`devos/plans/pending` → `approved`).
- `BUILDER_GUIDE.md` and `OPERATION_GUIDE.md`.

---

## [v2.0]

### Added
- Native instruction files (forerunner of `devos/`).
- Session logs.
- Agent registry.
- WHAT + CONTEXT ticket schema.

---

## [v1.x]

### Added
- Initial token-efficient multi-agent harness.

---

[v4.0.0]: https://github.com/theprdguy/deos/releases/tag/v4.0.0

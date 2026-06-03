# Project-Scoped pr-check & Sub-Agent Availability — Design

- Date: 2026-05-27
- Status: approved (design)
- Scope: OS3 engine — `server/cli_gates.py` (pr-check), project session launch (`server/launcher.py` / project setup). Host-OS migration scoping gap.

## Problem

A bollard project ticket (`T-BOLLARD-CLIP-01`) was code-complete (12/12 tests
pass, reviewer findings resolved) but could not reach `done` because the
`pr-check` gate's `scan-secrets` step FAILED on a finding in the **host** repo
(`~/dev-os/devos/questions/QUEUE.md:116`, commit `caf6d2c`) — a file unrelated to
bollard. Separately, the dispatch used `general-purpose` (for builder) and
`Explore` (for reviewer) instead of the named `builder`/`reviewer` sub-agents.

Both are host-OS scoping gaps: a project's quality work is being coupled to the
host repo's state and config.

## Root cause (verified)

**Gate contamination.** The failing gate was `pr-check` (`$HOME/dev-os/bin/osn
pr-check` → `cli_gates.handle_pr_check`). `handle_pr_check` runs
`gitleaks git --no-banner --redact .` with `cwd = Path.cwd()` (cli_gates.py:17,25-29)
and **ignores `--project` entirely** (it never calls `resolve_paths`). Because:
- the interactive orchestrator session's Bash cwd resets to the session base
  between commands (observed harness behavior), and the base is the host root,
- `os3 pr-check --project bollard` therefore ran gitleaks against `~/dev-os`
  (the host repo), where the dummy-token false-positive lives in tracked history,
- bollard is a **separate git repo, gitignored from host, and clean**
  (`gitleaks git .` in bollard → "0 commits scanned, no leaks", exit 0).

So pr-check scanned the wrong repo and failed on a stale host finding, never
examining bollard's actual code. The standalone `secrets`/`scan-secrets` gate
(`_run_command_gate`, `cwd=paths["root"]`) IS project-scoped; only the `pr-check`
aggregate gate is not.

**Secondary — 0-commit blind spot.** `gitleaks git .` scans committed history.
A freshly-checked-out project with 0 commits scans nothing, so a project-scoped
fix using only `git` mode would pass vacuously on uncommitted code.

**Agent unavailability.** `builder`/`reviewer` are invoked as **in-session
`Agent()` calls** (route_by_owner: `BUILDER` → `in_session_message`; only `CODEX`
→ `subprocess_codex`). The interactive orchestrator session is launched by
`os3 open` (`launcher.py:37-39`), which injects only
`--settings <host>/.claude/settings.json` — **not agents**. A project is a
separate git repo with no project-local `.claude/agents/`, so the named agents
are unresolved and the session falls back to generic agents. This weakens the
read-only-enforced reviewer objectivity required by Rule 7.

(Note: the dispatcher's CODEX subprocess is not the locus — CODEX does not use
Claude sub-agents.)

> **CORRECTION (2026-05-30) — this "Agent unavailability" premise is FALSE; Unit B is superseded.**
> Empirically verified (claude 2.1.158): Claude Code discovers project sub-agents by walking UP
> from cwd, so the host `~/dev-os/.claude/agents/` IS inherited by a sub-project session — a clean
> `~/dev-os/projects/*` dir with its own `.claude/` but no `agents/` resolves the host
> builder/builder-haiku/designer/reviewer/security set. `--settings` injection is still required
> (settings do NOT inherit), but agents DO. The symlink workaround was unnecessary and actively
> harmful (absolute-path links pollute the separate project git repos). The actual defect was
> `launcher.py::_ensure_project_agents` auto-creating those symlinks on every `os3 open`; it was
> removed in **T-OSN-LAUNCHER-AGENTS-NOSYMLINK** (2026-05-30). Do NOT implement Unit B. (Caught by
> the OS-feedback loop — INBOX #1.)

## Decision

Fix all three (user-selected full scope), implemented as **host-OS tickets
dispatched in `~/dev-os`** per Rule 1/10 (this design session does not hand-edit
engine code). Two independent units.

### Unit A — `pr-check` project-scoping + working-tree scan (`server/cli_gates.py`)

- `handle_pr_check` resolves the target project root explicitly via the same
  mechanism as `_load()` (`resolve_paths(project, cwd=Path.cwd())`, honoring
  `--project` and the cwd `.os3.yaml` marker). It MUST NOT rely on ambient
  `Path.cwd()` for the scan target.
- Secret scan covers the **working tree**: run `gitleaks dir <project_root>`
  (filesystem scan; valid in installed gitleaks 8.30.1). Additionally run
  `gitleaks git <project_root>` when the project repo has ≥1 commit (history
  coverage for committed-then-removed secrets). A finding from either fails the
  gate.
- The baseline check scripts (`check-contract-sync.sh`, `check-ticket-scope.sh`,
  `check-session-log.sh`, `check-tdd-first-commit.sh`) are sourced from
  **host** (`<host>/scripts/`) but run against the resolved project root passed
  explicitly (e.g. `cwd=project_root`), not ambient `Path.cwd()`.
- If project resolution fails, exit non-zero with a clear message; never silently
  scan the host or ambient cwd.
- Owner: CODEX (gate/infra).

### Unit B — host sub-agents available to project sessions (launcher / project setup)

> **SUPERSEDED 2026-05-30 — do NOT implement. See CORRECTION above: host agents already inherit via
> upward `.claude/agents` discovery; the symlink approach was removed as a bug (T-OSN-LAUNCHER-AGENTS-NOSYMLINK).**

- The locus is the **interactive session launch** (`os3 open` /
  `server/launcher.py` / `os3 register` project setup), NOT the dispatcher.
- Make the host sub-agents (`<host>/.claude/agents/{builder,reviewer,designer,
  security}.md`) resolvable in a project-cwd session. **Preferred mechanism:
  symlink** the host agents into the project's `.claude/agents/` at project
  setup/registration time (deterministic; precedent: the meation project already
  uses symlinked agent copies). Alternative considered and rejected as default:
  `CLAUDE_CONFIG_DIR=<host>/.claude` (adopts the entire host config — credentials,
  todos, settings — too broad a side effect).
- **Spike (first step of the ticket):** confirm that with the chosen mechanism,
  `Agent(subagent_type="builder")` and the reviewer actually resolve in a session
  whose cwd is a project dir. If the symlink approach does not resolve, fall back
  to `CLAUDE_CONFIG_DIR` and document why.
- Preserve agent write-scope: agents still operate with cwd = project root and
  their existing tool allowlists (reviewer read-only).
- Owner: CODEX (launcher/infra).

## Data flow (target)

`os3 dispatch T --project P`
→ `resolve_paths(P)` → `paths["root"] = projects/P`
→ gates (including `pr-check`) scan/check **projects/P** (working tree + history)
→ in-session `builder`/`reviewer` resolve from host agents exposed to the P session
→ verdict on P's own code, isolated from host repo state.

## Error handling

- `pr-check`: project unresolved → non-zero exit + explicit message; no host/cwd
  fallback scan.
- Unit B spike negative → fall back to `CLAUDE_CONFIG_DIR`, recorded in the ticket.

## Testing (TDD)

- `os3 pr-check --project P` scans P's root, not the host (plant a host-only dummy
  secret; assert pr-check for P passes while the host file is untouched/ignored).
- A dummy secret in an **uncommitted** file under P is detected by the working-tree
  (`gitleaks dir`) scan.
- A project with ≥1 commit also gets `gitleaks git` history coverage.
- Project resolution failure → pr-check exits non-zero with the documented message.
- Unit B: in a project-cwd session, `builder`/`reviewer` resolve to the named host
  agents (spike-validated; reviewer retains read-only tools).

## Ticket decomposition (dispatch in ~/dev-os)

- **T-A**: Unit A — owner CODEX. Independent.
- **T-B**: Unit B — owner CODEX. Independent; includes the resolution spike as step 1.
- Ticket creation + dispatch happen in a dev-os CLAUDE1 session (this external
  session produces design/spec/plan only).

## Companion: host hygiene (independent, non-blocking)

Once `pr-check` is project-scoped, the host false-positive no longer blocks
bollard. The host's own pr-check still flags it, so clean it (user choice:
allowlist only, no rotation): add the git-history fingerprint to `.gitleaksignore`
**and** replace the dummy token in `devos/questions/QUEUE.md` with a placeholder.
The placeholder is required because adding `gitleaks dir` (working-tree) scanning
means a `.gitleaksignore` git-fingerprint alone would not suppress the working-tree
hit. CLAUDE1-direct config edit (Q-004 precedent; devos/** + root config).

## Out of scope

- Rotating the dummy token (confirmed false positive; user chose no rotation).
- Broader gate redesign; only the pr-check scoping + working-tree coverage here.
- Making the standalone `secrets` gate change (already project-scoped).

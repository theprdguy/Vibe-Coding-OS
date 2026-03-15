# Vibe Coding Multi-LLM Playbook (Make + A-Mode)
Version: v2.0 (Native Instructions + Session Logs + WHAT+CONTEXT)
Mode: **A — Batch question triage at session start** (minimize interruptions during work)

---

## 0) Goals
- **Claude (Dispatcher/Manager + Researcher)** decomposes, researches, dispatches, and reviews work so **flow is never broken**.
- **Codex (Builder)** and **Gemini (UI/QA)** execute in parallel via **SSOT files** and **native instruction files** without needing to talk to each other.
- Your intervention is minimized to **answering choices (A/B/Default) at session start**.
- Claude does **NOT** write implementation code — every token goes to management and research.

---

## 1) Role Assignments

### Claude = Dispatcher / Manager + Researcher
- **Manager**: Ticket decomposition, owner assignment, file ownership, PR review
- **Researcher**: Uses MCP/context7/LSP to look up latest library APIs and version constraints before creating tickets
- Pre-generates questions and queues them; asks **only at session start** (A-Mode)
- Reads builder session logs at boot for cross-agent context
- Principle: **implementation code is forbidden** — writes WHAT+CONTEXT, not HOW

### Codex = Builder (Backend/Infra/Main implementation)
- Auto-reads `AGENTS.md` at CLI start (no clipboard needed)
- Implements per API_CONTRACT + tests/refactors
- Decides HOW to implement based on ticket context
- Writes session log to `devos/logs/` at session end
- Done criteria: ticket verify (`make pr-check`) passes + PR format compliance

### Gemini = Builder (Frontend/UI) + Multimodal QA
- Auto-reads `GEMINI.md` at CLI start (no clipboard needed)
- Implements screens/states (loading/empty/error/success) per UI_CONTRACT
- **Mock-first** even without a real API → switch to real API later
- Screenshot/repro-step-based QA artifacts
- Writes session log to `devos/logs/` at session end

---

## 2) SSOT (Single Source of Truth) — "Trust only these files"
Priority (truth order):
1) `PROJECT_STATE.md`
2) `docs/API_CONTRACT.md` + `docs/UI_CONTRACT.md`
3) `docs/ADR/*`
4) `tasks/QUEUE.yaml`
5) Code
6) `devos/logs/` (builder session logs — cross-agent context)
7) Chat logs

> When changes or assumptions arise, **update SSOT files before chat**.

---

## 3) Repo Skeleton
```
AGENTS.md              # Codex CLI native instruction file
GEMINI.md              # Gemini CLI native instruction file
Makefile
devos/
  AI.md
  PROJECT_STATE.md
  CONTEXT.md
  agents/
    registry.yaml      # Agent registry
  logs/                # Session logs
    README.md
  docs/
    API_CONTRACT.md
    UI_CONTRACT.md
    ARCHITECTURE.md
    ADR/
  tasks/
    QUEUE.yaml
  questions/
    QUEUE.md
```

---

## 4) Make Standard Interface

### Required commands (ticket verify uses only these)
- `make pr-check`
- `make lint`
- `make test`
- `make typecheck`
- `make e2e`

### Session start routine (for A-Mode)
- `make start`   (status + queue + questions)
- `make triage`  (show only open questions)

### Agents & Logs
- `make agents`       (list registered agents and status)
- `make logs`         (list recent session logs)
- `make log-review`   (show latest log per agent)

### Worktree (parallel isolation)
- `make worktree-create TICKET=T-123`
- `make worktree-list`
- `make worktree-clean`

> When the project stack is decided, replace only the internal Makefile commands — **external interface stays the same**.

---

## 5) Ticket Format — WHAT+CONTEXT

### Principles
- **1 PR = 1 Ticket** (keep them small)
- Every ticket must specify `owner` + `files` + `verify` + `deps`
- **Ownership**: only the ticket owner modifies files listed in `files:`
- API/UI changes follow **contract-first**: commit docs before code
- Claude writes **WHAT** (goal, dod, constraints) + **CONTEXT** (research)
- Builders decide **HOW** (implementation approach, code structure, patterns)

### Template (as it appears in QUEUE.yaml)
```yaml
- id: T-123
  status: todo|doing|blocked|done|parked
  owner: CODEX|GEMINI
  goal: "What to build — behavioral requirement (1 sentence)"
  context: |
    Why it's needed + Claude's research findings
    (MCP/context7: latest API changes, version info, compatibility notes)
  constraints: |
    Technical constraints (versions, compatibility, dependencies)
  dod:
    - "Acceptance criteria (behavior-based)"
  files:
    - "Files/directories to modify (no overlap allowed)"
  skills_hint: []   # optional: suggest approach to builder
  verify:
    - "make pr-check"
  contract_impact: none|api|ui|both
  deps: ["T-120"]
```

---

## 6) Question Queue — A-Mode (batch at session start)

### Rules
- If blocked or ambiguous, **don't stop working** — add a question to `questions/QUEUE.md`.
- Questions must include:
  - **Options (A/B/C/...)**
  - **Recommendation (1 line)**
  - **Default (proceed with this if no answer)**
  - **Blocking or not**
  - **Needed-by (which ticket needs this?)**
- Non-blocking: proceed with Default (no stoppage). Blocking: only that ticket is blocked.

### Question format (state-based)
```md
## Q-XXX [open] (Blocking|Non-blocking)
**Question:** ...
**Options:** A) ... B) ... C) ... D) ...
**Recommendation:** ...
**Default:** A/B/C/D
**Needed-by:** T-123 or "next dispatch"
**Impact:** API_CONTRACT / UI_CONTRACT / files
```

### Session-start triage (performed by Claude)
- Collect only **[open]** from `questions/QUEUE.md`
- Group by **Blocking first**, then Non-blocking, and ask all at once
- You answer like: `Q-003=B, Q-007=Default`
- Claude then:
  - Marks questions as `[answered]`
  - Writes ADRs
  - Updates contract docs (if needed)
  - Re-dispatches/unblocks tickets in the queue

---

## 7) Session Logs — Cross-Agent Visibility

### Rules
- Builders write a log to `devos/logs/` at session end (required, ≤50 lines)
- Filename: `{date}-{agent}-{ticket-ids}.md` (e.g., `2026-03-15-codex-T-001-T-002.md`)
- Claude reads latest logs at boot (step 7 of boot sequence)

### Log sections (required)
```md
## Summary
What was accomplished this session (2-3 sentences)

## Decisions Made
- Decision and rationale

## Questions Raised
- Questions (if any — add to questions/QUEUE.md too)

## Files Modified
- path/to/file

## Handoff
Done: ...
Next: ...
Block: ...
```

---

## 8) PR Format (for review automation)
PR description is fixed to these 4 sections:
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: `make pr-check` (+ additional if needed)
- Risks / edge cases (if any)

---

## 9) Operational Scenarios

### Scenario 0 — First-time setup (Foundation)
1) Create repo from GitHub template (or copy files)
2) Run:
```bash
make help
make status
make pr-check
```
3) First goal: mark T-000/T-001 as done in `tasks/QUEUE.yaml`

---

### Scenario 1 — Daily session start (A-Mode)
1) Terminal:
```bash
make start
```
2) Open Claude Code → auto-reads CLAUDE.md, reads builder logs
3) Claude: run session-start triage (batch questions)
4) You: answer `Q-xxx=A/B/Default`
5) Claude: update ADR/contracts/queue → unblock

---

### Scenario 2 — Dispatch → parallel execution
1) Claude researches tech context (MCP/context7) and decomposes into WHAT+CONTEXT tickets
2) Codex/Gemini start their CLIs — auto-read instruction files, work on their tickets
3) Parallel rules:
- If files overlap → no parallel (re-decompose or sequence)
- Contract changes → merge doc PR first

---

### Scenario 3 — Codex workflow (Builder)
1) Start Codex CLI → auto-reads `AGENTS.md`
2) Read ticket → understand WHAT + CONTEXT, decide HOW
3) If needed: commit contract docs first
4) Implement (own approach, not directed by Claude)
5) Verify: `make pr-check`
6) Write PR (fixed format)
7) Write session log to `devos/logs/`
8) If blocked, add to question queue (Options+Default required)

---

### Scenario 4 — Gemini workflow (UI/QA)
1) Start Gemini CLI → auto-reads `GEMINI.md`
2) Read ticket → understand WHAT + CONTEXT, decide HOW
3) Implement all UI states per UI_CONTRACT: loading/empty/error/success
4) Mock-first for UI
5) Verify: `make pr-check`
6) Include repro steps/screenshots in PR (if possible)
7) Write session log to `devos/logs/`

---

### Scenario 5 — Review/merge (Claude gate)
Claude checks every PR for:
- Contract compliance (docs updated?)
- Verify evidence (`make pr-check`)
- Ownership violation (touched someone else's files?)
- Risk/test gaps
→ Merge in dependency order, then update `PROJECT_STATE.md`

---

### Scenario 6 — Conflict/drift recovery protocol
1) Record the problem in 3 lines in `PROJECT_STATE.md`
2) Establish the "correct answer" in `API_CONTRACT` / `UI_CONTRACT`
3) Issue a small correction/refactor ticket
4) Return to parallel flow

---

### Scenario 7 — Second Claude (future)
If a second Claude instance is needed (Reviewer / QA-TDD / Second Dispatcher):
1) Edit `devos/agents/registry.yaml` → set `claude-secondary` to `active`
2) Copy `.claude/CLAUDE-SECONDARY.md` → define role
3) Run in a separate Claude Code session or worktree
4) Register in agent registry with `can_modify` scope

---

## 10) When a project is chosen (one-time onboarding)
1) Decide on the stack (e.g., Next.js/FastAPI)
2) Wire Makefile internal commands:
- `make dev` → actual dev server
- `make lint/test/typecheck/e2e` → actual execution
3) Ticket verify stays as `make ...` (playbook is reusable)

---

## 11) Checklist (essentials only)
- [ ] Maintain SSOT types (STATE, API, UI, QUEUE, LOGS)
- [ ] Enforce owner/files/verify/deps on every ticket
- [ ] Tickets use WHAT+CONTEXT (no code-level specs)
- [ ] Contract-first + Ownership + Small PR
- [ ] Queue questions, resolve only at session start (A-Mode)
- [ ] Builders write session logs at session end
- [ ] Claude reads builder logs at boot (step 7)
- [ ] Completion criteria is always `make pr-check`

# Vibe Coding Multi-LLM Playbook (Make + A-Mode)
Version: v1.5 (Token-Efficient Template)
Mode: **A — Batch question triage at session start** (minimize interruptions during work)

---

## 0) Goals
- **Claude (Dispatcher/Manager)** decomposes, dispatches, and reviews work so **flow is never broken**.
- **Codex (Builder)** and **Gemini (UI/QA)** execute in parallel via **SSOT files** without needing to talk to each other.
- Your intervention is minimized to **answering choices (A/B/Default) at session start**.
- Claude does **NOT** write implementation code — every token goes to management.

---

## 1) Role Assignments (fixed)

### Claude = Dispatcher / Manager
- Ticket decomposition (including dependencies), owner assignment, file ownership management
- Pre-generates questions and queues them; asks **only at session start** (A-Mode)
- PR review (risks/edge cases/contract compliance) + merge order decisions
- Principle: **implementation code is forbidden** — focus on docs/ADR/tickets

### Codex = Builder (Backend/Infra/Main implementation)
- Implements per API_CONTRACT + tests/refactors
- Done criteria: ticket verify (= make command) passes + PR format compliance

### Gemini = Builder (Frontend/UI) + Multimodal QA
- Implements screens/states (loading/empty/error/success) per UI_CONTRACT
- **Mock-first** even without a real API → switch to real API later
- Screenshot/repro-step-based QA artifacts

---

## 2) SSOT (Single Source of Truth) — "Trust only these files"
Priority (truth order):
1) `PROJECT_STATE.md`
2) `docs/API_CONTRACT.md` + `docs/UI_CONTRACT.md`
3) `docs/ADR/*`
4) Code
5) Chat logs

> When changes or assumptions arise, **update SSOT files before chat**.

---

## 3) Repo Skeleton (default before project is chosen)
```
Makefile
devos/
  AI.md
  PROJECT_STATE.md
  CONTEXT.md
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

## 4) Make Standard Interface (all verification/completion criteria)

### Required commands (ticket verify uses only these)
- `make pr-check`
- `make lint`
- `make test`
- `make typecheck`
- `make e2e`

### Session start routine (for A-Mode)
- `make start`   (status + queue + questions)
- `make triage`  (show only open questions)

> When the project stack is decided, replace only the internal Makefile commands — **external interface (make test, etc.) stays the same**.

---

## 5) Ticket Format — The key to handoff automation

### Principles
- **1 PR = 1 Ticket** (keep them small)
- Every ticket must specify `owner` + `files` + `verify` + `deps`
- **Ownership**: only the ticket owner modifies files listed in `files:`
- API/UI changes follow **contract-first**: commit docs before code

### Template (as it appears in QUEUE.yaml)
```yaml
- id: T-123
  status: todo|doing|blocked|done|parked
  owner: CLAUDE|CODEX|GEMINI
  goal: "One-sentence objective"
  context: |
    Why it's needed, current state (2-3 sentences)
  spec: |
    Detailed requirements (input/output/behavior)
  dod:
    - "Acceptance criteria"
  files:
    - "Files/directories to modify (no overlap allowed)"
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

## 7) PR Format (for review automation)
PR description is fixed to these 4 sections:
- What changed (3 bullets)
- Contract impact: none|api|ui|both
- How to verify: `make pr-check` (+ additional if needed)
- Risks / edge cases (if any)

---

## 8) Operational Scenarios (End-to-End)

### Scenario 0 — First-time setup (Foundation)
1) Create skeleton files
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
2) Claude: run session-start triage (batch questions)
3) You: answer `Q-xxx=A/B/Default`
4) Claude: update ADR/contracts/queue → unblock

---

### Scenario 2 — Dispatch (ticket creation) → parallel execution
1) Claude decomposes today's goals into PR-sized tickets in `tasks/QUEUE.yaml`
2) Codex/Gemini work on **only their own tickets**
3) Parallel rules:
- If files overlap → no parallel (re-decompose or sequence)
- Contract changes → merge doc PR first

---

### Scenario 3 — Codex workflow (Builder)
1) Read ticket → (if needed) commit contract docs first
2) Implement
3) Verify:
```bash
make pr-check
```
4) Write PR (fixed format)
5) If blocked, add to question queue (Options+Default required)

---

### Scenario 4 — Gemini workflow (UI/QA)
1) Implement all UI states per UI_CONTRACT: loading/empty/error/success
2) Mock-first for UI
3) Verify:
```bash
make pr-check
```
4) Include repro steps/screenshots in PR (if possible)
5) If blocked, add to question queue

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

## 9) When a project is chosen (one-time onboarding)
1) Decide on the stack (e.g., Next.js/FastAPI)
2) Wire Makefile internal commands:
- `make dev` → actual dev server
- `make lint/test/typecheck/e2e` → actual execution
3) Ticket verify stays as `make ...` (playbook is reusable)

---

## 10) Checklist (essentials only)
- [ ] Maintain 4 SSOT types (STATE, API, UI, QUEUE)
- [ ] Enforce owner/files/verify/deps on every ticket
- [ ] Contract-first + Ownership + Small PR
- [ ] Queue questions, resolve only at session start (A-Mode)
- [ ] Completion criteria is always `make pr-check`

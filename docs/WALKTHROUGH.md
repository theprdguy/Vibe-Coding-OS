# Full Cycle Walkthrough — notes-api example

This document walks through one complete OS cycle on a **fictional sample project** called
`notes-api` — a simple REST API for creating and retrieving text notes.

The walkthrough covers:
1. [Sample PRD](#1-sample-prd)
2. [CLAUDE1 decomposition → tickets](#2-claude1-decomposition--tickets)
3. [Approve + dispatch](#3-approve--dispatch)
4. [Builder implements — BUILDER ticket](#4-builder-implements--builder-ticket)
5. [Reviewer verdict](#5-reviewer-verdict)
6. [Merge](#6-merge)

---

## 1. Sample PRD

You drop this into Claude Code (CLAUDE1):

```
## notes-api — MVP PRD

Goal: A lightweight REST API that lets users create and retrieve personal notes.

User stories:
  - As a user, I can POST /notes with a title and body to create a note.
  - As a user, I can GET /notes to list all my notes (most recent first).
  - As a user, I can GET /notes/:id to retrieve a single note.

Constraints:
  - Python + FastAPI. SQLite for storage (MVP).
  - Each note has: id (uuid), title (str, max 200 chars), body (str), created_at (ISO8601).
  - Unauthenticated for MVP.

Error handling:
  - POST /notes with missing title → 422 Unprocessable Entity
  - GET /notes/:id with unknown id → 404 Not Found
```

---

## 2. CLAUDE1 decomposition → tickets

CLAUDE1 runs the PRD intake checklist, extracts user journeys, and produces a plan saved to
`devos/plans/pending/notes-api-mvp.yaml`. After you run `os3 approve`, the tickets land in
`devos/tasks/QUEUE.yaml`.

### Resulting QUEUE.yaml (excerpt)

```yaml
tickets:

  - id: T-NOTES-01
    status: todo
    owner: CODEX
    impl_owner: CODEX
    test_owner: CODEX
    tdd: required
    mode: productization
    security_audit: false
    cross_model: false
    goal: |
      Scaffold the notes-api FastAPI project: app entry point, SQLite model for Note
      (id uuid, title str max 200, body str, created_at ISO8601), and database init.
    context: |
      New project. No existing code. Use fastapi + sqlmodel (SQLite backend).
      Target Python 3.10+. Entry point: apps/api/main.py. DB init on startup.
    constraints: |
      - SQLite only (MVP). No auth.
      - Title max 200 chars enforced at model level.
    dod:
      - 'success: python -c "from apps.api.main import app" exits 0'
      - 'success: DB file created on first startup (apps/api/notes.db or :memory: in tests)'
      - 'error: Note with title > 200 chars fails model validation (ValueError or 422)'
    files:
      - apps/api/main.py
      - apps/api/models.py
      - apps/api/database.py
      - requirements.txt
    verify: |
      python -m pytest tests/api/test_models.py -q
    deps: []
    gates: [pr-check]

  - id: T-NOTES-02
    status: todo
    owner: CODEX
    impl_owner: CODEX
    test_owner: CODEX
    tdd: required
    mode: productization
    security_audit: false
    cross_model: false
    goal: |
      Implement the three note endpoints: POST /notes, GET /notes, GET /notes/:id.
    context: |
      Builds on T-NOTES-01 (model + DB). Use FastAPI routers. Return notes sorted by
      created_at DESC for GET /notes. Return 404 for unknown id. Validate title length
      (422 on missing or too-long title).
    constraints: |
      - No auth. No pagination for MVP.
      - Response shape: {id, title, body, created_at}.
    dod:
      - 'success: POST /notes {title, body} → 201 + {id, title, body, created_at}'
      - 'success: GET /notes → 200 + list sorted created_at DESC'
      - 'success: GET /notes/:id with valid id → 200 + note object'
      - 'error: POST /notes with missing title → 422 + detail message'
      - 'error: GET /notes/:id with unknown id → 404 + {detail: "Note not found"}'
    files:
      - apps/api/routers/notes.py
      - apps/api/main.py
      - tests/api/test_notes_endpoints.py
    verify: |
      python -m pytest tests/api/test_notes_endpoints.py -q
    deps: [T-NOTES-01]
    gates: [pr-check]

  - id: T-NOTES-03
    status: todo
    owner: BUILDER
    impl_owner: BUILDER
    tdd: skip
    mode: productization
    security_audit: false
    cross_model: false
    goal: |
      Add a minimal README for notes-api: endpoints table, local dev setup, curl examples.
    context: |
      The API is defined in T-NOTES-01 and T-NOTES-02. README should document the three
      endpoints, required env setup (python -m uvicorn apps.api.main:app), and curl examples
      for each endpoint including the error cases.
    constraints: |
      - Markdown only. No code changes.
    dod:
      - 'success: README.md present in apps/api/ with endpoint table (method + path + response)'
      - 'success: curl example for POST /notes with missing title shows 422 response'
    files:
      - apps/api/README.md
    verify: |
      test -f apps/api/README.md && grep -q "422" apps/api/README.md
    deps: [T-NOTES-02]
    gates: [pr-check]
```

---

## 3. Approve + dispatch

```bash
# Review the pending plan:
os3 pending

# Approve it (moves tickets to QUEUE.yaml):
os3 approve notes-api-mvp

# Check the queue:
os3 queue

# Dispatch tickets (CODEX tickets first as they have no deps):
os3 dispatch T-NOTES-01
# ... CODEX runs, commits scaffold + failing tests, marks code_ready

os3 dispatch T-NOTES-02
# ... CODEX runs endpoints + makes tests pass

os3 dispatch T-NOTES-03
# ... BUILDER runs in-session, writes the README
```

---

## 4. Builder implements — BUILDER ticket

For T-NOTES-03 (the BUILDER ticket), the dispatcher spawns the builder sub-agent with the ticket
body inline. The builder:

1. Reads `apps/api/routers/notes.py` and `apps/api/models.py` to understand the contract.
2. Writes `apps/api/README.md` with the endpoints table and curl examples.
3. Verifies: `test -f apps/api/README.md && grep -q "422" apps/api/README.md` → passes.
4. Returns: `Done: T-NOTES-03 — wrote apps/api/README.md — files: [apps/api/README.md]`

---

## 5. Reviewer verdict

After the builder or CODEX marks a ticket `code_ready`, CLAUDE1 invokes the reviewer sub-agent
(read-only tools — it cannot modify files). Example reviewer output:

```
## Reviewer verdict — T-NOTES-02

PASS (with warnings)

BLOCKER: none

WARNING:
  - test_notes_endpoints.py line 34: `assert response.json()` is a truthy check only.
    Replace with `assert response.json() == {"detail": "Note not found"}` to verify the
    exact 404 body. (Weak assertion — passes even if the body is wrong.)

DOD coverage:
  [x] POST /notes → 201 + object
  [x] GET /notes → 200 + list sorted DESC
  [x] GET /notes/:id → 200
  [x] POST /notes missing title → 422
  [x] GET /notes/:id unknown id → 404

No BLOCKER → verdict: PASS. WARNING to be addressed before Production mode.
```

A BLOCKER example (what would stop the merge):

```
BLOCKER:
  - GET /notes returns notes for ALL users, not scoped to the requester.
    The DOD says "personal notes" — this is a data-isolation violation.
    Fix: add user_id scoping or explicitly record a design decision to defer auth.
```

---

## 6. Merge

With no BLOCKERs:

```bash
# Mark done and archive:
os3 archive

# Merge the branch to main as normal. The ticket transition history is preserved in
# ARCHIVE.yaml for audit.
```

---

## Key patterns illustrated

| Pattern | Where it appeared |
|---|---|
| Failure-case DOD | T-NOTES-02: `error: GET /notes/:id with unknown id → 404` |
| Cross-test (tdd: required) | T-NOTES-01 + 02: CODEX writes failing tests before impl |
| BUILDER for doc/UX ticket | T-NOTES-03: no tests, experience-heavy authoring |
| Weak assertion flagged | Reviewer WARNING on truthy check |
| BLOCKER blocks merge | Data-isolation example stops the PR |

For the full gate matrix (which gates fire in which mode), see
[`docs/policy/MODE_GATE_MATRIX.md`](policy/MODE_GATE_MATRIX.md).

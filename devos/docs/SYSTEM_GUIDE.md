# Vibe Coding Development Environment & Structure Guide
Version: **v1.5 (Token-Efficient Multi-LLM OS)**
Scope: Multi-LLM parallel development operating system — Claude as manager, Codex/Gemini as builders

> v1.5 changes (summary)
- **Token efficiency principle**: Claude is manager-only, implementation code forbidden
- **CLAUDE.md dual placement**: repo root `.claude/CLAUDE.md` (auto-loaded by Claude Code) + `devos/.claude/CLAUDE.md` (reference)
- **Hooks**: Auto-blocks Claude from writing to implementation files (`guard-no-impl.sh`)
- **Enhanced ticket template**: `context` + `spec` fields added (enables independent builder work)
- **Makefile improvements**: `make start`, `make copy-*`, `make show-*` all functional
- **Builder prompt improvements**: Boot Sequence + Deliverable Format standardized

---

## 1. Purpose

This document describes the **multi-LLM parallel development operating system** using **Claude + Codex + Gemini** together.

### Why Multi-LLM?
- Each LLM has **limited tokens/context** per session
- If Claude does everything alone, tokens run out
- **Division of labor**: Claude (manager) + Codex/Gemini (builders) = maximize total token capacity
- If Claude spends tokens on implementation → cannot fulfill manager role → delegation fails

### Core Goals
1) Keep work flowing continuously (continuous flow)
2) Prevent context drift/collisions through system design
3) Minimize your intervention to **choosing from options**

---

## 2. Role Design

### Claude = Dispatcher / Manager
- Ticket decomposition/dispatch, question triage, PR review, merge order decisions
- **Implementation code forbidden** (no more than 10 lines, no exceptions)
- All implementation is delegated to Codex/Gemini via tickets
- Token budget: planning 30% + ticket writing 40% + review 15% + SSOT 15%

### Codex = Builder (Backend/Infra)
- Implementation based on API_CONTRACT + tests/refactors
- Modifies only files within own ticket scope

### Gemini = Builder (Frontend/UI + QA)
- UI implementation based on UI_CONTRACT
- Mock-first development
- Modifies only files within own ticket scope

---

## 3. Repo Structure

```
repo/
  .claude/
    CLAUDE.md             # Auto-loaded by Claude Code (manager rules)
    hooks/
      guard-no-impl.sh    # Blocks Claude from writing impl code
    settings.json          # Hook configuration
  Makefile                 # Wrapper (delegates to devos/Makefile)
  START_HERE.md

  devos/
    AI.md                  # Operating constitution (shared by all agents)
    CONTEXT.md             # TL;DR (100-line summary)
    PROJECT_STATE.md       # Current state (1 page)
    TASKS.md               # Human-readable task board view
    VERSION.txt

    docs/
      API_CONTRACT.md      # REST API contract
      UI_CONTRACT.md       # UI state/validation contract
      ARCHITECTURE.md      # Architecture overview
      ADR/                 # Decision records

    tasks/
      QUEUE.yaml           # Ticket queue (SSOT)
      archive/             # Completed ticket archive

    questions/
      QUEUE.md             # Question queue (A-Mode)

    prompts/
      claude/session-start.md
      claude/review-pr.md
      codex/session-start.md
      gemini/session-start.md
      common/handoff-3lines.md

    .claude/CLAUDE.md      # Claude role summary (reference)
    .codex/CODEX.md        # Codex role rules
    .gemini/GEMINI.md      # Gemini role rules
```

### Why CLAUDE.md is in two places
- **Repo root `.claude/CLAUDE.md`**: The location Claude Code auto-reads. Enforces manager rules.
- **`devos/.claude/CLAUDE.md`**: Referenced by prompts. Summary version.

---

## 4. Make Interface

### Core commands (daily use)
| Command | Description |
|---------|-------------|
| `make start` | Session start (status + queue + questions + next steps) |
| `make status` | Git + SSOT file status check |
| `make queue` | Ticket queue summary |
| `make triage` | Show [open] questions only |

### Prompt delivery
| Command | Description |
|---------|-------------|
| `make copy-claude` | Copy Claude triage prompt to clipboard |
| `make copy-codex` | Copy Codex builder prompt to clipboard |
| `make copy-gemini` | Copy Gemini builder prompt to clipboard |
| `make show-*` | Print to terminal instead of clipboard |

### Verification
| Command | Description |
|---------|-------------|
| `make pr-check` | Pre-PR checks (includes contract-check) |
| `make contract-check` | Verify contract docs updated when code changes |

---

## 5. Ticket System

### Required ticket fields (v1.5 enhanced)
```yaml
- id: T-XXX
  status: todo|doing|blocked|done|parked
  owner: CLAUDE|CODEX|GEMINI
  goal: "What to build (1 sentence)"
  context: |
    Why it's needed, current state (2-3 sentences)
    Enough background for builders to work independently
  spec: |
    Detailed requirements (input/output/behavior)
  dod:
    - "Acceptance criteria"
  files:
    - "Files to modify (ownership scope)"
  verify:
    - "make pr-check"
  contract_impact: none|api|ui|both
  deps: ["T-XXX"]
```

### Why context/spec matter
- To save Claude's tokens, builders must work **without asking follow-up questions**
- `context`: "Why is this task needed?" (builder understands the background)
- `spec`: "Exactly what needs to be built?" (builder can implement independently)

---

## 6. Collision Prevention Rules

1. **Ownership**: Only the ticket owner may modify ticket.files
2. **Small PR**: 1 ticket = 1 PR
3. **Contract-first**: Contract docs before code
4. **Dependency isolation**: Library changes in separate PRs
5. **Branch = Ticket**: `feat/T-123-short-title`

---

## 7. Claude Code Hooks (new in v1.5)

Configured in `.claude/settings.json`:
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write|Edit",
      "hook": ".claude/hooks/guard-no-impl.sh"
    }]
  }
}
```

When Claude tries to write to implementation directories like `src/`, `app/`, `components/`:
- Automatically blocked
- "Dispatcher Guard" warning message shown
- Guided to create a ticket instead

---

## 8. Session Flow

### 8.1 Every work session
```
make start
  |
Claude triage (make copy-claude -> paste into Claude)
  |
Deploy builders (make copy-codex / make copy-gemini -> paste into each LLM)
  |
Builders complete work -> PR
  |
Claude review -> merge -> update state
```

### 8.2 When a new PRD/feature request arrives
```
User provides PRD
  |
Claude reads PRD and decomposes into tickets
  |
Creates CODEX/GEMINI tickets in QUEUE.yaml
  |
Updates contract docs (if needed)
  |
Tells user: "Run make copy-codex / make copy-gemini"
```

**Important:** Even when Claude receives a PRD, it does NOT implement directly. It always decomposes into tickets.

---

## 9. A-Mode (Question Queue)

- If blocked, record in `devos/questions/QUEUE.md`
- Required: Options + Recommendation + Default + Blocking/Non-blocking
- Non-blocking: proceed with Default
- Blocking: only that ticket is blocked
- Claude resolves all questions in batch at session start

---

## 10. Summary

| Component | v1.4 | v1.5 |
|-----------|------|------|
| Claude role | "avoid" (loose) | "forbidden" (enforced + hooks) |
| CLAUDE.md location | devos/.claude/ (not loaded) | repo root .claude/ (auto-loaded) |
| Ticket template | goal/dod/files | + context/spec (independent work) |
| Makefile | kickoff only | start/copy-*/show-* fully functional |
| Enforcement mechanism | None | Hooks (guard-no-impl.sh) |
| Builder prompts | Basic runbook | Boot Sequence + Deliverable Format |

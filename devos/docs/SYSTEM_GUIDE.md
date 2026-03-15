# Vibe Coding Development Environment & Structure Guide
Version: **v2.0 (Native Instructions + Session Logs + WHAT+CONTEXT)**
Scope: Multi-LLM parallel development operating system — Claude as manager+researcher, Codex/Gemini as builders

> v2.0 changes (summary)
- **Native instruction files**: `AGENTS.md` / `GEMINI.md` at repo root — CLI tools auto-load on start (no clipboard)
- **Session logs**: `devos/logs/` — builders write structured logs at session end; Claude reads at boot
- **Agent registry**: `devos/agents/registry.yaml` — central N-agent configuration
- **WHAT+CONTEXT tickets**: `spec:` → `context:` + `constraints:` — Claude writes requirements + research context; builders decide HOW
- **Claude Researcher role**: MCP/context7/LSP tools used to research tech context before creating tickets
- **Skills integration**: `skills_hint` field in tickets; CLAUDE.md skills mapping
- **Worktree support**: `make worktree-create TICKET=T-xxx` for parallel isolation
- **4-line handoff**: Done/Next/Block/Log

---

## 1. Purpose

This document describes the **multi-LLM parallel development operating system** using **Claude + Codex + Gemini** together.

### Why Multi-LLM?
- Each LLM has **limited tokens/context** per session
- If Claude does everything alone, tokens run out
- **Division of labor**: Claude (manager+researcher) + Codex/Gemini (builders) = maximize total token capacity
- If Claude spends tokens on implementation → cannot fulfill manager role → delegation fails

### Core Goals
1) Keep work flowing continuously (continuous flow)
2) Prevent context drift/collisions through system design
3) Minimize your intervention to **choosing from options**

---

## 2. Role Design

### Claude = Dispatcher / Manager + Researcher
- **Manager**: Ticket decomposition/dispatch, question triage, PR review, merge order decisions
- **Researcher**: Uses MCP/context7/LSP to look up latest library APIs and version constraints before creating tickets; includes findings in ticket `context:` field
- **Implementation code forbidden** (no more than 10 lines, no exceptions)
- All implementation is delegated to Codex/Gemini via WHAT+CONTEXT tickets
- Token budget: Research 25% + Ticket writing 25% + Analysis/planning 25% + Review 10% + SSOT reading 10% + State updates 5%

### Codex = Builder (Backend/Infra)
- Auto-reads `AGENTS.md` at CLI start (no clipboard needed)
- Reads ticket WHAT+CONTEXT, decides HOW to implement
- Modifies only files within own ticket scope
- Writes session log to `devos/logs/` at session end

### Gemini = Builder (Frontend/UI + QA)
- Auto-reads `GEMINI.md` at CLI start (no clipboard needed)
- UI implementation based on UI_CONTRACT
- Mock-first development; multimodal QA
- Modifies only files within own ticket scope
- Writes session log to `devos/logs/` at session end

### Tool Asymmetry
| Tool | Claude | Codex | Gemini |
|------|--------|-------|--------|
| MCP servers (context7, etc.) | ✓ | ✗ | ✗ |
| LSP | ✓ | ✗ | ✗ |
| Web search | ✓ | ✓ (limited) | ✓ (limited) |
| File read/write | ✓ (devos/ only) | ✓ | ✓ |
| Training data | Aug 2025 | varies | varies |

Claude bridges this gap by including research results in ticket `context:` field.

---

## 3. Repo Structure

```
repo/
  AGENTS.md                # Codex CLI native instruction file (auto-loaded)
  GEMINI.md                # Gemini CLI native instruction file (auto-loaded)
  .claude/
    CLAUDE.md              # Auto-loaded by Claude Code (manager+researcher rules)
    CLAUDE-SECONDARY.md    # Second Claude instance template (inactive)
    hooks/
      guard-no-impl.sh     # Blocks Claude from writing impl code
    settings.json          # Hook configuration
  Makefile                 # Wrapper (delegates to devos/Makefile)
  START_HERE.md

  devos/
    AI.md                  # Operating constitution (shared by all agents)
    CONTEXT.md             # TL;DR (100-line summary)
    PROJECT_STATE.md       # Current state (1 page)
    TASKS.md               # Human-readable task board view
    VERSION.txt

    agents/
      registry.yaml        # Agent registry (id/role/status/can_modify)

    logs/                  # Session logs (cross-agent visibility)
      README.md
      {date}-{agent}-{ticket-ids}.md

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
      common/handoff-3lines.md  # (now 4 lines in v2.0)

    .claude/CLAUDE.md      # Claude role summary (reference)
    .codex/CODEX.md        # Codex role quick reference → see /AGENTS.md
    .gemini/GEMINI.md      # Gemini role quick reference → see /GEMINI.md
```

---

## 4. Make Interface

### Core commands (daily use)
| Command | Description |
|---------|-------------|
| `make start` | Session start (status + queue + questions + next steps) |
| `make status` | Git + SSOT file status check |
| `make queue` | Ticket queue summary |
| `make triage` | Show [open] questions only |
| `make new-ticket` | Add a new ticket |
| `make new-question` | Add a new question |

### Agents & Logs
| Command | Description |
|---------|-------------|
| `make agents` | List registered agents and their status |
| `make logs` | List recent session logs (last 10) |
| `make log-review` | Show latest log per agent |
| `make log-archive` | Archive logs older than 7 days |

### Worktree
| Command | Description |
|---------|-------------|
| `make worktree-create TICKET=T-123` | Create worktrees/T-123/ on feat/T-123 branch |
| `make worktree-list` | List active worktrees |
| `make worktree-clean` | Remove merged worktrees |

### Verification
| Command | Description |
|---------|-------------|
| `make pr-check` | Pre-PR checks (includes contract-check) |
| `make contract-check` | Verify contract docs updated when code changes |

### Deprecated (retained as fallback)
| Command | Description |
|---------|-------------|
| `make copy-claude` | [DEPRECATED] Copy Claude prompt to clipboard |
| `make copy-codex` | [DEPRECATED] Copy Codex prompt to clipboard |
| `make copy-gemini` | [DEPRECATED] Copy Gemini prompt to clipboard |

---

## 5. Ticket System — WHAT+CONTEXT

### Design principle
- Claude writes **WHAT** (behavioral requirements + research context)
- Builders decide **HOW** (implementation approach, code structure, patterns)
- No code-level instructions in tickets — tickets state outcomes, not methods

### Required ticket fields
```yaml
- id: T-XXX
  status: todo|doing|blocked|done|parked
  owner: CODEX|GEMINI
  goal: "What to build — behavioral requirement (1 sentence)"
  context: |
    Why it's needed + Claude's research findings
    (MCP/context7: latest API, version info, breaking changes, compatibility notes)
  constraints: |
    Technical constraints (versions, compatibility, dependencies)
  dod:
    - "Acceptance criteria (behavior-based)"
  files:
    - "Files to modify (ownership scope)"
  skills_hint: []   # optional: suggest approach (e.g., TDD, systematic-debugging)
  verify:
    - "make pr-check"
  contract_impact: none|api|ui|both
  deps: ["T-XXX"]
```

### Why context matters
- Builders lack MCP/context7/LSP — they can't easily look up latest API changes
- Claude's research findings in `context:` bridge this tool asymmetry
- Enough context = builder works independently without follow-up questions

---

## 6. Session Logs

### Purpose
Cross-agent visibility: Claude reads builder logs at boot to understand what was built,
what decisions were made, and what's pending — without needing to be in the same session.

### Format
- Filename: `{date}-{agent}-{ticket-ids}.md` (e.g., `2026-03-15-codex-T-001-T-002.md`)
- Max 50 lines
- Required sections: Summary / Decisions Made / Questions Raised / Files Modified / Handoff

### In boot sequence
Claude boot step 7: Read latest files in `devos/logs/` before triaging or creating tickets.

---

## 7. Agent Registry

`devos/agents/registry.yaml` is the central configuration for all registered agents.

```yaml
agents:
  - id: claude-dispatcher
    role: Manager + Researcher
    instruction_file: .claude/CLAUDE.md
    status: active

  - id: codex-builder
    role: Backend/Infra Builder
    instruction_file: AGENTS.md
    status: active

  - id: gemini-builder
    role: Frontend/UI Builder
    instruction_file: GEMINI.md
    status: active

  - id: claude-secondary
    role: TBD (Reviewer / QA-TDD / Second Dispatcher)
    instruction_file: .claude/CLAUDE-SECONDARY.md
    status: inactive
```

---

## 8. Collision Prevention Rules

1. **Ownership**: Only the ticket owner may modify ticket.files
2. **Small PR**: 1 ticket = 1 PR
3. **Contract-first**: Contract docs before code
4. **Dependency isolation**: Library changes in separate PRs
5. **Branch = Ticket**: `feat/T-123-short-title`

---

## 9. Claude Code Hooks

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
- `devos/` paths are allowed (SSOT files, logs, tickets)

---

## 10. Session Flow

### 10.1 Every work session
```
make start
  |
Claude Code (auto-reads CLAUDE.md)
  → reads SSOT + builder logs
  → researches tech context (MCP/context7)
  → triages questions
  → creates/updates tickets (WHAT+CONTEXT)
  |
Codex CLI (auto-reads AGENTS.md) → implements backend tickets → writes log
Gemini CLI (auto-reads GEMINI.md) → implements frontend tickets → writes log
  |
make log-review → Claude reads logs at next session start
  |
make pr-check → PR → Claude review → merge → update state
```

### 10.2 When a new PRD/feature request arrives
```
User provides PRD
  |
Claude reads PRD and decomposes into tickets
  |
Claude researches relevant libraries (MCP/context7)
  |
Creates CODEX/GEMINI tickets with WHAT+CONTEXT in QUEUE.yaml
  |
Updates contract docs (if needed)
  |
Tells user: "Tickets created. Start Codex/Gemini CLI in repo."
```

**Important:** Even when Claude receives a PRD, it does NOT implement directly. Always decomposes into tickets.

---

## 11. A-Mode (Question Queue)

- If blocked, record in `devos/questions/QUEUE.md`
- Required: Options + Recommendation + Default + Blocking/Non-blocking
- Non-blocking: proceed with Default
- Blocking: only that ticket is blocked
- Claude resolves all questions in batch at session start

---

## 12. Summary Comparison

| Component | v1.5 | v2.0 |
|-----------|------|------|
| Prompt delivery | `make copy-*` (clipboard) | Native files (AGENTS.md, GEMINI.md) |
| Cross-agent visibility | None | Session logs (`devos/logs/`) |
| Agent management | Fixed 3 | Registry (`agents/registry.yaml`) |
| Ticket design | code-level spec | WHAT+CONTEXT (behavioral + research) |
| Claude role | Manager | Manager + Researcher (MCP/context7) |
| Handoff format | 3 lines | 4 lines (+Log) |
| Worktree support | None | `make worktree-create TICKET=T-xxx` |
| Skills integration | None | `skills_hint` in tickets + CLAUDE.md mapping |

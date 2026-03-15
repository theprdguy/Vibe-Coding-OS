# Vibe Coding OS Manual 101 (v2.0)
_A step-by-step guide to follow before starting a project or daily work session_

---

## Purpose of this manual
- **Minimize what you need to remember**: start a session with just `make start`
- **Prevent mistakes**: check Git/remote/SSOT status upfront
- **Stabilize parallel work**: fixed order of Claude (dispatcher) → Codex/Gemini (builders)

---

# 0) 30-Second Glossary
- **Repo**: Project repository on GitHub (remote)
- **Clone**: Copy a GitHub repo to your local machine
- **Commit**: Save a snapshot (create a local record)
- **Push**: Upload commits to GitHub
- **SSOT**: "Single Source of Truth" documents (AI.md/CONTEXT/STATE/CONTRACT/QUEUE/QUESTIONS)
- **A-Mode**: Queue questions during work (don't interrupt), resolve them in batch at session start
- **WHAT+CONTEXT**: Ticket design — Claude writes behavioral requirements + research context; builders decide implementation
- **Session log**: Structured summary a builder writes at session end (≤50 lines) so Claude can understand what happened
- **Native instruction file**: `AGENTS.md` / `GEMINI.md` — auto-loaded by Codex/Gemini CLI on start
- **Agent registry**: `devos/agents/registry.yaml` — central list of all registered agents
- **Researcher role**: Claude's secondary role — uses MCP/context7/LSP to look up tech context before creating tickets

---

# 1) Project Setup (Day 0) — GitHub template (recommended)

## 1-1. Create a new repo from template
- Go to the Vibe Coding OS GitHub repo → **Use this template** → Create your project repo
- Default branch: **main**
- This copies all OS files into your new repo

## 1-2. Clone locally
```bash
git clone <your-repo-url>
cd <repo-folder>
```

## 1-3. Bootstrap
```bash
make start
```

## 1-4. First commit + push
```bash
git add .
git commit -m "chore: bootstrap vibe coding OS v2.0"
git push -u origin main
```

At this point, "OS installation is complete."

---

# 2) When you have a PRD (recommended flow)
> The best time for Claude to read a PRD is **right before decomposing into the first real tickets**.

## 2-1. Place the PRD file
- File: `devos/docs/PRD.md`
- Fill in the template or paste your existing PRD

## 2-2. Have Claude do PRD intake
1) Start a session:
```bash
make start
```

2) Open Claude Code in this repo

Claude auto-reads `.claude/CLAUDE.md` and runs boot sequence.
No clipboard needed.

Claude should automatically:
- Research relevant libraries via MCP/context7
- Update `CONTEXT.md` (TL;DR + demo path)
- Update `PROJECT_STATE.md` (milestone/DoD)
- Add questions to `questions/QUEUE.md` (Options/Default)
- Update `docs/API_CONTRACT.md`, `docs/UI_CONTRACT.md` (minimum contracts)
- Create tickets in `tasks/QUEUE.yaml` (WHAT+CONTEXT format)

---

# 3) Daily Session Start — "Just remember this"

## 3-1. Start today's session
```bash
make start
```

Read the **Dashboard** output:
- Open questions (max 5)
- Top tickets
- Agent status

## 3-2. Claude (Dispatcher + Researcher) session-start
Open Claude Code → auto-reads `.claude/CLAUDE.md`.

Claude will:
1. Read SSOT files + latest builder session logs (`devos/logs/`)
2. Research tech context (MCP/context7) if new tickets needed
3. Triage open questions (A-Mode)
4. Report status + next ticket assignments

You only need to **answer the choices**:
e.g., `Q-001=Default, Q-004=B`

## 3-3. Start builders (parallel)
### Codex (backend/main/refactor)
```bash
codex
```
Codex CLI auto-reads `AGENTS.md` at start. No clipboard needed.

### Gemini (frontend/UI/QA)
```bash
gemini
```
Gemini CLI auto-reads `GEMINI.md` at start. No clipboard needed.

## 3-4. Review builder logs after sessions
```bash
make log-review
```

---

# 4) Rules During Work (refer here when confused)

## 4-1. If blocked, use the question queue — not chat
- Questions always go in `questions/QUEUE.md`
- Must include:
  - Options (A/B/C/D)
  - Recommendation
  - Default
  - Blocking/Non-blocking

Add a question template:
```bash
make new-question
```

## 4-2. Ticket-sized work (1 Ticket = 1 PR)
- Create a ticket template:
```bash
make new-ticket
```
- Keep the `files:` scope narrow (prevents collisions)
- Tickets use WHAT+CONTEXT: Claude writes requirements + research; builders decide implementation

## 4-3. Contract-first
- If `apps/api/**` changes → update `docs/API_CONTRACT.md` first/together
- If `apps/web/**` changes → update `docs/UI_CONTRACT.md` first/together

## 4-4. Session logs (builders — required)
At the end of each session, builders write a log to `devos/logs/`:
- Filename: `{date}-{agent}-{ticket-ids}.md`
- Sections: Summary / Decisions Made / Questions Raised / Files Modified / Handoff
- Max 50 lines

---

# 5) Pre-PR Checklist (minimum)
```bash
make pr-check
```

---

# 6) Top Common Mistakes (checklist)
- [ ] Unpacked starter kit **in a subfolder** instead of the repo root
- [ ] Started working **without a first commit** (checks become ineffective)
- [ ] SSOT files are **in a different repo/path** with `../` references (not recommended)
- [ ] Changed API/UI behavior **without updating contract docs**
- [ ] Asked questions **in chat** instead of recording in `questions/QUEUE.md`
- [ ] Using `make copy-codex` / `make copy-gemini` — these are deprecated; use native CLI auto-load
- [ ] Writing code-level instructions in tickets — tickets should be WHAT+CONTEXT, not HOW
- [ ] Builders not writing session logs — Claude has no cross-agent visibility without them

---

# 7) Today's Shortest Routine (cheat sheet)
```bash
make start
# Open Claude Code — auto-reads CLAUDE.md, triages questions

codex          # Start Codex (auto-reads AGENTS.md)
gemini         # Start Gemini (auto-reads GEMINI.md)

make log-review      # Check what builders accomplished
make pr-check        # Minimum pre-PR gate
```

---

## Help
- To see available commands:
```bash
make help
```

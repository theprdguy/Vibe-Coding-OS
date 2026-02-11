# Vibe Coding OS Manual 101 (v1.5)
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

---

# 1) Project Setup (Day 0) — GitHub-first (recommended)

## 1-1. Create a new repo on GitHub
- **Empty repo recommended**: turn off auto-generation of README/License/Gitignore if possible
- Default branch: **main**

## 1-2. Clone locally
```bash
git clone <your-repo-url>
cd <repo-folder>
```

## 1-3. Unpack the starter kit
- Unpack the Vibe Coding OS files into the **repo root**
  (Makefile, devos/, .claude/, START_HERE.md should appear at the root)

## 1-4. Initial check + first commit + push
```bash
make start

git add .
git commit -m "chore: bootstrap vibe coding OS v1.5"
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
1) Start a session
```bash
make start
```

2) Copy the Claude prompt to clipboard (macOS)
```bash
make copy-claude
```

3) Paste into Claude and run

Claude should automatically update (expected behavior):
- `CONTEXT.md` (TL;DR + demo path)
- `PROJECT_STATE.md` (milestone/DoD)
- `questions/QUEUE.md` (decision questions with Options/Default)
- `docs/API_CONTRACT.md`, `docs/UI_CONTRACT.md` (minimum contracts)
- `tasks/QUEUE.yaml` (first real ticket dispatch)

---

# 3) Daily Session Start — "Just remember this"

## 3-1. Start today's session
```bash
make start
```

Read the **Dashboard** output:
- Open questions (max 5)
- Top tickets
- Next prompts to run (Claude/Codex/Gemini)

## 3-2. Claude (Dispatcher) session-start triage
```bash
make copy-claude
```
- Paste into Claude
- You only need to **answer the choices**
  e.g., `Q-001=Default, Q-004=B`

What Claude should do:
- Process answers in `questions/QUEUE.md` (mark [answered])
- Update ADR/Contracts/Tasks/STATE as needed
- Re-sort/unblock today's tickets

## 3-3. Start builders (parallel)
### Codex (backend/main/refactor)
```bash
make copy-codex
```

### Gemini (frontend/UI/QA)
```bash
make copy-gemini
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

## 4-3. Contract-first
- If `apps/api/**` changes → update `docs/API_CONTRACT.md` first/together
- If `apps/web/**` changes → update `docs/UI_CONTRACT.md` first/together

---

# 5) Pre-PR Checklist (minimum)
```bash
make pr-check
```

Claude PR review prompt:
```bash
make show-claude
```
(Use the review-pr prompt from `devos/prompts/claude/review-pr.md`)

---

# 6) Top 5 Common Mistakes (checklist)
- [ ] Unpacked starter kit **in a subfolder** instead of the repo root
- [ ] Started working **without a first commit** (checks become ineffective)
- [ ] SSOT files are **in a different repo/path** with `../` references (not recommended)
- [ ] Changed API/UI behavior **without updating contract docs**
- [ ] Asked questions **in chat** instead of recording in `questions/QUEUE.md`

---

# 7) Today's Shortest Routine (cheat sheet)
```bash
make start
make copy-claude      # Run Claude triage

make copy-codex       # Start Codex
make copy-gemini      # Start Gemini

make pr-check         # Minimum pre-PR gate
```

---

## Help
- To see available commands:
```bash
make help
```

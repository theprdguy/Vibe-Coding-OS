# START HERE — Vibe Coding OS v2.0

## 1) Session start
```bash
make start
```

## 2) Claude triage (Manager + Researcher)
Open Claude Code in this repo — it auto-reads `.claude/CLAUDE.md`.

Claude will:
- Read SSOT files + latest builder session logs
- Research tech context via MCP/context7
- Triage open questions (A-Mode)
- Report status + next ticket assignments

## 3) Start builders in parallel
Builders auto-read their instruction file on CLI start. No clipboard needed.

```bash
# Backend/Infra builder
codex        # auto-reads AGENTS.md

# Frontend/UI builder
gemini       # auto-reads GEMINI.md
```

## 4) Review builder session logs
```bash
make log-review
```

## 5) Before PR
```bash
make pr-check
```

## Key rules
- **Claude = Manager + Researcher** (plans, researches, creates tickets, reviews — no code)
- **Codex/Gemini = Builders** (implement from tickets, write session logs)
- **Tickets = WHAT + CONTEXT** (Claude writes requirements + research; builders decide HOW)
- **Session logs** = cross-agent visibility (write at session end, read at next boot)

## Useful commands
```bash
make agents        # list registered agents
make logs          # recent session logs
make log-review    # latest log per agent
make queue         # current ticket queue
make triage        # open questions only
make new-ticket    # add a ticket
make new-question  # add a question
make worktree-create TICKET=T-xxx  # isolated parallel work
```

## Learn more
- System Guide: `devos/docs/SYSTEM_GUIDE.md`
- Playbook: `devos/docs/PLAYBOOK.md`
- Manual 101: `devos/docs/MANUAL_101.md`

# START HERE — Vibe Coding OS v1.5

## 1) Session start
```bash
make start
```

## 2) Claude triage (Dispatcher)
```bash
make copy-claude
```
Paste into Claude. Answer queued questions (A/B/C/Default).

## 3) Start builders in parallel
```bash
make copy-codex    # paste into Codex
make copy-gemini   # paste into Gemini
```

## 4) Before PR
```bash
make pr-check
```

## Key rule
- **Claude = Manager** (plans, creates tickets, reviews)
- **Codex/Gemini = Builders** (implement code from tickets)
- Claude does NOT write implementation code

## Learn more
- System Guide: `devos/docs/SYSTEM_GUIDE.md`
- Playbook: `devos/docs/PLAYBOOK.md`
- Manual 101: `devos/docs/MANUAL_101.md`

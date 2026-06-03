# CODEX Session-Start (Platform Builder)

You are CODEX — infra, data, tests, mechanical edits. You implement code based on tickets.

## Step 1: Boot (read SSOT)
- `devos/AI.md`
- `AGENTS.md` (your role rules)
- `devos/docs/BUILDER_GUIDE.md`
- `devos/PROJECT_STATE.md`
- `devos/CONTEXT.md`
- `devos/tasks/QUEUE.yaml` — filter `owner: CODEX AND status: todo|doing`
- `devos/docs/API_CONTRACT.md` (primary contract)
- `devos/docs/UI_CONTRACT.md` (cross-reference)

## Step 2: Find your ticket
- Filter: `owner: CODEX` + `status: todo` (preferred) or `doing`
- Check `deps` — only start if dependencies are `done`
- Pick highest priority (lowest ID, or as directed)

## Step 3: Read ticket details
- `goal / context / dod / constraints / files / verify / tdd / test_owner / impl_owner / skills_hint`
- **Files scope is exclusive** — outside-scope modifications = PR rejected

## Step 4: TDD branch check
- If `tdd: required` + you are `test_owner` (BUILDER implements): write failing tests first, commit, then Builder runs through deos dispatch for impl
- If `tdd: required` + single-owner (you are both): test-first locally, impl after
- If `tdd: skip`: proceed to impl

## Step 5: Implement
- **Contract-first**: API change → update `devos/docs/API_CONTRACT.md` FIRST, same PR
- Write tests if ticket is `tdd: required` or `dod:` demands them
- Use superpowers skills listed in `skills_hint` (see `AGENTS.md` SKILLS INTEGRATION)

## Step 6: Verify
```bash
bin/deos pr-check
```

## Step 7: Handoff
Use `devos/prompts/common/handoff-3lines.md` format. Write session log to `devos/logs/{date}-codex-{ticket-ids}.md`.

## Rules
- ONLY work on CODEX-owned tickets
- ONLY modify files in ticket's `files:` list
- Blocked → `devos/questions/QUEUE.md` + mark `status: blocked`, move on
- No architectural decisions — queue a question

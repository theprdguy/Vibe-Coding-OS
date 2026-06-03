# Superpowers Plugin Install

The `.claude/CLAUDE.md` and `AGENTS.md` reference 6 Anthropic **superpowers** skills (brainstorming, writing-plans, dispatching-parallel-agents, systematic-debugging, requesting-code-review, verification-before-completion). These come from the `claude-plugins-official` marketplace (repo `anthropics/claude-plugins-official`). (옛 `.claude-b/CLAUDE.md` 는 W6 sunset 으로 제거됨, 2026-05-13.)

**This is a user-initiated install** — CLAUDE1 does not run plugin installs automatically.

## Install (one-time, per laptop)

In Claude Code:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install superpowers@claude-plugins-official
```

Verify:

```
/plugin list
```

You should see `superpowers` with a version (5.0.7 or later).

## Verify skills are available

In a Claude Code session, type `/` and look for:
- `/brainstorming`
- `/writing-plans`
- `/dispatching-parallel-agents`
- `/systematic-debugging`
- `/requesting-code-review`
- `/verification-before-completion`

If absent: re-run install, restart Claude Code.

## Two-laptop note

Install on both laptops (main + sub). Plugin cache lives in per-laptop `.claude/plugins/cache/`, not in git — so each machine installs once. (옛 `.claude-b/plugins/cache/` 경로는 W6 sunset 으로 제거됨.)

## If install fails

- Marketplace URL offline → ping the user
- Plugin version mismatch → pin via `superpowers@<version>` in the install command
- Don't try to copy cached plugin files from basket/ into os2/ manually — fragile, skips signature verification

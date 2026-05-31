# Third-Party Licenses

Vibe Coding OS is MIT-licensed (see `LICENSE`). This file lists vendored
sources and dependency attributions.

---

## Vendored sources (code included in this repo)

### GSD — get-shit-done

- **File**: `.claude/hooks/context-monitor.js`
- **Copyright**: Copyright (c) 2025 Lex Christopherson
- **License**: MIT
- **Source**: https://github.com/gsd-build/get-shit-done
- **What was vendored**: `gsd-context-monitor.js` — context-usage monitor hook
  that warns the agent when token budget is low. Minor modifications noted in
  the file header (gsd-tools spawn block removed; advisory messages adapted to
  the `devos/` SSOT references used by this OS).

### gstack

- **File**: `devos/prompts/claude/security-audit.md`
- **Copyright**: Copyright (c) 2026 Garry Tan
- **License**: MIT
- **Source**: https://github.com/garrytan/gstack
- **What was reused**: The *prompt portion* of the `/cso` skill
  (OWASP A01–A10 + STRIDE checklist). The original ML classifier, Haiku
  voting layer, and canary-token infrastructure are **not** included.

---

## Dependencies (not vendored)

The following packages are installed dependencies, not vendored. Their
licenses govern their respective distributions.

### obra/superpowers

- **License**: MIT
- **Source**: https://github.com/obra/superpowers
- **Usage**: Installed as a Claude Code plugin via the Anthropic
  claude-plugins-official marketplace. Provides agentic skills
  (`brainstorming`, `writing-plans`, `systematic-debugging`, etc.).
  No code from this package is copied into this repository.

---

If your work is referenced here and you would like an attribution updated,
corrected, or removed, please open an issue.

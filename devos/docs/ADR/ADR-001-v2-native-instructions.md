# ADR-001: Native Instruction Files

## Status
Accepted (v2.0)

## Context
v1.5 used `make copy-codex` / `make copy-gemini` to copy session-start prompts to clipboard. Users then manually pasted into each CLI. This was cumbersome and error-prone.

Codex CLI natively reads `AGENTS.md` from repo root. Gemini CLI natively reads `GEMINI.md` from repo root. Claude Code auto-reads `.claude/CLAUDE.md`.

## Decision
Create root-level `AGENTS.md` (consolidating Codex rules + session-start) and `GEMINI.md` (consolidating Gemini rules + session-start). Each CLI auto-loads its instruction file — no clipboard copy needed.

`make copy-*` targets are deprecated but kept as fallback.

## Consequences
- Zero-friction agent startup: just open CLI in the repo
- Each instruction file is the single source for that agent's rules
- Old `devos/.codex/CODEX.md` and `devos/prompts/codex/session-start.md` are superseded

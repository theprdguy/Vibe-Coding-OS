#!/usr/bin/env bash
# dropin-init.sh — scaffold Vibe Coding OS into an existing single repo.
#
# Run from the root of the repo you want to adopt the OS into:
#   cd /path/to/your-project
#   bash /path/to/vibe-coding-os/scripts/dropin-init.sh
#
# What this does:
#   1. Copies .claude/ (agents, hooks, settings) into your repo.
#   2. Creates a minimal devos/ skeleton (QUEUE.yaml, questions/QUEUE.md,
#      PROJECT_STATE.md, CONTEXT.md).
#   3. Writes a .os3.yaml marker so `os3` commands resolve this directory.
#   4. Rewrites .claude/settings.json hook paths to point at THIS repo's own
#      .claude/hooks/ directory (absolute, target-local), making the drop-in
#      repo fully self-contained. The source OS clone does not need to remain
#      in place for the hooks to fire.
#
# Idempotent: re-running skips files that already exist.
#
# NOTE on full os3 dispatch:
#   The `os3 dispatch` command (Python subprocess routing) requires the host
#   `bin/os3` CLI on PATH. You can either:
#   (a) Install the full host-OS (see README "host-OS model" section), or
#   (b) Run the OS in drop-in mode, which still gives you:
#       - CLAUDE1 doctrine + agent definitions (.claude/agents/)
#       - Read-only review/security/designer agents
#       - The guard-no-impl + context-monitor hooks
#       - devos/ SSOT skeleton for tickets, plans, logs, and questions
#   Graduate to the host-OS model when you want multi-project support and
#   full `os3` CLI routing.

set -euo pipefail

GREEN="$(printf '\033[32m')"
YELLOW="$(printf '\033[33m')"
BLUE="$(printf '\033[34m')"
RESET="$(printf '\033[0m')"

ok()   { printf "${GREEN}ok  %s${RESET}\n" "$1"; }
skip() { printf "${YELLOW}--  %s (already exists — skipped)${RESET}\n" "$1"; }
info() { printf "${BLUE}>>  %s${RESET}\n" "$1"; }

# Resolve paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$(pwd)"

if [ "$TARGET_DIR" = "$OS_ROOT" ]; then
  printf "error: run this from your project repo, not from the Vibe Coding OS repo itself.\n" >&2
  exit 1
fi

info "Vibe Coding OS drop-in init"
info "Source:  $OS_ROOT"
info "Target:  $TARGET_DIR"
printf "\n"

# ── 1. Copy .claude/ ──────────────────────────────────────────────────────────
if [ -d "$TARGET_DIR/.claude" ]; then
  skip ".claude/ directory"
else
  cp -r "$OS_ROOT/.claude" "$TARGET_DIR/.claude"
  ok "Copied .claude/"
fi

# Rewrite settings.json hook paths to be target-local:
# The default settings.json ships with $HOME/dev-os paths (the host-OS default).
# We rewrite every hook command path to TARGET_DIR's own .claude/hooks/ so the
# drop-in repo is self-contained and does not depend on the source OS clone.
SETTINGS="$TARGET_DIR/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  # Rewrite hook command paths in the copied settings.json so they point at
  # the TARGET repo's own .claude/hooks/ directory — not at the source OS clone.
  # This makes the drop-in repo fully self-contained: the hooks run from the
  # copy inside the target; the source OS clone does not need to remain in place.
  #
  # Two replacement passes cover both the generic host-OS default path and the
  # actual OS_ROOT (handles non-default install locations).  Both passes are
  # idempotent: if the target path is already present they are no-ops.
  TARGET_HOOKS="$TARGET_DIR/.claude/hooks"
  python3 - "$SETTINGS" "$OS_ROOT" "$TARGET_HOOKS" <<'PY'
import sys, pathlib

settings_path = pathlib.Path(sys.argv[1])
os_root       = sys.argv[2]
target_hooks  = sys.argv[3]

text = settings_path.read_text()

# Pass 1: replace the well-known host-OS default placeholder path
text = text.replace("$HOME/dev-os/.claude/hooks", target_hooks)

# Pass 2: replace the actual OS_ROOT hook path (non-default install locations)
text = text.replace(os_root + "/.claude/hooks", target_hooks)

settings_path.write_text(text)
PY
  ok "Rewrote hook paths in .claude/settings.json → target-local $TARGET_DIR/.claude/hooks/"
fi

# ── 2. devos/ skeleton ────────────────────────────────────────────────────────
mkdir -p "$TARGET_DIR/devos/tasks" \
         "$TARGET_DIR/devos/plans/pending" \
         "$TARGET_DIR/devos/plans/approved" \
         "$TARGET_DIR/devos/plans/rejected" \
         "$TARGET_DIR/devos/logs" \
         "$TARGET_DIR/devos/questions"

# QUEUE.yaml
QUEUE="$TARGET_DIR/devos/tasks/QUEUE.yaml"
if [ -f "$QUEUE" ]; then
  skip "devos/tasks/QUEUE.yaml"
else
  cat > "$QUEUE" <<'YAML'
version: '3.0'
# Vibe Coding OS — active ticket queue.
# See docs/policy/TICKET_SCHEMA.md for the full field reference.
tickets: []
YAML
  ok "Created devos/tasks/QUEUE.yaml"
fi

# questions/QUEUE.md
Q_QUEUE="$TARGET_DIR/devos/questions/QUEUE.md"
if [ -f "$Q_QUEUE" ]; then
  skip "devos/questions/QUEUE.md"
else
  cat > "$Q_QUEUE" <<'MD'
# Question Queue

Unresolved questions that need PM/owner judgment.

Format:
## Q-001 — short title
**Context**: why this came up
**Options**: A / B / C
**Recommendation**: X (default if no answer in 48h)
**Status**: open | resolved
MD
  ok "Created devos/questions/QUEUE.md"
fi

# PROJECT_STATE.md
PS="$TARGET_DIR/devos/PROJECT_STATE.md"
if [ -f "$PS" ]; then
  skip "devos/PROJECT_STATE.md"
else
  cat > "$PS" <<'MD'
# Project State

## Current milestone
<!-- Update after each sprint / major completion -->
- Status: setup
- What works: (describe)
- What is in progress: (describe)

## Locked Decisions (D-XX)
<!-- Decisions that must not be revisited without explicit owner approval -->
<!-- Format: D-01: short description (reason locked) -->
MD
  ok "Created devos/PROJECT_STATE.md"
fi

# CONTEXT.md
CTX="$TARGET_DIR/devos/CONTEXT.md"
if [ -f "$CTX" ]; then
  skip "devos/CONTEXT.md"
else
  cat > "$CTX" <<'MD'
# Project Context

## TL;DR
<!-- One paragraph describing what this project is and its current state -->

## Key constraints
<!-- Architecture, tech stack, non-negotiables -->

## Active focus
<!-- What the team is working on right now -->
MD
  ok "Created devos/CONTEXT.md"
fi

# ── 3. .os3.yaml marker ───────────────────────────────────────────────────────
OS3_YAML="$TARGET_DIR/.os3.yaml"
if [ -f "$OS3_YAML" ]; then
  skip ".os3.yaml"
else
  cat > "$OS3_YAML" <<YAML
# .os3.yaml — Vibe Coding OS project marker.
# This file tells os3 CLI that this directory is a project root.
# Override any host osn.yaml defaults below (all fields optional).

# project_root is resolved automatically from this file's location.
# devos_dir: devos                       # default
# queue_file: devos/tasks/QUEUE.yaml     # default
# plans_dir: devos/plans                 # default
# logs_dir: devos/logs                   # default
YAML
  ok "Created .os3.yaml"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
printf "\n"
info "Drop-in init complete."
printf "\n"
printf "Next steps:\n"
printf "  1. Start a Claude Code session in this repo:\n"
printf "       cd %s && claude\n" "$TARGET_DIR"
printf "\n"
printf "  2. CLAUDE1 will load doctrine from .claude/agents/builder.md + devos/ at session start.\n"
printf "\n"
printf "  3. Submit a PRD. CLAUDE1 decomposes it into tickets in devos/tasks/QUEUE.yaml.\n"
printf "\n"
printf "  4. To use full os3 dispatch (Python routing), install the host CLI:\n"
printf "       See README section 'host-OS model — one engine, many projects'\n"
printf "\n"
printf "  Without the host CLI you still have: doctrine, agent definitions, guard hooks,\n"
printf "  context monitor, and the full devos/ SSOT skeleton.\n"
printf "\n"

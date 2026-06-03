#!/bin/bash
# deos statusLine wrapper.
# Reads statusLine input from stdin, then:
#   1. Writes context bridge file (/tmp/claude-ctx-{session_id}.json) for
#      context-monitor.js to consume.
#   2. Forwards the same stdin to claude-hud, which renders the actual statusLine.
#
# This preserves claude-hud's rich HUD (tools/agents/todos/git/token breakdown)
# while keeping the agent-facing 35/25% context warnings (context-monitor.js)
# functional.
#
# Failure modes:
#   - claude-hud not installed → silent fallback (bridge still written)
#   - bridge writer fails → claude-hud still renders (best-effort)

set -e

INPUT=$(cat)

# 1) Bridge writer (silent — no stdout)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "$INPUT" | node "$SCRIPT_DIR/bridge-only.js" >/dev/null 2>&1 || true

# 2) claude-hud render — locate latest cached version, exec via Bun.
# Mirrors the global statusLine command in ~/.claude/settings.json.
plugin_dir=$(ls -d "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"/plugins/cache/claude-hud/claude-hud/*/ 2>/dev/null \
  | awk -F/ '{ print $(NF-1) "\t" $0 }' \
  | sort -t. -k1,1n -k2,2n -k3,3n -k4,4n \
  | tail -1 \
  | cut -f2-)

if [ -z "$plugin_dir" ] || [ ! -f "${plugin_dir}src/index.ts" ]; then
  # claude-hud not available — emit nothing (statusLine remains empty)
  exit 0
fi

BUN_BIN="${BUN_BIN:-}"
if [ -z "$BUN_BIN" ]; then
  BUN_BIN="$(command -v bun 2>/dev/null || true)"
fi
# Fallback: statusLine exec env may not have ~/.bun/bin on PATH (mirrors the
# hardcoded path used by the global statusLine in ~/.claude/settings.json).
if [ -z "$BUN_BIN" ] || [ ! -x "$BUN_BIN" ]; then
  BUN_BIN="$HOME/.bun/bin/bun"
fi
if [ ! -x "$BUN_BIN" ]; then
  exit 0
fi

echo "$INPUT" | exec "$BUN_BIN" --env-file /dev/null "${plugin_dir}src/index.ts"

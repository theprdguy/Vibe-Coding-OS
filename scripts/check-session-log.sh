#!/usr/bin/env bash

set -euo pipefail

printf '[4/4] session-log\n'

ROOT_DIR="$(pwd)"
QUEUE_FILE="$ROOT_DIR/devos/tasks/QUEUE.yaml"
TODAY="$(date '+%Y-%m-%d')"

agent_info="$(
python3 - <<'PY'
from pathlib import Path
import os
import re
import subprocess

queue_path = Path("devos/tasks/QUEUE.yaml")
agent_env = os.environ.get("AGENT_NAME", "").strip().lower()


def emit(source: str, agent: str) -> None:
    print(f"{source}\t{agent}")
    raise SystemExit(0)


def parse_queue() -> list[dict]:
    ticket_start = re.compile(r"^- id:\s*(.+)$")
    field = re.compile(r"^  ([A-Za-z_]+):\s*(.*)$")
    tickets: list[dict] = []
    current: dict | None = None

    for raw_line in queue_path.read_text().splitlines():
        match = ticket_start.match(raw_line)
        if match:
            if current:
                tickets.append(current)
            current = {"id": match.group(1).strip()}
            continue
        if current is None:
            continue
        match = field.match(raw_line)
        if match:
            key, value = match.groups()
            current[key] = value.strip()
    if current:
        tickets.append(current)
    return tickets


def infer_from_git_email() -> str:
    result = subprocess.run(
        ["git", "config", "user.email"],
        capture_output=True,
        text=True,
        check=False,
    )
    email = result.stdout.strip().lower()
    if not email:
        return ""

    matches = {
        "claude1": ("claude1", "claude-1"),
        "claude2": ("claude2", "claude-2"),
        "codex": ("codex",),
    }
    for agent, patterns in matches.items():
        if any(pattern in email for pattern in patterns):
            return agent
    return ""


if agent_env:
    emit("env", agent_env)

if not queue_path.exists():
    git_agent = infer_from_git_email()
    if git_agent:
        emit("fallback", git_agent)
    if Path(".claude/.claude.json").exists():
        emit("fallback", "claude1")
    if Path(".claude-b/.claude.json").exists():
        emit("fallback", "claude2")
    emit("fallback", "codex")

tickets = parse_queue()

doing = [ticket for ticket in tickets if ticket.get("status") == "doing"]
if doing:
    owner = doing[0].get("owner", "").strip().lower()
    if owner:
        emit("doing", owner)

git_agent = infer_from_git_email()
if git_agent:
    emit("fallback", git_agent)
if Path(".claude/.claude.json").exists():
    emit("fallback", "claude1")
if Path(".claude-b/.claude.json").exists():
    emit("fallback", "claude2")
emit("fallback", "codex")
PY
)"

agent_source="${agent_info%%	*}"
agent_name="${agent_info#*	}"
fallback_tag=""

if [ "$agent_source" = "$agent_info" ]; then
  agent_source=""
  agent_name=""
fi

if [ -z "$agent_name" ]; then
  echo "⚠️ WARN session-log: unable to determine agent name. Set AGENT_NAME env or mark ticket as doing. Example: AGENT_NAME=CLAUDE1 make pr-check"
  exit 0
fi

if [ "$agent_source" = "fallback" ]; then
  fallback_tag=" (fallback)"
fi

log_file="$ROOT_DIR/devos/logs/${TODAY}-${agent_name}.md"
agent_name_upper="$(printf '%s' "$agent_name" | tr '[:lower:]' '[:upper:]')"
if [ -f "$log_file" ]; then
  echo "✅ PASS session-log${fallback_tag}"
else
  echo "⚠️ WARN session-log${fallback_tag}: session log missing ($log_file)"
  echo "Set AGENT_NAME env or mark ticket as doing. Example: AGENT_NAME=${agent_name_upper} make pr-check"
fi

#!/usr/bin/env bash

set -euo pipefail

printf '[3/4] ticket-scope\n'

ROOT_DIR="$(pwd)"
QUEUE_FILE="$ROOT_DIR/devos/tasks/QUEUE.yaml"

if [ ! -f "$QUEUE_FILE" ]; then
  echo "⚠️ WARN ticket-scope: queue file missing"
  exit 0
fi

AGENT_NAME_VALUE="${AGENT_NAME:-}"
export AGENT_NAME_VALUE

out_of_scope="$(
python3 - <<'PY'
from pathlib import Path
import os
import subprocess
import sys
import re

queue_path = Path("devos/tasks/QUEUE.yaml")
agent_name = os.environ.get("AGENT_NAME_VALUE", "").strip().upper()


def collect_changed_files() -> list[str]:
    changed: list[str] = []
    seen: set[str] = set()
    commands = []
    head_ok = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if head_ok:
        commands.append(["git", "diff", "--name-only", "HEAD", "--"])
    else:
        commands.append(["git", "diff", "--name-only", "--cached", "--"])
    commands.append(["git", "ls-files", "--others", "--exclude-standard"])
    for cmd in commands:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        for line in proc.stdout.splitlines():
            path = line.strip()
            if path and path not in seen:
                seen.add(path)
                changed.append(path)
    return changed


def parse_queue() -> list[dict]:
    tickets: list[dict] = []
    current: dict | None = None
    in_files = False
    ticket_start = re.compile(r"^- id:\s*(.+)$")
    field = re.compile(r"^  ([A-Za-z_]+):\s*(.*)$")
    list_item = re.compile(r"^  -\s*(.+)$")

    for raw_line in queue_path.read_text().splitlines():
        match = ticket_start.match(raw_line)
        if match:
            if current:
                tickets.append(current)
            current = {"id": match.group(1).strip(), "files": []}
            in_files = False
            continue
        if current is None:
            continue
        match = field.match(raw_line)
        if match:
            key, value = match.groups()
            if key == "files":
                current["files"] = []
                in_files = True
            else:
                current[key] = value.strip()
                in_files = False
            continue
        if in_files:
            match = list_item.match(raw_line)
            if match:
                current["files"].append(match.group(1).strip())
                continue
        if raw_line and not raw_line.startswith(" "):
            in_files = False
    if current:
        tickets.append(current)
    return tickets


tickets = parse_queue()
doing_tickets = [ticket for ticket in tickets if ticket.get("status") == "doing"]
if agent_name:
    scoped_tickets = [ticket for ticket in doing_tickets if ticket.get("owner", "").upper() == agent_name]
else:
    scoped_tickets = doing_tickets

allowed = {
    path for ticket in scoped_tickets for path in ticket.get("files", [])
    if path and not Path(path).is_absolute()
}

if not allowed:
    sys.exit(0)

outside = [path for path in collect_changed_files() if path not in allowed]
print("\n".join(outside))
PY
)"

if [ -n "$out_of_scope" ]; then
  echo "⚠️ WARN ticket-scope: scope guard warning"
  printf '%s\n' "$out_of_scope"
else
  echo "✅ PASS ticket-scope"
fi

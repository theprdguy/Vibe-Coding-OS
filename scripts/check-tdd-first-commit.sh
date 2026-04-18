#!/usr/bin/env bash

set -euo pipefail

printf '[5/5] tdd-first-commit\n'

ROOT_DIR="$(pwd)"
QUEUE_FILE="$ROOT_DIR/devos/tasks/QUEUE.yaml"
TODAY="$(date '+%Y-%m-%d')"
AGENT_NAME_VALUE="${AGENT_NAME:-}"
export AGENT_NAME_VALUE TODAY

if [ ! -f "$QUEUE_FILE" ]; then
  echo "⚠️ WARN tdd-first-commit: queue file missing"
  exit 0
fi

python3 - <<'PY'
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

queue_path = Path("devos/tasks/QUEUE.yaml")
today = os.environ["TODAY"]
agent_name = os.environ.get("AGENT_NAME_VALUE", "").strip().upper()

ticket_start = re.compile(r"^- id:\s*(.+)$")
field = re.compile(r"^  ([A-Za-z_]+):\s*(.*)$")

tickets: list[dict[str, str]] = []
current: dict[str, str] | None = None

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

doing_tickets = [ticket for ticket in tickets if ticket.get("status") == "doing"]
if agent_name:
    doing_tickets = [ticket for ticket in doing_tickets if ticket.get("owner", "").upper() == agent_name]

if not doing_tickets:
    print("✅ PASS tdd-first-commit: no active ticket")
    raise SystemExit(0)

def first_commit_for_ticket(ticket_id: str) -> str:
    proc = subprocess.run(
        ["git", "log", "--reverse", "--grep", ticket_id, "--format=%H"],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return ""

def changed_files(commit_sha: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_sha],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

def is_test_file(path: str) -> bool:
    p = Path(path)
    path_text = p.as_posix()
    if path_text.startswith("tests/"):
        return True
    name = p.name
    return (
        "_test." in name
        or ".test." in name
        or ".spec." in name
    )

def append_waiver(ticket_id: str, owner: str) -> None:
    agent_slug = owner.strip().lower() or "unknown"
    log_path = Path("devos/logs") / f"{today}-{agent_slug}.md"
    line = f"self-evident TDD waiver for {ticket_id}"
    existing = log_path.read_text() if log_path.exists() else ""
    if line not in existing:
        with log_path.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{line}\n")

had_failure = False

for ticket in doing_tickets:
    ticket_id = ticket.get("id", "").strip()
    if not ticket_id:
        continue
    tdd_mode = ticket.get("tdd", "skip").strip() or "skip"
    owner = ticket.get("owner", "").strip()

    if tdd_mode == "skip":
        print(f"✅ PASS tdd-first-commit: {ticket_id} TDD skip")
        continue

    if tdd_mode == "self-evident":
        append_waiver(ticket_id, owner)
        print(f"✅ PASS tdd-first-commit: {ticket_id} self-evident waiver logged")
        continue

    if tdd_mode != "required":
        print(f"⚠️ WARN tdd-first-commit: {ticket_id} has unsupported tdd mode '{tdd_mode}'")
        continue

    commit_sha = first_commit_for_ticket(ticket_id)
    if not commit_sha:
        print(f"✅ PASS tdd-first-commit: {ticket_id} not found in commit history, skipped")
        continue

    files = changed_files(commit_sha)
    if any(is_test_file(path) for path in files):
        print(f"✅ PASS tdd-first-commit: {ticket_id} first commit includes test files")
        continue

    print(f"❌ FAIL tdd-first-commit: {ticket_id} first commit lacks test files")
    had_failure = True

if had_failure:
    raise SystemExit(1)
PY

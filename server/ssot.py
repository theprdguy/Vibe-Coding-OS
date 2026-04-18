"""SSOT file readers and writers for devos/."""
from __future__ import annotations

import fcntl
import re
from datetime import datetime
from pathlib import Path

import yaml


# ── QUEUE.yaml ─────────────────────────────────────────────────────────────

DEFAULT_QUEUE_PATH = Path("devos/tasks/QUEUE.yaml")
VALID_STATUSES = {"todo", "doing", "done", "blocked", "parked"}
VALID_TDD_VALUES = ("required", "skip", "self-evident")


class ValidationError(ValueError):
    """Raised when SSOT content violates queue schema expectations."""


def _validate_ticket(ticket: dict) -> dict:
    """Return a normalized ticket with compatibility fallbacks applied."""
    normalized = dict(ticket)
    owner = normalized.get("owner")
    normalized["tdd"] = normalized.get("tdd", "skip")
    normalized["test_owner"] = normalized.get("test_owner", owner)
    normalized["impl_owner"] = normalized.get("impl_owner", owner)

    tdd = normalized["tdd"]
    if tdd not in VALID_TDD_VALUES:
        raise ValidationError(f"tdd must be one of [{', '.join(VALID_TDD_VALUES)}]")

    return normalized


def _validate_queue_data(data: dict) -> dict:
    """Return normalized queue data after validating ticket schema."""
    normalized = dict(data)
    tickets = normalized.get("tickets", [])
    normalized["tickets"] = [_validate_ticket(ticket) for ticket in tickets]
    return normalized


def read_queue(queue_path: Path | None = None) -> dict:
    """Read QUEUE.yaml, validate schema, and return normalized content."""
    queue_path = queue_path or DEFAULT_QUEUE_PATH
    if not queue_path.exists():
        return {"version": "3.0", "tickets": []}
    with open(queue_path) as f:
        data = yaml.safe_load(f) or {}
    if "tickets" not in data:
        data["tickets"] = []
    return _validate_queue_data(data)


def write_queue(queue_path: Path, data: dict) -> None:
    """Write QUEUE.yaml with file lock to prevent concurrent writes."""
    with open(queue_path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def get_tickets_by_owner(queue_path: Path, owner: str) -> list[dict]:
    """Get all tickets for a given owner."""
    data = read_queue(queue_path)
    return [t for t in data.get("tickets", []) if t.get("owner") == owner]


def get_tickets_by_status(queue_path: Path, status: str) -> list[dict]:
    """Get all tickets with a given status."""
    data = read_queue(queue_path)
    return [t for t in data.get("tickets", []) if t.get("status") == status]


def update_ticket_status(queue_path: Path, ticket_id: str, status: str) -> bool:
    """Update the status of a ticket. Returns True if found and updated."""
    data = read_queue(queue_path)
    for ticket in data.get("tickets", []):
        if ticket.get("id") == ticket_id:
            ticket["status"] = status
            write_queue(queue_path, data)
            return True
    return False


def update_ticket_fields(queue_path: Path, ticket_id: str, updates: dict) -> bool:
    """Update arbitrary ticket fields. Returns True if found and updated."""
    data = read_queue(queue_path)
    for ticket in data.get("tickets", []):
        if ticket.get("id") != ticket_id:
            continue
        ticket.update(updates)
        write_queue(queue_path, data)
        return True
    return False

def append_tickets(queue_path: Path, new_tickets: list[dict]) -> None:
    """Append new tickets to QUEUE.yaml."""
    for ticket in new_tickets:
        status = ticket.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Ticket '{ticket.get('id')}' has invalid status '{status}'. "
                f"New tickets must use status 'todo'. Valid values: {sorted(VALID_STATUSES)}"
            )
    data = read_queue(queue_path)
    data["tickets"].extend(new_tickets)
    write_queue(queue_path, data)


def format_queue_summary(queue_path: Path) -> str:
    """Format queue as a readable summary."""
    data = read_queue(queue_path)
    tickets = data.get("tickets", [])
    if not tickets:
        return "Queue: Empty — no tickets yet."

    lines = ["Ticket Queue\n"]
    by_status: dict[str, list] = {}
    for t in tickets:
        s = t.get("status", "unknown")
        by_status.setdefault(s, []).append(t)

    for status in ["doing", "todo", "blocked", "parked", "done"]:
        if status not in by_status:
            continue
        lines.append(f"\n[{status.upper()}]")
        for t in by_status[status]:
            owner = t.get("owner", "?")
            tdd = t.get("tdd", "skip")
            test_owner = t.get("test_owner", owner)
            impl_owner = t.get("impl_owner", owner)
            goal_preview = str(t.get("goal", ""))[:60].strip()
            lines.append(
                f"  {t['id']} [{owner}] tdd={tdd} test_owner={test_owner} "
                f"impl_owner={impl_owner} {goal_preview}"
            )

    return "\n".join(lines)


# ── PROJECT_STATE.md ────────────────────────────────────────────────────────

def read_project_state(devos_path: Path) -> str:
    """Read PROJECT_STATE.md and return content."""
    state_file = devos_path / "PROJECT_STATE.md"
    if not state_file.exists():
        return "(PROJECT_STATE.md not found)"
    return state_file.read_text()


def format_status_summary(devos_path: Path) -> str:
    """Format a concise status summary."""
    content = read_project_state(devos_path)

    lines = content.split("\n")
    summary_lines = ["Project Status\n"]

    in_section = None
    for line in lines:
        if line.startswith("## North Star"):
            in_section = "north_star"
        elif line.startswith("## Current Milestone"):
            in_section = "milestone"
        elif line.startswith("## Agent Status"):
            in_section = "agents"
        elif line.startswith("## In progress"):
            in_section = "progress"
        elif line.startswith("## Blockers"):
            in_section = "blockers"
        elif line.startswith("## "):
            in_section = None

        if in_section in ("north_star", "milestone", "progress", "blockers") and line.strip():
            summary_lines.append(line)

    return "\n".join(summary_lines[:30])


# ── Session Logs ─────────────────────────────────────────────────────────────

def get_recent_logs(logs_path: Path, limit: int = 5) -> list[Path]:
    """Get the most recent session log files."""
    if not logs_path.exists():
        return []
    logs = [f for f in logs_path.iterdir() if f.suffix == ".md" and f.name != "README.md"]
    logs.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return logs[:limit]


def format_logs_summary(logs_path: Path) -> str:
    """Format recent logs as a readable summary."""
    recent = get_recent_logs(logs_path)
    if not recent:
        return "Logs: No session logs yet."

    lines = ["Recent Session Logs\n"]
    for log_file in recent:
        content = log_file.read_text()
        # Extract Summary section
        match = re.search(r"## Summary\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
        summary = match.group(1).strip()[:200] if match else "(no summary)"
        lines.append(f"\n{log_file.name}")
        lines.append(summary)

    return "\n".join(lines)


# ── Plans ────────────────────────────────────────────────────────────────────

def list_pending_plans(plans_path: Path) -> list[Path]:
    """List plans awaiting approval."""
    pending = plans_path / "pending"
    if not pending.exists():
        return []
    return sorted([f for f in pending.iterdir() if f.suffix == ".yaml"])


def read_plan(plan_path: Path) -> dict:
    """Read a plan YAML file."""
    with open(plan_path) as f:
        return yaml.safe_load(f) or {}


def approve_plan(plans_path: Path, plan_id: str, queue_path: Path) -> bool:
    """Move plan from pending to approved and write tickets to QUEUE.yaml."""
    pending_file = plans_path / "pending" / f"{plan_id}.yaml"
    if not pending_file.exists():
        return False

    plan = read_plan(pending_file)
    tickets = plan.get("tickets", [])

    # Write tickets to queue
    append_tickets(queue_path, tickets)

    # Move plan to approved
    approved_dir = plans_path / "approved"
    approved_dir.mkdir(exist_ok=True)
    pending_file.rename(approved_dir / f"{plan_id}.yaml")

    return True


def reject_plan(plans_path: Path, plan_id: str, reason: str) -> bool:
    """Move plan from pending to rejected with reason."""
    pending_file = plans_path / "pending" / f"{plan_id}.yaml"
    if not pending_file.exists():
        return False

    plan = read_plan(pending_file)
    plan["rejection_reason"] = reason
    plan["rejected_at"] = datetime.now().isoformat()

    # Move to rejected
    rejected_dir = plans_path / "rejected"
    rejected_dir.mkdir(exist_ok=True)
    rejected_file = rejected_dir / f"{plan_id}.yaml"
    with open(rejected_file, "w") as f:
        yaml.dump(plan, f, allow_unicode=True)

    pending_file.unlink()
    return True


def format_plan_summary(plan: dict) -> str:
    """Format a plan for approval review."""
    lines = [
        "Plan Ready for Approval",
        f"ID: {plan.get('id', 'unknown')}",
        f"Source: {plan.get('source', 'PRD')}",
        f"\nTickets ({len(plan.get('tickets', []))} total):",
    ]
    for ticket in plan.get("tickets", []):
        owner = ticket.get("owner", "?")
        goal = str(ticket.get("goal", ""))[:80].strip()
        lines.append(f"  {ticket.get('id', '?')} [{owner}] {goal}")

    lines.extend([
        "\nActions:",
        "  make approve           — start work",
        "  make reject R='reason' — revise plan",
    ])
    return "\n".join(lines)

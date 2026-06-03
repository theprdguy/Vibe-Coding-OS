"""Report-oriented handlers for the unified OS CLI."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_paths(args=None):
    from server.cli_gates import _invocation_cwd
    from server.config import resolve_paths

    project = getattr(args, "project", None)
    _config, paths = resolve_paths(project, cwd=_invocation_cwd())
    return paths


REQUIRED_PILOT_POLICY_ARTIFACTS = (
    "docs/policy/ROLE_AUTHORITY_MATRIX.md",
    "docs/policy/MODE_GATE_MATRIX.md",
    "docs/policy/TICKET_SCHEMA.md",
    "docs/policy/WAIVER_FORMAT.md",
    "docs/policy/GEMINI_VISUAL_REVIEW_SCHEMA.md",
)

ACTIVE_PILOT_STATUSES = {"todo", "doing", "code_ready", "needs_pm", "blocked"}


def _pilot_doc_status(project_root: Path) -> dict[str, Any]:
    path = project_root / "docs" / "OS3_E2E_PILOT.md"
    if not path.exists():
        return {"path": "docs/OS3_E2E_PILOT.md", "exists": False, "status": "missing"}

    status = "unknown"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Status:"):
            status = line.split(":", 1)[1].strip() or "unknown"
            break
    return {"path": "docs/OS3_E2E_PILOT.md", "exists": True, "status": status}


def _policy_artifacts(project_root: Path) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for rel_path in REQUIRED_PILOT_POLICY_ARTIFACTS:
        exists = (project_root / rel_path).exists()
        artifacts.append({"path": rel_path, "state": "OK" if exists else "MISSING"})
    return artifacts


def _active_pilot_tickets(queue: dict[str, Any]) -> list[dict[str, Any]]:
    tickets = []
    for ticket in queue.get("tickets", []):
        ticket_id = str(ticket.get("id", ""))
        status = str(ticket.get("status", ""))
        if ticket_id.startswith("T-OS3-PILOT") and status in ACTIVE_PILOT_STATUSES:
            tickets.append({
                "id": ticket_id,
                "status": status,
                "mode": ticket.get("mode", "unknown"),
                "owner": ticket.get("owner", "unknown"),
                "requires_pm_acceptance": bool(ticket.get("requires_pm_acceptance")),
            })
    return tickets


def _next_step(active_tickets: list[dict[str, Any]], artifacts_ok: bool, pilot_doc: dict[str, Any]) -> str:
    if not pilot_doc.get("exists"):
        return "Restore docs/OS3_E2E_PILOT.md before running the pilot."
    if not artifacts_ok:
        return "Restore missing policy artifacts before final pilot acceptance."
    if not active_tickets:
        return "Create or dispatch a narrow T-OS3-PILOT ticket."

    statuses = {str(ticket.get("status", "")) for ticket in active_tickets}
    if statuses & {"todo", "doing"}:
        return "Complete implementation evidence, tests, and move the pilot ticket to code_ready."
    if "code_ready" in statuses:
        return "Run independent reviewer/PM acceptance, then mark the pilot ticket done."
    if "needs_pm" in statuses:
        return "PM decision is required before final pilot acceptance."
    if "blocked" in statuses:
        return "Resolve the blocker or record a PM-approved waiver."
    return "Review pilot evidence and archive completed tickets."


def build_pilot_status(project_root: Path, queue: dict[str, Any]) -> dict[str, Any]:
    """Build a read-only deos pilot readiness report."""
    project_root = Path(project_root)
    pilot_doc = _pilot_doc_status(project_root)
    artifacts = _policy_artifacts(project_root)
    artifacts_ok = all(item["state"] == "OK" for item in artifacts)
    active_tickets = _active_pilot_tickets(queue)
    legacy_todo_count = sum(
        1
        for ticket in queue.get("tickets", [])
        if ticket.get("status") == "todo"
        and str(ticket.get("id", "")).startswith(("T-OS2", "T-OSN"))
    )
    ready = bool(pilot_doc.get("exists") and artifacts_ok and active_tickets)
    return {
        "ready": ready,
        "pilot_doc": pilot_doc,
        "policy_artifacts": artifacts,
        "active_pilot_tickets": active_tickets,
        "legacy_todo_count": legacy_todo_count,
        "next_step": _next_step(active_tickets, artifacts_ok, pilot_doc),
    }


def format_pilot_status(report: dict[str, Any]) -> str:
    """Render a PM-readable pilot status report."""
    lines = ["deos E2E pilot status"]
    pilot_doc = report["pilot_doc"]
    doc_state = "OK" if pilot_doc.get("exists") else "MISSING"
    lines.append(f"Pilot doc: {doc_state} {pilot_doc['path']} (status: {pilot_doc['status']})")

    lines.append("Policy artifacts:")
    for item in report["policy_artifacts"]:
        lines.append(f"  {item['state']} {item['path']}")

    lines.append("Active deos pilot tickets:")
    active = report["active_pilot_tickets"]
    if active:
        for ticket in active:
            pm_flag = " requires_pm_acceptance" if ticket.get("requires_pm_acceptance") else ""
            lines.append(
                f"  {ticket['id']} [{ticket['status']}] owner={ticket['owner']} "
                f"mode={ticket['mode']}{pm_flag}"
            )
    else:
        lines.append("  none")

    lines.append(f"Legacy todo tickets: {report['legacy_todo_count']}")
    lines.append(f"Next evidence step: {report['next_step']}")
    lines.append(f"Strict readiness: {'PASS' if report['ready'] else 'FAIL'}")
    return "\n".join(lines) + "\n"


def pilot_status_exit_code(report: dict[str, Any], *, strict: bool) -> int:
    return 1 if strict and not report.get("ready") else 0


def handle_pilot_status(args):
    """Print deos E2E pilot readiness and evidence state."""
    paths = _load_paths(args)
    from server.ssot import read_queue_with_archive

    project_root = paths["devos"].parent
    queue = read_queue_with_archive(paths["queue"])
    report = build_pilot_status(project_root, queue)
    print(format_pilot_status(report), end="")
    return pilot_status_exit_code(report, strict=bool(getattr(args, "strict", False)))


def handle_cost_report(args):
    """Aggregate dispatch/review channel usage from logs."""
    paths = _load_paths(args)
    log_path = paths["devos"] / "logs" / "dispatch-classification.jsonl"

    if not log_path.exists():
        print(f"no dispatch-classification log yet at {log_path}")
        print("Logs will accumulate as dispatch-orchestration.md Step 5.2 is followed.")
        return 0

    cutoff_days = getattr(args, "days", None) or 30
    cutoff_ts = datetime.now(tz=timezone.utc).timestamp() - cutoff_days * 86400

    classifications = Counter()
    channels = Counter()
    paired_runs = 0
    b_prime_escalations = 0
    total = 0
    with log_path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except Exception:
                continue
            try:
                date_str = row.get("date") or row.get("timestamp", "")
                if "T" in date_str:
                    ts = datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
                else:
                    ts = (
                        datetime.strptime(date_str, "%Y-%m-%d")
                        .replace(tzinfo=timezone.utc)
                        .timestamp()
                    )
            except Exception:
                continue
            if ts < cutoff_ts:
                continue
            total += 1
            classifications[row.get("classification", "unknown")] += 1
            for ch in row.get("channels", []):
                channels[ch] += 1
            if row.get("paired_run"):
                paired_runs += 1
            if row.get("b_prime_escalated"):
                b_prime_escalations += 1

    cost_c1 = (
        channels.get("reviewer_opus", 0) * 0.20
        + channels.get("security_opus", 0) * 0.20
        + channels.get("designer_sonnet", 0) * 0.10
    )
    cost_c2 = channels.get("agent_review_haiku", 0) * 0.017 + channels.get("review_claude_p", 0) * 0.07
    cost_c0 = channels.get("codex_subprocess", 0) * 0.05 + channels.get("codex_cross_model", 0) * 0.03

    print(f"=== deos cost report ({cutoff_days}d) ===")
    print(f"Total dispatches: {total}")
    print("Classification:")
    for cls, n in classifications.most_common():
        print(f"  {cls:30s} {n:4d}")
    print(f"Paired-run trials: {paired_runs}")
    escalation_rate = b_prime_escalations / total * 100 if total else 0
    print(f"b' escalations: {b_prime_escalations} ({escalation_rate:.1f}%)")
    print("")
    print("Estimated channel cost (rough):")
    print(f"  C1 (Interactive Max 5x):  ${cost_c1:6.2f}")
    print(f"  C2 (Agent SDK $100/mo):   ${cost_c2:6.2f}   ({cost_c2 / 100 * 100:.1f}% of credit)")
    print(f"  C0 (CODEX OpenAI):        ${cost_c0:6.2f}")
    print(f"  TOTAL:                    ${cost_c1 + cost_c2 + cost_c0:6.2f}")
    if cost_c2 > 80:
        print("WARN C2 usage > 80%; confirm extra-usage toggle.")
    if total and b_prime_escalations / total > 0.25:
        print("WARN b' escalation rate > 25%; review classification protocol.")
    return 0

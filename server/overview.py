"""Cross-project overview for the host OS.

Aggregates ticket counts from every registered project's QUEUE so the host can
show a unified status table (`deos overview`). Read-only: never writes into projects.
One unreadable project must not break the whole table.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

_STATUSES = ("todo", "doing", "blocked")


def build_overview(host: Path) -> list[dict]:
    """Return one row per registered project with todo/doing/blocked counts."""
    from server.projects_registry import list_projects
    from server.ssot import read_queue

    host = Path(host)
    rows: list[dict] = []
    for rec in list_projects(host):
        repo_path = rec.get("repo_path", "")
        root = Path(repo_path)
        if not root.is_absolute():
            root = host / repo_path
        entry = {
            "name": rec.get("name", "?"),
            "status": rec.get("status", ""),
            "repo_path": repo_path,
            "todo": 0,
            "doing": 0,
            "blocked": 0,
            "error": None,
        }
        try:
            queue = read_queue(root / "devos" / "tasks" / "QUEUE.yaml")
            counts = Counter(t.get("status") for t in queue.get("tickets", []))
            for s in _STATUSES:
                entry[s] = counts.get(s, 0)
        except Exception as exc:  # resilience: a bad project must not break overview
            entry["error"] = str(exc)
        rows.append(entry)
    return rows


def format_overview(rows: list[dict]) -> str:
    if not rows:
        return "no projects registered"
    lines = ["project\tstatus\ttodo\tdoing\tblocked"]
    for r in rows:
        if r["error"]:
            lines.append(f"{r['name']}\t{r['status']}\t(error: {r['error']})")
        else:
            lines.append(
                f"{r['name']}\t{r['status']}\t{r['todo']}\t{r['doing']}\t{r['blocked']}"
            )
    return "\n".join(lines)


def handle_overview(args) -> int:
    from server.config import host_root

    print(format_overview(build_overview(host_root())))
    return 0

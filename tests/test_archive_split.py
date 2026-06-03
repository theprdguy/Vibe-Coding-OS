from __future__ import annotations

from pathlib import Path

import yaml

from server.dispatcher import Dispatcher
from server.ssot import (
    archive_done_tickets,
    archive_path_for_queue,
    find_ticket,
    read_archive,
    read_queue,
    read_queue_with_archive,
)


def _write_queue(path: Path, tickets: list[dict]) -> None:
    path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str, status: str, **extra: object) -> dict:
    ticket = {
        "id": ticket_id,
        "owner": "CODEX",
        "status": status,
        "goal": f"{ticket_id} goal",
        "files": ["server/ssot.py"],
        "verify": "pytest tests/test_archive_split.py -v",
        "deps": [],
    }
    ticket.update(extra)
    return ticket


def _dispatcher(tmp_path: Path) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()
    return Dispatcher(
        config={"agents": {"CODEX": {}}},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def test_archive_done_tickets_creates_archive_and_removes_done_from_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        [
            _ticket("T-DONE-1", "done"),
            _ticket("T-TODO-1", "todo"),
            _ticket("T-DONE-2", "done"),
        ],
    )

    moved, skipped = archive_done_tickets(queue_path)

    assert moved == 2
    assert skipped == []
    assert [ticket["id"] for ticket in read_queue(queue_path)["tickets"]] == ["T-TODO-1"]
    archive_tickets = read_archive(queue_path)["tickets"]
    assert [ticket["id"] for ticket in archive_tickets] == ["T-DONE-1", "T-DONE-2"]
    assert all(ticket["status"] == "done" for ticket in archive_tickets)


def test_archive_done_tickets_is_idempotent_when_no_done_tickets_remain(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-DONE-1", "done"), _ticket("T-TODO-1", "todo")])
    assert archive_done_tickets(queue_path) == (1, [])
    queue_before = queue_path.read_text(encoding="utf-8")
    archive_path = archive_path_for_queue(queue_path)
    archive_before = archive_path.read_text(encoding="utf-8")

    moved, skipped = archive_done_tickets(queue_path)

    assert (moved, skipped) == (0, [])
    assert queue_path.read_text(encoding="utf-8") == queue_before
    assert archive_path.read_text(encoding="utf-8") == archive_before


def test_find_ticket_prefers_queue_over_archive_and_warns(tmp_path: Path, capsys) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-DUP", "todo", goal="active copy")])
    _write_queue(archive_path_for_queue(queue_path), [_ticket("T-DUP", "done", goal="archived copy")])

    ticket, source = find_ticket(queue_path, "T-DUP")

    assert source == "queue"
    assert ticket is not None
    assert ticket["goal"] == "active copy"
    assert "duplicate ticket id T-DUP in archive (using active)" in capsys.readouterr().err


def test_dispatch_archived_done_ticket_exits_before_mutating_queue(tmp_path: Path, capsys) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    archive_path = archive_path_for_queue(queue_path)
    _write_queue(queue_path, [_ticket("T-ACTIVE", "todo")])
    _write_queue(archive_path, [_ticket("T-ARCHIVED", "done")])
    queue_before = queue_path.read_text(encoding="utf-8")
    archive_before = archive_path.read_text(encoding="utf-8")

    ok, msg = _dispatcher(tmp_path).dispatch("T-ARCHIVED")

    assert ok is False
    assert msg == "ticket already done (in archive)"
    assert "ticket already done (in archive)" in capsys.readouterr().err
    assert queue_path.read_text(encoding="utf-8") == queue_before
    assert archive_path.read_text(encoding="utf-8") == archive_before


def test_dispatch_without_archive_preserves_not_found_message(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-ACTIVE", "todo")])

    ok, msg = _dispatcher(tmp_path).dispatch("T-MISSING")

    assert ok is False
    assert msg == "Ticket `T-MISSING` not found in queue."


def test_archive_lock_blocks_dispatch(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-ACTIVE", "todo")])
    queue_path.with_name(".archive.lock").write_text("pid: test\n", encoding="utf-8")

    ok, msg = _dispatcher(tmp_path).dispatch("T-ACTIVE")

    assert ok is False
    assert msg == "archive migration in progress"


def test_dependencies_can_be_satisfied_by_archived_done_ticket(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-CHILD", "todo", deps=["T-PARENT"])])
    _write_queue(archive_path_for_queue(queue_path), [_ticket("T-PARENT", "done")])
    dispatcher = _dispatcher(tmp_path)

    blocked_by = dispatcher._check_deps(read_queue_with_archive(queue_path), ["T-PARENT"])

    assert blocked_by == []


def test_archived_ticket_gates_resolve_against_current_config() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((repo_root / "deos.yaml").read_text(encoding="utf-8"))
    archive = read_archive(repo_root / "devos/tasks/QUEUE.yaml")
    dispatcher = Dispatcher(
        config=config,
        paths={
            "root": repo_root,
            "logs": repo_root / "devos" / "logs",
            "queue": repo_root / "devos" / "tasks" / "QUEUE.yaml",
        },
    )

    failures = []
    for ticket in archive["tickets"]:
        try:
            dispatcher._resolve_gates(ticket)
        except Exception as exc:  # pragma: no cover - diagnostic detail for failures
            failures.append(f"{ticket.get('id')}: {exc}")

    assert failures == []

from __future__ import annotations

from pathlib import Path

import yaml

from server.dashboard_data import (
    BOARD_STATUSES,
    list_dashboard_projects,
    load_project_board,
    load_ticket_detail,
)
from server.projects_registry import register_project


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str, status: str = "todo", **extra: object) -> dict:
    ticket = {
        "id": ticket_id,
        "owner": "CODEX",
        "status": status,
        "priority": "P2",
        "goal": f"{ticket_id} goal\nsecond line",
        "dod": [f"{ticket_id} dod"],
        "files": ["server/dashboard_data.py"],
    }
    ticket.update(extra)
    return ticket


def _write_queue(root: Path, tickets: list[dict]) -> Path:
    path = root / "devos" / "tasks" / "QUEUE.yaml"
    _write_yaml(path, {"version": "3.0", "tickets": tickets})
    return path


def _write_archive(root: Path, tickets: list[dict]) -> Path:
    path = root / "devos" / "tasks" / "ARCHIVE.yaml"
    _write_yaml(path, {"version": "3.0", "tickets": tickets})
    return path


def test_list_dashboard_projects_includes_host_first_then_registry_projects(tmp_path: Path) -> None:
    host = tmp_path / "dev-os"
    _write_queue(host, [_ticket("T-HOST", "todo"), _ticket("T-HOST-DONE", "done")])

    alpha = host / "projects" / "alpha"
    beta = host / "projects" / "beta"
    _write_queue(alpha, [_ticket("T-ALPHA", "doing")])
    _write_queue(beta, [_ticket("T-BETA", "blocked"), _ticket("T-BETA-2", "todo")])
    register_project(host, "alpha", "projects/alpha")
    register_project(host, "beta", "projects/beta")

    rows = list_dashboard_projects(host)

    assert [row["name"] for row in rows] == ["dev-os", "alpha", "beta"]
    assert all(
        set(row) == {"name", "repo_path", "ok", "error", "counts", "total"} for row in rows
    )
    host_row = rows[0]
    assert host_row["ok"] is True
    assert host_row["error"] is None
    assert host_row["counts"]["todo"] == 1
    assert host_row["counts"]["done"] == 1
    assert host_row["total"] == 2

    beta_row = rows[2]
    assert beta_row["ok"] is True
    assert beta_row["counts"]["blocked"] == 1
    assert beta_row["counts"]["todo"] == 1
    assert beta_row["total"] == 2


def test_list_dashboard_projects_isolates_missing_queue_to_that_project(
    tmp_path: Path,
) -> None:
    host = tmp_path / "dev-os"
    _write_queue(host, [])
    valid = host / "projects" / "valid"
    _write_queue(valid, [_ticket("T-VALID", "todo")])
    (host / "projects" / "broken").mkdir(parents=True)
    register_project(host, "broken", "projects/broken")
    register_project(host, "valid", "projects/valid")

    rows = {row["name"]: row for row in list_dashboard_projects(host)}

    assert rows["broken"]["ok"] is False
    assert rows["broken"]["error"]
    assert rows["broken"]["total"] == 0
    assert rows["valid"]["ok"] is True
    assert rows["valid"]["error"] is None
    assert rows["valid"]["counts"]["todo"] == 1


def test_list_dashboard_projects_isolates_malformed_queue_to_that_project(
    tmp_path: Path,
) -> None:
    host = tmp_path / "dev-os"
    _write_queue(host, [])
    bad = host / "projects" / "bad"
    (bad / "devos" / "tasks").mkdir(parents=True)
    (bad / "devos" / "tasks" / "QUEUE.yaml").write_text("tickets: [\n", encoding="utf-8")
    register_project(host, "bad", "projects/bad")

    rows = {row["name"]: row for row in list_dashboard_projects(host)}

    assert rows["bad"]["ok"] is False
    assert rows["bad"]["error"]
    assert rows["bad"]["total"] == 0


def test_load_project_board_returns_status_columns_in_order_with_unknown_appended(
    tmp_path: Path,
) -> None:
    host = tmp_path / "dev-os"
    _write_queue(
        host,
        [
            _ticket("T-TODO", "todo"),
            _ticket("T-DOING", "doing"),
            _ticket("T-CODE", "code_ready"),
            _ticket("T-PM", "needs_pm"),
            _ticket("T-BLOCK", "blocked"),
            _ticket("T-PARK", "parked"),
            _ticket("T-WEIRD", "weird"),
        ],
    )
    _write_archive(host, [_ticket("T-DONE", "done")])

    board = load_project_board(host, "dev-os")

    assert board is not None
    assert board["ok"] is True
    columns = board["columns"]
    assert [column["status"] for column in columns[:7]] == list(BOARD_STATUSES)
    assert [column["status"] for column in columns] == [*BOARD_STATUSES, "unknown"]
    unknown = next(column for column in columns if column["status"] == "unknown")
    assert [ticket["id"] for ticket in unknown["tickets"]] == ["T-WEIRD"]


def test_board_card_shape_and_goal_summary_first_nonempty_line(tmp_path: Path) -> None:
    host = tmp_path / "dev-os"
    _write_queue(
        host,
        [
            _ticket(
                "T-SUMMARY",
                "todo",
                owner="BUILDER",
                priority="P0",
                goal="\n\nFirst non-empty line\nSecond line",
            )
        ],
    )

    board = load_project_board(host, "dev-os")

    assert board is not None
    todo = next(column for column in board["columns"] if column["status"] == "todo")
    assert todo["tickets"] == [
        {
            "id": "T-SUMMARY",
            "owner": "BUILDER",
            "status": "todo",
            "priority": "P0",
            "goal_summary": "First non-empty line",
        }
    ]
    assert set(todo["tickets"][0]) == {"id", "owner", "status", "priority", "goal_summary"}


def test_load_project_board_limits_done_cards_to_archive_tail(tmp_path: Path) -> None:
    host = tmp_path / "dev-os"
    _write_queue(host, [])
    _write_archive(host, [_ticket(f"T-DONE-{i:02d}", "done") for i in range(35)])

    board = load_project_board(host, "dev-os")

    assert board is not None
    done = next(column for column in board["columns"] if column["status"] == "done")
    assert done["done_truncated"] == 5
    assert len(done["tickets"]) == 30
    assert [ticket["id"] for ticket in done["tickets"]] == [
        f"T-DONE-{i:02d}" for i in range(5, 35)
    ]

    small_host = tmp_path / "small-dev-os"
    _write_queue(small_host, [])
    _write_archive(small_host, [_ticket(f"T-SMALL-{i:02d}", "done") for i in range(3)])
    small_board = load_project_board(small_host, "dev-os")
    assert small_board is not None
    small_done = next(column for column in small_board["columns"] if column["status"] == "done")
    assert small_done["done_truncated"] == 0
    assert [ticket["id"] for ticket in small_done["tickets"]] == [
        "T-SMALL-00",
        "T-SMALL-01",
        "T-SMALL-02",
    ]


def test_load_ticket_detail_finds_queue_archive_and_absent_tickets(tmp_path: Path) -> None:
    host = tmp_path / "dev-os"
    active = _ticket("T-ACTIVE", "todo", context="active context")
    archived = _ticket("T-ARCHIVED", "done", context="archived context")
    _write_queue(host, [active])
    _write_archive(host, [archived])

    active_detail = load_ticket_detail(host, "dev-os", "T-ACTIVE")
    archived_detail = load_ticket_detail(host, "dev-os", "T-ARCHIVED")

    assert active_detail is not None
    assert active_detail["id"] == "T-ACTIVE"
    assert active_detail["goal"] == active["goal"]
    assert active_detail["dod"] == active["dod"]
    assert active_detail["context"] == "active context"

    assert archived_detail is not None
    assert archived_detail["id"] == "T-ARCHIVED"
    assert archived_detail["goal"] == archived["goal"]
    assert archived_detail["dod"] == archived["dod"]
    assert archived_detail["context"] == "archived context"

    assert load_ticket_detail(host, "dev-os", "T-ABSENT") is None

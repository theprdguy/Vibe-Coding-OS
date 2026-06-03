from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from server.dispatcher import Dispatcher
from server.ssot import (
    ValidationError,
    read_queue,
    resume_blocked_ticket,
    update_ticket_fields,
    update_ticket_status,
    validate_queue_file,
)


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _dispatcher(tmp_path: Path) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()
    return Dispatcher(
        config={},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def test_update_ticket_status_requires_reason_and_actor(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, {"id": "T-META", "owner": "CODEX", "status": "todo"})

    with pytest.raises(ValidationError, match="transition reason is required"):
        update_ticket_status(
            queue_path,
            "T-META",
            "doing",
            reason="",
            actor="dispatcher",
        )

    with pytest.raises(ValidationError, match="transition actor is required"):
        update_ticket_status(
            queue_path,
            "T-META",
            "doing",
            reason="dispatch started",
            actor="",
        )


def test_update_ticket_fields_rejects_status_without_transition_metadata(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, {"id": "T-META", "owner": "CODEX", "status": "todo"})

    with pytest.raises(ValidationError, match="status changes must use update_ticket_status"):
        update_ticket_fields(queue_path, "T-META", {"status": "doing"})


def test_update_ticket_status_records_transition_metadata(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, {"id": "T-META", "owner": "CODEX", "status": "todo"})

    assert update_ticket_status(
        queue_path,
        "T-META",
        "doing",
        reason="dispatch started",
        actor="dispatcher",
    )

    saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
    assert saved["status"] == "doing"
    assert saved["_transition_reason"] == "dispatch started"
    assert saved["_transition_actor"] == "dispatcher"
    assert saved["_transition_ts"].endswith("Z")


def test_read_queue_backfills_legacy_transition_defaults(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, {"id": "T-LEGACY", "owner": "CODEX", "status": "blocked"})

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["_transition_reason"] == "legacy"
    assert ticket["_transition_actor"] == "pre-meta-02"
    assert ticket["_transition_ts"] == "pre-meta-02"


def test_yaml_validation_rejects_partial_transition_metadata(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": "T-PARTIAL",
            "owner": "CODEX",
            "status": "doing",
            "_transition_actor": "dispatcher",
            "_transition_ts": "2026-04-30T00:00:00Z",
        },
    )

    with pytest.raises(ValidationError, match="_transition_reason is required"):
        validate_queue_file(queue_path)


def test_transition_history_accumulates_when_enabled(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, {"id": "T-HISTORY", "owner": "CODEX", "status": "todo"})

    update_ticket_status(
        queue_path,
        "T-HISTORY",
        "doing",
        reason="dispatch started",
        actor="dispatcher",
        record_history=True,
    )
    update_ticket_status(
        queue_path,
        "T-HISTORY",
        "blocked",
        reason="agent exited with code 1",
        actor="dispatcher",
        record_history=True,
    )

    saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
    assert [entry["status"] for entry in saved["_transition_history"]] == [
        "doing",
        "blocked",
    ]
    assert saved["_transition_history"][1]["reason"] == "agent exited with code 1"


def test_dispatcher_success_records_transition_metadata(tmp_path: Path, monkeypatch) -> None:
    ticket_id = "T-DISPATCH"
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": ticket_id,
            "owner": "CODEX",
            "status": "doing",
            "files": [],
            "deps": [],
            "verify": f"{sys.executable} -c 'print(\"ok\")'",
        },
    )
    dispatcher = _dispatcher(tmp_path)
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
        ),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr=""),
    )

    dispatcher._run_agent(
        {
            "id": ticket_id,
            "owner": "CODEX",
            "files": [],
            "deps": [],
            "verify": f"{sys.executable} -c 'print(\"ok\")'",
        },
        "HEAD",
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "done"
    assert saved["_transition_reason"] == "agent completed + gates pass"
    assert saved["_transition_actor"] == "dispatcher"
    assert [entry["status"] for entry in saved["_transition_history"]] == [
        "code_ready",
        "done",
    ]
    assert saved["_transition_history"][0]["reason"] == (
        "agent completed; awaiting gates and required reviews"
    )


def test_resume_records_user_transition_metadata(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": "T-RESUME",
            "owner": "CODEX",
            "status": "blocked",
            "_blocked_reason": "verify failed",
        },
    )

    resumed = resume_blocked_ticket(queue_path, "T-RESUME")

    assert resumed["status"] == "todo"
    assert resumed["_transition_reason"] == "resumed from blocked"
    assert resumed["_transition_actor"] == "user"

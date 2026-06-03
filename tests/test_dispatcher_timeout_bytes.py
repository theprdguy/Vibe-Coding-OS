from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from server.dispatcher import Dispatcher
from server.ssot import read_queue


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _dispatcher(tmp_path: Path) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()
    return Dispatcher(
        config={"agents": {"CODEX": {"mode": "subprocess"}}},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def test_timeout_failure_with_bytes_stderr_blocks_without_type_error(tmp_path, monkeypatch):
    ticket_id = "T-TIMEOUT-BYTES"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = {"id": ticket_id, "owner": "CODEX", "status": "doing", "files": [], "deps": []}
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    def fake_run_subprocess(ticket, agent_cfg):
        exc = subprocess.TimeoutExpired(
            cmd=["codex"],
            timeout=900,
            output=b"partial stdout \xff",
            stderr=b"partial stderr \xff",
        )
        return False, {
            "reason": "agent timed out after 900s",
            "stdout": exc.stdout,
            "stderr": exc.stderr,
            "returncode": None,
        }

    monkeypatch.setattr(dispatcher, "_run_subprocess", fake_run_subprocess)

    dispatcher._run_agent(ticket, "HEAD")

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert "agent timed out after 900s" in saved["_blocked_reason"]
    assert "_blocked_log" in saved


def test_handle_dispatch_failure_with_str_stderr_blocks_timeout_reason(tmp_path):
    ticket_id = "T-TIMEOUT-STR"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = {"id": ticket_id, "owner": "CODEX", "status": "doing", "files": [], "deps": []}
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    message = dispatcher._handle_dispatch_failure(
        ticket,
        "CODEX",
        {
            "reason": "agent timed out after 900s",
            "stdout": "partial stdout",
            "stderr": "partial stderr",
            "returncode": None,
        },
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert "agent timed out after 900s" in saved["_blocked_reason"]
    assert "partial stderr" in message


def test_handle_dispatch_failure_with_none_stderr_blocks_timeout_reason(tmp_path):
    ticket_id = "T-TIMEOUT-NONE"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = {"id": ticket_id, "owner": "CODEX", "status": "doing", "files": [], "deps": []}
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    message = dispatcher._handle_dispatch_failure(
        ticket,
        "CODEX",
        {
            "reason": "agent timed out after 900s",
            "stdout": None,
            "stderr": None,
            "returncode": None,
        },
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert "agent timed out after 900s" in saved["_blocked_reason"]
    assert "Full log:" in message


def test_detect_quota_reset_accepts_bytes_quota_stderr(tmp_path):
    dispatcher = _dispatcher(tmp_path)

    reset = dispatcher._detect_quota_reset(
        b"CODEX quota exceeded. Please try again at 7:45 PM."
    )

    assert reset == "7:45 PM"

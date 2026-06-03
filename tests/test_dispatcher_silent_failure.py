from __future__ import annotations

import signal
import subprocess
from pathlib import Path

import pytest
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
        config={"agents": {"CODEX": {"mode": "subprocess", "timeout": 17}}},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def _ticket(ticket_id: str) -> dict:
    return {"id": ticket_id, "owner": "CODEX", "status": "doing", "files": [], "deps": []}


def test_signal_terminated_subprocess_blocks_with_signal_reason(tmp_path, monkeypatch, capsys):
    ticket_id = "T-SIGNAL-KILL"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = _ticket(ticket_id)
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            -signal.SIGKILL,
            stdout="",
            stderr="",
        ),
    )

    success, failure = dispatcher._run_subprocess(ticket, {"command": ["codex"], "timeout": 17})
    assert success is False
    dispatcher._run_agent(ticket, "HEAD")

    saved = read_queue(queue_path)["tickets"][0]
    captured = capsys.readouterr()
    assert saved["status"] == "blocked"
    assert "signal_terminated: SIGKILL" in saved["_blocked_reason"]
    assert "signal_terminated: SIGKILL" in captured.err


def test_timeout_subprocess_blocks_with_dispatch_timeout_reason(tmp_path, monkeypatch, capsys):
    ticket_id = "T-TIMEOUT-FIXTURE"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = _ticket(ticket_id)
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=17,
            output=b"partial stdout",
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    success, failure = dispatcher._run_subprocess(ticket, {"command": ["codex"], "timeout": 17})
    assert success is False
    dispatcher._run_agent(ticket, "HEAD")

    saved = read_queue(queue_path)["tickets"][0]
    captured = capsys.readouterr()
    assert saved["status"] == "blocked"
    assert f"dispatch_timeout: {ticket_id} after 17s" in saved["_blocked_reason"]
    assert f"dispatch_timeout: {ticket_id} after 17s" in captured.err


def test_ssot_update_status_exception_blocks_with_explicit_reason(
    tmp_path, monkeypatch, capsys
):
    ticket_id = "T-SSOT-UPDATE-STATUS-FAIL"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = _ticket(ticket_id)
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
        ),
    )
    monkeypatch.setattr(dispatcher, "_run_gates", lambda ticket, sha: (True, "all gates passed"))
    monkeypatch.setattr(dispatcher, "_get_agent_log", lambda owner, tid: "")

    def fail_update_status(*args, **kwargs):
        raise RuntimeError("queue write exploded")

    monkeypatch.setattr("server.dispatcher.update_ticket_status", fail_update_status)

    dispatcher._run_agent(ticket, "HEAD")

    saved = read_queue(queue_path)["tickets"][0]
    captured = capsys.readouterr()
    assert saved["status"] == "blocked"
    assert "ssot_update_failed: queue write exploded" in saved["_blocked_reason"]
    assert "ssot_update_failed: queue write exploded" in captured.err


def test_gate_exception_blocks_with_gate_exception_reason(tmp_path, monkeypatch, capsys):
    ticket_id = "T-GATE-EXCEPTION"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = _ticket(ticket_id)
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
        ),
    )

    def explode_gates(ticket, sha):
        raise RuntimeError("gate config exploded")

    monkeypatch.setattr(dispatcher, "_run_gates", explode_gates)
    monkeypatch.setattr(dispatcher, "_get_agent_log", lambda owner, tid: "")

    dispatcher._run_agent(ticket, "HEAD")

    saved = read_queue(queue_path)["tickets"][0]
    captured = capsys.readouterr()
    assert saved["status"] == "blocked"
    assert "gate_exception: gate config exploded" in saved["_blocked_reason"]
    assert "gate_exception: gate config exploded" in captured.err

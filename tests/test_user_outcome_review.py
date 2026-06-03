from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.dispatcher import (
    Dispatcher,
    USER_REVIEW_CAPTURE_CMD_ENV,
    USER_REVIEW_DECISION_ENV,
)
from server.ssot import read_queue


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str, **kwargs) -> dict:
    base: dict = {
        "id": ticket_id,
        "owner": "CLAUDE2",
        "status": "doing",
        "files": ["apps/web/src/foo.tsx"],
        "deps": [],
        "verify": "python3 -c 'print(\"ok\")'",
    }
    base.update(kwargs)
    return base


def _production_ui_ticket(ticket_id: str, **kwargs) -> dict:
    base = _ticket(
        ticket_id,
        mode="production",
        user_outcome="User can complete the production UI workflow safely.",
        risk_level="medium",
        work_type="ui",
        policy_class="hard",
        requires_visual_review=True,
        requires_security_review=False,
        requires_pm_acceptance=False,
        dod=["Production UI has a captured visual review outcome."],
        screenshot_tool="playwright",
    )
    base.update(kwargs)
    return base


def _dispatcher(tmp_path: Path) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    return Dispatcher(
        config={},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


# Fixture 1: screenshot_tool not set → graceful skip, no error, no decision
def test_no_screenshot_tool_graceful_skip(tmp_path):
    ticket_id = "T-OS2-UOR-01"
    ticket = _ticket(ticket_id)
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is True
    assert "SKIP" in msg
    assert "no screenshot_tool" in msg
    # Queue must not be modified (ticket stays doing, no blocked_reason)
    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "doing"
    assert "_blocked_reason" not in saved


# Fixture 2: screenshot_tool=playwright + tool executable missing → stderr warning + graceful skip
def test_playwright_tool_missing_warns_stderr_and_skips(tmp_path, monkeypatch, capsys):
    ticket_id = "T-OS2-UOR-02"
    ticket = _ticket(ticket_id, screenshot_tool="playwright")
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _exe: None)

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    # Gate gracefully skips (passes True) when tool binary is absent
    assert passed is True
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "not found" in captured.err
    assert "playwright" in captured.err.lower() or "npx" in captured.err


def test_required_production_visual_review_tool_missing_blocks(tmp_path, monkeypatch, capsys):
    ticket_id = "T-OS2-UOR-PROD-MISSING"
    ticket = _production_ui_ticket(ticket_id)
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _exe: None)

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is False
    assert "infra_failure" in msg
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == "visual_review_infra_failure"
    assert "tool unavailable" in saved["_blocked_log"]


def test_required_production_visual_review_capture_failure_blocks(tmp_path, monkeypatch):
    ticket_id = "T-OS2-UOR-PROD-CAPTURE"
    ticket = _production_ui_ticket(ticket_id)
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _exe: "/usr/local/bin/npx")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess(
            "",
            1,
            stdout="",
            stderr="browser failed",
        ),
    )

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is False
    assert "infra_failure" in msg
    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == "visual_review_infra_failure"
    assert "capture failed" in saved["_blocked_log"]
    assert "browser failed" in saved["_blocked_log"]


# Fixture 3: user decision OK → review passes, ticket is done-processable
def test_user_ok_decision_returns_pass(tmp_path, monkeypatch):
    ticket_id = "T-OS2-UOR-03"
    ticket = _ticket(ticket_id, screenshot_tool="playwright")
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.setenv(USER_REVIEW_DECISION_ENV, "ok")
    monkeypatch.setattr(shutil, "which", lambda _exe: "/usr/local/bin/npx")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess("", 0, stdout="Playwright passed", stderr=""),
    )

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is True
    assert "PASS" in msg
    assert ticket_id in msg
    assert "accepted" in msg


def test_missing_user_decision_moves_ticket_to_needs_pm(tmp_path, monkeypatch):
    ticket_id = "T-OS2-UOR-03B"
    ticket = _ticket(ticket_id, screenshot_tool="playwright")
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.delenv(USER_REVIEW_DECISION_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda _exe: "/usr/local/bin/npx")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess("", 0, stdout="Playwright ran", stderr=""),
    )

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is False
    assert "PENDING" in msg
    assert f"bin/os3 user-review {ticket_id}" in msg
    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "needs_pm"
    assert saved["_transition_reason"] == "user_outcome_review_pending"
    assert saved["_transition_actor"] == "dispatcher"


# Fixture 4: user decision reject → fast-follow draft created + source ticket blocked
def test_user_reject_drafts_fast_follow_and_blocks_source(tmp_path, monkeypatch):
    ticket_id = "T-OS2-UOR-04"
    ticket = _ticket(ticket_id, screenshot_tool="playwright")
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    monkeypatch.setenv(USER_REVIEW_DECISION_ENV, "reject")
    monkeypatch.setattr(shutil, "which", lambda _exe: "/usr/local/bin/npx")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: subprocess.CompletedProcess("", 0, stdout="Playwright ran", stderr=""),
    )

    passed, msg = dispatcher._run_user_outcome_review(ticket, allow_prompt=False)

    assert passed is False
    assert "REJECT" in msg
    assert ticket_id in msg

    queue_data = read_queue(queue_path)
    by_id = {t["id"]: t for t in queue_data["tickets"]}

    # Source ticket must be blocked with rejection reason
    assert by_id[ticket_id]["status"] == "blocked"
    assert "user_outcome_rejected" in by_id[ticket_id]["_blocked_reason"]

    # Fast-follow draft must exist, parked, owned by CLAUDE1
    ff_tickets = [t for t in queue_data["tickets"] if t["id"].startswith(f"{ticket_id}-FF-")]
    assert len(ff_tickets) == 1
    ff = ff_tickets[0]
    assert ff["status"] == "parked"
    assert ff["owner"] == "CLAUDE1"
    assert ff["_source_ticket"] == ticket_id
    assert ff["_drafted_by"] == "user-outcome-review"
    # fast-follow id must appear in the rejection message
    assert ff["id"] in msg


# Fixture 5: RN tool branches — detox/maestro/simctl/eas_preview each calls correct command
@pytest.mark.parametrize(
    ("tool", "expected_executable", "expected_cmd_fragment"),
    [
        ("detox", "npx", "detox test"),
        ("maestro", "maestro", "maestro test"),
        ("simctl", "xcrun", "simctl io booted screenshot"),
        ("eas_preview", "eas", "eas update:list"),
    ],
)
def test_rn_tool_capture_branches_invoke_correct_command(
    tmp_path, monkeypatch, tool, expected_executable, expected_cmd_fragment
):
    ticket_id = "T-OS2-UOR-05"
    ticket = _ticket(ticket_id, screenshot_tool=tool)
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    monkeypatch.delenv(USER_REVIEW_CAPTURE_CMD_ENV, raising=False)
    captured_commands: list[str] = []

    def fake_which(exe: str) -> str | None:
        return f"/usr/local/bin/{exe}" if exe == expected_executable else None

    def fake_run(cmd: str, **_kw: object) -> subprocess.CompletedProcess:
        captured_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="capture ok", stderr="")

    monkeypatch.setattr(shutil, "which", fake_which)
    monkeypatch.setattr(subprocess, "run", fake_run)

    capture_ok, capture_msg = dispatcher._run_user_review_capture(ticket)

    assert capture_ok is True, f"capture failed for tool={tool!r}: {capture_msg}"
    assert len(captured_commands) == 1
    assert expected_cmd_fragment in captured_commands[0]

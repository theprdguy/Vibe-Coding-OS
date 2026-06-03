from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from server.dispatcher import Dispatcher, VERIFY_VENV_PYTHON
from server.ssot import ValidationError, read_queue


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _dispatcher(tmp_path: Path, *, config: dict | None = None) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()
    return Dispatcher(
        config=config or {},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def test_verify_gate_runs_pytest_with_venv_python_and_project_pythonpath(
    tmp_path, monkeypatch
):
    venv_python = tmp_path / VERIFY_VENV_PYTHON
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("# fake python\n", encoding="utf-8")
    dispatcher = _dispatcher(tmp_path)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="15 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_gates(
        {
            "id": "T-PYTEST",
            "owner": "CODEX",
            "verify": "pytest tests/test_handoff_parser.py -v",
        },
        "HEAD",
    )

    assert passed is True
    assert message == "all gates passed"
    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd == f"{venv_python} -m pytest tests/test_handoff_parser.py -v"
    assert kwargs["shell"] is True
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["timeout"] == 120
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["env"]["PYTHONPATH"] == str(tmp_path)


def test_verify_gate_falls_back_to_system_python3_when_venv_missing(tmp_path, monkeypatch):
    dispatcher = _dispatcher(tmp_path)
    seen_commands = []

    def fake_run(cmd, **kwargs):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="passed", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_gates(
        {
            "id": "T-PYTEST",
            "owner": "CODEX",
            "verify": "pytest tests/test_handoff_parser.py -v",
        },
        "HEAD",
    )

    assert passed is True
    assert message == "all gates passed"
    assert seen_commands == ["python3 -m pytest tests/test_handoff_parser.py -v"]


def test_verify_gate_does_not_rewrite_non_pytest_commands_for_codex_regression(
    tmp_path, monkeypatch
):
    dispatcher = _dispatcher(tmp_path)
    seen_commands = []

    def fake_run(cmd, **kwargs):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_gates(
        {
            "id": "T-OS2-V35-REGRESSION",
            "owner": "CODEX",
            "verify": "python3 -c 'print(\"ok\")'",
        },
        "HEAD",
    )

    assert passed is True
    assert message == "all gates passed"
    assert seen_commands == ["python3 -c 'print(\"ok\")'"]


def test_pythonpath_env_is_limited_to_ticket_verify_gate(tmp_path, monkeypatch):
    dispatcher = _dispatcher(
        tmp_path,
        config={"gates": {"defaults": [{"name": "smoke", "run": "echo smoke"}]}},
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_gates(
        {
            "id": "T-ENV",
            "owner": "CODEX",
            "verify": "python3 -c 'print(\"verify\")'",
        },
        "HEAD",
    )

    assert passed is True
    assert message == "all gates passed"
    assert calls[0][0] == "echo smoke"
    # _run_command_gate injects OS3_PROJECT_ROOT so env is always present
    assert calls[0][1]["env"]["OS3_PROJECT_ROOT"] == str(tmp_path)
    # _run_ticket_verify also sets PYTHONPATH for pytest commands
    assert calls[1][0] == "python3 -c 'print(\"verify\")'"
    assert calls[1][1]["env"]["PYTHONPATH"] == str(tmp_path)


def test_resolve_gates_rejects_production_without_baseline_gates(tmp_path):
    dispatcher = _dispatcher(
        tmp_path,
        config={"gates": {"defaults": [{"name": "tests", "run": "pytest tests/ -q"}]}},
    )

    with pytest.raises(ValidationError, match="production tickets require gate\\(s\\): secrets, review"):
        dispatcher._resolve_gates(
            {
                "id": "T-PROD-GATES",
                "owner": "CODEX",
                "mode": "production",
                "work_type": "api",
                "requires_visual_review": False,
            }
        )


def test_resolve_gates_accepts_production_baseline_gates(tmp_path):
    dispatcher = _dispatcher(
        tmp_path,
        config={
            "gates": {
                "defaults": [
                    {"name": "tests", "run": "pytest tests/ -q"},
                    {"name": "scan-secrets", "run": "gitleaks git --redact ."},
                    {"name": "review", "type": "agent-review"},
                ]
            }
        },
    )

    gates = dispatcher._resolve_gates(
        {
            "id": "T-PROD-GATES",
            "owner": "CODEX",
            "mode": "production",
            "work_type": "api",
            "requires_visual_review": False,
        }
    )

    assert [gate["name"] for gate in gates] == ["tests", "scan-secrets", "review"]


def test_resolve_gates_requires_security_gate_when_security_review_required(tmp_path):
    dispatcher = _dispatcher(
        tmp_path,
        config={
            "gates": {
                "defaults": [
                    {"name": "tests", "run": "pytest tests/ -q"},
                    {"name": "secrets", "run": "gitleaks git --redact ."},
                    {"name": "review", "type": "agent-review"},
                ]
            }
        },
    )

    with pytest.raises(ValidationError, match="production tickets require gate\\(s\\): security"):
        dispatcher._resolve_gates(
            {
                "id": "T-PROD-SECURITY",
                "owner": "CODEX",
                "mode": "production",
                "work_type": "api",
                "requires_security_review": True,
                "requires_visual_review": False,
            }
        )


def test_resolve_gates_requires_screenshot_tool_for_production_visual_review(tmp_path):
    dispatcher = _dispatcher(
        tmp_path,
        config={
            "gates": {
                "defaults": [
                    {"name": "tests", "run": "pytest tests/ -q"},
                    {"name": "secrets", "run": "gitleaks git --redact ."},
                    {"name": "review", "type": "agent-review"},
                ]
            }
        },
    )

    with pytest.raises(
        ValidationError,
        match="production tickets with requires_visual_review=true require screenshot_tool",
    ):
        dispatcher._resolve_gates(
            {
                "id": "T-PROD-UI",
                "owner": "CODEX",
                "mode": "production",
                "work_type": "ui",
                "requires_visual_review": True,
            }
        )


def test_verify_gate_skips_human_dummy_ticket_fixture_placeholder(tmp_path, monkeypatch):
    dispatcher = _dispatcher(tmp_path)
    seen_commands = []

    def fake_run(cmd, **kwargs):
        seen_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_gates(
        {
            "id": "T-DUMMY-FIXTURE",
            "owner": "CODEX",
            "verify": [
                "pytest tests/test_handoff_parser.py -v",
                (
                    "make dispatch T=<dummy ticket with 'Block: none' handoff fixture> "
                    "&& make queue | grep 'T-XXX' | grep -q 'done'"
                ),
            ],
        },
        "HEAD",
    )

    assert passed is True
    assert message == "all gates passed"
    assert seen_commands == ["python3 -m pytest tests/test_handoff_parser.py -v"]


def test_done_handoff_with_verify_failure_records_blocked_reason_once(tmp_path):
    ticket_id = "T-VERIFY-FAIL"
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": ticket_id,
            "owner": "CODEX",
            "status": "doing",
            "files": [],
            "deps": [],
            "verify": f"{sys.executable} -c 'import sys; sys.exit(1)'",
        },
    )
    dispatcher = _dispatcher(tmp_path)
    dispatcher._run_subprocess = lambda ticket, cfg: (
        True,
        {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
    )

    dispatcher._run_agent(
        {
            "id": ticket_id,
            "owner": "CODEX",
            "files": [],
            "deps": [],
            "verify": f"{sys.executable} -c 'import sys; sys.exit(1)'",
        },
        "HEAD",
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == "verify_failed_but_agent_claimed_done"
    assert list(saved).count("_blocked_reason") == 1


def test_done_handoff_gate_retry_can_still_mark_done(tmp_path, monkeypatch):
    ticket_id = "T-VERIFY-RETRY"
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": ticket_id,
            "owner": "CODEX",
            "status": "doing",
            "files": [],
            "deps": [],
            "verify": "python3 -c 'print(\"ok\")'",
        },
    )
    dispatcher = _dispatcher(tmp_path)
    gate_results = iter([(False, "verify failed"), (True, "verify passed")])
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
        ),
    )
    monkeypatch.setattr(dispatcher, "_run_gates", lambda ticket, sha: next(gate_results))
    monkeypatch.setattr(dispatcher, "_attempt_retry", lambda ticket, msg, sha: True)
    monkeypatch.setattr(dispatcher, "_get_agent_log", lambda owner, tid: "")

    dispatcher._run_agent(
        {
            "id": ticket_id,
            "owner": "CODEX",
            "files": [],
            "deps": [],
            "verify": "python3 -c 'print(\"ok\")'",
        },
        "HEAD",
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved


def test_done_handoff_verify_failure_records_blocked_reason_after_retry(tmp_path, monkeypatch):
    ticket_id = "T-VERIFY-RETRY-FAIL"
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": ticket_id,
            "owner": "CODEX",
            "status": "doing",
            "files": [],
            "deps": [],
            "verify": "python3 -c 'import sys; sys.exit(1)'",
        },
    )
    dispatcher = _dispatcher(tmp_path)
    gate_results = iter([(False, "first verify failed"), (False, "retry verify failed")])
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": f"Done: {ticket_id}\nNext: waiting\nBlock: none\n"},
        ),
    )
    monkeypatch.setattr(dispatcher, "_run_gates", lambda ticket, sha: next(gate_results))
    monkeypatch.setattr(dispatcher, "_attempt_retry", lambda ticket, msg, sha: True)

    dispatcher._run_agent(
        {
            "id": ticket_id,
            "owner": "CODEX",
            "files": [],
            "deps": [],
            "verify": "python3 -c 'import sys; sys.exit(1)'",
        },
        "HEAD",
    )

    saved = read_queue(queue_path)["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == "verify_failed_but_agent_claimed_done"
    assert dispatcher._dispatch_failures[ticket_id] == (
        f"[BLOCKED] {ticket_id} verify failed but agent claimed done: retry verify failed"
    )

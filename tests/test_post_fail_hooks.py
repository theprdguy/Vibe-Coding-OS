from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.dispatcher import (
    Dispatcher,
    _compile_post_fail_hooks,
    _find_post_fail_hook,
)
from server.ssot import read_queue


NPM_ENOTFOUND = "npm ERR! request to https://registry.npmjs.org failed: ENOTFOUND registry.npmjs.org"
DEFAULT_HANDOFF_TEXT = "Done: T-HOOK\nNext: waiting\nBlock: none\n"


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str) -> dict:
    return {
        "id": ticket_id,
        "owner": "CODEX",
        "status": "doing",
        "files": [],
        "deps": [],
        "verify": "python3 -c 'print(\"ok\")'",
    }


def _dispatcher(tmp_path: Path, *, hooks: list[dict] | None = None) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()
    config = {"agents": {"CODEX": {"mode": "subprocess"}}}
    if hooks is not None:
        config["dispatch"] = {"post_fail_hooks": hooks}
    return Dispatcher(
        config=config,
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def _run_agent_with_subprocess_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ticket_id: str,
    hooks: list[dict] | None,
    subprocess_results: list[tuple[bool, dict]],
    hook_result: dict | None = None,
) -> tuple[dict, Dispatcher, dict]:
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = _ticket(ticket_id)
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path, hooks=hooks)
    calls = {"subprocess": 0, "hook": 0}

    def fake_run_subprocess(ticket: dict, agent_cfg: dict) -> tuple[bool, dict]:
        index = calls["subprocess"]
        calls["subprocess"] += 1
        return subprocess_results[index]

    def fake_run_post_fail_hook(hook: dict) -> dict:
        calls["hook"] += 1
        return hook_result or {"success": True, "reason": "ok", "stdout": "", "stderr": ""}

    monkeypatch.setattr(dispatcher, "_run_subprocess", fake_run_subprocess)
    monkeypatch.setattr(dispatcher, "_run_post_fail_hook", fake_run_post_fail_hook)
    monkeypatch.setattr(dispatcher, "_run_gates", lambda ticket, sha: (True, "all gates passed"))
    monkeypatch.setattr(dispatcher, "_get_agent_log", lambda owner, tid: "")

    dispatcher._run_agent(ticket, "HEAD")
    return read_queue(queue_path)["tickets"][0], dispatcher, calls


def test_no_post_fail_hooks_preserves_existing_blocked_behavior(tmp_path, monkeypatch):
    saved, _dispatcher_instance, calls = _run_agent_with_subprocess_results(
        tmp_path,
        monkeypatch,
        ticket_id="T-NO-HOOKS",
        hooks=None,
        subprocess_results=[
            (
                False,
                {
                    "reason": "agent exited with code 1",
                    "stdout": "",
                    "stderr": NPM_ENOTFOUND,
                    "returncode": 1,
                },
            )
        ],
    )

    assert saved["status"] == "blocked"
    assert "agent exited with code 1" in saved["_blocked_reason"]
    assert calls == {"subprocess": 1, "hook": 0}


def test_matching_npm_hook_runs_action_and_retries_once_to_done(tmp_path, monkeypatch):
    hooks = [
        {
            "pattern": r"ENOTFOUND registry\.npmjs\.org",
            "action": "cd . && npm install",
            "retry": True,
        }
    ]
    saved, _dispatcher_instance, calls = _run_agent_with_subprocess_results(
        tmp_path,
        monkeypatch,
        ticket_id="T-NPM-HOOK",
        hooks=hooks,
        subprocess_results=[
            (
                False,
                {
                    "reason": "agent exited with code 1",
                    "stdout": "",
                    "stderr": NPM_ENOTFOUND,
                    "returncode": 1,
                },
            ),
            (
                True,
                {"stdout": DEFAULT_HANDOFF_TEXT, "stderr": "", "returncode": 0},
            ),
        ],
    )

    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved
    assert calls == {"subprocess": 2, "hook": 1}


def test_hook_action_failure_reports_hook_and_original_failure_then_blocks(
    tmp_path, monkeypatch, capsys
):
    hooks = [
        {
            "pattern": r"ENOTFOUND registry\.npmjs\.org",
            "action": "cd . && npm install",
            "retry": True,
        }
    ]
    saved, _dispatcher_instance, calls = _run_agent_with_subprocess_results(
        tmp_path,
        monkeypatch,
        ticket_id="T-HOOK-FAIL",
        hooks=hooks,
        subprocess_results=[
            (
                False,
                {
                    "reason": "agent exited with code 1",
                    "stdout": "",
                    "stderr": NPM_ENOTFOUND,
                    "returncode": 1,
                },
            )
        ],
        hook_result={
            "success": False,
            "reason": "exit code 42",
            "stdout": "",
            "stderr": "npm install exploded",
            "returncode": 42,
        },
    )

    captured = capsys.readouterr()
    assert saved["status"] == "blocked"
    assert "agent exited with code 1" in saved["_blocked_reason"]
    assert "hook ENOTFOUND registry\\.npmjs\\.org failed: exit code 42" in captured.err
    assert "npm install exploded" in captured.err
    assert NPM_ENOTFOUND in captured.err
    assert calls == {"subprocess": 1, "hook": 1}


def test_retry_failure_does_not_run_hook_second_time_and_blocks(tmp_path, monkeypatch):
    hooks = [
        {
            "pattern": r"ENOTFOUND registry\.npmjs\.org",
            "action": "cd . && npm install",
            "retry": True,
        }
    ]
    saved, _dispatcher_instance, calls = _run_agent_with_subprocess_results(
        tmp_path,
        monkeypatch,
        ticket_id="T-HOOK-RETRY-FAIL",
        hooks=hooks,
        subprocess_results=[
            (
                False,
                {
                    "reason": "agent exited with code 1",
                    "stdout": "",
                    "stderr": NPM_ENOTFOUND,
                    "returncode": 1,
                },
            ),
            (
                False,
                {
                    "reason": "agent exited with code 1",
                    "stdout": "",
                    "stderr": NPM_ENOTFOUND,
                    "returncode": 1,
                },
            ),
        ],
    )

    assert saved["status"] == "blocked"
    assert "agent exited with code 1" in saved["_blocked_reason"]
    assert calls == {"subprocess": 2, "hook": 1}


def test_compile_post_fail_hooks_rejects_broken_regex():
    with pytest.raises(ValueError, match="pattern is invalid"):
        _compile_post_fail_hooks(
            [{"pattern": r"ENOTFOUND (registry", "action": "npm install", "retry": True}]
        )


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("npm ERR! ENOTFOUND registry.npmjs.org", True),
        ("prefix\nENOTFOUND registry.npmjs.org\nsuffix", True),
        ("npm ERR! ENOTFOUND registry.yarnpkg.com", False),
        ("request failed: ETIMEDOUT registry.npmjs.org", False),
    ],
)
def test_find_post_fail_hook_regex_cases(stderr, expected):
    hooks = _compile_post_fail_hooks(
        [{"pattern": r"ENOTFOUND registry\.npmjs\.org", "action": "npm install"}]
    )

    assert (_find_post_fail_hook(stderr, hooks) is not None) is expected

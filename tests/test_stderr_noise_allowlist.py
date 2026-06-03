from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from server.dispatcher import (
    KNOWN_STDERR_NOISE_PATTERNS,
    Dispatcher,
    _stderr_is_known_noise,
)
from server.ssot import read_queue


COSMETIC_NOISE = "failed to record rollout items: thread abcdef-1234 not found"
DEFAULT_HANDOFF_TEXT = "Done: T-X\nNext: waiting\nBlock: none\n"


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


def _run_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ticket_id: str,
    returncode: int,
    stderr: str,
    verify_pass: bool,
    stdout: str = "",
    handoff_text: str | None = DEFAULT_HANDOFF_TEXT,
) -> tuple[dict, Dispatcher]:
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = {
        "id": ticket_id,
        "owner": "CODEX",
        "status": "doing",
        "files": [],
        "deps": [],
        "verify": "python3 -c 'print(\"ok\")'",
    }
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)
    subprocess_stdout = stdout or (handoff_text or "")
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            returncode == 0,
            {
                "reason": f"agent exited with code {returncode}",
                "stdout": subprocess_stdout,
                "stderr": stderr,
                "returncode": returncode,
            },
        ),
    )
    monkeypatch.setattr(
        dispatcher,
        "_run_gates",
        lambda ticket, sha: (verify_pass, "all gates passed" if verify_pass else "verify failed"),
    )
    monkeypatch.setattr(dispatcher, "_get_agent_log", lambda owner, tid: "")

    dispatcher._run_agent(ticket, "HEAD")
    return read_queue(queue_path)["tickets"][0], dispatcher


def test_noise_returncode_1_verify_pass_marks_done_and_preserves_dispatch_log(
    tmp_path, monkeypatch
):
    saved, dispatcher = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-NOISE-PASS",
        returncode=1,
        stderr=COSMETIC_NOISE,
        verify_pass=True,
    )

    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved
    assert "_blocked_log" not in saved
    dispatch_logs = list((tmp_path / "logs" / "dispatch").glob("T-NOISE-PASS-*.log"))
    assert len(dispatch_logs) == 1
    log_text = dispatch_logs[0].read_text(encoding="utf-8")
    assert COSMETIC_NOISE in log_text
    assert "STDERR TAIL" in log_text
    assert dispatcher._dispatch_failures == {}


def test_deck_19_cosmetic_noise_fixture_marks_done(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-DECK-19",
        returncode=1,
        stderr="failed to record rollout items: thread abcdef-1234 not found",
        verify_pass=True,
    )

    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved


def test_noise_returncode_1_verify_fail_stays_blocked(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-NOISE-VERIFY-FAIL",
        returncode=1,
        stderr=COSMETIC_NOISE,
        verify_pass=False,
    )

    assert saved["status"] == "blocked"
    assert "known stderr noise but gates failed: verify failed" in saved["_blocked_reason"]


def test_noise_returncode_1_handoff_block_stays_blocked_before_verify_done(
    tmp_path, monkeypatch
):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-NOISE-HANDOFF-BLOCK",
        returncode=1,
        stderr=COSMETIC_NOISE,
        verify_pass=True,
        stdout=(
            "Done: T-NOISE-HANDOFF-BLOCK -- partial\n"
            "Next: waiting\n"
            "Block: context unavailable\n"
        ),
    )

    assert saved["status"] == "blocked"
    assert (
        "known stderr noise but agent handoff blocked: context unavailable"
        in saved["_blocked_reason"]
    )


def test_new_error_pattern_with_verify_pass_stays_blocked(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-NEW-ERROR",
        returncode=1,
        stderr="fatal: agent failed after writing files",
        verify_pass=True,
    )

    assert saved["status"] == "blocked"
    assert "agent exited with code 1" in saved["_blocked_reason"]


def test_clean_stderr_returncode_0_keeps_existing_done_behavior(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-CLEAN-SUCCESS",
        returncode=0,
        stderr="",
        verify_pass=True,
    )

    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved


def test_no_handoff_returncode_0_keeps_doing_per_v37_01(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-NO-HANDOFF-SUCCESS",
        returncode=0,
        stderr="",
        verify_pass=True,
        handoff_text=None,
    )

    assert saved["status"] == "doing"
    assert "_blocked_reason" not in saved


def test_clean_stderr_returncode_1_keeps_existing_blocked_behavior(tmp_path, monkeypatch):
    saved, _dispatcher_instance = _run_fixture(
        tmp_path,
        monkeypatch,
        ticket_id="T-CLEAN-FAIL",
        returncode=1,
        stderr="",
        verify_pass=True,
    )

    assert saved["status"] == "blocked"
    assert "agent exited with code 1" in saved["_blocked_reason"]


def test_known_stderr_noise_patterns_are_module_level_compiled_regex_list():
    assert isinstance(KNOWN_STDERR_NOISE_PATTERNS, list)
    assert len(KNOWN_STDERR_NOISE_PATTERNS) == 1
    assert all(isinstance(pattern, re.Pattern) for pattern in KNOWN_STDERR_NOISE_PATTERNS)


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("failed to record rollout items: thread abcdef-1234 not found", True),
        ("FAILED TO RECORD ROLLOUT ITEMS: THREAD ABCDEF-1234 NOT FOUND", True),
        ("prefix\nfailed to record rollout items: thread a-b-c-123 not found\nsuffix", True),
        ("failed to record rollout items: thread xyz-123 not found", False),
        ("failed to record rollout items: thread abcdef-1234 missing", False),
    ],
)
def test_stderr_is_known_noise_regex_cases(stderr, expected):
    assert _stderr_is_known_noise(stderr) is expected

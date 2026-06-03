from __future__ import annotations

import re
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
        config={
            "agents": {
                "CODEX": {
                    "mode": "subprocess",
                    "command": ["codex"],
                    "timeout": 17,
                }
            }
        },
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
    )


def test_codex_timeout_fallback_log_wraps_stdout_and_stderr_in_text_fences(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ticket = {"id": "T-TIMEOUT-FENCE", "owner": "CODEX", "status": "doing", "files": [], "deps": []}
    dispatcher = _dispatcher(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["codex"],
            timeout=17,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, failure = dispatcher._run_subprocess(ticket, dispatcher.agent_configs["CODEX"])

    assert ok is False
    fallback_log_path = failure["fallback_log_path"]
    assert re.fullmatch(
        r"logs/\d{4}-\d{2}-\d{2}-codex-T-TIMEOUT-FENCE-timeout\.md",
        fallback_log_path,
    )

    fallback_log = (tmp_path / fallback_log_path).read_text(encoding="utf-8")
    assert "### stdout tail (last 8192 bytes; captured 14 of 14 bytes)\n```text\npartial stdout\n```" in fallback_log
    assert "### stderr tail (last 8192 bytes; captured 14 of 14 bytes)\n```text\npartial stderr\n```" in fallback_log


def test_codex_timeout_block_metadata_uses_independent_log_patterns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ticket_id = "T-TIMEOUT-METADATA"
    queue_path = tmp_path / "QUEUE.yaml"
    ticket = {"id": ticket_id, "owner": "CODEX", "status": "doing", "files": [], "deps": []}
    _write_queue(queue_path, ticket)
    dispatcher = _dispatcher(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["codex"],
            timeout=17,
            output="stdout tail",
            stderr="stderr tail",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, failure = dispatcher._run_subprocess(ticket, dispatcher.agent_configs["CODEX"])
    assert ok is False
    assert re.fullmatch(
        rf"logs/\d{{4}}-\d{{2}}-\d{{2}}-codex-{ticket_id}-timeout\.md",
        failure["fallback_log_path"],
    )

    dispatcher._handle_dispatch_failure(ticket, "CODEX", failure)

    saved = read_queue(queue_path)["tickets"][0]
    blocked_log_pattern = rf"logs/dispatch/{ticket_id}-\d{{8}}-\d{{6}}\.log"
    assert re.fullmatch(blocked_log_pattern, saved["_blocked_log"])

    reason = saved["_transition_reason"]
    assert f"fallback log: {failure['fallback_log_path']}" in reason
    reason_log = re.search(r"; log: (logs/dispatch/T-TIMEOUT-METADATA-\d{8}-\d{6}\.log)$", reason)
    assert reason_log is not None
    assert reason_log.group(1) == saved["_blocked_log"]


def test_codex_timeout_fallback_log_does_not_overwrite_existing_log(tmp_path: Path) -> None:
    ticket_id = "T-TIMEOUT-SUFFIX"
    dispatcher = _dispatcher(tmp_path)
    date_prefix = Path(dispatcher._write_timeout_fallback_session_log(
        {"id": ticket_id},
        timeout=17,
        stdout="first stdout",
        stderr="first stderr",
    )).name.removesuffix(".md")

    second_log_path = dispatcher._write_timeout_fallback_session_log(
        {"id": ticket_id},
        timeout=17,
        stdout="second stdout",
        stderr="second stderr",
    )

    assert second_log_path == f"logs/{date_prefix}-1.md"
    assert "first stdout" in (tmp_path / "logs" / f"{date_prefix}.md").read_text(encoding="utf-8")
    assert "second stdout" in (tmp_path / second_log_path).read_text(encoding="utf-8")

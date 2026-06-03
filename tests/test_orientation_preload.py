from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from server.dispatcher import (
    ORIENTATION_END_MARKER,
    ORIENTATION_START_MARKER,
    ORIENTATION_TRUNCATED_MARKER,
    Dispatcher,
)


def _dispatcher(tmp_path: Path, *, dispatch_config: dict | None = None) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    return Dispatcher(
        config={
            "agents": {"CODEX": {"mode": "subprocess", "command": ["codex"], "timeout": 10}},
            "dispatch": dispatch_config or {},
        },
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
        host=tmp_path,  # β: orientation/doctrine resolves from host (== project root here)
    )


def _ticket(ticket_id: str = "T-ORIENTATION") -> dict:
    return {
        "id": ticket_id,
        "owner": "CODEX",
        "status": "todo",
        "goal": "exercise orientation preload",
        "files": ["server/dispatcher.py"],
        "deps": [],
    }


def test_missing_orientation_config_preserves_legacy_prompt(tmp_path: Path) -> None:
    dispatcher = _dispatcher(tmp_path)
    ticket = _ticket()

    assert dispatcher._build_prompt(ticket) == dispatcher._build_prompt(ticket, owner="CODEX")
    assert ORIENTATION_START_MARKER not in dispatcher._build_prompt(ticket)


def test_missing_orientation_file_preserves_legacy_prompt(tmp_path: Path) -> None:
    dispatcher = _dispatcher(
        tmp_path,
        dispatch_config={"orientation_files": [{"path": "devos/dispatch-header.yaml"}]},
    )
    ticket = _ticket()

    legacy = _dispatcher(tmp_path)._build_prompt(ticket)

    assert dispatcher._build_prompt(ticket) == legacy


def test_orientation_header_prepends_ticket_yaml_with_exact_byte_delta(tmp_path: Path) -> None:
    header_file = tmp_path / "devos" / "dispatch-header.yaml"
    header_file.parent.mkdir()
    header_file.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    dispatcher = _dispatcher(
        tmp_path,
        dispatch_config={
            "orientation_files": [{"path": "devos/dispatch-header.yaml", "range": "2-3"}],
            "orientation_max_bytes": 8192,
        },
    )
    legacy = _dispatcher(tmp_path)._build_prompt(_ticket())

    prompt = dispatcher._build_prompt(_ticket())
    header = dispatcher._build_orientation_header()

    assert prompt.startswith(ORIENTATION_START_MARKER)
    assert "alpha" not in prompt
    assert "beta\ngamma" in prompt
    assert len(prompt.encode("utf-8")) - len(legacy.encode("utf-8")) == len(
        header.encode("utf-8")
    )


def test_orientation_header_truncates_to_max_bytes_with_marker(tmp_path: Path) -> None:
    header_file = tmp_path / "header.txt"
    header_file.write_text("x" * 500, encoding="utf-8")
    dispatcher = _dispatcher(
        tmp_path,
        dispatch_config={
            "orientation_files": ["header.txt"],
            "orientation_max_bytes": 120,
        },
    )

    header = dispatcher._build_orientation_header()

    assert ORIENTATION_TRUNCATED_MARKER in header
    assert ORIENTATION_END_MARKER in header
    assert len(header.encode("utf-8")) <= 120


def test_run_subprocess_prints_orientation_marker_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    header_file = tmp_path / "header.txt"
    header_file.write_text("preloaded context\n", encoding="utf-8")
    dispatcher = _dispatcher(
        tmp_path,
        dispatch_config={"orientation_files": ["header.txt"], "orientation_max_bytes": 8192},
    )

    def fake_run(cmd, **kwargs):
        assert ORIENTATION_START_MARKER in kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout="Done\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    success, result = dispatcher._run_subprocess(_ticket(), {"command": ["codex"]})

    assert success is True
    assert result["returncode"] == 0
    assert "ORIENTATION (preloaded) for T-ORIENTATION" in capsys.readouterr().err


def test_verify_normalization_handles_short_dummy_dispatch_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatcher = _dispatcher(tmp_path)
    seen_commands: list[str] = []

    def fake_run(cmd, **kwargs):
        seen_commands.append(cmd)
        assert "T=<dummy>" not in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_ticket_verify(
        {"verify": "make dispatch T=<dummy> 2>&1 | grep -q 'ORIENTATION'"}
    )

    assert passed is True
    assert message == "verify passed"
    assert seen_commands == [
        "printf '%s\\n' 'ORIENTATION (preloaded) dummy dispatch fixture' | grep -q 'ORIENTATION'"
    ]

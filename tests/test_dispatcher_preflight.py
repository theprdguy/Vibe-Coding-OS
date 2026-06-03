from __future__ import annotations

from pathlib import Path

import yaml

from server.dispatcher import Dispatcher, validate_ticket
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


def test_validate_ticket_missing_file_path_returns_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = validate_ticket(
        {
            "id": "T-PREFLIGHT-MISSING-FILE",
            "files": ["server/missing.py"],
            "verify": "python3 --version",
        }
    )

    assert result["ok"] is False
    assert "server/missing.py" in "\n".join(result["reasons"])


def test_validate_ticket_allows_new_marker_for_file_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = validate_ticket(
        {
            "id": "T-PREFLIGHT-NEW-FILE",
            "files": ["NEW: tests/test_new_feature.py"],
            "verify": "python3 --version",
        }
    )

    assert result == {"ok": True, "reasons": []}


def test_validate_ticket_missing_verify_token_returns_reason(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "server" / "dispatcher.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing\n", encoding="utf-8")

    missing_token = "definitely-not-a-real-os3-tool-zzzz"
    result = validate_ticket(
        {
            "id": "T-PREFLIGHT-MISSING-VERIFY",
            "files": ["server/dispatcher.py"],
            "verify": f"{missing_token} --check",
        }
    )

    assert result["ok"] is False
    assert missing_token in "\n".join(result["reasons"])


def test_dispatch_blocks_ticket_when_preflight_validation_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    ticket_id = "T-PREFLIGHT-BLOCK"
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(
        queue_path,
        {
            "id": ticket_id,
            "owner": "CODEX",
            "status": "todo",
            "files": ["missing/path.py"],
            "verify": "python3 --version",
            "deps": [],
        },
    )
    dispatcher = _dispatcher(tmp_path)

    ok, message = dispatcher.dispatch(ticket_id)

    saved = read_queue(queue_path)["tickets"][0]
    captured = capsys.readouterr()
    assert ok is False
    assert "ticket_preflight_failed" in message
    assert saved["status"] == "blocked"
    assert "ticket_preflight_failed" in saved["_blocked_reason"]
    assert "missing/path.py" in saved["_blocked_reason"]
    assert "missing/path.py" in captured.err

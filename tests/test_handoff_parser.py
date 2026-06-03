import re
from pathlib import Path

import pytest
import yaml

from server.dispatcher import Dispatcher
from server.handoff_parser import (
    BLOCK_LINE_PATTERN,
    DONE_LINE_PATTERN,
    NEXT_LINE_PATTERN,
    Handoff,
    parse_block_line,
    parse_handoff,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Block: none", "none"),
        ("  block: none  ", "none"),
        ("Block : T-066 quota exhausted", "T-066 quota exhausted"),
        ("Block:   ", None),
        ("Block:: none", "none"),
        ("Just a comment", None),
    ],
)
def test_parse_block_line_handles_expected_forms(line, expected):
    assert parse_block_line(line) == expected


@pytest.mark.parametrize(
    "pattern",
    [BLOCK_LINE_PATTERN, DONE_LINE_PATTERN, NEXT_LINE_PATTERN],
)
def test_handoff_line_patterns_are_module_level_ignorecase_regexes(pattern):
    assert isinstance(pattern, re.Pattern)
    assert pattern.flags & re.IGNORECASE


def test_parse_handoff_returns_complete_handoff_with_none_block():
    parsed = parse_handoff(
        "## Handoff\n"
        "Done: T-001 - work\n"
        "Next: review\n"
        "Block: none"
    )

    assert parsed == Handoff(done="T-001 - work", next="review", block="none")
    assert parsed.block_is_none is True


def test_parse_handoff_returns_self_block_when_block_has_reason():
    parsed = parse_handoff(
        "## Handoff\n"
        "Done: T-066 - checked runtime\n"
        "Next: waiting\n"
        "Block: T-066 quota exhausted"
    )

    assert parsed == Handoff(
        done="T-066 - checked runtime",
        next="waiting",
        block="T-066 quota exhausted",
    )
    assert parsed.block_is_none is False


def test_parse_handoff_requires_done_and_next_lines():
    assert parse_handoff("Block: none") is None


def test_parse_handoff_uses_last_complete_handoff_block():
    parsed = parse_handoff(
        "## Handoff\n"
        "Done: T-000 - old work\n"
        "Next: old next\n"
        "Block: T-000 old block\n"
        "\n"
        "noise after first block\n"
        "\n"
        "## Handoff\n"
        "Done: T-001 - final work\n"
        "Next: final review\n"
        "Block: none"
    )

    assert parsed == Handoff(
        done="T-001 - final work",
        next="final review",
        block="none",
    )
    assert parsed.block_is_none is True


@pytest.mark.parametrize("text", ["", None])
def test_parse_handoff_returns_none_for_empty_or_none_input(text):
    assert parse_handoff(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Done: T-001 - work",
        "Done: T-001 - work\nBlock: none",
        "Done: T-001 - work\nNext: review",
        "Next: review\nBlock: none",
        "Done T-001 - work\nNext: review\nBlock: none",
    ],
)
def test_parse_handoff_returns_none_for_malformed_incomplete_blocks(text):
    assert parse_handoff(text) is None


def test_parse_handoff_accepts_case_and_spacing_variants():
    parsed = parse_handoff(
        "  done : T-123 - mixed case spacing  \n"
        "  NEXT: handoff review  \n"
        "  block : NONE  "
    )

    assert parsed == Handoff(
        done="T-123 - mixed case spacing",
        next="handoff review",
        block="NONE",
    )
    assert parsed.block_is_none is True


def test_parse_handoff_accepts_legacy_double_colon_block_typo():
    parsed = parse_handoff(
        "Done: T-124 - legacy typo\n"
        "Next: review parser\n"
        "Block:: none"
    )

    assert parsed == Handoff(
        done="T-124 - legacy typo",
        next="review parser",
        block="none",
    )


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _make_dispatcher_fixture(tmp_path: Path, ticket_id: str) -> tuple[Dispatcher, Path, Path]:
    queue_path = tmp_path / "QUEUE.yaml"
    logs_path = tmp_path / "logs"
    logs_path.mkdir()
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
    dispatcher = Dispatcher(
        config={"dispatch": {"auto_chain": True}},
        paths={"root": tmp_path, "logs": logs_path, "queue": queue_path},
    )
    return dispatcher, queue_path, logs_path


def test_run_agent_self_blocked_in_session_log_with_gates_pass_marks_blocked(
    tmp_path, monkeypatch
):
    ticket_id = "T-OS2-V36-02"
    dispatcher, queue_path, logs_path = _make_dispatcher_fixture(tmp_path, ticket_id)
    (logs_path / "2026-04-30-codex-T-OS2-V36-02.md").write_text(
        "# Session Log: CODEX - 2026-04-30\n"
        "Tickets: T-OS2-V36-02\n"
        "\n"
        "## Handoff\n"
        "Done: T-OS2-V36-02 - project MCP isolation config moved to `.mcp.json` with opt-in settings - files: .mcp.json, .claude/settings.json, .claude-b/settings.json, devos/ETHOS.md\n"
        "Next: confirm context7 health in a Claude Code session with normal npm/network access\n"
        "Block: context7 runtime health unverified in this sandbox; config scope verified\n"
        "Log: devos/logs/2026-04-30-codex-T-OS2-V36-02.md written\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {"stdout": "subprocess completed without final handoff\n"},
        ),
    )
    gate_calls = 0

    def count_gate_calls(ticket, sha):
        nonlocal gate_calls
        gate_calls += 1
        return True, "all gates passed"

    monkeypatch.setattr(dispatcher, "_run_gates", count_gate_calls)
    auto_chain_calls = []
    monkeypatch.setattr(
        dispatcher,
        "_dispatch_auto_chain_todo",
        lambda: auto_chain_calls.append(ticket_id) or [],
    )

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

    saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == (
        "agent_self_blocked: context7 runtime health unverified in this sandbox; "
        "config scope verified"
    )
    assert gate_calls == 0
    assert auto_chain_calls == []
    dispatch_logs = list((logs_path / "dispatch").glob(f"{ticket_id}-*.log"))
    assert len(dispatch_logs) == 1
    dispatch_log = dispatch_logs[0].read_text(encoding="utf-8")
    assert "reason: agent_self_blocked: context7 runtime health unverified" in dispatch_log


def test_run_agent_block_none_in_stdout_runs_gates_and_marks_done(tmp_path, monkeypatch):
    ticket_id = "T-OS2-V37-05"
    dispatcher, queue_path, _logs_path = _make_dispatcher_fixture(tmp_path, ticket_id)
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda ticket, cfg: (
            True,
            {
                "stdout": (
                    "Done: T-OS2-V37-05 - completed\n"
                    "Next: waiting\n"
                    "Block: none\n"
                )
            },
        ),
    )
    gate_calls = 0

    def count_gate_calls(ticket, sha):
        nonlocal gate_calls
        gate_calls += 1
        return True, "all gates passed"

    monkeypatch.setattr(dispatcher, "_run_gates", count_gate_calls)
    auto_chain_calls = []
    monkeypatch.setattr(
        dispatcher,
        "_dispatch_auto_chain_todo",
        lambda: auto_chain_calls.append(ticket_id) or [],
    )

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

    saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
    assert saved["status"] == "done"
    assert "_blocked_reason" not in saved
    assert gate_calls == 1
    assert auto_chain_calls == [ticket_id]

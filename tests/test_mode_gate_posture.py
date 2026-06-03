from __future__ import annotations

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


def _dispatcher(
    tmp_path: Path,
    messages: list[str],
    config: dict | None = None,
) -> Dispatcher:
    logs = tmp_path / "logs"
    logs.mkdir()

    async def notify(message: str) -> None:
        messages.append(message)

    return Dispatcher(
        config=config or {},
        paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
        notify_callback=notify,
    )


def _session_log(dispatcher: Dispatcher, ticket_id: str, owner: str = "codex") -> Path:
    path = dispatcher.paths["logs"] / f"2026-05-29-{owner}-{ticket_id}.md"
    path.write_text(
        f"# Session Log: {owner.upper()}\n"
        f"Tickets: {ticket_id}\n"
        "\n"
        "## Handoff\n"
        f"Done: {ticket_id} - implementation complete - files: docs/example.md\n"
        "Next: waiting\n"
        "Block: none\n"
        f"Log: devos/logs/{path.name} written\n",
        encoding="utf-8",
    )
    return path


def _handoff_stdout(ticket_id: str) -> str:
    return (
        f"Done: {ticket_id} - implementation complete\n"
        "Next: waiting\n"
        "Block: none\n"
    )


def _run_agent_success(
    dispatcher: Dispatcher,
    monkeypatch: pytest.MonkeyPatch,
    ticket: dict,
) -> None:
    monkeypatch.setattr(
        dispatcher,
        "_run_subprocess",
        lambda runtime_ticket, agent_cfg: (
            True,
            {"stdout": _handoff_stdout(str(runtime_ticket["id"]))},
        ),
    )
    monkeypatch.setattr(
        dispatcher,
        "_run_user_outcome_review",
        lambda runtime_ticket, allow_prompt: (True, "not configured"),
    )
    monkeypatch.setattr(dispatcher, "_dispatch_auto_chain_todo", lambda: [])

    dispatcher._run_agent(ticket, "HEAD")


def _exploration_ticket(ticket_id: str, *, gates: list[dict], files: list[str] | None = None) -> dict:
    return {
        "id": ticket_id,
        "owner": "CODEX",
        "impl_owner": "CODEX",
        "status": "doing",
        "mode": "exploration",
        "files": files if files is not None else ["docs/example.md"],
        "deps": [],
        "gates": gates,
    }


def _production_ticket(ticket_id: str, *, gates: list[dict]) -> dict:
    return {
        "id": ticket_id,
        "owner": "CODEX",
        "impl_owner": "CODEX",
        "status": "doing",
        "mode": "production",
        "user_outcome": "Production behavior remains guarded.",
        "risk_level": "medium",
        "work_type": "api",
        "policy_class": "soft",
        "files": ["server/example.py"],
        "deps": [],
        "dod": ["Failing tests block production tickets."],
        "gates": gates,
    }


@pytest.mark.parametrize(
    "run",
    [
        "pytest -q",
        "make test:unit",
        "npm run test -- --runInBand",
    ],
)
def test_exploration_verify_gate_keeps_anchored_test_commands_report_only(
    tmp_path: Path,
    run: str,
) -> None:
    dispatcher = _dispatcher(tmp_path, [])

    blocking = dispatcher._gate_is_blocking(
        {"mode": "exploration"},
        "verify",
        {"name": "verify", "run": run},
        "verify command failed",
    )

    assert blocking is False


def test_exploration_verify_gate_does_not_soft_report_test_prefix_argument(
    tmp_path: Path,
) -> None:
    dispatcher = _dispatcher(tmp_path, [])

    blocking = dispatcher._gate_is_blocking(
        {"mode": "exploration"},
        "verify",
        {"name": "verify", "run": "python3 -m testdata_audit --strict"},
        "verify command failed",
    )

    assert blocking is True


@pytest.mark.parametrize("mode", [None, "exploration", "productization", "production"])
def test_verify_gate_secret_scan_signal_blocks_in_any_mode(
    tmp_path: Path,
    mode: str | None,
) -> None:
    dispatcher = _dispatcher(tmp_path, [])
    ticket = {} if mode is None else {"mode": mode}

    blocking = dispatcher._gate_is_blocking(
        ticket,
        "verify",
        {"name": "verify", "run": "pytest -q"},
        "FAIL scan-secrets: leaks found",
    )

    assert blocking is True


def test_exploration_failed_non_secret_gate_reports_and_reaches_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _exploration_ticket(
        "T-EXP-REPORTS",
        gates=[{"name": "tests", "run": "python3 -c 'raise SystemExit(7)'"}],
    )
    _write_queue(dispatcher.paths["queue"], ticket)
    log_path = _session_log(dispatcher, ticket["id"])

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "done"
    assert "[REPORTED] tests:" in saved["_transition_reason"]
    assert messages, "dispatcher should notify the completed result"
    assert messages[-1].startswith("[DONE] T-EXP-REPORTS")
    assert "[REPORTED] tests:" in messages[-1]
    assert "[BLOCKED]" not in messages[-1]
    assert "[REPORTED] tests:" in log_path.read_text(encoding="utf-8")


def test_exploration_failed_secrets_gate_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _exploration_ticket(
        "T-EXP-SECRETS-BLOCK",
        gates=[{"name": "secrets", "run": "python3 -c 'raise SystemExit(9)'"}],
    )
    _write_queue(dispatcher.paths["queue"], ticket)

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert saved["_blocked_reason"] == "verify_failed_but_agent_claimed_done"
    assert messages[-1].startswith("[BLOCKED] T-EXP-SECRETS-BLOCK gates failed: secrets:")
    assert "[REPORTED]" not in messages[-1]


def test_exploration_pr_check_secret_scan_bundle_blocks_and_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(
        tmp_path,
        messages,
        config={
            "gates": {
                "defaults": [
                    {
                        "name": "pr-check",
                        "run": (
                            "python3 -c \"import sys; print('FAIL scan-secrets'); "
                            "print('leaks found: 1', file=sys.stderr); raise SystemExit(1)\""
                        ),
                    }
                ]
            }
        },
    )
    ticket = _exploration_ticket("T-EXP-PRCHECK-BLOCKS", gates=["pr-check"])
    _write_queue(dispatcher.paths["queue"], ticket)

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert messages[-1].startswith("[BLOCKED] T-EXP-PRCHECK-BLOCKS gates failed: pr-check:")
    assert "FAIL scan-secrets" in messages[-1]
    assert "leaks found: 1" in messages[-1]
    assert "[REPORTED]" not in messages[-1]


def test_exploration_unknown_gate_failure_blocks_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _exploration_ticket(
        "T-EXP-UNKNOWN-BLOCKS",
        gates=[{"name": "unknown-future-gate", "run": "python3 -c 'raise SystemExit(3)'"}],
    )
    _write_queue(dispatcher.paths["queue"], ticket)

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert messages[-1].startswith(
        "[BLOCKED] T-EXP-UNKNOWN-BLOCKS gates failed: unknown-future-gate:"
    )
    assert "[REPORTED]" not in messages[-1]


def test_production_failed_tests_gate_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _production_ticket(
        "T-PROD-TESTS-BLOCK",
        gates=[
            {"name": "tests", "run": "python3 -c 'raise SystemExit(5)'"},
            {"name": "secrets", "run": "python3 -c 'print(\"clean\")'"},
            {"name": "review", "type": "agent-review"},
        ],
    )
    _write_queue(dispatcher.paths["queue"], ticket)

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert messages[-1].startswith("[BLOCKED] T-PROD-TESTS-BLOCK gates failed: tests:")
    assert "[REPORTED]" not in messages[-1]


def test_production_agent_review_reject_blocks_without_warning_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _production_ticket(
        "T-PROD-REVIEW-BLOCKS",
        gates=[
            {"name": "tests", "run": "python3 -c 'print(\"tests pass\")'"},
            {"name": "secrets", "run": "python3 -c 'print(\"secrets pass\")'"},
            {"name": "review", "type": "agent-review"},
        ],
    )
    _write_queue(dispatcher.paths["queue"], ticket)
    monkeypatch.setattr(
        dispatcher,
        "_run_agent_review",
        lambda runtime_ticket, sha: (False, "FAIL: production reviewer rejected the change"),
    )

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert "_review_verdict" not in saved
    assert messages[-1].startswith("[BLOCKED] T-PROD-REVIEW-BLOCKS gates failed: review:")
    assert "FAIL: production reviewer rejected the change" in messages[-1]
    assert "[REPORTED]" not in messages[-1]


def test_legacy_ticket_without_mode_failed_gate_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = {
        "id": "T-LEGACY-BLOCK",
        "owner": "CODEX",
        "impl_owner": "CODEX",
        "status": "doing",
        "files": ["docs/legacy.md"],
        "deps": [],
        "gates": [{"name": "tests", "run": "python3 -c 'raise SystemExit(4)'"}],
    }
    _write_queue(dispatcher.paths["queue"], ticket)

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "blocked"
    assert messages[-1].startswith("[BLOCKED] T-LEGACY-BLOCK gates failed: tests:")
    assert "[REPORTED]" not in messages[-1]


def test_exploration_agent_review_reject_records_warning_verdict_and_reaches_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = _exploration_ticket(
        "T-EXP-REVIEW-REJECT",
        files=["server/reviewed.py"],
        gates=[{"name": "review", "type": "agent-review"}],
    )
    _write_queue(dispatcher.paths["queue"], ticket)
    _session_log(dispatcher, ticket["id"])
    monkeypatch.setattr(
        dispatcher,
        "_run_agent_review",
        lambda runtime_ticket, sha: (False, "FAIL: reviewer rejected the change"),
    )

    _run_agent_success(dispatcher, monkeypatch, ticket)

    saved = read_queue(dispatcher.paths["queue"])["tickets"][0]
    assert saved["status"] == "done"
    assert saved["_review_verdict"]["by"] == "agent-review"
    assert saved["_review_verdict"]["verdict"] == "WARNING"
    assert "FAIL: reviewer rejected the change" in saved["_review_verdict"]["note"]
    assert "[REPORTED] review:" in saved["_transition_reason"]
    assert messages[-1].startswith("[DONE] T-EXP-REVIEW-REJECT")
    assert "[BLOCKED]" not in messages[-1]


def test_agent_review_mixed_positive_and_concern_is_not_auto_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    dispatcher = _dispatcher(tmp_path, messages)
    ticket = {
        "id": "T-REVIEW-MIXED",
        "owner": "CODEX",
        "files": ["server/dispatcher.py"],
        "dod": ["Production review rejection must block."],
    }

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return subprocess.CompletedProcess(cmd, 0, stdout="diff --git a/x b/x\n", stderr="")
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "The implementation logic appears sound.\n"
                "However, I still have a concern about the production review rejection path."
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_agent_review(ticket, "HEAD")

    assert passed is False
    assert message.startswith("no verdict in response:")

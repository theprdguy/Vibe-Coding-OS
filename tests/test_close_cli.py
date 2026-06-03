"""T-OS3-CLOSE-CLI-ERGONOMICS — tests for `os3 close` subcommand.

DOD coverage:
1. os3 close <id> --verdict OK --by ... --confidence 0.9 records verdict
   + doing→code_ready→done transition + rc 0.
2. verdict argument missing → rejected (rc != 0).
3. already-done ticket → rejected (rc != 0).
4. python3 -m pytest tests/test_close_cli.py -v pass.

Error cases:
- #2: --verdict omitted
- #3: ticket already done
- extra: invalid verdict value (not OK|WARNING)
- extra: ticket not found
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.cli import main as cli_main
from server.ssot import read_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _builder_ticket(tid: str, status: str = "doing") -> dict:
    """Minimal BUILDER ticket in the given status with required transition metadata."""
    return {
        "id": tid,
        "owner": "BUILDER",
        "impl_owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": ["server/cli.py"],
    }


def _run_close(
    tmp_path: Path,
    ticket_id: str,
    *,
    verdict: str | None = "OK",
    by: str = "test-reviewer",
    confidence: str = "0.9",
    reason: str = "close test",
) -> int:
    """Run `os3 close <id> ...` via cli.main and return exit code.

    --project must come after the subcommand (it's registered on the subparser,
    not the main parser).

    argparse calls sys.exit(2) on missing required args; we catch SystemExit and
    return its code so the test can assert rc != 0.
    """
    args = ["close", ticket_id, "--project", str(tmp_path)]
    if verdict is not None:
        args += ["--verdict", verdict]
    args += ["--by", by, "--confidence", confidence, "--reason", reason]
    try:
        return cli_main(args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1


# ---------------------------------------------------------------------------
# DOD 1 — verdict OK + doing→code_ready→done transition + rc 0
# ---------------------------------------------------------------------------


class TestCloseSuccess:
    """os3 close with valid verdict transitions ticket all the way to done."""

    def test_close_doing_ticket_ok_verdict(self, tmp_path: Path) -> None:
        """DOD 1a: ticket in 'doing' → close with OK → done, rc 0."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-DOING", status="doing"))

        rc = _run_close(tmp_path, "T-CLOSE-DOING", verdict="OK")

        assert rc == 0, f"Expected rc=0 but got rc={rc}"
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done", (
            f"Expected status=done but got {saved['status']!r}"
        )

    def test_close_records_review_verdict(self, tmp_path: Path) -> None:
        """DOD 1b: _review_verdict is recorded with correct fields."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-VERDICT", status="doing"))

        rc = _run_close(
            tmp_path,
            "T-CLOSE-VERDICT",
            verdict="OK",
            by="test-reviewer",
            confidence="0.9",
        )

        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        verdict_record = saved.get("_review_verdict")
        assert verdict_record is not None, "_review_verdict not recorded"
        assert verdict_record["verdict"] == "OK"
        assert verdict_record["by"] == "test-reviewer"
        assert abs(verdict_record["confidence"] - 0.9) < 1e-6

    def test_close_warning_verdict_succeeds(self, tmp_path: Path) -> None:
        """WARNING verdict is valid and also transitions to done."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-WARN", status="doing"))

        rc = _run_close(tmp_path, "T-CLOSE-WARN", verdict="WARNING")

        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        assert saved["_review_verdict"]["verdict"] == "WARNING"

    def test_close_code_ready_ticket(self, tmp_path: Path) -> None:
        """ticket in code_ready (already past doing) → close → done."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-CR", status="code_ready"))

        rc = _run_close(tmp_path, "T-CLOSE-CR", verdict="OK")

        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_close_transition_history_includes_done(self, tmp_path: Path) -> None:
        """done appears in _transition_history after close."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-HIST", status="doing"))

        rc = _run_close(tmp_path, "T-CLOSE-HIST", verdict="OK")

        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        statuses = [e["status"] for e in history]
        assert "code_ready" in statuses, f"intermediate code_ready missing: {statuses}"
        assert "done" in statuses, f"done not in history: {statuses}"


# ---------------------------------------------------------------------------
# DOD 2 — verdict argument missing → rc != 0
# ---------------------------------------------------------------------------


class TestCloseMissingVerdict:
    """--verdict is required; omitting it must return nonzero exit code."""

    def test_missing_verdict_rejected(self, tmp_path: Path) -> None:
        """DOD 2: no --verdict → rc != 0."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-NO-VERDICT", status="doing"))

        rc = _run_close(tmp_path, "T-CLOSE-NO-VERDICT", verdict=None)

        assert rc != 0, "Expected nonzero rc when --verdict is missing"

    def test_invalid_verdict_value_rejected(self, tmp_path: Path) -> None:
        """verdict='SKIP' (not OK/WARNING) → rc != 0."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-BAD-VERDICT", status="doing"))

        rc = _run_close(tmp_path, "T-CLOSE-BAD-VERDICT", verdict="SKIP")

        assert rc != 0, "Expected nonzero rc for invalid verdict value"

    def test_missing_by_rejected(self, tmp_path: Path) -> None:
        """--by is required; calling with empty string must return nonzero."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLOSE-NO-BY", status="doing"))

        args = [
            "close", "T-CLOSE-NO-BY",
            "--project", str(tmp_path),
            "--verdict", "OK",
            "--by", "",  # empty string → ssot.ValidationError "by is required"
            "--confidence", "0.9",
            "--reason", "test",
        ]
        try:
            rc = cli_main(args)
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 1

        assert rc != 0, "Expected nonzero rc when --by is empty"


# ---------------------------------------------------------------------------
# DOD 3 — already-done ticket → rc != 0
# ---------------------------------------------------------------------------


class TestCloseAlreadyDone:
    """close on an already-done ticket must return nonzero exit code."""

    def test_done_ticket_rejected(self, tmp_path: Path) -> None:
        """DOD 3: ticket status=done → close → rc != 0."""
        ticket = _builder_ticket("T-CLOSE-ALREADY-DONE", status="done")
        # done is terminal — needs _review_verdict + transition metadata for read_queue to accept
        ticket["_review_verdict"] = {
            "by": "prior-reviewer",
            "verdict": "OK",
            "confidence": 1.0,
            "ts": "2026-01-01T00:00:00Z",
        }
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        rc = _run_close(tmp_path, "T-CLOSE-ALREADY-DONE", verdict="OK")

        assert rc != 0, "Expected nonzero rc when ticket is already done"

    def test_done_ticket_not_modified(self, tmp_path: Path) -> None:
        """close on done ticket must not mutate the ticket."""
        ticket = _builder_ticket("T-CLOSE-DONE-NOMUT", status="done")
        ticket["_review_verdict"] = {
            "by": "prior-reviewer",
            "verdict": "OK",
            "confidence": 1.0,
            "ts": "2026-01-01T00:00:00Z",
        }
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        # Load original state
        original = read_queue(queue_path)["tickets"][0]

        _run_close(tmp_path, "T-CLOSE-DONE-NOMUT", verdict="OK")

        after = read_queue(queue_path)["tickets"][0]
        assert after["status"] == "done"
        assert after.get("_review_verdict", {}).get("by") == "prior-reviewer", (
            "close mutated the review verdict on an already-done ticket"
        )


# ---------------------------------------------------------------------------
# Additional error cases: ticket not found
# ---------------------------------------------------------------------------


class TestCloseTicketNotFound:
    """close on non-existent ticket id must return nonzero exit code."""

    def test_unknown_ticket_id_rejected(self, tmp_path: Path) -> None:
        """Ticket not in queue → rc != 0."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-OTHER", status="doing"))

        rc = _run_close(tmp_path, "T-NOT-EXIST", verdict="OK")

        assert rc != 0, "Expected nonzero rc for unknown ticket id"

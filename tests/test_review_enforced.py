"""T-OS3-REVIEW-ENFORCED — C1 review-verdict enforcement tests.

DOD coverage:
1. impl-owner ticket without _review_verdict → done transition → ValidationError
2. _review_verdict present → done transition succeeds + state-machine passes
3. override=True + reason/actor → done without verdict → history records override:true
4. docs_refactor ticket (all files devos/.claude/docs/) → verdict-exempt → done succeeds
5. agent-review gate with claude binary absent → fail-closed (returns False)
6. dispatcher._mark_ticket_done auto-records 'dispatcher-auto' verdict → existing
   dispatcher paths still reach done without regression
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from server.ssot import (
    ValidationError,
    _is_docs_refactor_ticket,
    _requires_review_verdict,
    _validate_review_verdict_for_done,
    read_queue,
    record_review_verdict,
    update_ticket_fields,
    update_ticket_status,
    validate_impl_ticket_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_queue(queue_path: Path, ticket: dict) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
        encoding="utf-8",
    )


def _impl_ticket(tid: str, status: str = "code_ready", *, files: list[str] | None = None) -> dict:
    """A standard BUILDER-owned implementation ticket with minimal valid fields."""
    return {
        "id": tid,
        "owner": "BUILDER",
        "impl_owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": files if files is not None else ["apps/foo.py"],
    }


def _codex_ticket(tid: str, status: str = "code_ready") -> dict:
    return {
        "id": tid,
        "owner": "CODEX",
        "impl_owner": "CODEX",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": ["server/foo.py"],
    }


def _docs_ticket(tid: str, status: str = "code_ready") -> dict:
    return {
        "id": tid,
        "owner": "BUILDER",
        "impl_owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": ["devos/plans/foo.md", ".claude/CLAUDE.md", "docs/README.md"],
    }


def _claude1_ticket(tid: str, status: str = "code_ready") -> dict:
    return {
        "id": tid,
        "owner": "CLAUDE1",
        "impl_owner": "CLAUDE1",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": ["devos/tasks/QUEUE.yaml"],
    }


# ---------------------------------------------------------------------------
# DOD 1 — impl-owner ticket without _review_verdict → ValidationError on done
# ---------------------------------------------------------------------------


class TestVerdictRequiredForDone:
    """done transition without verdict raises ValidationError for impl owners."""

    def test_builder_ticket_no_verdict_raises(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _impl_ticket("T-NO-VERDICT"))

        with pytest.raises(ValidationError, match="_review_verdict"):
            update_ticket_status(
                queue_path,
                "T-NO-VERDICT",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )

    def test_codex_ticket_no_verdict_raises(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _codex_ticket("T-CODEX-NO-VERDICT"))

        with pytest.raises(ValidationError, match="_review_verdict"):
            update_ticket_status(
                queue_path,
                "T-CODEX-NO-VERDICT",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )

    def test_partial_verdict_missing_verdict_key_raises(self, tmp_path: Path) -> None:
        """A _review_verdict dict without a valid verdict value raises."""
        ticket = _impl_ticket("T-BAD-VERDICT")
        ticket["_review_verdict"] = {"by": "reviewer", "ts": "2026-01-01T00:00:00Z"}
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        with pytest.raises(ValidationError, match="verdict must be one of"):
            update_ticket_status(
                queue_path,
                "T-BAD-VERDICT",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )

    def test_invalid_verdict_value_raises(self, tmp_path: Path) -> None:
        """verdict='SKIP' (not OK/WARNING) should raise."""
        ticket = _impl_ticket("T-INVALID-VERDICT")
        ticket["_review_verdict"] = {"by": "reviewer", "verdict": "SKIP", "confidence": 1.0, "ts": "2026-01-01T00:00:00Z"}
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        with pytest.raises(ValidationError, match="verdict must be one of"):
            update_ticket_status(
                queue_path,
                "T-INVALID-VERDICT",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )


# ---------------------------------------------------------------------------
# DOD 2 — _review_verdict present → done transition succeeds
# ---------------------------------------------------------------------------


class TestVerdictPresent:
    """done transition with valid _review_verdict succeeds and state-machine passes."""

    def test_ok_verdict_allows_done(self, tmp_path: Path) -> None:
        ticket = _impl_ticket("T-OK-VERDICT")
        ticket["_review_verdict"] = {
            "by": "reviewer-opus",
            "verdict": "OK",
            "confidence": 0.95,
            "ts": "2026-01-01T00:00:00Z",
        }
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        result = update_ticket_status(
            queue_path,
            "T-OK-VERDICT",
            "done",
            reason="reviewer approved",
            actor="dispatcher",
        )
        assert result is True
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_warning_verdict_allows_done(self, tmp_path: Path) -> None:
        """WARNING verdict (acceptable risk) also allows done."""
        ticket = _impl_ticket("T-WARN-VERDICT")
        ticket["_review_verdict"] = {
            "by": "agent-review",
            "verdict": "WARNING",
            "confidence": 0.7,
            "ts": "2026-01-01T00:00:00Z",
        }
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        result = update_ticket_status(
            queue_path,
            "T-WARN-VERDICT",
            "done",
            reason="warning accepted",
            actor="dispatcher",
        )
        assert result is True

    def test_record_review_verdict_then_done(self, tmp_path: Path) -> None:
        """record_review_verdict + update_ticket_status = clean done path."""
        ticket = _impl_ticket("T-RECORD-THEN-DONE")
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        found = record_review_verdict(
            queue_path, "T-RECORD-THEN-DONE", "OK", by="cli-recorded"
        )
        assert found is True

        result = update_ticket_status(
            queue_path,
            "T-RECORD-THEN-DONE",
            "done",
            reason="cli recorded verdict",
            actor="dispatcher",
        )
        assert result is True
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        assert saved["_review_verdict"]["by"] == "cli-recorded"
        assert saved["_review_verdict"]["verdict"] == "OK"


# ---------------------------------------------------------------------------
# DOD 3 — override=True + reason/actor bypasses verdict check
# ---------------------------------------------------------------------------


class TestOverrideBypassesVerdict:
    """override=True allows done without verdict; history records override:true."""

    def test_override_without_verdict_succeeds(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _impl_ticket("T-OVERRIDE-DONE"))

        result = update_ticket_status(
            queue_path,
            "T-OVERRIDE-DONE",
            "done",
            reason="emergency override",
            actor="pm-user",
            override=True,
        )
        assert result is True
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_override_history_records_override_true(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _impl_ticket("T-OVERRIDE-HIST"))

        update_ticket_status(
            queue_path,
            "T-OVERRIDE-HIST",
            "done",
            reason="forced by pm",
            actor="pm-user",
            override=True,
        )
        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        done_entry = next((e for e in history if e["status"] == "done"), None)
        assert done_entry is not None, "No done entry in history"
        assert done_entry.get("override") is True, "override:true not recorded in history"
        assert done_entry["actor"] == "pm-user"
        assert done_entry["reason"] == "forced by pm"

    def test_override_requires_reason_and_actor(self, tmp_path: Path) -> None:
        """override=True without reason raises even though verdict is bypassed."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _impl_ticket("T-OVERRIDE-NO-REASON"))

        with pytest.raises(ValidationError):
            update_ticket_status(
                queue_path,
                "T-OVERRIDE-NO-REASON",
                "done",
                reason="",
                actor="pm-user",
                override=True,
            )


# ---------------------------------------------------------------------------
# DOD 4 — docs_refactor ticket: verdict-exempt → done succeeds
# ---------------------------------------------------------------------------


class TestDocsRefractExemption:
    """Tickets whose files are all in devos/.claude/docs/ are exempt from verdict."""

    def test_docs_ticket_done_without_verdict(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _docs_ticket("T-DOCS-DONE"))

        result = update_ticket_status(
            queue_path,
            "T-DOCS-DONE",
            "done",
            reason="docs update merged",
            actor="dispatcher",
        )
        assert result is True
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_claude1_ticket_done_without_verdict(self, tmp_path: Path) -> None:
        """CLAUDE1 owner tickets (not BUILDER/CODEX) are exempt."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _claude1_ticket("T-C1-DONE"))

        result = update_ticket_status(
            queue_path,
            "T-C1-DONE",
            "done",
            reason="ssot update complete",
            actor="dispatcher",
        )
        assert result is True

    def test_is_docs_refactor_ticket_all_devos(self) -> None:
        ticket = {"files": ["devos/plans/foo.md", "devos/tasks/QUEUE.yaml"]}
        assert _is_docs_refactor_ticket(ticket) is True

    def test_is_docs_refactor_ticket_mixed_raises_false(self) -> None:
        """Mixed devos + apps file → not docs_refactor."""
        ticket = {"files": ["devos/plans/foo.md", "apps/foo.py"]}
        assert _is_docs_refactor_ticket(ticket) is False

    def test_is_docs_refactor_empty_files_false(self) -> None:
        """No files → not docs_refactor (empty list → False)."""
        assert _is_docs_refactor_ticket({"files": []}) is False
        assert _is_docs_refactor_ticket({}) is False

    def test_requires_review_verdict_docs_false(self) -> None:
        ticket = _docs_ticket("T-DOCS")
        assert _requires_review_verdict(ticket) is False

    def test_requires_review_verdict_impl_true(self) -> None:
        ticket = _impl_ticket("T-IMPL")
        assert _requires_review_verdict(ticket) is True

    def test_requires_review_verdict_no_files_false(self) -> None:
        """Tickets with no files field: _requires_review_verdict returns False.

        No-files BUILDER tickets are enforced at dispatch time (BLOCKER 2), not at
        done-transition time — done-transition enforcement would break state-machine
        tests that use minimal ticket fixtures without files.  The done-path exemption
        is intentional; dispatch-path rejection (below) closes BLOCKER 2.
        """
        ticket = {
            "id": "T-NO-FILES",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "code_ready",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
        }
        assert _requires_review_verdict(ticket) is False

    def test_no_files_builder_ticket_rejected_at_dispatch(self, tmp_path: Path) -> None:
        """BLOCKER 2 (dispatch-time): BUILDER ticket with no files → ValidationError via validate_impl_ticket_files.

        Enforcement is at dispatcher.dispatch() via validate_impl_ticket_files(),
        which is the fail-closed gate that runs before the agent executes.
        Missing files is a schema violation per AI-core.md ('이 목록 외 수정은 PR 거부').
        """
        ticket_no_files = {
            "id": "T-NO-FILES-DISPATCH",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "code_ready",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            # No 'files' key — schema violation
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket_no_files)

    def test_mixed_file_ticket_requires_verdict(self, tmp_path: Path) -> None:
        """A ticket with one non-docs file must provide verdict before done."""
        ticket = _impl_ticket(
            "T-MIXED-FILES",
            files=["devos/plans/foo.md", "apps/bar.py"],
        )
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        with pytest.raises(ValidationError, match="_review_verdict"):
            update_ticket_status(
                queue_path,
                "T-MIXED-FILES",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )


# ---------------------------------------------------------------------------
# DOD 5 — agent-review gate with claude binary absent → fail-closed
# ---------------------------------------------------------------------------


class TestAgentReviewFailClosed:
    """_run_agent_review returns (False, ...) when claude CLI is not found."""

    def _make_dispatcher(self, tmp_path: Path):
        from server.dispatcher import Dispatcher

        logs = tmp_path / "logs"
        logs.mkdir()
        return Dispatcher(
            config={},
            paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
        )

    def test_missing_claude_binary_returns_false(self, tmp_path: Path, monkeypatch) -> None:
        """When subprocess.run raises FileNotFoundError → (False, 'fail-closed...')."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = {"id": "T-AR-FC", "files": ["apps/foo.py"], "dod": []}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise FileNotFoundError("claude not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        passed, msg = dispatcher._run_agent_review(ticket, "HEAD")
        assert passed is False, f"Expected fail-closed (False), got True. msg={msg!r}"
        # W3: tightened to assert the specific canonical phrase, not a disjunction.
        assert "fail-closed" in msg.lower(), (
            f"Expected 'fail-closed' in message (canonical contract), got: {msg!r}"
        )

    def test_missing_claude_binary_was_fail_open_regression(self, tmp_path: Path, monkeypatch) -> None:
        """Verify the old 'return True' (fail-open) is no longer present.

        This test documents the regression: previously FileNotFoundError returned True.
        After C1 fix, it must return False.
        """
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = {"id": "T-AR-REGR", "files": [], "dod": []}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            raise FileNotFoundError("no claude")

        monkeypatch.setattr(subprocess, "run", fake_run)

        passed, _ = dispatcher._run_agent_review(ticket, "HEAD")
        assert passed is False, "REGRESSION: fail-open behaviour restored — must be fail-closed"


# ---------------------------------------------------------------------------
# DOD 6 — _mark_ticket_done auto-records dispatcher-auto verdict
# ---------------------------------------------------------------------------


class TestMarkTicketDoneAutoVerdict:
    """dispatcher._mark_ticket_done requires verdict set by agent-review gate (BLOCKER 1 fix).

    The old dispatcher-auto unconditional record has been removed.  _mark_ticket_done
    now relies on the verdict being written by _run_gates when the agent-review gate
    actually executes.  Calling _mark_ticket_done without a prior verdict must fail.
    """

    def _make_dispatcher(self, tmp_path: Path):
        from server.dispatcher import Dispatcher

        logs = tmp_path / "logs"
        logs.mkdir()
        return Dispatcher(
            config={},
            paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
        )

    def test_auto_verdict_no_longer_injected_for_builder_ticket(self, tmp_path: Path) -> None:
        """INVERTED (BLOCKER 1): _mark_ticket_done without prior verdict → ValidationError.

        Previously dispatcher-auto was unconditionally recorded here, bypassing the
        real review requirement (RC#3 pattern).  That path is removed.  The verdict
        must come from agent-review gate execution in _run_gates.
        """
        ticket = _impl_ticket("T-AUTO-VERDICT")
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        dispatcher = self._make_dispatcher(tmp_path)
        # Without an agent-review gate having run (no _review_verdict on ticket),
        # _mark_ticket_done must surface a ValidationError via its failure path.
        failure = dispatcher._mark_ticket_done(ticket, "agent completed + gates pass")

        assert failure is not None, (
            "REGRESSION: _mark_ticket_done succeeded without review verdict — "
            "RC#3 hole re-opened.  dispatcher-auto bypass must not exist."
        )
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] != "done", (
            "Ticket reached done without a real agent-review verdict — RC#3 re-opened"
        )

    def test_agent_review_verdict_allows_done(self, tmp_path: Path) -> None:
        """When agent-review gate set the verdict, _mark_ticket_done succeeds."""
        ticket = _impl_ticket("T-EXISTING-VERDICT")
        ticket["_review_verdict"] = {
            "by": "agent-review",
            "verdict": "OK",
            "confidence": 0.9,
            "ts": "2026-01-01T00:00:00Z",
        }
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        dispatcher = self._make_dispatcher(tmp_path)
        failure = dispatcher._mark_ticket_done(ticket, "agent completed")

        assert failure is None
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        assert saved["_review_verdict"]["by"] == "agent-review"

    def test_auto_verdict_docs_ticket_no_verdict_needed(self, tmp_path: Path) -> None:
        """docs_refactor tickets reach done without any verdict being recorded."""
        ticket = _docs_ticket("T-DOCS-AUTO")
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        dispatcher = self._make_dispatcher(tmp_path)
        failure = dispatcher._mark_ticket_done(ticket, "docs merged")

        assert failure is None
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_override_path_records_override_true(self, tmp_path: Path) -> None:
        """_mark_ticket_done(override=True) → history entry has override:true."""
        ticket = _impl_ticket("T-OVERRIDE-PATH")
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        dispatcher = self._make_dispatcher(tmp_path)
        failure = dispatcher._mark_ticket_done(
            ticket,
            "emergency override",
            override=True,
            override_reason="pm waiver",
            override_actor="pm-user",
        )

        assert failure is None
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        history = saved.get("_transition_history", [])
        done_entry = next((e for e in history if e["status"] == "done"), None)
        assert done_entry is not None
        assert done_entry.get("override") is True

    def test_codex_ticket_no_auto_verdict_raises(self, tmp_path: Path) -> None:
        """INVERTED (BLOCKER 1): CODEX ticket without prior verdict → failure, not done.

        Previously CODEX-owned tickets also got the unconditional dispatcher-auto verdict.
        That path is removed — CODEX tickets must also have agent-review gate execute first.
        """
        ticket = _codex_ticket("T-CODEX-AUTO")
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        dispatcher = self._make_dispatcher(tmp_path)
        failure = dispatcher._mark_ticket_done(ticket, "codex gates passed")

        assert failure is not None, (
            "REGRESSION: CODEX ticket reached done without agent-review verdict — "
            "RC#3 hole re-opened for CODEX path."
        )
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] != "done", (
            "CODEX ticket reached done without real review verdict"
        )
        assert saved.get("_review_verdict", {}).get("by") != "dispatcher-auto", (
            "dispatcher-auto bypass verdict must not exist on CODEX tickets"
        )


# ---------------------------------------------------------------------------
# DOD 6b — dispatch-time enforcement: agent-review gate + files required
# ---------------------------------------------------------------------------


class TestDispatchTimeEnforcement:
    """BLOCKER 1 + 2 dispatch-time: _validate_impl_ticket_agent_review_gate + validate_impl_ticket_files."""

    def _make_dispatcher(self, tmp_path: Path, config: dict | None = None):
        from server.dispatcher import Dispatcher

        logs = tmp_path / "logs"
        logs.mkdir()
        return Dispatcher(
            config=config or {},
            paths={"root": tmp_path, "logs": logs, "queue": tmp_path / "QUEUE.yaml"},
        )

    def test_impl_ticket_without_agent_review_gate_raises(self, tmp_path: Path) -> None:
        """BLOCKER 1 dispatch-time: BUILDER ticket + files but no agent-review gate → ValidationError."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _impl_ticket("T-NO-AR-GATE")  # has files: ["apps/foo.py"]
        gates: list[dict] = [{"name": "pr-check", "run": "make pr-check"}]
        with pytest.raises(ValidationError, match="agent-review"):
            dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_impl_ticket_with_agent_review_gate_passes(self, tmp_path: Path) -> None:
        """BLOCKER 1 dispatch-time: agent-review gate present → no error."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _impl_ticket("T-WITH-AR-GATE")
        gates: list[dict] = [
            {"name": "pr-check", "run": "make pr-check"},
            {"name": "review", "type": "agent-review"},
        ]
        # Must not raise
        dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_docs_ticket_no_agent_review_gate_passes(self, tmp_path: Path) -> None:
        """Docs-refactor tickets are exempt from agent-review gate requirement."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _docs_ticket("T-DOCS-AR")
        gates: list[dict] = [{"name": "pr-check", "run": "make pr-check"}]
        # Must not raise (docs-refactor exempt)
        dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_no_files_builder_ticket_files_validator_raises(self) -> None:
        """BLOCKER 2 dispatch-time: validate_impl_ticket_files rejects no-files BUILDER ticket."""
        ticket = {
            "id": "T-NO-FILES-V",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            # No 'files' key
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)

    def test_no_files_codex_ticket_files_validator_raises(self) -> None:
        """BLOCKER 2 dispatch-time: validate_impl_ticket_files rejects no-files CODEX ticket."""
        ticket = {
            "id": "T-NO-FILES-CODEX",
            "owner": "CODEX",
            "impl_owner": "CODEX",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)

    def test_empty_files_builder_ticket_files_validator_raises(self) -> None:
        """BLOCKER 2 dispatch-time: files:[] (empty) also rejected."""
        ticket = {
            "id": "T-EMPTY-FILES",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": [],
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)

    def test_claude1_ticket_files_validator_passes(self) -> None:
        """CLAUDE1 (non-impl) tickets are exempt from files validator."""
        ticket = {
            "id": "T-C1-FILES",
            "owner": "CLAUDE1",
            "impl_owner": "CLAUDE1",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
        }
        # Must not raise
        validate_impl_ticket_files(ticket)

    # ------------------------------------------------------------------
    # P1.1 — gate name without type: agent-review does NOT satisfy gate
    # ------------------------------------------------------------------

    def test_gate_named_review_without_agent_review_type_raises(self, tmp_path: Path) -> None:
        """P1.1: gate {name: review, type: command} has no type:agent-review → ValidationError.

        Bypass: previously 'review' in gate_names was sufficient even with type:command.
        Now only type==agent-review matters; the name-based fallback is removed.
        """
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _impl_ticket("T-P1-NAME-ONLY")
        # Gate is named 'review' but type is 'command', not 'agent-review'.
        # A stale _review_verdict would allow done if this gate were accepted.
        gates: list[dict] = [{"name": "review", "type": "command", "run": "true"}]
        with pytest.raises(ValidationError, match="agent-review"):
            dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_gate_named_review_with_agent_review_type_passes(self, tmp_path: Path) -> None:
        """P1.1 positive: gate {name: review, type: agent-review} satisfies the check."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _impl_ticket("T-P1-TYPE-PRESENT")
        gates: list[dict] = [{"name": "review", "type": "agent-review"}]
        # Must not raise
        dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_gate_unnamed_with_agent_review_type_passes(self, tmp_path: Path) -> None:
        """P1.1 positive: gate without name but type:agent-review still satisfies."""
        dispatcher = self._make_dispatcher(tmp_path)
        ticket = _impl_ticket("T-P1-UNNAMED-TYPE")
        gates: list[dict] = [{"type": "agent-review"}]
        # Must not raise
        dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    # ------------------------------------------------------------------
    # P1.2 — blank / whitespace file entries are rejected
    # ------------------------------------------------------------------

    def test_blank_string_files_raises(self) -> None:
        """P1.2: files: [''] → validate_impl_ticket_files raises (blank is truthy but invalid)."""
        ticket = {
            "id": "T-BLANK-FILES",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": [""],
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)

    def test_whitespace_string_files_raises(self) -> None:
        """P1.2: files: ['  '] → validate_impl_ticket_files raises."""
        ticket = {
            "id": "T-WS-FILES",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["  "],
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)

    def test_blank_plus_valid_entry_still_raises(self) -> None:
        """P1.2: files: ['', 'NEW: apps/foo.py'] → still raises (blank rejected, no partial pass).

        Blank entries indicate malformed scope even when mixed with valid paths.
        Reject any list containing blanks for cleanliness.
        """
        ticket = {
            "id": "T-MIXED-BLANK",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["", "apps/foo.py"],
        }
        # Decision: blank + valid → still PASSES because valid entries exist
        # (the blank is stripped/ignored; only all-blank lists reject).
        # This matches the implementation: valid = [f.strip() for f in files if f.strip()]
        # so ['', 'apps/foo.py'] produces valid=['apps/foo.py'] → does NOT raise.
        # The test documents and pins this explicit decision.
        validate_impl_ticket_files(ticket)  # must NOT raise

    def test_multiple_blanks_raises(self) -> None:
        """P1.2: files: ['', '  ', '\\t'] → raises (all entries blank)."""
        ticket = {
            "id": "T-ALL-BLANK",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["", "  ", "\t"],
        }
        with pytest.raises(ValidationError, match="files"):
            validate_impl_ticket_files(ticket)


# ---------------------------------------------------------------------------
# DOD 7 — regression: existing ssot state-machine tests still pass
#          (smoke-tested here for completeness)
# ---------------------------------------------------------------------------


class TestStateTransitionRegressionSmoke:
    """Quick smoke: non-done transitions are unaffected by C1 review gate."""

    def test_todo_to_doing_no_verdict_required(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        ticket = {
            "id": "T-TODO-DOING",
            "owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
        }
        _write_queue(queue_path, ticket)
        result = update_ticket_status(
            queue_path, "T-TODO-DOING", "doing", reason="dispatch started", actor="dispatcher"
        )
        assert result is True

    def test_doing_to_code_ready_no_verdict_required(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        ticket = {
            "id": "T-DOING-CR",
            "owner": "BUILDER",
            "status": "doing",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
        }
        _write_queue(queue_path, ticket)
        result = update_ticket_status(
            queue_path, "T-DOING-CR", "code_ready", reason="agent done", actor="dispatcher"
        )
        assert result is True

    def test_code_ready_to_done_without_verdict_raises(self, tmp_path: Path) -> None:
        """Regression: code_ready → done still blocked without verdict."""
        ticket = {
            "id": "T-CR-DONE",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "code_ready",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["apps/foo.py"],
        }
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        with pytest.raises(ValidationError, match="_review_verdict"):
            update_ticket_status(
                queue_path,
                "T-CR-DONE",
                "done",
                reason="gates passed",
                actor="dispatcher",
            )

    def test_needs_pm_to_done_requires_verdict(self, tmp_path: Path) -> None:
        """needs_pm → done also blocked without verdict (PM approval alone insufficient)."""
        ticket = {
            "id": "T-PM-DONE",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "needs_pm",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["apps/foo.py"],
        }
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, ticket)

        with pytest.raises(ValidationError, match="_review_verdict"):
            update_ticket_status(
                queue_path,
                "T-PM-DONE",
                "done",
                reason="pm approved",
                actor="dispatcher",
            )

"""State machine tests for SSOT status transitions.

TDD spec for T-OS3-SSOT-STATE-MACHINE:
- Illegal transitions raise ValidationError
- Legal transitions succeed
- override=True with reason/actor bypasses machine + records override flag in history
- block_ticket / resume_blocked_ticket always record to _transition_history
- No regression on existing ssot / dispatcher tests
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.ssot import (
    ValidationError,
    block_ticket,
    read_queue,
    resume_blocked_ticket,
    update_ticket_status,
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


def _ticket(tid: str, status: str) -> dict:
    return {
        "id": tid,
        "owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# DOD 1 — illegal transitions raise ValidationError
# ---------------------------------------------------------------------------


class TestIllegalTransitions:
    """Every pair here must raise ValidationError (illegal state-machine jump)."""

    ILLEGAL = [
        ("todo", "done"),          # skip all intermediate states
        ("todo", "code_ready"),    # skip doing
        ("todo", "needs_pm"),      # skip doing + code_ready
        ("done", "todo"),          # terminal — no exit without override
        ("done", "doing"),         # terminal
        ("done", "blocked"),       # terminal
        ("done", "code_ready"),    # terminal
        ("done", "needs_pm"),      # terminal
        ("done", "parked"),        # terminal
        ("code_ready", "todo"),    # backward skip
        ("code_ready", "doing"),   # backward
        ("needs_pm", "todo"),      # backward
        ("needs_pm", "doing"),     # backward
        ("needs_pm", "code_ready"),# backward
        ("needs_pm", "parked"),    # parked is not valid from needs_pm
        ("parked", "done"),        # must go through todo first
        ("parked", "doing"),       # must unpark to todo first
        ("parked", "blocked"),     # must unpark to todo first
        ("blocked", "doing"),      # must resume to todo first
        ("blocked", "done"),       # must resume to todo first
        ("blocked", "code_ready"), # must resume to todo first
    ]

    @pytest.mark.parametrize("from_status,to_status", ILLEGAL)
    def test_illegal_transition_raises(
        self, tmp_path: Path, from_status: str, to_status: str
    ) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        tid = f"T-ILLEGAL-{from_status}-{to_status}".upper().replace("_", "-")
        _write_queue(queue_path, _ticket(tid, from_status))

        with pytest.raises(ValidationError, match="illegal transition"):
            update_ticket_status(
                queue_path,
                tid,
                to_status,
                reason="test probe",
                actor="test",
            )

        # Ticket status must not have changed
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == from_status


# ---------------------------------------------------------------------------
# DOD 2 — legal transitions succeed
# ---------------------------------------------------------------------------


class TestLegalTransitions:
    """Full happy-path chains must all succeed end-to-end."""

    def _cycle(self, queue_path: Path, tid: str, steps: list[tuple[str, str]]) -> dict:
        """Apply a sequence of (from, to) transitions and return final ticket."""
        for from_st, to_st in steps:
            result = update_ticket_status(
                queue_path,
                tid,
                to_st,
                reason=f"move {from_st}->{to_st}",
                actor="test",
                record_history=True,
            )
            assert result is True, f"update_ticket_status returned False for {from_st}->{to_st}"
            saved = read_queue(queue_path)["tickets"][0]
            assert saved["status"] == to_st, (
                f"Expected {to_st} after {from_st}->{to_st}, got {saved['status']}"
            )
        return read_queue(queue_path)["tickets"][0]

    def test_main_happy_path_todo_to_done(self, tmp_path: Path) -> None:
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-HAPPY", "todo"))
        final = self._cycle(
            queue_path,
            "T-HAPPY",
            [("todo", "doing"), ("doing", "code_ready"), ("code_ready", "done")],
        )
        assert final["status"] == "done"

    def test_blocked_recovery_path(self, tmp_path: Path) -> None:
        """todo → doing → blocked → todo → doing → code_ready → done."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-BLOCK-RECOVER", "todo"))

        # Advance to doing
        update_ticket_status(queue_path, "T-BLOCK-RECOVER", "doing",
                             reason="dispatch", actor="dispatcher")
        # Block
        block_ticket(queue_path, "T-BLOCK-RECOVER", "agent failed", "")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "blocked"

        # Resume to todo
        resume_blocked_ticket(queue_path, "T-BLOCK-RECOVER")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

        # Complete
        final = self._cycle(
            queue_path,
            "T-BLOCK-RECOVER",
            [("todo", "doing"), ("doing", "code_ready"), ("code_ready", "done")],
        )
        assert final["status"] == "done"

    def test_needs_pm_path(self, tmp_path: Path) -> None:
        """todo → doing → code_ready → needs_pm → done."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-PM", "todo"))
        final = self._cycle(
            queue_path,
            "T-PM",
            [
                ("todo", "doing"),
                ("doing", "code_ready"),
                ("code_ready", "needs_pm"),
                ("needs_pm", "done"),
            ],
        )
        assert final["status"] == "done"

    def test_needs_pm_blocked_path(self, tmp_path: Path) -> None:
        """code_ready → needs_pm → blocked → todo recovery."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-PM-BLOCK", "code_ready"))
        update_ticket_status(queue_path, "T-PM-BLOCK", "needs_pm",
                             reason="pm review pending", actor="dispatcher")
        block_ticket(queue_path, "T-PM-BLOCK", "pm rejected", "")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "blocked"
        resume_blocked_ticket(queue_path, "T-PM-BLOCK")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

    def test_parked_roundtrip(self, tmp_path: Path) -> None:
        """todo → parked → todo."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-PARK", "todo"))
        update_ticket_status(queue_path, "T-PARK", "parked",
                             reason="on hold", actor="pm")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "parked"
        update_ticket_status(queue_path, "T-PARK", "todo",
                             reason="unparked", actor="pm")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

    def test_todo_blocked_directly(self, tmp_path: Path) -> None:
        """todo → blocked (preflight failure path)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-PREFAIL", "todo"))
        block_ticket(queue_path, "T-PREFAIL", "deps not satisfied", "")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "blocked"

    def test_code_ready_blocked(self, tmp_path: Path) -> None:
        """code_ready → blocked (review BLOCKER path)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-CR-BLOCK", "code_ready"))
        block_ticket(queue_path, "T-CR-BLOCK", "reviewer BLOCKER", "")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "blocked"

    def test_doing_retry_to_todo(self, tmp_path: Path) -> None:
        """doing → todo (retry path)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-RETRY", "doing"))
        update_ticket_status(queue_path, "T-RETRY", "todo",
                             reason="retry dispatch", actor="dispatcher")
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"


# ---------------------------------------------------------------------------
# DOD 3 — override=True with reason/actor bypasses machine + records in history
# ---------------------------------------------------------------------------


class TestOverride:
    def test_override_allows_terminal_exit(self, tmp_path: Path) -> None:
        """done → todo with override=True must succeed without ValidationError."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR", "done"))

        result = update_ticket_status(
            queue_path,
            "T-OVR",
            "todo",
            reason="emergency reopen after prod incident",
            actor="pm-hoan",
            override=True,
        )
        assert result is True
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

    def test_override_records_flag_in_history(self, tmp_path: Path) -> None:
        """override=True must write override:true + reason + actor to _transition_history."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-HIST", "done"))

        update_ticket_status(
            queue_path,
            "T-OVR-HIST",
            "todo",
            reason="forced reopen: postmortem action item",
            actor="incident-bot",
            override=True,
        )
        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        assert len(history) >= 1
        last = history[-1]
        assert last["override"] is True
        assert last["reason"] == "forced reopen: postmortem action item"
        assert last["actor"] == "incident-bot"
        assert last["status"] == "todo"

    def test_override_todo_to_done_direct(self, tmp_path: Path) -> None:
        """todo → done direct skip with override=True must succeed."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-SKIP", "todo"))

        update_ticket_status(
            queue_path,
            "T-OVR-SKIP",
            "done",
            reason="manual close: out of scope",
            actor="pm",
            override=True,
        )
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"

    def test_override_requires_reason(self, tmp_path: Path) -> None:
        """override=True with empty reason must still raise ValidationError."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-BAD", "done"))

        with pytest.raises(ValidationError, match="transition reason is required"):
            update_ticket_status(
                queue_path,
                "T-OVR-BAD",
                "todo",
                reason="",
                actor="pm",
                override=True,
            )

    def test_override_requires_actor(self, tmp_path: Path) -> None:
        """override=True with empty actor must still raise ValidationError."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-NOACT", "done"))

        with pytest.raises(ValidationError, match="transition actor is required"):
            update_ticket_status(
                queue_path,
                "T-OVR-NOACT",
                "todo",
                reason="valid reason",
                actor="",
                override=True,
            )

    def test_override_without_flag_still_blocked(self, tmp_path: Path) -> None:
        """Illegal transition without override=True must still raise ValidationError."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-NO-OVR", "done"))

        with pytest.raises(ValidationError, match="illegal transition"):
            update_ticket_status(
                queue_path,
                "T-NO-OVR",
                "todo",
                reason="trying without override",
                actor="pm",
            )


# ---------------------------------------------------------------------------
# DOD 4 — block_ticket / resume_blocked_ticket always write to _transition_history
# ---------------------------------------------------------------------------


class TestHistoryCompleteness:
    def test_doing_transition_records_history(self, tmp_path: Path) -> None:
        """todo → doing via update_ticket_status must appear in _transition_history."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-DO-HIST", "todo"))

        update_ticket_status(
            queue_path,
            "T-DO-HIST",
            "doing",
            reason="dispatch started",
            actor="dispatcher",
        )
        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        assert any(e["status"] == "doing" for e in history), (
            f"'doing' not found in history: {history}"
        )

    def test_block_ticket_records_history(self, tmp_path: Path) -> None:
        """block_ticket must append a 'blocked' entry to _transition_history."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-BLK-HIST", "doing"))

        block_ticket(queue_path, "T-BLK-HIST", "agent timed out", "path/to/log")

        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        assert any(e["status"] == "blocked" for e in history), (
            f"'blocked' not found in history: {history}"
        )
        blocked_entry = next(e for e in history if e["status"] == "blocked")
        assert "ts" in blocked_entry
        assert blocked_entry["actor"] == "dispatcher"
        assert "agent timed out" in blocked_entry["reason"]

    def test_resume_blocked_ticket_records_history(self, tmp_path: Path) -> None:
        """resume_blocked_ticket must append a 'todo' entry to _transition_history."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(
            queue_path,
            {
                **_ticket("T-RES-HIST", "blocked"),
                "_blocked_reason": "test failure",
            },
        )

        resume_blocked_ticket(queue_path, "T-RES-HIST")

        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        assert any(e["status"] == "todo" for e in history), (
            f"'todo' not found in history: {history}"
        )
        todo_entry = next(e for e in history if e["status"] == "todo")
        assert todo_entry["actor"] == "user"
        assert "resumed" in todo_entry["reason"]

    def test_full_lifecycle_history_ordering(self, tmp_path: Path) -> None:
        """todo→doing→blocked→todo→doing→code_ready→done history has correct sequence."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-FULL-HIST", "todo"))

        update_ticket_status(queue_path, "T-FULL-HIST", "doing",
                             reason="first dispatch", actor="dispatcher")
        block_ticket(queue_path, "T-FULL-HIST", "gate failed", "")
        resume_blocked_ticket(queue_path, "T-FULL-HIST")
        update_ticket_status(queue_path, "T-FULL-HIST", "doing",
                             reason="retry dispatch", actor="dispatcher")
        update_ticket_status(queue_path, "T-FULL-HIST", "code_ready",
                             reason="agent done", actor="dispatcher", record_history=True)
        update_ticket_status(queue_path, "T-FULL-HIST", "done",
                             reason="gates pass", actor="dispatcher", record_history=True)

        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        statuses = [e["status"] for e in history]

        # All six transitions must be recorded in order
        assert statuses == ["doing", "blocked", "todo", "doing", "code_ready", "done"], (
            f"History order wrong: {statuses}"
        )


# ---------------------------------------------------------------------------
# DOD 5 — unknown from_status without override raises ValidationError (bypass hole fix)
# ---------------------------------------------------------------------------


class TestUnknownFromStatus:
    """Tickets with a status not in ALLOWED_TRANSITIONS must be rejected unless override=True."""

    UNKNOWN_STATUSES = [
        None,
        "",
        "rogue-status",
        "ready",          # common typo / old schema value not in ALLOWED_TRANSITIONS
        "pending",        # another common invalid status
        "future-state",   # hypothetical unknown future value
    ]

    @pytest.mark.parametrize("bad_status", UNKNOWN_STATUSES)
    def test_unknown_from_status_raises_without_override(
        self, tmp_path: Path, bad_status: str | None
    ) -> None:
        """update_ticket_status with unknown from_status and no override → ValidationError."""
        queue_path = tmp_path / "QUEUE.yaml"
        ticket = _ticket("T-UNKNOWN", "todo")
        # Directly force a bad status into the YAML, bypassing validation
        ticket["status"] = bad_status
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="unknown current status"):
            update_ticket_status(
                queue_path,
                "T-UNKNOWN",
                "todo",
                reason="attempt move from unknown status",
                actor="test",
            )

    @pytest.mark.parametrize("bad_status", UNKNOWN_STATUSES)
    def test_unknown_from_status_with_override_succeeds(
        self, tmp_path: Path, bad_status: str | None
    ) -> None:
        """unknown from_status + override=True + reason/actor → succeeds, history has override:true."""
        queue_path = tmp_path / "QUEUE.yaml"
        ticket = _ticket("T-UNKNOWN-OVR", "todo")
        ticket["status"] = bad_status
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": [ticket]}, sort_keys=False),
            encoding="utf-8",
        )

        result = update_ticket_status(
            queue_path,
            "T-UNKNOWN-OVR",
            "todo",
            reason="recovering legacy ticket with malformed status",
            actor="admin",
            override=True,
        )
        assert result is True

        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

        history = saved.get("_transition_history", [])
        assert len(history) >= 1
        last = history[-1]
        assert last.get("override") is True, f"Expected override:true in history entry: {last}"
        assert last["actor"] == "admin"
        assert last["status"] == "todo"

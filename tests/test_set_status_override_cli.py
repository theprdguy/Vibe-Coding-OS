"""TDD tests for T-OS3-SET-STATUS-OVERRIDE-CLI.

Covers --override / --reason / --actor flag additions to `os3 set-status`.

DOD coverage:
  #1: --override + --reason + --actor forces terminal done exit (rc 0)
  #2: no --override on illegal transition → ValidationError + rc 1
  #3: --override without both --reason and --actor → rejected (rc != 0)
  #4a: --override + --actor only (--reason missing) → rejected (rc != 0)
  #4b: --override + --reason only (--actor missing) → rejected (rc != 0)
"""
from __future__ import annotations

import yaml
from pathlib import Path
from unittest.mock import patch

import pytest

from server.cli import _build_parser, _handle_set_status, main
from server.ssot import (
    ValidationError,
    read_queue,
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
        "_review_verdict": {"verdict": "OK", "by": "reviewer", "ts": "2026-01-01T00:00:00Z"},
    }


def _load_paths(queue_path: Path) -> tuple:
    """Return (config, paths) stub for monkeypatching _load()."""
    config = {}
    paths = {"queue": queue_path}
    return config, paths


# ---------------------------------------------------------------------------
# DOD #1 — override forces terminal done exit (rc 0)
# ---------------------------------------------------------------------------


class TestOverrideForcesDoneTransition:
    """--override + --reason + --actor must allow done→todo or any terminal exit."""

    def test_override_done_to_todo_rc0(self, tmp_path: Path) -> None:
        """os3 set-status <id> todo --override --reason '...' --actor '...' succeeds (rc 0)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-01", "done"))

        argv = [
            "set-status", "T-OVR-01", "todo",
            "--override",
            "--reason", "emergency reopen by ops",
            "--actor", "ops-admin",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0

        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "todo"

    def test_override_records_override_flag_in_history(self, tmp_path: Path) -> None:
        """override=True must record override:true in _transition_history."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-02", "done"))

        argv = [
            "set-status", "T-OVR-02", "todo",
            "--override",
            "--reason", "ops escalation",
            "--actor", "sre-bot",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0

        saved = read_queue(queue_path)["tickets"][0]
        history = saved.get("_transition_history", [])
        assert history, "expected _transition_history to be populated"
        last = history[-1]
        assert last["override"] is True
        assert last["reason"] == "ops escalation"
        assert last["actor"] == "sre-bot"

    def test_override_flag_reason_actor_via_flags_takes_priority(self, tmp_path: Path) -> None:
        """When --reason/--actor flags are given alongside positional, flags win."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-03", "done"))

        argv = [
            "set-status", "T-OVR-03", "todo",
            "--override",
            "--reason", "flag reason",
            "--actor", "flag-actor",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["_transition_actor"] == "flag-actor"
        assert saved["_transition_reason"] == "flag reason"

    def test_override_todo_to_done_force_skip_rc0(self, tmp_path: Path) -> None:
        """os3 set-status <id> done --override --reason '...' --actor '...' forces todo→done (rc 0).

        This covers the DOD #1 literal example direction: force-to-done skipping intermediate states.
        """
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-OVR-04", "todo"))

        argv = [
            "set-status", "T-OVR-04", "done",
            "--override",
            "--reason", "emergency force-close by admin",
            "--actor", "ops-admin",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0

        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        history = saved.get("_transition_history", [])
        assert history, "expected _transition_history to be populated"
        last = history[-1]
        assert last["override"] is True
        assert last["reason"] == "emergency force-close by admin"
        assert last["actor"] == "ops-admin"


# ---------------------------------------------------------------------------
# DOD #2 — no --override on illegal transition → ValidationError + rc 1
# ---------------------------------------------------------------------------


class TestIllegalTransitionWithoutOverride:
    """Without --override, state-machine violations must return rc 1."""

    def test_done_to_todo_without_override_rc1(self, tmp_path: Path, capsys) -> None:
        """done→todo without --override returns rc 1 + ValidationError message."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-NOOVR-01", "done"))

        argv = ["set-status", "T-NOOVR-01", "todo", "reason without override", "user"]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 1
        captured = capsys.readouterr()
        assert "ValidationError" in captured.err
        assert "done" in captured.err
        assert "todo" in captured.err

    def test_todo_to_done_without_override_rc1(self, tmp_path: Path, capsys) -> None:
        """todo→done (skip) without --override returns rc 1."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-NOOVR-02", "todo"))

        argv = ["set-status", "T-NOOVR-02", "done", "skip", "user"]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 1
        captured = capsys.readouterr()
        assert "ValidationError" in captured.err
        assert "done" in captured.err
        assert "todo" in captured.err

    def test_illegal_transition_status_unchanged(self, tmp_path: Path) -> None:
        """Ticket status must not change on rejected illegal transition."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-NOOVR-03", "done"))

        argv = ["set-status", "T-NOOVR-03", "todo", "reason", "user"]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            main(argv)

        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done", "status must not change on rejected transition"


# ---------------------------------------------------------------------------
# DOD #3 — --override without --reason OR --actor → rejected
# ---------------------------------------------------------------------------


class TestOverrideRequiresBothFlags:
    """--override alone (no reason, no actor) must be rejected."""

    def test_override_no_reason_no_actor_rejected(self, tmp_path: Path, capsys) -> None:
        """--override without --reason or --actor must be rejected (rc != 0)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-FLAG-01", "done"))

        # No --reason flag, no --actor flag
        argv = [
            "set-status", "T-FLAG-01", "todo",
            "--override",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc != 0
        captured = capsys.readouterr()
        assert "--reason" in captured.err
        assert "--actor" in captured.err


# ---------------------------------------------------------------------------
# DOD #4a — --override + --actor only (missing --reason) → rejected
# ---------------------------------------------------------------------------


class TestOverrideMissingReason:
    """--override + --actor without --reason must be rejected."""

    def test_override_actor_only_missing_reason_rejected(self, tmp_path: Path, capsys) -> None:
        """--override + --actor but missing --reason → rejected (rc != 0)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-FLAG-02", "done"))

        argv = [
            "set-status", "T-FLAG-02", "todo",
            "--override",
            "--actor", "ops-admin",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc != 0
        captured = capsys.readouterr()
        assert "--reason" in captured.err


# ---------------------------------------------------------------------------
# DOD #4b — --override + --reason only (missing --actor) → rejected
# ---------------------------------------------------------------------------


class TestOverrideMissingActor:
    """--override + --reason without --actor must be rejected."""

    def test_override_reason_only_missing_actor_rejected(self, tmp_path: Path, capsys) -> None:
        """--override + --reason but missing --actor → rejected (rc != 0)."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-FLAG-03", "done"))

        argv = [
            "set-status", "T-FLAG-03", "todo",
            "--override",
            "--reason", "emergency",
        ]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc != 0
        captured = capsys.readouterr()
        assert "--actor" in captured.err


# ---------------------------------------------------------------------------
# Positional compat: existing positional reason/actor form still works
# ---------------------------------------------------------------------------


class TestPositionalCompatibility:
    """Existing positional `<reason> [actor]` form must continue to work."""

    def test_positional_reason_actor_legal_transition(self, tmp_path: Path) -> None:
        """os3 set-status <id> doing <reason> <actor> (positional) succeeds."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-COMPAT-01", "todo"))

        argv = ["set-status", "T-COMPAT-01", "doing", "starting work", "builder"]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "doing"

    def test_positional_reason_only_defaults_actor_to_user(self, tmp_path: Path) -> None:
        """os3 set-status <id> doing <reason> (no actor) defaults actor to 'user'."""
        queue_path = tmp_path / "QUEUE.yaml"
        _write_queue(queue_path, _ticket("T-COMPAT-02", "todo"))

        argv = ["set-status", "T-COMPAT-02", "doing", "starting work"]
        with patch("server.cli._load", return_value=_load_paths(queue_path)):
            rc = main(argv)
        assert rc == 0
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["_transition_actor"] == "user"

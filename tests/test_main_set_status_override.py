"""TDD tests for T-OS3-CLI-MAIN-DEDUPE.

Verifies that `python3 -m server set-status` (the __main__.py entrypoint) correctly
handles --override/--reason/--actor flags, positional back-compat, and rejection
cases — exercising the ACTUAL __main__ path (subprocess-based), not just cli.py.

DOD coverage:
  #1: python3 -m server set-status <id> done --override --reason ... --actor ...
      → rc 0 + saved status == done + transition_history.override == True
  #2: python3 -m server set-status <id> done --override without --reason
      → rc != 0 + stderr contains "--reason"
  #3: positional form python3 -m server set-status <id> <status> <reason> [actor]
      → rc 0 + status saved (back-compat)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_env() -> dict:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _make_project(root: Path, tickets: list[dict]) -> Path:
    """Scaffold a minimal project tree: osn.yaml + QUEUE.yaml + ARCHIVE.yaml."""
    devos = root / "devos" / "tasks"
    devos.mkdir(parents=True, exist_ok=True)
    queue_path = devos / "QUEUE.yaml"
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )
    (devos / "ARCHIVE.yaml").write_text(
        yaml.safe_dump({"version": "3.0", "tickets": []}, sort_keys=False),
        encoding="utf-8",
    )
    # Minimal deos.yaml — server/__main__.py checks cwd/deos.yaml
    (root / "deos.yaml").write_text(
        "project_root: .\n"
        "devos_dir: devos\n"
        "queue_file: devos/tasks/QUEUE.yaml\n"
        "plans_dir: devos/plans\n"
        "logs_dir: devos/logs\n",
        encoding="utf-8",
    )
    return queue_path


def _ticket(tid: str, status: str) -> dict:
    return {
        "id": tid,
        "owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "_review_verdict": {
            "verdict": "OK",
            "by": "reviewer",
            "ts": "2026-01-01T00:00:00Z",
        },
    }


def _run_server(*args: str, cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run python3 -m server with list-form args in the given cwd."""
    return subprocess.run(
        [PYTHON, "-m", "server", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout,
        env=_base_env(),
    )


def _read_ticket(queue_path: Path, tid: str) -> dict:
    data = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
    ticket = next(
        (t for t in data.get("tickets", []) if t.get("id") == tid), None
    )
    assert ticket is not None, f"ticket {tid!r} not found in {queue_path}"
    return ticket


# ---------------------------------------------------------------------------
# DOD #1 — override forces terminal done exit (rc 0 + saved + override=True in history)
# ---------------------------------------------------------------------------


class TestMainOverrideForcesDone:
    """python3 -m server set-status with --override + --reason + --actor must succeed."""

    def test_override_todo_to_done_rc0_and_saved(self, tmp_path: Path) -> None:
        """DOD #1: python3 -m server set-status <id> done --override --reason ... --actor ...
        → rc 0, saved status == done, transition_history.override == True.
        """
        queue_path = _make_project(tmp_path, [_ticket("T-MAIN-OVR-01", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-OVR-01", "done",
            "--override",
            "--reason", "emergency force-close by admin",
            "--actor", "ops-admin",
            cwd=tmp_path,
        )

        assert result.returncode == 0, (
            f"Expected rc 0 for override done, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )

        saved = _read_ticket(queue_path, "T-MAIN-OVR-01")
        assert saved["status"] == "done", (
            f"Expected saved status 'done', got {saved['status']!r}"
        )

        history = saved.get("_transition_history", [])
        assert history, "Expected _transition_history to be populated after override"
        last = history[-1]
        assert last.get("override") is True, (
            f"Expected override=True in history, got: {last!r}"
        )
        assert last.get("reason") == "emergency force-close by admin"
        assert last.get("actor") == "ops-admin"

    def test_override_done_to_todo_rc0(self, tmp_path: Path) -> None:
        """Force terminal done ticket back to todo (escape hatch pattern)."""
        queue_path = _make_project(tmp_path, [_ticket("T-MAIN-OVR-02", "done")])

        result = _run_server(
            "set-status", "T-MAIN-OVR-02", "todo",
            "--override",
            "--reason", "emergency reopen",
            "--actor", "sre-bot",
            cwd=tmp_path,
        )

        assert result.returncode == 0, (
            f"Expected rc 0 for override reopen, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )

        saved = _read_ticket(queue_path, "T-MAIN-OVR-02")
        assert saved["status"] == "todo"

    def test_override_output_includes_ticket_and_status(self, tmp_path: Path) -> None:
        """Successful override prints updated <id> -> <status> confirmation."""
        _make_project(tmp_path, [_ticket("T-MAIN-OVR-03", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-OVR-03", "done",
            "--override",
            "--reason", "forced",
            "--actor", "admin",
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert "T-MAIN-OVR-03" in result.stdout
        assert "done" in result.stdout


# ---------------------------------------------------------------------------
# DOD #2 — --override without --reason → rc != 0 + stderr mentions "--reason"
# ---------------------------------------------------------------------------


class TestMainOverrideMissingRequiredFlags:
    """python3 -m server set-status --override without full --reason/--actor must reject."""

    def test_override_no_reason_rejected_rc_nonzero(self, tmp_path: Path) -> None:
        """DOD #2: --override without --reason → rc != 0 + stderr contains '--reason'."""
        _make_project(tmp_path, [_ticket("T-MAIN-FLAG-01", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-FLAG-01", "done",
            "--override",
            "--actor", "admin",
            # --reason intentionally omitted
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero rc when --reason is missing, got {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "--reason" in result.stderr, (
            f"Expected '--reason' in stderr, got: {result.stderr!r}"
        )

    def test_override_no_actor_rejected_rc_nonzero(self, tmp_path: Path) -> None:
        """--override without --actor → rc != 0 + stderr mentions '--actor'."""
        _make_project(tmp_path, [_ticket("T-MAIN-FLAG-02", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-FLAG-02", "done",
            "--override",
            "--reason", "emergency",
            # --actor intentionally omitted
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero rc when --actor is missing, got {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "--actor" in result.stderr, (
            f"Expected '--actor' in stderr, got: {result.stderr!r}"
        )

    def test_override_no_reason_no_actor_rejected(self, tmp_path: Path) -> None:
        """--override alone (no reason, no actor) must be rejected."""
        _make_project(tmp_path, [_ticket("T-MAIN-FLAG-03", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-FLAG-03", "done",
            "--override",
            cwd=tmp_path,
        )

        assert result.returncode != 0
        # stderr must mention the missing required flag
        assert "--reason" in result.stderr or "--actor" in result.stderr, (
            f"Expected mention of missing flags in stderr, got: {result.stderr!r}"
        )

    def test_override_status_unchanged_on_missing_flags(self, tmp_path: Path) -> None:
        """Ticket status must not change when override is rejected due to missing flags."""
        queue_path = _make_project(tmp_path, [_ticket("T-MAIN-FLAG-04", "todo")])

        _run_server(
            "set-status", "T-MAIN-FLAG-04", "done",
            "--override",
            # missing --reason and --actor
            cwd=tmp_path,
        )

        saved = _read_ticket(queue_path, "T-MAIN-FLAG-04")
        assert saved["status"] == "todo", (
            "Ticket status must not change on rejected override (missing flags)"
        )


# ---------------------------------------------------------------------------
# DOD #3 — positional form back-compat: python3 -m server set-status <id> <status> <reason> [actor]
# ---------------------------------------------------------------------------


class TestMainPositionalBackCompat:
    """Existing positional invocation must still work after delegation."""

    def test_positional_reason_and_actor_legal_transition(self, tmp_path: Path) -> None:
        """DOD #3: python3 -m server set-status <id> doing <reason> <actor> → rc 0."""
        queue_path = _make_project(tmp_path, [_ticket("T-MAIN-COMPAT-01", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-COMPAT-01", "doing", "starting work", "builder",
            cwd=tmp_path,
        )

        assert result.returncode == 0, (
            f"Expected rc 0 for positional set-status, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )

        saved = _read_ticket(queue_path, "T-MAIN-COMPAT-01")
        assert saved["status"] == "doing"

    def test_positional_reason_only_defaults_actor_to_user(self, tmp_path: Path) -> None:
        """Positional with only reason (no actor) defaults actor to 'user'."""
        queue_path = _make_project(tmp_path, [_ticket("T-MAIN-COMPAT-02", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-COMPAT-02", "doing", "starting work",
            cwd=tmp_path,
        )

        assert result.returncode == 0
        saved = _read_ticket(queue_path, "T-MAIN-COMPAT-02")
        assert saved["status"] == "doing"
        assert saved.get("_transition_actor") == "user"

    def test_positional_missing_status_exits_nonzero(self, tmp_path: Path) -> None:
        """python3 -m server set-status <id> (missing status) → rc != 0 + usage in stderr."""
        _make_project(tmp_path, [_ticket("T-MAIN-COMPAT-03", "todo")])

        result = _run_server(
            "set-status", "T-MAIN-COMPAT-03",
            # status omitted
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero rc for missing status arg, got {result.returncode}"
        )

    def test_positional_illegal_transition_without_override_rc1(self, tmp_path: Path) -> None:
        """Positional done→todo (illegal) without --override returns rc != 0."""
        _make_project(tmp_path, [_ticket("T-MAIN-COMPAT-04", "done")])

        result = _run_server(
            "set-status", "T-MAIN-COMPAT-04", "todo", "reason", "user",
            cwd=tmp_path,
        )

        assert result.returncode != 0, (
            f"Expected non-zero rc for illegal transition, got {result.returncode}; "
            f"stderr={result.stderr!r}"
        )

    def test_ticket_not_found_exits_nonzero(self, tmp_path: Path) -> None:
        """set-status on a nonexistent ticket id → rc != 0."""
        _make_project(tmp_path, [_ticket("T-MAIN-COMPAT-05", "todo")])

        result = _run_server(
            "set-status", "T-NONEXISTENT-9999", "doing", "reason",
            cwd=tmp_path,
        )

        assert result.returncode != 0


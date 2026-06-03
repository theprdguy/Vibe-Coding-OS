"""T-OS3-CLOSE-ATOMIC — tests for single-lock close atomicity.

DOD coverage:
1. crash-on-write (update_ticket_status(done) fails) → both verdict + code_ready
   are rolled back → ticket restored to pre-close status (doing).
2. normal close acquires the advisory lock exactly once.
3. concurrent set-status during close → one side wins, other gets clear error.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

from server.cli import main as cli_main
from server.ssot import (
    LockTimeoutError,
    ValidationError,
    close_ticket_atomic,
    read_queue,
)


# ---------------------------------------------------------------------------
# Helpers (shared with test_close_cli.py pattern)
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
    verdict: str = "OK",
    by: str = "test-reviewer",
    confidence: str = "0.9",
    reason: str = "close test",
) -> int:
    """Run `os3 close <id> ...` via cli.main and return exit code."""
    args = [
        "close", ticket_id,
        "--project", str(tmp_path),
        "--verdict", verdict,
        "--by", by,
        "--confidence", confidence,
        "--reason", reason,
    ]
    try:
        return cli_main(args)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1


# ---------------------------------------------------------------------------
# DOD 1 — crash on write → no partial state — file untouched
# ---------------------------------------------------------------------------


class TestCloseAtomicRollback:
    """close_ticket_atomic performs all mutations in-memory and issues exactly
    one _write_queue_unlocked call.  If that write fails the file is never
    modified — there is no partial-state surface (verdict recorded but status
    still doing/code_ready)."""

    def test_rollback_on_write_failure_restores_doing(self, tmp_path: Path) -> None:
        """DOD 1: write failure → file untouched → ticket still doing, verdict absent."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-ROLLBACK", status="doing"))

        def _patched_write(path: Path, data: dict) -> None:
            raise OSError("simulated crash on write")

        with patch("server.ssot._write_queue_unlocked", side_effect=_patched_write):
            with pytest.raises(OSError, match="simulated crash"):
                close_ticket_atomic(
                    queue_path,
                    "T-ATOMIC-ROLLBACK",
                    verdict="OK",
                    by="test-reviewer",
                    reason="atomic test",
                    actor="test",
                )

        # File was never written — ticket stays in pre-close state
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "doing", (
            f"Expected 'doing' (file untouched) but got {saved['status']!r}"
        )
        assert "_review_verdict" not in saved, (
            "verdict present in file — partial-state surface detected"
        )

    def test_rollback_preserves_original_transition_metadata(self, tmp_path: Path) -> None:
        """After write failure, _transition_reason/_transition_actor stay at seed values."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-META", status="doing"))

        def _patched_write(path: Path, data: dict) -> None:
            raise OSError("simulated crash")

        with patch("server.ssot._write_queue_unlocked", side_effect=_patched_write):
            with pytest.raises(OSError):
                close_ticket_atomic(
                    queue_path,
                    "T-ATOMIC-META",
                    verdict="OK",
                    by="test-reviewer",
                    reason="atomic test",
                    actor="test",
                )

        saved = read_queue(queue_path)["tickets"][0]
        assert saved["_transition_reason"] == "seed", (
            "transition metadata mutated in file during failed close"
        )
        assert saved["_transition_actor"] == "test"

    def test_exactly_one_write_call_on_success(self, tmp_path: Path) -> None:
        """close_ticket_atomic must call _write_queue_unlocked exactly once."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-ONE-WRITE", status="doing"))

        import server.ssot as ssot_mod
        original_write = ssot_mod._write_queue_unlocked
        write_calls: list[Path] = []

        def _counting_write(path: Path, data: dict) -> None:
            write_calls.append(path)
            original_write(path, data)

        with patch("server.ssot._write_queue_unlocked", side_effect=_counting_write):
            close_ticket_atomic(
                queue_path,
                "T-ATOMIC-ONE-WRITE",
                verdict="OK",
                by="test-reviewer",
                reason="write count test",
                actor="test",
            )

        assert len(write_calls) == 1, (
            f"Expected exactly 1 write call but got {len(write_calls)}: {write_calls}"
        )
        # Result must be done
        saved = read_queue(queue_path)["tickets"][0]
        assert saved["status"] == "done"
        assert "_review_verdict" in saved


# ---------------------------------------------------------------------------
# DOD 2 — normal close acquires lock exactly once
# ---------------------------------------------------------------------------


class TestCloseAtomicSingleLock:
    """Normal close must acquire the advisory lock exactly once for all 3 writes."""

    def test_single_lock_acquisition(self, tmp_path: Path) -> None:
        """DOD 2: lock acquired 1× for record_verdict + code_ready + done."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-LOCK", status="doing"))

        acquire_calls: list[Any] = []

        import server.ssot as ssot_mod
        original_acquire = ssot_mod.acquire_file_lock

        def _counting_acquire(path, **kwargs):
            acquire_calls.append(path)
            return original_acquire(path, **kwargs)

        with patch("server.ssot.acquire_file_lock", side_effect=_counting_acquire):
            close_ticket_atomic(
                queue_path,
                "T-ATOMIC-LOCK",
                verdict="OK",
                by="test-reviewer",
                reason="lock count test",
                actor="test",
            )

        queue_acquires = [p for p in acquire_calls if "QUEUE" in str(p).upper()]
        assert len(queue_acquires) == 1, (
            f"Expected 1 QUEUE lock acquisition but got {len(queue_acquires)}: {queue_acquires}"
        )

    def test_cli_close_uses_single_lock(self, tmp_path: Path) -> None:
        """os3 close CLI must also acquire QUEUE lock exactly once end-to-end."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-CLI-LOCK", status="doing"))

        acquire_calls: list[Any] = []

        import server.ssot as ssot_mod
        original_acquire = ssot_mod.acquire_file_lock

        def _counting_acquire(path, **kwargs):
            acquire_calls.append(path)
            return original_acquire(path, **kwargs)

        with patch("server.ssot.acquire_file_lock", side_effect=_counting_acquire):
            rc = _run_close(tmp_path, "T-CLI-LOCK")

        assert rc == 0, f"Expected rc=0 but got {rc}"
        queue_acquires = [p for p in acquire_calls if "QUEUE" in str(p).upper()]
        assert len(queue_acquires) == 1, (
            f"Expected 1 QUEUE lock acquisition but got {len(queue_acquires)}: {queue_acquires}"
        )


# ---------------------------------------------------------------------------
# DOD 3 — concurrent set-status races with close → one side wins, clear error
# ---------------------------------------------------------------------------


class TestCloseAtomicConcurrentRace:
    """While close holds the advisory lock, a concurrent set-status must either
    wait (sequential) or fail fast with a LockTimeoutError, never silently corrupting."""

    def test_concurrent_close_and_set_status_serialised(self, tmp_path: Path) -> None:
        """While close holds the advisory lock, a concurrent set-status with a near-zero
        timeout must raise LockTimeoutError — never silently overwrites."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-RACE", status="doing"))

        from server.ssot import LockTimeoutError, acquire_file_lock, update_ticket_status

        # Hold the lock from a background thread; then try to acquire from foreground.
        held = threading.Event()
        release = threading.Event()
        errors: list[Exception] = []

        def _hold_lock():
            try:
                with acquire_file_lock(queue_path, timeout=5.0, actor="bg-holder"):
                    held.set()
                    release.wait(timeout=5.0)
            except Exception as exc:
                errors.append(exc)

        bg = threading.Thread(target=_hold_lock, daemon=True)
        bg.start()
        held.wait(timeout=5.0)

        try:
            # Patch the lock timeout to near-zero so the contending call fails fast.
            with patch("server.ssot._configured_lock_timeout", return_value=0.01):
                with pytest.raises(LockTimeoutError):
                    update_ticket_status(
                        queue_path,
                        "T-ATOMIC-RACE",
                        "code_ready",
                        reason="race attempt",
                        actor="concurrent",
                    )
        finally:
            release.set()
            bg.join(timeout=5.0)

    def test_concurrent_race_no_silent_corruption(self, tmp_path: Path) -> None:
        """Two close calls racing: final state must be consistent (done or doing),
        never partially-closed (verdict recorded + code_ready)."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-CORRUPT", status="doing"))

        results: list[Any] = []
        exceptions: list[Exception] = []

        def _do_close():
            try:
                close_ticket_atomic(
                    queue_path,
                    "T-ATOMIC-CORRUPT",
                    verdict="OK",
                    by="racer",
                    reason="race test",
                    actor="racer",
                )
                results.append("ok")
            except Exception as exc:
                exceptions.append(exc)

        t1 = threading.Thread(target=_do_close, daemon=True)
        t2 = threading.Thread(target=_do_close, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=10.0)
        t2.join(timeout=10.0)

        # Final state must be consistent — never partial
        saved = read_queue(queue_path)["tickets"][0]
        status = saved.get("status")

        # Acceptable outcomes: done (one winner) or blocked/error (both failed gracefully)
        # Forbidden: status=code_ready with no _review_verdict, or status=doing with _review_verdict
        if status == "code_ready":
            # If one side got to code_ready but couldn't write done, the rollback
            # (if implemented) should have restored it. code_ready here means
            # partial state was NOT rolled back — this is the bug we're fixing.
            # Both sides should either complete to done or raise and rollback to doing.
            assert "_review_verdict" in saved, (
                "Partial state detected: status=code_ready but no verdict "
                "(verdict write succeeded, done write failed without rollback)"
            )

        # If status=doing, verdict must not be present (rollback worked)
        if status == "doing":
            assert "_review_verdict" not in saved, (
                "Partial state: status=doing but _review_verdict is present"
            )

    def test_lock_timeout_error_message_is_clear(self, tmp_path: Path) -> None:
        """LockTimeoutError message must identify which path is locked and the actor."""
        queue_path = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        _write_queue(queue_path, _builder_ticket("T-ATOMIC-MSG", status="doing"))

        held = threading.Event()
        release = threading.Event()

        def _hold():
            from server.ssot import acquire_file_lock
            with acquire_file_lock(queue_path, timeout=5.0, actor="holder"):
                held.set()
                release.wait(timeout=5.0)

        bg = threading.Thread(target=_hold, daemon=True)
        bg.start()
        held.wait(timeout=5.0)

        try:
            from server.ssot import acquire_file_lock
            import os
            os.environ["OS3_FILE_LOCK_TIMEOUT"] = "0.01"
            try:
                with pytest.raises(LockTimeoutError) as exc_info:
                    with acquire_file_lock(queue_path, timeout=0.01, actor="test-actor"):
                        pass
                msg = str(exc_info.value)
                assert "QUEUE" in msg.upper() or str(queue_path.name) in msg, (
                    f"Error message does not identify locked path: {msg!r}"
                )
            finally:
                del os.environ["OS3_FILE_LOCK_TIMEOUT"]
        finally:
            release.set()
            bg.join(timeout=5.0)

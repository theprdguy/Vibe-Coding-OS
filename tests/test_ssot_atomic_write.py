"""Atomic write tests for SSOT queue/archive/plan writers.

TDD spec for T-OS3-SSOT-ATOMIC-WRITE:
DOD 1 — write failure leaves original file parseable (atomicity)
DOD 2 — temp file lifecycle: same dir, cleaned up on success and failure
DOD 3 — fcntl=None without OS3_ALLOW_NO_LOCK raises LockUnavailableError
DOD 4 — stale ARCHIVE-INDEX triggers on-demand rebuild in find_archived_ticket
DOD 5 — B1 state-machine regression check (covered by test_ssot_state_machine.py,
          but smoke-tested here too for completeness)
DOD 6 — BLOCKER-1 fix: mtime-based freshness — no ARCHIVE.yaml full parse on index hit
DOD 7 — BLOCKER-2 fix: stale-rebuild uses .archive-index.lock, never .archive.lock
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

import server.ssot as ssot_module
from server.ssot import (
    ARCHIVE_INDEX_LOCK_FILE_NAME,
    ARCHIVE_INDEX_MTIME_KEY,
    ARCHIVE_LOCK_FILE_NAME,
    LockUnavailableError,
    ValidationError,
    _archive_index_lock_path,
    _write_plan,
    _write_queue_unlocked,
    acquire_file_lock,
    archive_done_tickets,
    archive_lock_exists,
    build_archive_index,
    find_archived_ticket,
    index_path_for_archive,
    update_ticket_status,
    write_queue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_queue(queue_path: Path, tickets: list[dict] | None = None) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        yaml.safe_dump(
            {"version": "3.0", "tickets": tickets or []},
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _make_ticket(tid: str, status: str = "done") -> dict:
    return {
        "id": tid,
        "owner": "BUILDER",
        "status": status,
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# DOD 1 — atomicity: failure during write leaves original parseable
# ---------------------------------------------------------------------------


class TestAtomicWriteQueue:
    """_write_queue_unlocked: crash during os.replace must not corrupt original."""

    def test_original_survives_replace_failure(self, tmp_path):
        queue_path = tmp_path / "QUEUE.yaml"
        original_data = {"version": "3.0", "tickets": [_make_ticket("T-ORIG", "todo")]}
        _make_queue(queue_path, original_data["tickets"])

        new_data = {"version": "3.0", "tickets": [_make_ticket("T-NEW", "doing")]}

        with patch("server.ssot.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _write_queue_unlocked(queue_path, new_data)

        # Original file must still be parseable and unchanged
        loaded = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
        assert loaded is not None
        ids = [t["id"] for t in loaded.get("tickets", [])]
        assert "T-ORIG" in ids
        assert "T-NEW" not in ids

    def test_original_survives_dump_failure(self, tmp_path):
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path, [_make_ticket("T-ORIG", "todo")])

        with patch("server.ssot.yaml.dump", side_effect=RuntimeError("yaml exploded")):
            with pytest.raises(RuntimeError, match="yaml exploded"):
                _write_queue_unlocked(queue_path, {"version": "3.0", "tickets": []})

        # Original must be intact
        loaded = yaml.safe_load(queue_path.read_text(encoding="utf-8"))
        assert loaded is not None


class TestAtomicWritePlan:
    """_write_plan: crash during write must not corrupt original."""

    def test_original_survives_replace_failure(self, tmp_path):
        plan_path = tmp_path / "my-plan.yaml"
        original = {"id": "plan-1", "status": "pending", "tickets": []}
        plan_path.write_text(yaml.safe_dump(original), encoding="utf-8")

        with patch("server.ssot.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _write_plan(plan_path, {"id": "plan-2", "status": "rejected"})

        loaded = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert loaded["id"] == "plan-1"

    def test_original_survives_dump_failure(self, tmp_path):
        plan_path = tmp_path / "my-plan.yaml"
        original = {"id": "plan-orig", "status": "pending"}
        plan_path.write_text(yaml.safe_dump(original), encoding="utf-8")

        with patch("server.ssot.yaml.dump", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                _write_plan(plan_path, {"id": "plan-new"})

        loaded = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert loaded["id"] == "plan-orig"


# ---------------------------------------------------------------------------
# DOD 2 — temp file lifecycle
# ---------------------------------------------------------------------------


class TestTempFileLifecycle:
    """Temp files must live in same directory, be cleaned up on both paths."""

    def test_no_orphan_temp_on_success(self, tmp_path):
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path, [_make_ticket("T-A", "todo")])

        _write_queue_unlocked(queue_path, {"version": "3.0", "tickets": []})

        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"orphan temp files: {leftover}"

    def test_no_orphan_temp_on_failure(self, tmp_path):
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path, [_make_ticket("T-B", "todo")])

        with patch("server.ssot.os.replace", side_effect=OSError("fail")):
            with pytest.raises(OSError):
                _write_queue_unlocked(queue_path, {"version": "3.0", "tickets": []})

        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"orphan temp files after failure: {leftover}"

    def test_temp_file_in_same_directory(self, tmp_path):
        """Temp file must be created in same dir as target for os.replace to be atomic."""
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path, [])

        created_paths: list[Path] = []
        real_replace = os.replace

        def spy_replace(src, dst):
            created_paths.append(Path(src))
            real_replace(src, dst)

        with patch("server.ssot.os.replace", side_effect=spy_replace):
            _write_queue_unlocked(queue_path, {"version": "3.0", "tickets": []})

        assert len(created_paths) == 1
        assert created_paths[0].parent == tmp_path

    def test_plan_no_orphan_temp_on_success(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(yaml.safe_dump({"id": "p1"}), encoding="utf-8")

        _write_plan(plan_path, {"id": "p2"})

        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"orphan temp files: {leftover}"

    def test_plan_no_orphan_temp_on_failure(self, tmp_path):
        plan_path = tmp_path / "plan.yaml"
        plan_path.write_text(yaml.safe_dump({"id": "p1"}), encoding="utf-8")

        with patch("server.ssot.os.replace", side_effect=OSError("fail")):
            with pytest.raises(OSError):
                _write_plan(plan_path, {"id": "p2"})

        leftover = list(tmp_path.glob("*.tmp"))
        assert leftover == [], f"orphan temp files after failure: {leftover}"


# ---------------------------------------------------------------------------
# DOD 3 — fcntl=None fail-closed
# ---------------------------------------------------------------------------


class TestFcntlFailClosed:
    """Without OS3_ALLOW_NO_LOCK, missing fcntl must raise LockUnavailableError."""

    def test_raises_without_allow_env(self, tmp_path):
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path)

        env = {k: v for k, v in os.environ.items() if k != "OS3_ALLOW_NO_LOCK"}
        with patch.object(ssot_module, "fcntl", None):
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(LockUnavailableError):
                    with acquire_file_lock(queue_path, actor="test"):
                        pass

    def test_allow_env_permits_no_lock(self, tmp_path, capsys):
        """OS3_ALLOW_NO_LOCK=1 must allow the lock to proceed with a warning."""
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path)

        with patch.object(ssot_module, "fcntl", None):
            with patch.dict(os.environ, {"OS3_ALLOW_NO_LOCK": "1"}):
                # Must not raise; context body runs
                executed = []
                with acquire_file_lock(queue_path, actor="test"):
                    executed.append(True)

        assert executed == [True]
        captured = capsys.readouterr()
        assert "OS3_ALLOW_NO_LOCK" in captured.err or "no-lock" in captured.err.lower()

    def test_allow_env_zero_still_raises(self, tmp_path):
        """OS3_ALLOW_NO_LOCK=0 must not enable the bypass."""
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path)

        with patch.object(ssot_module, "fcntl", None):
            with patch.dict(os.environ, {"OS3_ALLOW_NO_LOCK": "0"}):
                with pytest.raises(LockUnavailableError):
                    with acquire_file_lock(queue_path, actor="test"):
                        pass

    def test_no_silent_pass_without_env(self, tmp_path):
        """Ensure the error is not merely a warning — it must raise."""
        queue_path = tmp_path / "QUEUE.yaml"
        _make_queue(queue_path)

        with patch.object(ssot_module, "fcntl", None):
            with patch.dict(os.environ, {}, clear=True):
                raised = False
                try:
                    with acquire_file_lock(queue_path, actor="test"):
                        pass
                except LockUnavailableError:
                    raised = True
                assert raised, "Expected LockUnavailableError but nothing was raised"


# ---------------------------------------------------------------------------
# DOD 4 — stale ARCHIVE-INDEX triggers on-demand rebuild
# ---------------------------------------------------------------------------


class TestStaleIndexDetection:
    """find_archived_ticket must detect stale index and rebuild on-demand."""

    def _make_archive(self, archive_path: Path, tickets: list[dict]) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
            encoding="utf-8",
        )

    def _make_index(self, archive_path: Path, index: dict) -> None:
        from server.ssot import index_path_for_archive

        idx_path = index_path_for_archive(archive_path)
        idx_path.write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")

    def test_stale_index_triggers_rebuild(self, tmp_path, monkeypatch):
        """Index has T-OLD only; ARCHIVE has T-OLD + T-NEW → stale → rebuild → finds T-NEW."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t_old = _make_ticket("T-OLD")
        t_new = _make_ticket("T-NEW")
        self._make_archive(archive_path, [t_old, t_new])

        # Stale index: only has T-OLD
        self._make_index(archive_path, {"T-OLD": 1})

        result = find_archived_ticket(archive_path, "T-NEW")
        assert result is not None
        assert result["id"] == "T-NEW"

    def test_fresh_index_no_rebuild(self, tmp_path):
        """Fresh index returns ticket without rebuilding."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t1 = _make_ticket("T-ALPHA")
        self._make_archive(archive_path, [t1])

        build_archive_index(archive_path)

        rebuild_count = []
        real_build = ssot_module.build_archive_index

        def counting_build(ap):
            rebuild_count.append(1)
            return real_build(ap)

        with patch.object(ssot_module, "build_archive_index", side_effect=counting_build):
            result = find_archived_ticket(archive_path, "T-ALPHA")

        assert result is not None
        assert result["id"] == "T-ALPHA"
        assert len(rebuild_count) == 0, "should not rebuild a fresh index"

    def test_missing_index_triggers_rebuild(self, tmp_path):
        """Absent index still falls back to building it (existing behavior preserved)."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t1 = _make_ticket("T-BETA")
        self._make_archive(archive_path, [t1])
        # No index file written

        result = find_archived_ticket(archive_path, "T-BETA")
        assert result is not None
        assert result["id"] == "T-BETA"

    def test_stale_index_rebuild_warning_on_stderr(self, tmp_path, capsys):
        """Stale index detection emits a warning to stderr before rebuilding."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t_extra = _make_ticket("T-EXTRA")
        self._make_archive(archive_path, [t_extra])
        self._make_index(archive_path, {})  # stale: T-EXTRA missing

        find_archived_ticket(archive_path, "T-EXTRA")

        captured = capsys.readouterr()
        assert "stale" in captured.err.lower() or "index" in captured.err.lower()

    def test_stale_index_not_found_still_returns_none(self, tmp_path):
        """Stale index rebuild succeeds but ticket truly absent → returns None."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t1 = _make_ticket("T-PRESENT")
        self._make_archive(archive_path, [t1])
        self._make_index(archive_path, {})  # stale

        result = find_archived_ticket(archive_path, "T-GHOST")
        assert result is None


# ---------------------------------------------------------------------------
# DOD 5 — B1 state-machine regression smoke tests
# ---------------------------------------------------------------------------


class TestStateMachineRegression:
    """Smoke tests: atomic write changes must not break state-machine behaviour."""

    def _queue_path(self, tmp_path: Path) -> Path:
        q = tmp_path / "devos" / "tasks" / "QUEUE.yaml"
        q.parent.mkdir(parents=True, exist_ok=True)
        return q

    def test_legal_transition_still_persisted(self, tmp_path):
        q = self._queue_path(tmp_path)
        t = _make_ticket("T-SM-1", "todo")
        _make_queue(q, [t])

        update_ticket_status(
            q,
            "T-SM-1",
            "doing",
            reason="starting work",
            actor="builder",
        )

        from server.ssot import read_queue

        data = read_queue(q)
        ticket = next(x for x in data["tickets"] if x["id"] == "T-SM-1")
        assert ticket["status"] == "doing"

    def test_illegal_transition_still_raises(self, tmp_path):
        q = self._queue_path(tmp_path)
        t = _make_ticket("T-SM-2", "todo")
        _make_queue(q, [t])

        with pytest.raises(ValidationError):
            update_ticket_status(
                q,
                "T-SM-2",
                "done",  # illegal: todo → done
                reason="skip",
                actor="builder",
            )

        # File must be unchanged + parseable
        from server.ssot import read_queue

        data = read_queue(q)
        ticket = next(x for x in data["tickets"] if x["id"] == "T-SM-2")
        assert ticket["status"] == "todo"

    def test_override_still_works(self, tmp_path):
        q = self._queue_path(tmp_path)
        t = _make_ticket("T-SM-3", "done")
        _make_queue(q, [t])

        update_ticket_status(
            q,
            "T-SM-3",
            "todo",
            reason="reopening",
            actor="pm",
            override=True,
        )

        from server.ssot import read_queue

        data = read_queue(q)
        ticket = next(x for x in data["tickets"] if x["id"] == "T-SM-3")
        assert ticket["status"] == "todo"
        assert any(e.get("override") for e in ticket.get("_transition_history", []))


# ---------------------------------------------------------------------------
# DOD 6 — BLOCKER-1: mtime-based freshness (no ARCHIVE.yaml parse on index hit)
# ---------------------------------------------------------------------------


class TestMtimeFreshness:
    """find_archived_ticket with a valid, fresh index must not parse ARCHIVE.yaml."""

    def _make_archive(self, archive_path: Path, tickets: list[dict]) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
            encoding="utf-8",
        )

    def _count_archive_read_text_calls(
        self, archive_path: Path, ticket_id: str
    ) -> tuple[object, int]:
        """Call find_archived_ticket and count how many times ARCHIVE.yaml's
        read_text is invoked (distinct from index reads).

        Strategy: patch ``Path.read_text`` at the class level, counting calls
        whose resolved path matches archive_path.
        """
        import pathlib

        archive_read_count = [0]
        real_read_text = pathlib.Path.read_text

        def counting_read_text(self_path, encoding="utf-8"):
            if Path(self_path).resolve() == archive_path.resolve():
                archive_read_count[0] += 1
            return real_read_text(self_path, encoding=encoding)

        with patch.object(pathlib.Path, "read_text", counting_read_text):
            result = find_archived_ticket(archive_path, ticket_id)

        return result, archive_read_count[0]

    def test_index_hit_no_archive_parse(self, tmp_path):
        """Fresh index + matching mtime: ARCHIVE.yaml must be read at most once
        (the final ticket-dict lookup) — NOT twice (old code: stale-detection
        read + final lookup).

        Verifies BLOCKER-1 fix: the old stale-detection always called
        yaml.safe_load(archive_path.read_text()) unconditionally; the new mtime
        path skips the extra read when the index is current.
        """
        archive_path = tmp_path / "ARCHIVE.yaml"
        ticket = _make_ticket("T-FRESH")
        self._make_archive(archive_path, [ticket])
        build_archive_index(archive_path)

        result, read_count = self._count_archive_read_text_calls(archive_path, "T-FRESH")

        assert result is not None
        assert result["id"] == "T-FRESH"
        # Exactly 1 read: the final ticket dict lookup.
        # The old code did 2: one unconditional stale-detection + one final lookup.
        assert read_count == 1, (
            f"ARCHIVE.yaml was read {read_count} time(s); expected exactly 1 "
            "(stale-detection must use stat()/mtime, not a full file read)"
        )

    def test_index_miss_no_archive_full_parse(self, tmp_path):
        """Fresh index + ticket NOT present: ARCHIVE.yaml must not be read at all."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        ticket = _make_ticket("T-EXISTS")
        self._make_archive(archive_path, [ticket])
        build_archive_index(archive_path)

        result, read_count = self._count_archive_read_text_calls(archive_path, "T-GHOST")

        assert result is None
        assert read_count == 0, (
            "ARCHIVE.yaml must NOT be read when ticket is absent from a fresh index "
            f"(got {read_count} read(s))"
        )

    def test_mtime_change_triggers_rebuild(self, tmp_path):
        """After ARCHIVE.yaml is modified, mtime mismatch triggers rebuild and lookup succeeds."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        t_old = _make_ticket("T-V1")
        self._make_archive(archive_path, [t_old])
        build_archive_index(archive_path)

        # Verify initial state
        result = find_archived_ticket(archive_path, "T-V1")
        assert result is not None

        # Modify archive (add a new ticket) — mtime changes
        t_new = _make_ticket("T-V2")
        self._make_archive(archive_path, [t_old, t_new])

        # Lookup the newly added ticket — must trigger rebuild and succeed
        result = find_archived_ticket(archive_path, "T-V2")
        assert result is not None
        assert result["id"] == "T-V2"

    def test_mtime_change_emits_warning(self, tmp_path, capsys):
        """Mtime mismatch must emit a warning to stderr before rebuilding."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        ticket = _make_ticket("T-WARN")
        self._make_archive(archive_path, [ticket])
        build_archive_index(archive_path)

        # Overwrite archive to change mtime
        self._make_archive(archive_path, [ticket, _make_ticket("T-WARN2")])

        find_archived_ticket(archive_path, "T-WARN")

        captured = capsys.readouterr()
        assert "mtime" in captured.err.lower() or "stale" in captured.err.lower()

    def test_index_stores_mtime_ns(self, tmp_path):
        """build_archive_index must embed __mtime_ns__ in the written index."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        self._make_archive(archive_path, [_make_ticket("T-MNS")])
        build_archive_index(archive_path)

        idx_path = index_path_for_archive(archive_path)
        index = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
        assert ARCHIVE_INDEX_MTIME_KEY in index
        stored_mtime = index[ARCHIVE_INDEX_MTIME_KEY]
        actual_mtime = archive_path.stat().st_mtime_ns
        assert stored_mtime == actual_mtime, (
            f"Stored mtime {stored_mtime} != actual {actual_mtime}"
        )


# ---------------------------------------------------------------------------
# DOD 7 — BLOCKER-2: stale-rebuild uses .archive-index.lock, never .archive.lock
# ---------------------------------------------------------------------------


class TestIndexRebuildLock:
    """Stale-index rebuild must not touch the dispatcher sentinel .archive.lock."""

    def _make_archive(self, archive_path: Path, tickets: list[dict]) -> None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
            encoding="utf-8",
        )

    def test_stale_rebuild_does_not_create_archive_lock(self, tmp_path):
        """Stale-detection rebuild must NOT create or touch .archive.lock.

        Verifies BLOCKER-2 fix: the old code called acquire_file_lock(archive_path)
        which resolved to .archive.lock (the dispatcher sentinel).  The new code
        uses _rebuild_archive_index_locked which uses .archive-index.lock.
        """
        archive_path = tmp_path / "ARCHIVE.yaml"
        t1 = _make_ticket("T-SENTINEL")
        self._make_archive(archive_path, [t1])

        # Write a stale index (no __mtime_ns__ → mtime mismatch on first stat)
        idx_path = index_path_for_archive(archive_path)
        idx_path.write_text(
            yaml.safe_dump({"T-SENTINEL": 1}, sort_keys=False),
            encoding="utf-8",
        )

        archive_lock = archive_path.parent / ARCHIVE_LOCK_FILE_NAME
        assert not archive_lock.exists(), "precondition: .archive.lock must be absent"

        # Trigger stale-detection rebuild via find_archived_ticket
        find_archived_ticket(archive_path, "T-SENTINEL")

        assert not archive_lock.exists(), (
            ".archive.lock must NOT be created during index rebuild "
            "(dispatcher sentinel must remain clean)"
        )

    def test_stale_rebuild_creates_index_lock_not_archive_lock(self, tmp_path):
        """The rebuild must use .archive-index.lock (different file from sentinel)."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        self._make_archive(archive_path, [_make_ticket("T-IDX-LOCK")])

        # Stale index (no mtime key)
        idx_path = index_path_for_archive(archive_path)
        idx_path.write_text(yaml.safe_dump({"T-IDX-LOCK": 1}), encoding="utf-8")

        archive_lock = archive_path.parent / ARCHIVE_LOCK_FILE_NAME
        index_lock = archive_path.parent / ARCHIVE_INDEX_LOCK_FILE_NAME

        assert not archive_lock.exists()
        # Index lock path is consistent with constant
        assert index_lock == _archive_index_lock_path(archive_path)

        find_archived_ticket(archive_path, "T-IDX-LOCK")

        # Sentinel must be untouched
        assert not archive_lock.exists(), ".archive.lock sentinel must not be created"

    def test_archive_lock_exists_returns_false_during_index_rebuild(self, tmp_path):
        """archive_lock_exists() must return False while index rebuild is running.

        This proves concurrent dispatch would NOT raise ArchiveLockError during a
        stale-detection rebuild (the dispatcher sentinel is clean).
        """
        from server.ssot import archive_path_for_queue

        queue_path = tmp_path / "QUEUE.yaml"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": []}, sort_keys=False),
            encoding="utf-8",
        )
        archive_path = archive_path_for_queue(queue_path)
        self._make_archive(archive_path, [_make_ticket("T-DISP")])

        # Stale index
        idx_path = index_path_for_archive(archive_path)
        idx_path.write_text(yaml.safe_dump({"T-DISP": 1}), encoding="utf-8")

        sentinel_seen_during_rebuild: list[bool] = []

        real_build = ssot_module.build_archive_index

        def spying_build(ap):
            # During rebuild, the dispatcher sentinel must NOT be present.
            sentinel_seen_during_rebuild.append(
                (archive_path.parent / ARCHIVE_LOCK_FILE_NAME).exists()
            )
            return real_build(ap)

        with patch.object(ssot_module, "build_archive_index", side_effect=spying_build):
            find_archived_ticket(archive_path, "T-DISP")

        assert len(sentinel_seen_during_rebuild) > 0, "spy was not called"
        assert not any(sentinel_seen_during_rebuild), (
            "dispatcher sentinel (.archive.lock) was present during index rebuild — "
            "concurrent dispatch would have been incorrectly rejected"
        )

    def test_missing_index_rebuild_also_uses_index_lock(self, tmp_path):
        """Missing-index branch (not just stale-branch) must also use .archive-index.lock."""
        archive_path = tmp_path / "ARCHIVE.yaml"
        self._make_archive(archive_path, [_make_ticket("T-MISS-IDX")])
        # No index file

        archive_lock = archive_path.parent / ARCHIVE_LOCK_FILE_NAME

        find_archived_ticket(archive_path, "T-MISS-IDX")

        assert not archive_lock.exists(), (
            ".archive.lock must not be created during missing-index rebuild"
        )


# ---------------------------------------------------------------------------
# DOD 6+7 — OS3_ALLOW_NO_LOCK case-insensitive (W1)
# ---------------------------------------------------------------------------


class TestNoLockCaseInsensitive:
    """OS3_ALLOW_NO_LOCK must accept TRUE/True/YES/on in addition to 1/true/yes."""

    @pytest.mark.parametrize("value", ["TRUE", "True", "YES", "on", "ON", "On"])
    def test_truthy_variants_allow_no_lock(self, tmp_path, value, monkeypatch):
        """All common truthy spellings must enable no-lock mode without raising."""
        queue_path = tmp_path / "QUEUE.yaml"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": []}, sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setattr(ssot_module, "fcntl", None)
        monkeypatch.setenv("OS3_ALLOW_NO_LOCK", value)

        executed = []
        with acquire_file_lock(queue_path, actor="test"):
            executed.append(True)

        assert executed == [True], f"OS3_ALLOW_NO_LOCK={value!r} did not bypass lock"

    @pytest.mark.parametrize("value", ["FALSE", "false", "0", "no", "NO", "off", "OFF", ""])
    def test_falsy_variants_still_raise(self, tmp_path, value, monkeypatch):
        """Falsy variants must still raise LockUnavailableError."""
        queue_path = tmp_path / "QUEUE.yaml"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(
            yaml.safe_dump({"version": "3.0", "tickets": []}, sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setattr(ssot_module, "fcntl", None)
        monkeypatch.setenv("OS3_ALLOW_NO_LOCK", value)

        with pytest.raises(LockUnavailableError):
            with acquire_file_lock(queue_path, actor="test"):
                pass

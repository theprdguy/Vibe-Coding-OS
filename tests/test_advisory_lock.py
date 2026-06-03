from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest
import yaml

from server import ssot
from server.ssot import (
    LockTimeoutError,
    acquire_file_lock,
    archive_done_tickets,
    archive_path_for_queue,
    read_queue,
    update_ticket_status,
)


def _write_queue(path: Path, tickets: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )


def _ticket(ticket_id: str, status: str) -> dict:
    return {
        "id": ticket_id,
        "owner": "CODEX",
        "status": status,
        "goal": f"{ticket_id} goal",
        "files": ["server/ssot.py"],
        "verify": "python3 -m pytest tests/test_advisory_lock.py -v",
        "deps": [],
    }


def _hold_lock(path: str, ready: multiprocessing.Queue, release: multiprocessing.Queue) -> None:
    with acquire_file_lock(Path(path), timeout=1.0, actor="holder"):
        ready.put("locked")
        release.get(timeout=5)


def _update_status(path: str, result: multiprocessing.Queue) -> None:
    os.environ["OS3_FILE_LOCK_TIMEOUT"] = "0.2"
    try:
        updated = update_ticket_status(
            Path(path),
            "T-RACE",
            "doing",
            reason="race attempt",
            actor="contender",
        )
        result.put(("ok", updated))
    except Exception as exc:  # pragma: no cover - assertion happens in parent process
        result.put((type(exc).__name__, str(exc)))


def test_single_writer_updates_status_and_releases_lock(tmp_path: Path) -> None:
    queue_path = tmp_path / "devos/tasks/QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-SINGLE", "todo")])

    assert update_ticket_status(
        queue_path,
        "T-SINGLE",
        "doing",
        reason="dispatch started",
        actor="dispatcher",
    )

    ticket = read_queue(queue_path)["tickets"][0]
    assert ticket["status"] == "doing"
    with acquire_file_lock(queue_path, timeout=0.1, actor="test"):
        assert queue_path.with_name(".QUEUE.yaml.lock").exists()
    with acquire_file_lock(queue_path, timeout=0.1, actor="test-after-release"):
        assert queue_path.with_name(".QUEUE.yaml.lock").exists()


def test_concurrent_process_writer_times_out_with_debug_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue_path = tmp_path / "devos/tasks/QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-RACE", "todo")])
    ready: multiprocessing.Queue = multiprocessing.Queue()
    release: multiprocessing.Queue = multiprocessing.Queue()
    result: multiprocessing.Queue = multiprocessing.Queue()

    holder = multiprocessing.Process(target=_hold_lock, args=(str(queue_path), ready, release))
    holder.start()
    assert ready.get(timeout=5) == "locked"

    try:
        contender = multiprocessing.Process(target=_update_status, args=(str(queue_path), result))
        contender.start()
        kind, detail = result.get(timeout=5)
        contender.join(timeout=5)
    finally:
        release.put("release")
        holder.join(timeout=5)

    assert kind == "LockTimeoutError"
    assert "timed out acquiring file lock" in detail
    assert read_queue(queue_path)["tickets"][0]["status"] == "todo"


def test_lock_timeout_reports_retry_count_and_actor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-TIMEOUT", "todo")])

    with acquire_file_lock(queue_path, timeout=0.5, actor="holder"):
        with pytest.raises(LockTimeoutError, match="timed out acquiring file lock"):
            with acquire_file_lock(
                queue_path,
                timeout=0.05,
                retry_interval=0.01,
                actor="contender",
            ):
                raise AssertionError("lock should not be acquired")

    stderr = capsys.readouterr().err
    assert "file lock busy" in stderr
    assert "retry=1" in stderr
    assert "actor=contender" in stderr


def test_lock_releases_after_exception_to_prevent_deadlock(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-DEADLOCK", "todo")])

    with pytest.raises(RuntimeError, match="boom"):
        with acquire_file_lock(queue_path, timeout=0.1, actor="test"):
            raise RuntimeError("boom")

    with acquire_file_lock(queue_path, timeout=0.1, actor="test"):
        assert queue_path.with_name(".QUEUE.yaml.lock").exists()


def test_fcntl_unavailable_warns_skips_lock_and_still_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """With OS3_ALLOW_NO_LOCK=1 the update proceeds with a warning (opt-in mode)."""
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-FALLBACK", "todo")])
    monkeypatch.setattr(ssot, "fcntl", None)
    monkeypatch.setenv("OS3_ALLOW_NO_LOCK", "1")

    assert update_ticket_status(
        queue_path,
        "T-FALLBACK",
        "doing",
        reason="windows fallback",
        actor="dispatcher",
    )

    stderr = capsys.readouterr().err
    assert "OS3_ALLOW_NO_LOCK" in stderr
    assert read_queue(queue_path)["tickets"][0]["status"] == "doing"


def test_archive_done_tickets_locks_queue_and_archive_then_releases(tmp_path: Path) -> None:
    queue_path = tmp_path / "devos/tasks/QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-DONE", "done"), _ticket("T-TODO", "todo")])

    moved, skipped = archive_done_tickets(queue_path)

    assert (moved, skipped) == (1, [])
    assert [ticket["id"] for ticket in read_queue(queue_path)["tickets"]] == ["T-TODO"]
    assert [ticket["id"] for ticket in read_queue(archive_path_for_queue(queue_path))["tickets"]] == [
        "T-DONE"
    ]
    with acquire_file_lock(queue_path, timeout=0.1, actor="post-archive"):
        assert queue_path.with_name(".QUEUE.yaml.lock").exists()
    assert not queue_path.with_name(".archive.lock").exists()


def test_retry_after_lock_release_succeeds(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    _write_queue(queue_path, [_ticket("T-RETRY", "todo")])

    with acquire_file_lock(queue_path, timeout=0.1, actor="first"):
        pass

    with acquire_file_lock(queue_path, timeout=0.1, actor="second"):
        assert queue_path.with_name(".QUEUE.yaml.lock").exists()

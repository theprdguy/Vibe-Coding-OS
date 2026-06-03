from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from server import dispatcher as dispatcher_module
from server.dispatcher import (
    DISPATCHER_LOCK_OVERRIDE_ENV,
    DispatcherSingletonError,
    acquire_dispatcher_singleton,
    dispatcher_lock_path,
)


def _paths(root: Path) -> dict:
    return {"root": root, "devos": root / "devos"}


def test_single_dispatcher_acquires_and_releases_pid_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "dispatcher.pid"
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(lock_path))

    with acquire_dispatcher_singleton({}, _paths(tmp_path)) as lock:
        assert lock.acquired is True
        assert lock_path.exists()
        assert f"pid={os.getpid()}" in lock_path.read_text(encoding="utf-8")
        assert "started=" in lock_path.read_text(encoding="utf-8")

    assert not lock_path.exists()


def test_second_dispatcher_instance_is_rejected_with_holder_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "dispatcher.pid"
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(lock_path))

    with acquire_dispatcher_singleton({}, _paths(tmp_path)):
        with pytest.raises(DispatcherSingletonError) as excinfo:
            with acquire_dispatcher_singleton({}, _paths(tmp_path)):
                raise AssertionError("second instance should not acquire")

    message = str(excinfo.value)
    assert message.startswith(f"[dispatcher] another instance is running (PID {os.getpid()}, started ")
    assert excinfo.value.exit_code == 1


def test_stale_dispatcher_lock_reports_manual_removal_guide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "dispatcher.pid"
    lock_path.write_text("pid=999999\nstarted=2026-04-30T01:02:03+00:00\n", encoding="utf-8")
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(lock_path))
    monkeypatch.setattr(dispatcher_module, "_pid_is_running", lambda pid: False)

    with pytest.raises(DispatcherSingletonError) as excinfo:
        with acquire_dispatcher_singleton({}, _paths(tmp_path)):
            raise AssertionError("stale lock must require manual removal")

    message = str(excinfo.value)
    assert "[dispatcher] stale dispatcher lock found" in message
    assert "PID 999999" in message
    assert "rm " in message
    assert str(lock_path) in message
    assert lock_path.exists()


def test_fcntl_unavailable_skips_singleton_with_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lock_path = tmp_path / "dispatcher.pid"
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(lock_path))
    monkeypatch.setattr(dispatcher_module, "fcntl", None)

    with acquire_dispatcher_singleton({}, _paths(tmp_path)) as lock:
        assert lock.acquired is False

    assert not lock_path.exists()
    assert "fcntl unavailable; skipping dispatcher singleton lock" in capsys.readouterr().err


def test_lock_path_override_env_wins_over_project_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom" / "dispatcher.pid"
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(override))

    assert dispatcher_lock_path({"project": {"name": "ignored"}}, _paths(tmp_path)) == override


def test_case_variant_project_paths_map_to_same_default_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(DISPATCHER_LOCK_OVERRIDE_ENV, raising=False)

    upper = dispatcher_lock_path({}, _paths(Path("/tmp/fake-host/Desktop/thePRD/02.meta/OS3")))
    lower = dispatcher_lock_path({}, _paths(Path("/tmp/fake-host/desktop/theprd/02.meta/os3")))

    assert upper == lower
    assert upper == home / ".os3" / "dispatcher.os3.pid"


def test_cli_rejects_second_dispatch_instance_before_agent_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock_path = tmp_path / "dispatcher.pid"
    monkeypatch.setenv(DISPATCHER_LOCK_OVERRIDE_ENV, str(lock_path))

    with acquire_dispatcher_singleton({}, _paths(tmp_path)):
        result = subprocess.run(
            [sys.executable, "-m", "server", "dispatch-all"],
            cwd=Path.cwd(),
            env={**os.environ, DISPATCHER_LOCK_OVERRIDE_ENV: str(lock_path)},
            text=True,
            capture_output=True,
            check=False,
        )

    assert result.returncode == 1
    assert f"[dispatcher] another instance is running (PID {os.getpid()}, started " in result.stderr

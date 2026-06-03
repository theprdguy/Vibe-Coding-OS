from __future__ import annotations

import subprocess
from pathlib import Path

from server.dispatcher import Dispatcher


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    snapshot = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return tracked, snapshot


def _dispatcher(root: Path) -> Dispatcher:
    return Dispatcher(
        config={"agents": {}},
        paths={
            "root": root,
            "queue": root / "devos/tasks/QUEUE.yaml",
            "logs": root / "devos/logs",
            "plans": root / "devos/plans",
        },
    )


def _failure_for(root: Path, files: list[str], snapshot: str) -> dict | None:
    return _dispatcher(root)._detect_no_ticket_file_diff(
        {"id": "T-NO-DIFF", "files": files},
        {
            "stdout": "Done: T-NO-DIFF\nNext: waiting\nBlock: none\n",
            "stderr": "",
            "returncode": 0,
        },
        snapshot,
    )


def test_untracked_ticket_file_counts_as_diff(tmp_path: Path) -> None:
    _tracked, snapshot = _init_repo(tmp_path)
    (tmp_path / "new_test.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")

    assert _failure_for(tmp_path, ["new_test.py"], snapshot) is None


def test_no_ticket_file_changes_returns_synthetic_failure(tmp_path: Path) -> None:
    _tracked, snapshot = _init_repo(tmp_path)

    failure = _failure_for(tmp_path, ["tracked.txt"], snapshot)

    assert failure == {
        "reason": (
            "agent_runtime_failure: subprocess returned 0 but produced no diff "
            "— check session log"
        ),
        "stdout": "Done: T-NO-DIFF\nNext: waiting\nBlock: none\n",
        "stderr": "",
        "returncode": 0,
    }


def test_tracked_ticket_file_modify_counts_as_diff(tmp_path: Path) -> None:
    tracked, snapshot = _init_repo(tmp_path)
    tracked.write_text("after\n", encoding="utf-8")

    assert _failure_for(tmp_path, ["tracked.txt"], snapshot) is None


def test_mixed_untracked_and_modified_ticket_files_count_as_diff(tmp_path: Path) -> None:
    tracked, snapshot = _init_repo(tmp_path)
    tracked.write_text("after\n", encoding="utf-8")
    (tmp_path / "new_test.py").write_text("def test_new():\n    assert True\n", encoding="utf-8")

    assert _failure_for(tmp_path, ["tracked.txt", "new_test.py"], snapshot) is None

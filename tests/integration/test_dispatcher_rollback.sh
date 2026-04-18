#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 - <<'PY'
import io
import logging
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from server.dispatcher import Dispatcher


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def make_dispatcher(repo: Path) -> Dispatcher:
    return Dispatcher(
        config={"agents": {}},
        paths={
            "root": repo,
            "queue": repo / "devos/tasks/QUEUE.yaml",
            "logs": repo / "devos/logs",
        },
    )


def create_repo(name: str) -> Path:
    repo = Path(tempfile.mkdtemp(prefix=f"{name}-"))
    (repo / "devos/tasks").mkdir(parents=True)
    (repo / "devos/logs").mkdir(parents=True)
    (repo / "bar.py").write_text("print('baseline')\n")
    (repo / "good.py").write_text("print('good baseline')\n")
    (repo / "devos/tasks/QUEUE.yaml").write_text("version: '3.0'\ntickets: []\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    return repo


def test_tracked_restore_untracked_delete_and_scope_protection() -> None:
    repo = create_repo("rollback-scope")
    dispatcher = make_dispatcher(repo)

    (repo / "bar.py").write_text("print('modified')\n")
    (repo / "foo.py").write_text("print('temp file')\n")
    (repo / ".env").write_text("SECRET=keep\n")

    ok = dispatcher._rollback_retry_files("T-ROLLBACK-1", ["bar.py", "foo.py"])

    assert ok is True
    assert (repo / "bar.py").read_text() == "print('baseline')\n"
    assert not (repo / "foo.py").exists()
    assert (repo / ".env").exists()
    assert git(repo, "status", "--short", "--", "bar.py", "foo.py").stdout.strip() == ""


def test_missing_scope_file_does_not_abort_cleanup() -> None:
    repo = create_repo("rollback-missing")
    dispatcher = make_dispatcher(repo)

    (repo / "foo.py").write_text("print('temp file')\n")

    ok = dispatcher._rollback_retry_files("T-ROLLBACK-2", ["foo.py", "scripts/check-contract-sync.sh"])

    assert ok is True
    assert not (repo / "foo.py").exists()


def test_partial_failure_continues_and_logs_failed_files() -> None:
    repo = create_repo("rollback-partial")
    dispatcher = make_dispatcher(repo)

    (repo / "good.py").write_text("print('good modified')\n")
    (repo / "bad.py").write_text("print('bad temp')\n")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("server.dispatcher")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[:3] == ["git", "clean", "-f"] and cmd[-1] == "bad.py":
            return subprocess.CompletedProcess(cmd, 1, "", "simulated clean failure")
        return real_run(cmd, *args, **kwargs)

    try:
        with mock.patch("server.dispatcher.subprocess.run", side_effect=fake_run):
            ok = dispatcher._rollback_retry_files("T-ROLLBACK-3", ["good.py", "bad.py"])
    finally:
        logger.removeHandler(handler)

    logs = stream.getvalue()
    assert ok is False
    assert (repo / "good.py").read_text() == "print('good baseline')\n"
    assert (repo / "bad.py").exists()
    assert "bad.py" in logs


test_tracked_restore_untracked_delete_and_scope_protection()
test_missing_scope_file_does_not_abort_cleanup()
test_partial_failure_continues_and_logs_failed_files()
print("PASS: dispatcher rollback integration")
PY

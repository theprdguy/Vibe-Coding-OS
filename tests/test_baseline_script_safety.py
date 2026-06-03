from __future__ import annotations

import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "baseline-test.sh"
PASSING_TEST = "tests/test_reviewer_no_destructive_git.py"

FORBIDDEN_SNIPPETS = [
    "git stash",
    "git reset --hard",
    "git checkout HEAD --",
    "git clean -fd",
    "git restore --worktree",
    "git restore --staged",
]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _run_baseline(*pytest_args: str, tmp_parent: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["OS3_BASELINE_TMP_PARENT"] = str(tmp_parent)
    return subprocess.run(
        [str(SCRIPT), *pytest_args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_baseline_script_exists_is_executable_and_uses_bash_strict_mode() -> None:
    assert SCRIPT.exists(), f"missing {SCRIPT}"
    assert SCRIPT.stat().st_mode & stat.S_IXUSR, f"{SCRIPT} must be chmod +x"

    lines = _script_text().splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in lines


def test_baseline_script_uses_worktree_cleanup_trap_and_no_forbidden_git() -> None:
    text = _script_text()

    assert "git worktree add" in text
    assert "trap" in text and "EXIT" in text
    assert "INT" in text and "TERM" in text

    for snippet in FORBIDDEN_SNIPPETS:
        assert snippet not in text, f"{SCRIPT} must not contain {snippet!r}"


def test_baseline_script_runs_passing_pytest_in_temp_worktree_without_reverting_dirty_tree(
    tmp_path: Path,
) -> None:
    sentinel = PROJECT_ROOT / f".baseline-test-sentinel-{os.getpid()}"
    sentinel.write_text("dirty sentinel\n", encoding="utf-8")
    before_status = _git("status", "--porcelain")

    try:
        result = _run_baseline(PASSING_TEST, "-q", tmp_parent=tmp_path)
        after_status = _git("status", "--porcelain")

        assert result.returncode == 0, result.stdout + result.stderr
        assert sentinel.exists(), "baseline script must not remove untracked caller files"
        assert after_status == before_status, (
            "baseline script changed the caller working tree status\n"
            f"before:\n{before_status}\nafter:\n{after_status}"
        )
        assert not list(tmp_path.glob("os3-baseline-*"))
    finally:
        sentinel.unlink(missing_ok=True)


def test_baseline_script_cleans_worktree_after_pytest_nonzero_exit(tmp_path: Path) -> None:
    result = _run_baseline(
        PASSING_TEST,
        "--definitely-not-a-pytest-option",
        tmp_parent=tmp_path,
    )

    assert result.returncode == 4, result.stdout + result.stderr
    assert not list(tmp_path.glob("os3-baseline-*"))


def test_baseline_script_cleans_worktree_on_sigint(tmp_path: Path) -> None:
    marker = tmp_path / "pytest-started"
    plugin = tmp_path / "os3_slow_pytest_plugin.py"
    plugin.write_text(
        "import time\n"
        "from pathlib import Path\n"
        f"MARKER = Path({str(marker)!r})\n"
        "def pytest_sessionstart(session):\n"
        "    MARKER.write_text('started', encoding='utf-8')\n"
        "    time.sleep(30)\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["OS3_BASELINE_TMP_PARENT"] = str(tmp_path)
    env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["PYTEST_ADDOPTS"] = "-p os3_slow_pytest_plugin"

    process = subprocess.Popen(
        [str(SCRIPT), PASSING_TEST, "-q"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if marker.exists():
                break
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"baseline script exited before SIGINT setup; code={process.returncode}\n"
                    f"stdout:\n{stdout}\nstderr:\n{stderr}"
                )
            time.sleep(0.1)
        else:
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            raise AssertionError(
                "baseline script did not start pytest before SIGINT deadline\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )

        os.killpg(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=20)

        assert process.returncode not in (0, None), stdout + stderr
        assert not list(tmp_path.glob("os3-baseline-*"))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
BIN_OS3 = REPO / "bin" / "deos"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    path.chmod(0o755)


def _make_host(tmp_path: Path) -> Path:
    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "scripts").mkdir()
    (host / "deos.yaml").write_text("project: host\n", encoding="utf-8")
    for index, script in enumerate(
        [
            "check-contract-sync.sh",
            "check-ticket-scope.sh",
            "check-session-log.sh",
            "check-tdd-first-commit.sh",
        ],
        start=2,
    ):
        _write_executable(
            host / "scripts" / script,
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            printf '[{index}/5] {script}\\n'
            printf '%s\\n' "$PWD" >> "$SCRIPT_CWD_LOG"
            printf 'PASS {script}\\n'
            """,
        )
    return host


def _make_project(host: Path, name: str, *, with_commit: bool = False) -> Path:
    project = host / "projects" / name
    (project / "devos" / "tasks").mkdir(parents=True)
    (project / "devos" / "logs").mkdir(parents=True)
    (project / ".deos.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (project / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    (project / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=project, check=True
    )
    if with_commit:
        (project / "README.md").write_text("# project\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-qm", "baseline"], cwd=project, check=True)
    return project


def _write_gitleaks_stub(bin_dir: Path) -> None:
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "gitleaks",
        """
        #!/usr/bin/env bash
        set -euo pipefail

        mode="${1:-}"
        shift || true
        target="${@: -1}"
        if [ -z "$target" ]; then
          target="."
        fi
        if [[ "$target" != /* ]]; then
          target="$PWD/$target"
        fi
        target="$(cd "$target" && pwd)"
        printf '%s|%s|%s\\n' "$mode" "$PWD" "$target" >> "$GITLEAKS_LOG"

        if [ "$mode" = "git" ]; then
          if git -C "$target" rev-parse --verify HEAD >/dev/null 2>&1; then
            if git -C "$target" grep -n "SECRET_TEST_VALUE" $(git -C "$target" rev-list --all) >/dev/null 2>&1; then
              printf 'gitleaks git: secret detected\\n' >&2
              exit 1
            fi
          fi
          printf 'gitleaks git: clean\\n'
          exit 0
        fi

        if [ "$mode" = "dir" ]; then
          if grep -R "SECRET_TEST_VALUE" "$target" --exclude-dir=.git >/dev/null 2>&1; then
            printf 'gitleaks dir: secret detected\\n' >&2
            exit 1
          fi
          printf 'gitleaks dir: clean\\n'
          exit 0
        fi

        printf 'unexpected gitleaks mode: %s\\n' "$mode" >&2
        exit 2
        """,
    )


def _run_pr_check(host: Path, cwd: Path, *args: str, env_extra: dict[str, str] | None = None):
    env = {
        **os.environ,
        "PATH": f"{host / 'bin'}:{os.environ['PATH']}",
        "PYTHONPATH": str(REPO),
        "OS3_HOST_ROOT": str(host),
        "GITLEAKS_LOG": str(host / "gitleaks.log"),
        "SCRIPT_CWD_LOG": str(host / "script-cwd.log"),
        "PWD": str(cwd),
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(BIN_OS3), "pr-check", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_project_flag_scans_project_root_not_host_root(tmp_path):
    host = _make_host(tmp_path)
    _write_gitleaks_stub(host / "bin")
    project = _make_project(host, "clean")
    (host / "host-only-secret.txt").write_text("SECRET_TEST_VALUE\n", encoding="utf-8")

    result = _run_pr_check(host, host, "--project", "clean")

    assert result.returncode == 0, result.stdout + result.stderr
    gitleaks_log = (host / "gitleaks.log").read_text(encoding="utf-8")
    assert f"dir|{project}|{project}" in gitleaks_log
    assert str(host / "host-only-secret.txt") not in gitleaks_log
    script_cwds = (host / "script-cwd.log").read_text(encoding="utf-8").splitlines()
    assert script_cwds == [str(project)] * 4


def test_project_working_tree_secret_fails_pr_check(tmp_path):
    host = _make_host(tmp_path)
    _write_gitleaks_stub(host / "bin")
    project = _make_project(host, "worktree")
    (project / "uncommitted.txt").write_text("SECRET_TEST_VALUE\n", encoding="utf-8")

    result = _run_pr_check(host, host, "--project", "worktree")

    assert result.returncode != 0
    assert "gitleaks dir: secret detected" in result.stderr
    assert "FAIL scan-secrets" in result.stdout


def test_project_with_commits_scans_git_history(tmp_path):
    host = _make_host(tmp_path)
    _write_gitleaks_stub(host / "bin")
    project = _make_project(host, "history", with_commit=True)
    (project / "historical.txt").write_text("SECRET_TEST_VALUE\n", encoding="utf-8")
    subprocess.run(["git", "add", "historical.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "add historical secret"], cwd=project, check=True)
    (project / "historical.txt").unlink()
    subprocess.run(["git", "add", "historical.txt"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "remove historical secret"], cwd=project, check=True)

    result = _run_pr_check(host, host, "--project", "history")

    assert result.returncode != 0
    assert "gitleaks git: secret detected" in result.stderr
    gitleaks_log = (host / "gitleaks.log").read_text(encoding="utf-8")
    assert f"git|{project}|{project}" in gitleaks_log


def test_unresolved_project_fails_without_host_fallback_or_secret_scan(tmp_path):
    host = _make_host(tmp_path)
    _write_gitleaks_stub(host / "bin")
    outside = tmp_path / "outside"
    outside.mkdir()

    result = _run_pr_check(host, outside)

    assert result.returncode != 0
    assert "no project: pass --project <name> or run inside a project dir" in result.stderr
    assert not (host / "gitleaks.log").exists()


def test_host_root_pr_check_runs_git_mode_only_not_dir_mode(tmp_path):
    """root == host: gitleaks must run git mode only; dir mode must be skipped.

    DOD: host cwd + no --project flag => gitleaks.log contains git|... line and
    does NOT contain any dir|... line.  This directly covers the root == host
    branch in _run_gitleaks.
    """
    host = _make_host(tmp_path)
    _write_gitleaks_stub(host / "bin")
    # Initialise a git repo at host so git mode has a HEAD to scan.
    subprocess.run(["git", "init", "-q"], cwd=host, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=host, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=host, check=True)
    (host / "README.md").write_text("# host\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=host, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=host, check=True)

    # Run pr-check from host cwd with no --project flag (root == host path).
    result = _run_pr_check(host, host)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (host / "gitleaks.log").exists(), "gitleaks stub was never invoked"
    gitleaks_log = (host / "gitleaks.log").read_text(encoding="utf-8")

    lines = gitleaks_log.splitlines()
    modes_invoked = [line.split("|")[0] for line in lines if line]
    assert "git" in modes_invoked, f"Expected git mode call; log: {gitleaks_log!r}"
    assert "dir" not in modes_invoked, (
        f"dir mode must NOT be called for host root; log: {gitleaks_log!r}"
    )


def test_trapb_path_allowlist_independent_of_host_guard(tmp_path):
    """trap-b independent neutralisation: the .gitleaks.toml [[allowlists]] path
    rule must protect fixture files in dir mode even when root != host (i.e. the
    root == host guard is NOT active).

    Scenario: a project vendors a copy of the test fixture file
    (tests/test_gemini_dispatcher.py) that contains dummy credential strings.
    A dir-mode scan of that project must succeed (gitleaks exits 0) because the
    path-based allowlist in .gitleaks.toml covers it, independently of the
    root != host guard.

    This test uses the real gitleaks binary (if available) or skips gracefully.
    It exercises the actual .gitleaks.toml from the repo root so the allowlist
    coverage is real, not stubbed.
    """
    import shutil

    if not shutil.which("gitleaks"):
        import pytest
        pytest.skip("gitleaks binary not found; skipping real-binary allowlist test")

    # Build a minimal project with a vendored copy of the fixture file.
    project = tmp_path / "vendored-project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)

    # Copy the actual test_gemini_dispatcher.py into the project so it triggers
    # the same detections that the .gitleaksignore SHA-fingerprints cover in git
    # mode.  The dir-mode scan must pass via the .gitleaks.toml path allowlist.
    src = REPO / "tests" / "test_gemini_dispatcher.py"
    dst = tests_dir / "test_gemini_dispatcher.py"
    import shutil as _shutil
    _shutil.copy2(str(src), str(dst))

    result = subprocess.run(
        [
            "gitleaks",
            "dir",
            "--no-banner",
            "--redact",
            "--config", str(REPO / ".gitleaks.toml"),
            str(project),
        ],
        cwd=str(project),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, (
        f"gitleaks dir should pass with path allowlist active.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

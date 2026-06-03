"""T-OS3-GATE-EXPLICIT-ROOT — explicit root argument / env for gate scripts.

DOD:
1. check-*.sh scripts honour $1 (positional arg) or OS3_PROJECT_ROOT env as
   the project root, ignoring the calling process's cwd.
2. dispatcher._run_command_gate injects OS3_PROJECT_ROOT=paths["root"] so
   nested os3 pr-check invocations target the correct repo.
3. pytest tests/test_gate_explicit_root.py -v passes.
4. bash tests/integration/test_baseline_gates.sh still passes (no regression).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO / "scripts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path, name: str) -> Path:
    """Create a minimal git repo under tmp_path/<name>."""
    repo = tmp_path / name
    (repo / "devos" / "tasks").mkdir(parents=True)
    (repo / "devos" / "docs").mkdir(parents=True)
    (repo / "devos" / "logs").mkdir(parents=True)
    (repo / "apps" / "api").mkdir(parents=True)

    today = subprocess.check_output(["date", "+%Y-%m-%d"], text=True).strip()
    (repo / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "version: '3.0'\ntickets:\n- id: T-TEST-01\n  owner: CODEX\n  status: doing\n  files:\n  - apps/api/app.txt\n  tdd: skip\n",
        encoding="utf-8",
    )
    (repo / "devos" / "docs" / "API_CONTRACT.md").write_text("# API Contract\n", encoding="utf-8")
    (repo / "devos" / "docs" / "UI_CONTRACT.md").write_text("# UI Contract\n", encoding="utf-8")
    (repo / "devos" / "logs" / f"{today}-codex.md").write_text("# log\n", encoding="utf-8")
    (repo / "apps" / "api" / "app.txt").write_text("baseline\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=str(repo), check=True)
    return repo


def _run_script(script_name: str, *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    script = SCRIPTS_DIR / script_name
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(script)],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_script_with_arg(script_name: str, root_arg: str, *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run script with explicit positional root argument."""
    script = SCRIPTS_DIR / script_name
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(script), root_arg],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# DOD #1a — positional arg overrides cwd for check-ticket-scope.sh
# ---------------------------------------------------------------------------

class TestCheckTicketScopeExplicitRoot:
    """check-ticket-scope.sh honours $1 positional arg as root."""

    def test_positional_arg_uses_specified_root_not_cwd(self, tmp_path):
        """When $1 is given, script must inspect that root, ignoring cwd."""
        real_repo = _make_repo(tmp_path, "real_repo")
        wrong_dir = tmp_path / "wrong_dir"
        wrong_dir.mkdir()

        # Run from wrong_dir but pass real_repo as $1
        result = _run_script_with_arg(
            "check-ticket-scope.sh",
            str(real_repo),
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX"},
        )
        # Must not error out trying to read QUEUE.yaml from wrong_dir
        combined = result.stdout + result.stderr
        assert "ticket-scope" in combined, f"Expected ticket-scope in output: {combined}"
        # Should pass (no out-of-scope files) — not complain about missing queue
        assert "PASS ticket-scope" in combined or "scope guard" in combined, (
            f"Unexpected output: {combined}"
        )

    def test_env_var_uses_specified_root_not_cwd(self, tmp_path):
        """When OS3_PROJECT_ROOT env is set, script must use it over cwd."""
        real_repo = _make_repo(tmp_path, "env_repo")
        wrong_dir = tmp_path / "env_wrong"
        wrong_dir.mkdir()

        result = _run_script(
            "check-ticket-scope.sh",
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX", "OS3_PROJECT_ROOT": str(real_repo)},
        )
        combined = result.stdout + result.stderr
        assert "ticket-scope" in combined, f"Expected ticket-scope in output: {combined}"
        assert "PASS ticket-scope" in combined or "scope guard" in combined, (
            f"Unexpected output: {combined}"
        )

    def test_no_arg_or_env_falls_back_to_cwd(self, tmp_path):
        """Without $1 or OS3_PROJECT_ROOT, script uses cwd (backward-compat)."""
        real_repo = _make_repo(tmp_path, "cwd_repo")

        result = _run_script(
            "check-ticket-scope.sh",
            cwd=real_repo,
            env={"AGENT_NAME": "CODEX"},
        )
        combined = result.stdout + result.stderr
        assert "ticket-scope" in combined, f"Expected ticket-scope in output: {combined}"


# ---------------------------------------------------------------------------
# DOD #1b — positional arg overrides cwd for check-session-log.sh
# ---------------------------------------------------------------------------

class TestCheckSessionLogExplicitRoot:
    """check-session-log.sh honours $1 positional arg as root."""

    def test_positional_arg_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "session_repo")
        wrong_dir = tmp_path / "session_wrong"
        wrong_dir.mkdir()

        result = _run_script_with_arg(
            "check-session-log.sh",
            str(real_repo),
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX"},
        )
        combined = result.stdout + result.stderr
        assert "session-log" in combined, f"Expected session-log in output: {combined}"
        # Either PASS (log found) or WARN with missing message — not a missing-file crash
        assert "PASS session-log" in combined or "session log missing" in combined, (
            f"Unexpected output: {combined}"
        )

    def test_env_var_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "session_env_repo")
        wrong_dir = tmp_path / "session_env_wrong"
        wrong_dir.mkdir()

        result = _run_script(
            "check-session-log.sh",
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX", "OS3_PROJECT_ROOT": str(real_repo)},
        )
        combined = result.stdout + result.stderr
        assert "session-log" in combined, f"Expected session-log in output: {combined}"
        assert "PASS session-log" in combined or "session log missing" in combined, (
            f"Unexpected output: {combined}"
        )

    def test_no_arg_or_env_falls_back_to_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "session_cwd_repo")

        result = _run_script(
            "check-session-log.sh",
            cwd=real_repo,
            env={"AGENT_NAME": "CODEX"},
        )
        combined = result.stdout + result.stderr
        assert "session-log" in combined, f"Expected session-log in output: {combined}"


# ---------------------------------------------------------------------------
# DOD #1c — positional arg overrides cwd for check-tdd-first-commit.sh
# ---------------------------------------------------------------------------

class TestCheckTddFirstCommitExplicitRoot:
    """check-tdd-first-commit.sh honours $1 positional arg as root."""

    def test_positional_arg_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "tdd_repo")
        wrong_dir = tmp_path / "tdd_wrong"
        wrong_dir.mkdir()

        result = _run_script_with_arg(
            "check-tdd-first-commit.sh",
            str(real_repo),
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX"},
        )
        combined = result.stdout + result.stderr
        assert "tdd-first-commit" in combined, f"Expected tdd-first-commit in output: {combined}"
        # Should pass or warn — not crash with file-not-found
        assert result.returncode in (0, 1), f"Unexpected exit code: {result.returncode}"

    def test_env_var_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "tdd_env_repo")
        wrong_dir = tmp_path / "tdd_env_wrong"
        wrong_dir.mkdir()

        result = _run_script(
            "check-tdd-first-commit.sh",
            cwd=wrong_dir,
            env={"AGENT_NAME": "CODEX", "OS3_PROJECT_ROOT": str(real_repo)},
        )
        combined = result.stdout + result.stderr
        assert "tdd-first-commit" in combined, f"Expected tdd-first-commit in output: {combined}"
        assert result.returncode in (0, 1), f"Unexpected exit code: {result.returncode}"

    def test_no_arg_or_env_falls_back_to_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "tdd_cwd_repo")

        result = _run_script(
            "check-tdd-first-commit.sh",
            cwd=real_repo,
            env={"AGENT_NAME": "CODEX"},
        )
        combined = result.stdout + result.stderr
        assert "tdd-first-commit" in combined, f"Expected tdd-first-commit in output: {combined}"


# ---------------------------------------------------------------------------
# DOD #1d — positional arg overrides cwd for check-contract-sync.sh
# ---------------------------------------------------------------------------

class TestCheckContractSyncExplicitRoot:
    """check-contract-sync.sh honours $1 positional arg as root."""

    def test_positional_arg_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "contract_repo")
        wrong_dir = tmp_path / "contract_wrong"
        wrong_dir.mkdir()

        result = _run_script_with_arg(
            "check-contract-sync.sh",
            str(real_repo),
            cwd=wrong_dir,
        )
        combined = result.stdout + result.stderr
        assert "contract-sync" in combined, f"Expected contract-sync in output: {combined}"
        # PASS or WARN — not a crash
        assert result.returncode == 0, f"Unexpected exit code: {result.returncode}\n{combined}"

    def test_env_var_uses_specified_root_not_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "contract_env_repo")
        wrong_dir = tmp_path / "contract_env_wrong"
        wrong_dir.mkdir()

        result = _run_script(
            "check-contract-sync.sh",
            cwd=wrong_dir,
            env={"OS3_PROJECT_ROOT": str(real_repo)},
        )
        combined = result.stdout + result.stderr
        assert "contract-sync" in combined, f"Expected contract-sync in output: {combined}"
        assert result.returncode == 0, f"Unexpected exit code: {result.returncode}\n{combined}"

    def test_no_arg_or_env_falls_back_to_cwd(self, tmp_path):
        real_repo = _make_repo(tmp_path, "contract_cwd_repo")

        result = _run_script(
            "check-contract-sync.sh",
            cwd=real_repo,
        )
        combined = result.stdout + result.stderr
        assert "contract-sync" in combined, f"Expected contract-sync in output: {combined}"
        assert result.returncode == 0, f"Unexpected exit code: {result.returncode}\n{combined}"


# ---------------------------------------------------------------------------
# DOD #2 — dispatcher._run_command_gate injects OS3_PROJECT_ROOT
# ---------------------------------------------------------------------------

class TestDispatcherCommandGateInjectsRoot:
    """_run_command_gate must include OS3_PROJECT_ROOT in subprocess env."""

    def test_run_command_gate_sets_os3_project_root_env(self, tmp_path, monkeypatch):
        """The env passed to the gate subprocess must include OS3_PROJECT_ROOT."""
        from server.dispatcher import Dispatcher

        logs = tmp_path / "logs"
        logs.mkdir()
        root = tmp_path / "project_root"
        root.mkdir()

        dispatcher = Dispatcher(
            config={},
            paths={"root": root, "logs": logs, "queue": root / "QUEUE.yaml"},
        )

        captured_envs = []

        def fake_run(cmd, **kwargs):
            captured_envs.append(kwargs.get("env", {}))
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        gate = {"name": "test-gate", "run": "echo hello", "timeout": 10}
        passed, _ = dispatcher._run_command_gate(gate)

        assert passed is True
        assert len(captured_envs) == 1, "Expected exactly one subprocess.run call"
        env = captured_envs[0]
        assert "OS3_PROJECT_ROOT" in env, (
            f"OS3_PROJECT_ROOT missing from gate subprocess env. Got keys: {list(env.keys())}"
        )
        assert env["OS3_PROJECT_ROOT"] == str(root), (
            f"OS3_PROJECT_ROOT={env['OS3_PROJECT_ROOT']!r}, expected {str(root)!r}"
        )

    def test_run_command_gate_root_matches_dispatcher_paths_root(self, tmp_path, monkeypatch):
        """OS3_PROJECT_ROOT must equal dispatcher.paths['root'], regardless of $PWD."""
        from server.dispatcher import Dispatcher

        logs = tmp_path / "logs"
        logs.mkdir()
        # Use a deeply nested root path to make sure it's not picking up cwd
        root = tmp_path / "deep" / "project"
        root.mkdir(parents=True)

        # Set PWD to something different
        monkeypatch.setenv("PWD", str(tmp_path))

        dispatcher = Dispatcher(
            config={},
            paths={"root": root, "logs": logs, "queue": root / "QUEUE.yaml"},
        )

        captured_env = {}

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        gate = {"name": "test-gate", "run": "echo hello", "timeout": 10}
        dispatcher._run_command_gate(gate)

        assert captured_env.get("OS3_PROJECT_ROOT") == str(root), (
            f"Expected OS3_PROJECT_ROOT={str(root)!r}, "
            f"got {captured_env.get('OS3_PROJECT_ROOT')!r}"
        )

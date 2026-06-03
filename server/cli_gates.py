"""Gate-running handlers for the unified OS CLI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from server.config import ProjectResolutionError, host_root, resolve_project_root


def _invocation_cwd() -> Path:
    """Return the shell cwd from before server.cli's legacy auto-chdir."""
    pwd = os.environ.get("PWD", "")
    if pwd:
        try:
            candidate = Path(pwd).resolve()
        except OSError:
            candidate = None
        if candidate and candidate.is_dir():
            return candidate
    return Path.cwd().resolve()


def _resolve_pr_check_root(project: str | None) -> tuple[Path, Path]:
    host = host_root().resolve()
    cwd = _invocation_cwd()
    try:
        return resolve_project_root(project, cwd=cwd, host=host).resolve(), host
    except ProjectResolutionError:
        if project:
            raise
        if (cwd / "deos.yaml").is_file():
            return cwd.resolve(), host
        raise


def _has_git_commits(root: Path) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        ).returncode
        == 0
    )


def _run_gitleaks(root: Path, host: Path) -> bool:
    clean = True
    if _has_git_commits(root):
        if (
            subprocess.run(
                ["gitleaks", "git", "--no-banner", "--redact", str(root)],
                cwd=str(root),
                shell=False,
            ).returncode
            != 0
        ):
            clean = False

    # Preserve host-root compatibility: historically host pr-check scanned git
    # history only. Project/local roots need dir mode to catch uncommitted files.
    if root != host:
        if (
            subprocess.run(
                ["gitleaks", "dir", "--no-banner", "--redact", str(root)],
                cwd=str(root),
                shell=False,
            ).returncode
            != 0
        ):
            clean = False
    return clean


def handle_pr_check(args):
    """Run all baseline PR gates. Replaces `make pr-check`."""
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    try:
        cwd, host = _resolve_pr_check_root(getattr(args, "project", None))
    except ProjectResolutionError as exc:
        print(f"FAIL project-scope: {exc}", file=sys.stderr, flush=True)
        return 1

    scripts_dir = host / "scripts"
    status = 0

    print("[1/5] scan-secrets", flush=True)
    if not shutil.which("gitleaks"):
        print("FAIL scan-secrets: gitleaks not found. Install: brew install gitleaks", flush=True)
        status = 1
    elif not _run_gitleaks(cwd, host):
        print("FAIL scan-secrets", flush=True)
        status = 1
    else:
        print("PASS scan-secrets", flush=True)

    cwd_str = str(cwd)
    gate_env = {**os.environ, "OS3_PROJECT_ROOT": cwd_str}
    for script in [
        "check-contract-sync.sh",
        "check-ticket-scope.sh",
        "check-session-log.sh",
        "check-tdd-first-commit.sh",
    ]:
        if subprocess.run(
            ["bash", str(scripts_dir / script), cwd_str],
            cwd=cwd_str,
            env=gate_env,
            shell=False,
        ).returncode != 0:
            status = 1

    print("All baseline gates passed" if status == 0 else "Baseline gates failed", flush=True)
    return status

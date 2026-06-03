"""tests/test_verify_project_scope.py — Integration tests for os3 verify --project X.

DOD:
1. os3 verify --project X runs the ticket's verify command with cwd=project root (X).
2. os3 verify (no --project) uses host root — backward compat preserved.

Test strategy:
  - OS3_HOST_ROOT env var points config.host_root() at the tmp_path.
  - project dir lives at tmp_path/projects/<name> (host_root fallback path).
  - A verify command that `touch`es a relative sentinel file proves which cwd was used.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_OSN = PROJECT_ROOT / "bin" / "deos"


def _base_env(host_root: Path | None = None) -> dict:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    if host_root is not None:
        env["OS3_HOST_ROOT"] = str(host_root)
    return env


def _make_host(tmp_path: Path) -> Path:
    """Create a minimal host tree under tmp_path."""
    host_devos = tmp_path / "devos" / "tasks"
    host_devos.mkdir(parents=True)
    (host_devos / "QUEUE.yaml").write_text(yaml.safe_dump({"tickets": []}))
    (host_devos / "ARCHIVE.yaml").write_text(yaml.safe_dump({"tickets": []}))
    (tmp_path / "deos.yaml").write_text("project: host\n")
    return tmp_path


def _make_project(host: Path, project_name: str, verify_cmd: str) -> Path:
    """Create a project under host/projects/<name> with one ticket."""
    proj = host / "projects" / project_name
    devos = proj / "devos" / "tasks"
    devos.mkdir(parents=True)
    queue_data = {
        "tickets": [
            {
                "id": "T-SCOPE-TEST-01",
                "owner": "BUILDER",
                "status": "doing",
                "goal": "scope test",
                "verify": verify_cmd,
            }
        ]
    }
    (devos / "QUEUE.yaml").write_text(yaml.safe_dump(queue_data))
    (devos / "ARCHIVE.yaml").write_text(yaml.safe_dump({"tickets": []}))
    (proj / "deos.yaml").write_text(f"project: {project_name}\n")
    return proj


def _run(args: list[str], cwd: Path, host: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BIN_OSN), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=15,
        env=_base_env(host_root=host),
    )


# ---------------------------------------------------------------------------
# DOD 1: --project X runs verify with cwd = project root
# ---------------------------------------------------------------------------

def test_verify_project_scope_uses_project_cwd(tmp_path):
    """os3 verify --project X must run the ticket verify command with cwd=project root.

    Proof: the verify command creates a sentinel file with a relative path.
    If cwd is the project root the sentinel appears inside that project dir.
    """
    host = _make_host(tmp_path)
    proj_root = _make_project(host, "scope-proj", "touch .verify_sentinel")

    result = _run(
        ["verify", "--project", "scope-proj", "T-SCOPE-TEST-01"],
        cwd=host,
        host=host,
    )

    sentinel = proj_root / ".verify_sentinel"
    assert sentinel.exists(), (
        f"Sentinel not created at project root {sentinel}. "
        f"returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def test_verify_project_scope_sentinel_not_in_host(tmp_path):
    """Complementary: sentinel must NOT appear in host cwd when --project is used."""
    host = _make_host(tmp_path)
    _make_project(host, "scope-proj2", "touch .verify_sentinel")

    _run(
        ["verify", "--project", "scope-proj2", "T-SCOPE-TEST-01"],
        cwd=host,
        host=host,
    )

    host_sentinel = host / ".verify_sentinel"
    assert not host_sentinel.exists(), (
        f"Sentinel appeared in host cwd {host} — verify did NOT scope to project root!"
    )


# ---------------------------------------------------------------------------
# DOD 2: host verify (no --project) uses host root — backward compat
# ---------------------------------------------------------------------------

def test_verify_host_fallback_uses_host_cwd(tmp_path):
    """os3 verify (no --project) must run verify with cwd=host root."""
    host = _make_host(tmp_path)
    # Add a ticket directly in the host queue
    host_queue = host / "devos" / "tasks" / "QUEUE.yaml"
    queue_data = {
        "tickets": [
            {
                "id": "T-HOST-VERIFY-01",
                "owner": "BUILDER",
                "status": "doing",
                "goal": "host verify test",
                "verify": "touch .host_verify_sentinel",
            }
        ]
    }
    host_queue.write_text(yaml.safe_dump(queue_data))

    result = _run(["verify", "T-HOST-VERIFY-01"], cwd=host, host=host)

    sentinel = host / ".host_verify_sentinel"
    assert sentinel.exists(), (
        f"Host sentinel not created at {sentinel}. "
        f"returncode={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Edge: ticket not found prints error, exits nonzero
# ---------------------------------------------------------------------------

def test_verify_unknown_ticket_exits_nonzero(tmp_path):
    """os3 verify for a non-existent ticket must exit nonzero."""
    host = _make_host(tmp_path)

    result = _run(["verify", "T-NONEXIST-01"], cwd=host, host=host)

    assert result.returncode != 0, (
        f"Expected nonzero exit for unknown ticket, got 0. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

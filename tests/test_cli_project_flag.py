"""Phase 1 Task 5: `--project` flag selects the target project.

Targets the real CLI entry point (`server/cli.py` via `bin/os3`), not the
legacy `python3 -m server` path. Verifies project selection + back-compat
fallback when no project is selected.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from server.config import resolve_paths

REPO = Path(__file__).resolve().parent.parent  # engine/host root
BIN_OS3 = REPO / "bin" / "deos"


def _make_project(host_projects: Path, name: str):
    proj = host_projects / name
    (proj / "devos" / "tasks").mkdir(parents=True)
    (proj / ".deos.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (proj / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "tickets:\n  - id: T-PROJ-ONLY-01\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    (proj / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    return proj


# ── unit: resolve_paths ──────────────────────────────────────────────────────

def test_resolve_paths_by_project_name(tmp_path, monkeypatch):
    # Point host_root at a fake host with an osn.yaml + one project
    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    proj = _make_project(host / "projects", "meation")
    monkeypatch.setattr("server.config.host_root", lambda: host)

    config, paths = resolve_paths("meation", cwd=tmp_path)
    assert paths["root"] == proj
    assert paths["queue"] == proj / "devos/tasks/QUEUE.yaml"


def test_resolve_paths_legacy_fallback_when_no_project(tmp_path, monkeypatch):
    # No project name, no .os3.yaml marker -> legacy load_config() from cwd
    host = tmp_path / "dev-os"
    host.mkdir()
    monkeypatch.setattr("server.config.host_root", lambda: host)
    work = tmp_path / "work"
    work.mkdir()
    (work / "deos.yaml").write_text("project_root: '.'\n", encoding="utf-8")
    monkeypatch.chdir(work)

    config, paths = resolve_paths(None, cwd=work)
    assert str(paths["root"]) == "."  # legacy cwd-relative


# ── e2e: bin/os3 --project ───────────────────────────────────────────────────

def test_status_reads_named_project_queue(tmp_path):
    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _make_project(host / "projects", "meation")

    env = {**os.environ, "PYTHONPATH": str(REPO), "OS3_HOST_ROOT": str(host)}
    result = subprocess.run(
        [sys.executable, str(BIN_OS3), "queue", "--project", "meation"],
        cwd=str(host),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "T-PROJ-ONLY-01" in result.stdout, (result.stdout, result.stderr)


def test_cli_reports_load_paths_honors_project(tmp_path, monkeypatch):
    # Regression: pilot-status/cost-report must honor --project, not bypass it.
    from types import SimpleNamespace

    from server import cli_reports

    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    proj = _make_project(host / "projects", "meation")
    monkeypatch.setattr("server.config.host_root", lambda: host)

    paths = cli_reports._load_paths(SimpleNamespace(project="meation"))
    assert paths["root"] == proj


# ── T-OS3-CWD-NO-SILENT-HOST: new regression tests ───────────────────────────


def _make_bollard_project(projects_dir: "Path", name: str) -> "Path":
    """Create a project with .deos.yaml only (no deos.yaml) — mirrors bollard layout."""
    proj = projects_dir / name
    (proj / "devos" / "tasks").mkdir(parents=True)
    (proj / ".deos.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    (proj / "devos" / "tasks" / "QUEUE.yaml").write_text(
        f"tickets:\n  - id: T-{name.upper()}-01\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    (proj / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    return proj


def test_project_cwd_no_project_flag_reads_project_not_host(tmp_path, monkeypatch):
    """DOD #1 — bollard repro: .deos.yaml-only project, no --project flag.

    os3 queue from inside the project dir must read the PROJECT queue,
    never the host queue.  Silent host fallback is the bug being fixed.
    """
    import os
    import subprocess
    import sys

    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Host-only ticket — must NOT appear when running from project dir
    host_queue = host / "devos" / "tasks" / "QUEUE.yaml"
    (host / "devos" / "tasks").mkdir(parents=True)
    host_queue.write_text(
        "tickets:\n  - id: T-HOST-ONLY-99\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    host_archive = host / "devos" / "tasks" / "ARCHIVE.yaml"
    host_archive.write_text("tickets: []\n", encoding="utf-8")

    proj = _make_bollard_project(host / "projects", "bollard")

    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "OS3_HOST_ROOT": str(host),
        # Simulate shell PWD = project dir (cli_gates._invocation_cwd reads $PWD)
        "PWD": str(proj),
    }
    result = subprocess.run(
        [sys.executable, str(BIN_OS3), "queue"],
        cwd=str(proj),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert "T-HOST-ONLY-99" not in result.stdout, (
        f"Host queue leaked into project output!\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "T-BOLLARD-01" in result.stdout, (
        f"Project ticket not found in output.\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_host_root_no_project_flag_preserves_host_behavior(tmp_path, monkeypatch):
    """DOD #2 — host-maintenance regression: running os3 queue from host root
    without --project must still read the host SSOT queue.
    """
    import os
    import subprocess
    import sys

    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (host / "devos" / "tasks").mkdir(parents=True)
    (host / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "tickets:\n  - id: T-HOST-MAINT-01\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    (host / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )

    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "OS3_HOST_ROOT": str(host),
        "PWD": str(host),
    }
    result = subprocess.run(
        [sys.executable, str(BIN_OS3), "queue"],
        cwd=str(host),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Expected 0, got {result.returncode}\nstderr={result.stderr}"
    assert "T-HOST-MAINT-01" in result.stdout, (
        f"Host queue ticket missing.\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_cli_reports_no_implicit_host_fallback_from_project_dir(tmp_path, monkeypatch):
    """DOD #3 — cli_reports._load_paths must not silently fall back to host
    when invoked from a project cwd (no --project flag).
    """
    from types import SimpleNamespace

    from server import cli_gates, cli_reports

    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    proj = _make_bollard_project(host / "projects", "bollard")
    monkeypatch.setattr("server.config.host_root", lambda: host)

    # Simulate $PWD pointing at the project dir (what the shell sets before exec)
    monkeypatch.setenv("PWD", str(proj))

    # No --project flag: project=None, but PWD is inside project dir
    paths = cli_reports._load_paths(SimpleNamespace(project=None))

    # Must resolve to project root, not host
    assert paths["root"] == proj, (
        f"cli_reports silently used host root instead of project root!\n"
        f"paths['root']={paths['root']}, expected={proj}"
    )

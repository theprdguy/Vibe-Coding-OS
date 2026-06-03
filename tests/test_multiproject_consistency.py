"""T-OS3-MULTIPROJECT-TESTS — multi-project invariant regression tests.

Coverage gap identified by 2026-05-27 audit:
- External absolute repo_path: open/overview/queue/dispatch all resolve same root.
- External repo's QUEUE is read by `queue --project` (host QUEUE is NOT read).

Fixture strategy: tmp_path creates all repos; nothing under the real
host/projects/ is touched (constraints: host/projects 밖 tmp repo fixture 사용).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent  # engine/host root
BIN_OS3 = REPO / "bin" / "deos"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_host(tmp_path: Path) -> Path:
    """Minimal host tree: deos.yaml + devos/ + projects/."""
    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    (host / "devos" / "tasks").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Host-specific QUEUE — must NOT leak into project-scoped commands.
    (host / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "tickets:\n  - id: T-HOST-LEAK-CHECK\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    (host / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    return host


def _make_external_repo(tmp_path: Path, name: str) -> Path:
    """Create an external git repo with its own devos/tasks/QUEUE.yaml.

    Lives at tmp_path/external/<name> — outside any host/projects/ directory,
    mimicking a real project checked out at an arbitrary absolute path.
    """
    repo = tmp_path / "external" / name
    (repo / "devos" / "tasks").mkdir(parents=True)
    (repo / ".deos.yaml").write_text(f"name: {name}\n", encoding="utf-8")
    # External project's unique ticket — used to verify isolation.
    (repo / "devos" / "tasks" / "QUEUE.yaml").write_text(
        f"tickets:\n  - id: T-EXTERNAL-{name.upper()}-01\n    owner: CODEX\n    status: todo\n",
        encoding="utf-8",
    )
    (repo / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "tickets: []\n", encoding="utf-8"
    )
    return repo


def _register(host: Path, name: str, repo_path: str) -> None:
    """Register a project in the host registry."""
    from server.projects_registry import register_project
    register_project(host, name, repo_path)


def _run_os3(host: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run os3 CLI against a fake host, capturing stdout/stderr."""
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "OS3_HOST_ROOT": str(host),
        "PWD": str(cwd or host),
    }
    return subprocess.run(
        [sys.executable, str(BIN_OS3), *args],
        cwd=str(cwd or host),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# DOD 1 — cross-command root consistency (open/overview/queue/dispatch)
#
# "open/overview/queue/dispatch 가 동일 루트로 해석"
#
# open resolves via launcher._resolve_project_dir
# overview resolves via overview.build_overview (which reads QUEUE at repo_path)
# queue resolves via config.resolve_paths (which calls resolve_project_root)
# dispatch resolves via config.resolve_paths (same path as queue)
#
# We verify at the Python API level so we can assert the exact Path objects
# are equal, without needing to exec into a real claude session or codex.
# ---------------------------------------------------------------------------

class TestCrossCommandRootConsistency:
    """External absolute repo_path: all commands resolve to the same project root."""

    def test_queue_and_dispatch_resolve_same_root_absolute_path(self, tmp_path, monkeypatch):
        """queue --project and dispatch --project both resolve to the external repo root."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "alpha")
        _register(host, "alpha", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.config import resolve_project_root

        queue_root = resolve_project_root("alpha", cwd=host, host=host)
        dispatch_root = resolve_project_root("alpha", cwd=host, host=host)

        assert queue_root == external.resolve()
        assert dispatch_root == external.resolve()
        assert queue_root == dispatch_root, (
            f"queue root ({queue_root}) != dispatch root ({dispatch_root})"
        )

    def test_open_and_queue_resolve_same_root_absolute_path(self, tmp_path, monkeypatch):
        """launcher._resolve_project_dir (open) and config.resolve_project_root (queue)
        return the same resolved directory for an external absolute path registration.
        """
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "beta")
        _register(host, "beta", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.config import resolve_project_root
        from server.launcher import _resolve_project_dir

        open_root = _resolve_project_dir(host, "beta").resolve()
        queue_root = resolve_project_root("beta", cwd=host, host=host)

        assert open_root == external.resolve(), (
            f"open resolved {open_root!r}, expected {external.resolve()!r}"
        )
        assert queue_root == external.resolve(), (
            f"queue resolved {queue_root!r}, expected {external.resolve()!r}"
        )
        assert open_root == queue_root, (
            f"open root ({open_root}) != queue root ({queue_root}): cross-command inconsistency"
        )

    def test_overview_reads_external_repo_at_same_root(self, tmp_path, monkeypatch):
        """overview.build_overview uses the same repo_path as queue/dispatch.

        build_overview reads QUEUE at (repo_path / devos/tasks/QUEUE.yaml).
        If it resolves the external path correctly, the external ticket count appears.
        """
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "gamma")
        _register(host, "gamma", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.overview import build_overview

        rows = build_overview(host)
        # Must find exactly the gamma project row.
        assert len(rows) == 1, f"Expected 1 project row, got: {rows}"
        row = rows[0]
        assert row["name"] == "gamma"
        assert row["error"] is None, f"overview error for gamma: {row['error']}"
        assert row["todo"] == 1, (
            f"Expected 1 todo ticket in external repo, got: {row['todo']}"
        )
        # Resolve the path overview used: must equal external.resolve()
        resolved_path = Path(row["repo_path"])
        if not resolved_path.is_absolute():
            resolved_path = host / resolved_path
        assert resolved_path.resolve() == external.resolve(), (
            f"overview used {resolved_path.resolve()!r}, expected {external.resolve()!r}"
        )

    def test_all_four_commands_resolve_same_root(self, tmp_path, monkeypatch):
        """Invariant: open == queue == dispatch (config) == overview all point to same root."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "delta")
        _register(host, "delta", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.config import resolve_project_root
        from server.launcher import _resolve_project_dir
        from server.overview import build_overview

        expected = external.resolve()

        # open path
        open_root = _resolve_project_dir(host, "delta").resolve()
        # queue / dispatch path (same resolver)
        queue_root = resolve_project_root("delta", cwd=host, host=host)
        # overview path (reads from registered repo_path field)
        rows = build_overview(host)
        overview_row = next((r for r in rows if r["name"] == "delta"), None)
        assert overview_row is not None, "overview must include 'delta' project"
        ov_path = Path(overview_row["repo_path"])
        if not ov_path.is_absolute():
            ov_path = host / ov_path
        overview_root = ov_path.resolve()

        assert open_root == expected, f"open: {open_root!r} != {expected!r}"
        assert queue_root == expected, f"queue: {queue_root!r} != {expected!r}"
        assert overview_root == expected, f"overview: {overview_root!r} != {expected!r}"
        assert open_root == queue_root == overview_root, (
            f"Cross-command root mismatch: open={open_root}, "
            f"queue={queue_root}, overview={overview_root}"
        )


# ---------------------------------------------------------------------------
# DOD 2 — queue --project reads the EXTERNAL repo's QUEUE, not the host QUEUE
#
# "외부 repo 의 QUEUE 를 queue --project 가 실제로 읽음(host 아님)"
#
# Two verification angles:
#  a) CLI subprocess: `os3 queue --project <name>` stdout contains external
#     ticket id and does NOT contain the host-only ticket id.
#  b) Python API: resolve_paths("name") returns paths["queue"] pointing inside
#     the external repo, not inside the host devos/tasks/.
# ---------------------------------------------------------------------------

class TestExternalRepoQueueIsolation:
    """queue --project reads the external project QUEUE, never the host QUEUE."""

    def test_queue_project_flag_returns_external_ticket_cli(self, tmp_path):
        """E2E: os3 queue --project <name> stdout includes external ticket id."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "epsilon")
        _register(host, "epsilon", str(external))

        result = _run_os3(host, "queue", "--project", "epsilon")

        assert result.returncode == 0, (
            f"os3 queue --project epsilon failed (rc={result.returncode})\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "T-EXTERNAL-EPSILON-01" in result.stdout, (
            f"External ticket not found in output.\nstdout={result.stdout}"
        )

    def test_queue_project_flag_does_not_read_host_queue(self, tmp_path):
        """E2E: os3 queue --project <name> must NOT include the host-only ticket."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "zeta")
        _register(host, "zeta", str(external))

        result = _run_os3(host, "queue", "--project", "zeta")

        assert result.returncode == 0, (
            f"os3 queue --project zeta failed (rc={result.returncode})\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "T-HOST-LEAK-CHECK" not in result.stdout, (
            f"Host ticket leaked into project output!\nstdout={result.stdout}"
        )

    def test_resolve_paths_queue_points_inside_external_repo(self, tmp_path, monkeypatch):
        """Python API: resolve_paths returns paths['queue'] inside external repo."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "eta")
        _register(host, "eta", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.config import resolve_paths

        _config, paths = resolve_paths("eta", cwd=host)

        expected_queue = external.resolve() / "devos" / "tasks" / "QUEUE.yaml"
        assert paths["queue"] == expected_queue, (
            f"paths['queue']={paths['queue']!r}, expected {expected_queue!r}"
        )
        # Sanity: queue path must NOT be inside host devos/tasks/
        host_queue = host / "devos" / "tasks" / "QUEUE.yaml"
        assert paths["queue"] != host_queue, (
            f"paths['queue'] resolved to host QUEUE — isolation broken: {paths['queue']}"
        )

    def test_external_queue_tickets_readable_via_ssot(self, tmp_path, monkeypatch):
        """External QUEUE.yaml contents are readable through server.ssot.read_queue."""
        host = _make_host(tmp_path)
        external = _make_external_repo(tmp_path, "theta")
        _register(host, "theta", str(external))

        monkeypatch.setattr("server.config.host_root", lambda: host)

        from server.config import resolve_paths
        from server.ssot import read_queue

        _config, paths = resolve_paths("theta", cwd=host)
        queue_data = read_queue(paths["queue"])

        ticket_ids = [t.get("id") for t in queue_data.get("tickets", [])]
        assert "T-EXTERNAL-THETA-01" in ticket_ids, (
            f"External ticket not found in read_queue result: {ticket_ids}"
        )
        assert "T-HOST-LEAK-CHECK" not in ticket_ids, (
            f"Host ticket leaked into external queue read: {ticket_ids}"
        )

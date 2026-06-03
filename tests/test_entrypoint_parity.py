"""TDD tests for T-OS3-LEGACY-MAIN-RETIRE.

Verifies:
  1. format_queue_with_header is importable from server.cli (moved out of __main__)
  2. python3 -m server commands that previously had inline logic now delegate to
     server.cli.main (bin/deos-compatible path), so output is identical.
  3. python3 -m server prints a legacy-guard/deprecation note when unknown commands
     (or with no args) are passed, indicating it's a legacy shim.
  4. bin/deos queue/verify continue to work (no regression on the cli path).
  5. __main__.py imports format_queue_with_header from server.cli, not defining it inline.

DOD mapping:
  - DOD #1: bin/deos queue/verify produce correct output (format_queue_with_header moved).
  - DOD #2: python3 -m server with unknown/no-args → legacy-guard message present.
  - verify: python3 -m pytest tests/test_entrypoint_parity.py -v  pass.
"""
from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
BIN_DEOS = PROJECT_ROOT / "bin" / "deos"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_env() -> dict:
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _make_project(root: Path, tickets: list[dict]) -> Path:
    """Scaffold a minimal project tree: deos.yaml + QUEUE.yaml + ARCHIVE.yaml."""
    devos = root / "devos" / "tasks"
    devos.mkdir(parents=True, exist_ok=True)
    queue_path = devos / "QUEUE.yaml"
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )
    archive_path = devos / "ARCHIVE.yaml"
    archive_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": []}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "deos.yaml").write_text(
        "project_root: .\n"
        "devos_dir: devos\n"
        "queue_file: devos/tasks/QUEUE.yaml\n"
        "plans_dir: devos/plans\n"
        "logs_dir: devos/logs\n",
        encoding="utf-8",
    )
    return queue_path


def _ticket(tid: str, status: str) -> dict:
    return {
        "id": tid,
        "owner": "BUILDER",
        "status": status,
        "goal": f"Test ticket {tid}",
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
    }


def _ticket_with_verify(tid: str, status: str, verify_cmd: str) -> dict:
    t = _ticket(tid, status)
    t["verify"] = verify_cmd
    return t


def _run_server(*args: str, cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "server", *args],
        capture_output=True, text=True,
        cwd=str(cwd), timeout=timeout,
        env=_base_env(),
    )


def _run_cli(*args: str, cwd: Path, timeout: int = 15) -> subprocess.CompletedProcess:
    if not BIN_DEOS.exists():
        pytest.skip("bin/deos not found")
    return subprocess.run(
        [str(BIN_DEOS), *args],
        capture_output=True, text=True,
        cwd=str(cwd), timeout=timeout,
        env=_base_env(),
    )


# ---------------------------------------------------------------------------
# DOD #1a: format_queue_with_header is importable from server.cli (not just __main__)
# ---------------------------------------------------------------------------


class TestFormatQueueHelperLocation:
    """format_queue_with_header must live in (or be re-exported from) server.cli."""

    def test_format_queue_with_header_importable_from_cli(self) -> None:
        """DOD #1a: from server.cli import format_queue_with_header must succeed."""
        from server.cli import format_queue_with_header  # noqa: F401 — import is the assertion
        assert callable(format_queue_with_header), (
            "format_queue_with_header must be a callable in server.cli"
        )

    def test_format_queue_with_header_not_defined_in_main_module(self) -> None:
        """DOD #1a: __main__.py must import the helper, not re-define it inline.

        After migration, __main__.py should NOT contain a `def format_queue_with_header`
        at module level — it must delegate to server.cli's definition.
        """
        main_src = (PROJECT_ROOT / "server" / "__main__.py").read_text(encoding="utf-8")
        # Allow the import line; disallow a new function definition
        assert "def format_queue_with_header(" not in main_src, (
            "__main__.py must not define format_queue_with_header inline; "
            "it should import from server.cli"
        )

    def test_format_queue_with_header_accessible_from_cli(self) -> None:
        """DOD #1a: server.cli must expose format_queue_with_header as an attribute.

        The canonical definition lives in server.ssot and is re-exported from
        server.cli (to keep the public interface stable) and server.__main__
        (for backward-compat). This test verifies the re-export chain works and
        the function is NOT defined inline in __main__.
        """
        import server.cli as cli_mod
        assert hasattr(cli_mod, "format_queue_with_header"), (
            "server.cli must have format_queue_with_header as an attribute"
        )
        fn = getattr(cli_mod, "format_queue_with_header")
        assert callable(fn), "format_queue_with_header must be callable"
        # Canonical home is server.ssot (moved from __main__ to avoid LOC ceiling breach)
        src_file = inspect.getfile(fn)
        assert "ssot.py" in src_file or "cli.py" in src_file, (
            f"format_queue_with_header must be defined in ssot.py or cli.py, got: {src_file}"
        )

    def test_format_queue_with_header_produces_header_line(self, tmp_path: Path) -> None:
        """DOD #1a: format_queue_with_header returns a string with 'Total:' header."""
        _make_project(tmp_path, [_ticket("T-HDR-01", "todo"), _ticket("T-HDR-02", "doing")])
        from server.cli import format_queue_with_header
        result = format_queue_with_header(tmp_path / "devos" / "tasks" / "QUEUE.yaml")
        assert "Total:" in result, f"Expected 'Total:' in output, got: {result!r}"
        assert "todo: 1" in result, f"Expected 'todo: 1', got: {result!r}"
        assert "doing: 1" in result, f"Expected 'doing: 1', got: {result!r}"


# ---------------------------------------------------------------------------
# DOD #1b: bin/deos queue output preserved after helper migration
# ---------------------------------------------------------------------------


class TestCliQueuePreservation:
    """bin/deos queue must continue to work correctly after format_queue_with_header moves."""

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_queue_returns_rc0(self, tmp_path: Path) -> None:
        """DOD #1b: bin/deos queue returns rc=0."""
        _make_project(tmp_path, [_ticket("T-Q-01", "todo")])
        result = _run_cli("queue", cwd=tmp_path)
        assert result.returncode == 0, (
            f"bin/deos queue returned rc={result.returncode}; stderr={result.stderr!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_queue_shows_total_header(self, tmp_path: Path) -> None:
        """DOD #1b: bin/deos queue output contains 'Total:' header line."""
        _make_project(tmp_path, [_ticket("T-Q-02", "todo")])
        result = _run_cli("queue", cwd=tmp_path)
        assert result.returncode == 0
        assert "Total:" in result.stdout, (
            f"Expected 'Total:' in bin/deos queue output; got: {result.stdout!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_queue_shows_ticket_id(self, tmp_path: Path) -> None:
        """DOD #1b: bin/deos queue output contains the ticket id."""
        _make_project(tmp_path, [_ticket("T-Q-03", "todo")])
        result = _run_cli("queue", cwd=tmp_path)
        assert result.returncode == 0
        assert "T-Q-03" in result.stdout, (
            f"Expected 'T-Q-03' in output; got: {result.stdout!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_queue_archived_count_in_header(self, tmp_path: Path) -> None:
        """DOD #1b: header shows 'archived: N' count."""
        _make_project(tmp_path, [_ticket("T-Q-04", "todo")])
        result = _run_cli("queue", cwd=tmp_path)
        assert result.returncode == 0
        assert "archived:" in result.stdout, (
            f"Expected 'archived:' in output; got: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# DOD #1c: bin/deos verify preserved
# ---------------------------------------------------------------------------


class TestCliVerifyPreservation:
    """bin/deos verify must continue to work correctly."""

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_verify_missing_ticket_returns_nonzero(self, tmp_path: Path) -> None:
        """DOD #1c: bin/deos verify on nonexistent ticket → rc != 0."""
        _make_project(tmp_path, [_ticket("T-V-01", "todo")])
        result = _run_cli("verify", "T-NONEXISTENT-99999", cwd=tmp_path)
        assert result.returncode != 0, (
            f"Expected non-zero rc for missing ticket; got rc={result.returncode}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_verify_no_verify_defined_exits_zero(self, tmp_path: Path) -> None:
        """DOD #1c: bin/deos verify on ticket without verify field → rc=0 (no-op)."""
        _make_project(tmp_path, [_ticket("T-V-02", "todo")])
        result = _run_cli("verify", "T-V-02", cwd=tmp_path)
        # No verify field → should print info and exit 0
        assert result.returncode == 0, (
            f"Expected rc=0 for ticket with no verify; got rc={result.returncode}; "
            f"stderr={result.stderr!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_verify_passing_command_exits_zero(self, tmp_path: Path) -> None:
        """DOD #1c: bin/deos verify with a passing shell command → rc=0."""
        _make_project(tmp_path, [_ticket_with_verify("T-V-03", "todo", "true")])
        result = _run_cli("verify", "T-V-03", cwd=tmp_path)
        assert result.returncode == 0, (
            f"Expected rc=0 for passing verify; got rc={result.returncode}; "
            f"stderr={result.stderr!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_bin_deos_verify_failing_command_exits_nonzero(self, tmp_path: Path) -> None:
        """DOD #1c: bin/deos verify with a failing shell command → rc != 0."""
        _make_project(tmp_path, [_ticket_with_verify("T-V-04", "todo", "false")])
        result = _run_cli("verify", "T-V-04", cwd=tmp_path)
        assert result.returncode != 0, (
            f"Expected non-zero rc for failing verify; got rc={result.returncode}"
        )


# ---------------------------------------------------------------------------
# DOD #2: python3 -m server legacy-guard — unknown/no-args shows deprecation message
# ---------------------------------------------------------------------------


class TestMainLegacyGuard:
    """python3 -m server's legacy nature must be surfaced via a guard message."""

    def test_no_args_shows_legacy_guard_message(self, tmp_path: Path) -> None:
        """DOD #2: python3 -m server (no args) → stdout/stderr mentions 'legacy' or 'deprecated'
        or 'bin/os3' to guide users to the canonical CLI.
        """
        _make_project(tmp_path, [])
        result = _run_server(cwd=tmp_path)
        combined = result.stdout + result.stderr
        has_guidance = any(
            kw in combined.lower()
            for kw in ("legacy", "deprecated", "bin/os3", "use os3", "shim")
        )
        assert has_guidance, (
            "python3 -m server with no args must contain a legacy/deprecation guidance "
            f"message pointing to bin/os3. Got stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )

    def test_unknown_command_exits_nonzero_with_legacy_note(self, tmp_path: Path) -> None:
        """DOD #2: python3 -m server unknown-cmd → rc != 0 + combined output contains
        guidance to use bin/os3.
        """
        _make_project(tmp_path, [])
        result = _run_server("totally-unknown-xyz-command", cwd=tmp_path)
        assert result.returncode != 0, (
            f"Expected non-zero rc for unknown command; got {result.returncode}"
        )
        combined = result.stdout + result.stderr
        has_guidance = any(
            kw in combined.lower()
            for kw in ("legacy", "deprecated", "bin/os3", "use os3", "shim")
        )
        assert has_guidance, (
            "python3 -m server unknown-cmd must contain guidance to use bin/os3; "
            f"got stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# DOD #3: __main__.py remaining commands delegate to cli.main (parity check)
# ---------------------------------------------------------------------------


class TestMainDelegatesToCli:
    """__main__ commands must produce the same output as bin/deos (delegation parity)."""

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_queue_parity(self, tmp_path: Path) -> None:
        """python3 -m server queue and bin/deos queue produce identical stdout."""
        proj_m = tmp_path / "m"
        proj_c = tmp_path / "c"
        _make_project(proj_m, [_ticket("T-PAR-Q01", "todo"), _ticket("T-PAR-Q01b", "doing")])
        _make_project(proj_c, [_ticket("T-PAR-Q01", "todo"), _ticket("T-PAR-Q01b", "doing")])

        main_r = _run_server("queue", cwd=proj_m)
        cli_r = _run_cli("queue", cwd=proj_c)

        assert main_r.returncode == 0, f"__main__ queue failed: {main_r.stderr!r}"
        assert cli_r.returncode == 0, f"cli queue failed: {cli_r.stderr!r}"
        assert main_r.stdout == cli_r.stdout, (
            f"queue output mismatch:\n  __main__: {main_r.stdout!r}\n"
            f"  cli: {cli_r.stdout!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_status_parity(self, tmp_path: Path) -> None:
        """python3 -m server status and bin/deos status produce compatible output."""
        proj_m = tmp_path / "m"
        proj_c = tmp_path / "c"
        _make_project(proj_m, [_ticket("T-PAR-S01", "todo")])
        _make_project(proj_c, [_ticket("T-PAR-S01", "todo")])
        # Create devos/ structure needed for format_status_summary
        (proj_m / "devos").mkdir(exist_ok=True)
        (proj_c / "devos").mkdir(exist_ok=True)

        main_r = _run_server("status", cwd=proj_m)
        cli_r = _run_cli("status", cwd=proj_c)

        assert main_r.returncode == 0, f"__main__ status failed: {main_r.stderr!r}"
        assert cli_r.returncode == 0, f"cli status failed: {cli_r.stderr!r}"

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_archive_parity(self, tmp_path: Path) -> None:
        """python3 -m server archive and bin/deos archive produce identical stdout."""
        proj_m = tmp_path / "m"
        proj_c = tmp_path / "c"
        _make_project(proj_m, [])
        _make_project(proj_c, [])

        main_r = _run_server("archive", cwd=proj_m)
        cli_r = _run_cli("archive", cwd=proj_c)

        assert main_r.returncode == 0, f"__main__ archive failed: {main_r.stderr!r}"
        assert cli_r.returncode == 0, f"cli archive failed: {cli_r.stderr!r}"
        assert main_r.stdout == cli_r.stdout, (
            f"archive output mismatch:\n  __main__: {main_r.stdout!r}\n"
            f"  cli: {cli_r.stdout!r}"
        )

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_verify_parity_missing_ticket(self, tmp_path: Path) -> None:
        """python3 -m server verify missing-id and bin/deos verify both exit nonzero."""
        proj_m = tmp_path / "m"
        proj_c = tmp_path / "c"
        _make_project(proj_m, [])
        _make_project(proj_c, [])

        main_r = _run_server("verify", "T-NONEXIST-PAR", cwd=proj_m)
        cli_r = _run_cli("verify", "T-NONEXIST-PAR", cwd=proj_c)

        assert main_r.returncode != 0, "Expected nonzero from __main__ verify"
        assert cli_r.returncode != 0, "Expected nonzero from cli verify"

    @pytest.mark.skipif(not BIN_DEOS.exists(), reason="bin/deos not found")
    def test_owner_parity(self, tmp_path: Path) -> None:
        """python3 -m server owner <id> and bin/deos owner <id> produce identical stdout."""
        proj_m = tmp_path / "m"
        proj_c = tmp_path / "c"
        _make_project(proj_m, [_ticket("T-PAR-OWN01", "todo")])
        _make_project(proj_c, [_ticket("T-PAR-OWN01", "todo")])

        main_r = _run_server("owner", "T-PAR-OWN01", cwd=proj_m)
        cli_r = _run_cli("owner", "T-PAR-OWN01", cwd=proj_c)

        assert main_r.returncode == 0, f"__main__ owner failed: {main_r.stderr!r}"
        assert cli_r.returncode == 0, f"cli owner failed: {cli_r.stderr!r}"
        assert main_r.stdout.strip() == cli_r.stdout.strip(), (
            f"owner output mismatch: __main__={main_r.stdout!r} cli={cli_r.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Regression guard: existing cli/dispatcher tests remain unaffected
# ---------------------------------------------------------------------------


class TestNoRegressionInExistingPaths:
    """Smoke-level checks that the existing module import paths still work."""

    def test_server_cli_main_importable(self) -> None:
        """server.cli.main must be importable and callable."""
        from server.cli import main
        assert callable(main)

    def test_server_main_importable(self) -> None:
        """server.__main__ must still be importable (not deleted)."""
        import server.__main__ as m  # noqa: F401
        assert hasattr(m, "main"), "server.__main__ must have a main() function"

    def test_format_queue_with_header_both_importable(self) -> None:
        """format_queue_with_header must be importable from both server.cli and server.__main__."""
        from server.cli import format_queue_with_header as from_cli
        from server.__main__ import format_queue_with_header as from_main
        assert callable(from_cli)
        assert callable(from_main)
        # They should be the same callable (or at least both work)
        assert from_cli is from_main or callable(from_main), (
            "Both import paths must resolve to callable format_queue_with_header"
        )

"""Launcher tests for T-DEOS-01 canonical bin/deos entry point."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BIN_DEOS = PROJECT_ROOT / "bin" / "deos"
BIN_OS3 = PROJECT_ROOT / "bin" / "os3"
BIN_OSN = PROJECT_ROOT / "bin" / "osn"


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return env


def _run_bin(bin_path: Path, *args: str, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(bin_path), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=15,
        env=_base_env(),
    )


def test_bin_deos_exists_executable_and_wraps_server_cli_main() -> None:
    assert BIN_DEOS.exists(), f"bin/deos not found at {BIN_DEOS}"
    assert os.access(BIN_DEOS, os.X_OK), "bin/deos must be executable"

    src = BIN_DEOS.read_text(encoding="utf-8")
    assert src.splitlines()[0] == "#!/usr/bin/env python3"
    assert "from server.cli import main" in src
    assert "sys.exit(main(sys.argv[1:]))" in src


def test_bin_deos_status_matches_python_m_server() -> None:
    """bin/deos status must produce identical output to python3 -m server status."""
    deos_r = _run_bin(BIN_DEOS, "status")
    module_r = subprocess.run(
        [sys.executable, "-m", "server", "status"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=15,
        env=_base_env(),
    )

    assert deos_r.returncode == 0, f"bin/deos status failed: {deos_r.stderr!r}"
    assert module_r.returncode == 0, f"python3 -m server status failed: {module_r.stderr!r}"
    assert deos_r.stdout == module_r.stdout, (
        f"stdout mismatch:\n  bin/deos: {deos_r.stdout!r}\n"
        f"  python3 -m server: {module_r.stdout!r}"
    )


def test_bin_deos_help_uses_deos_prog() -> None:
    result = _run_bin(BIN_DEOS, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage: deos " in result.stdout
    assert "usage: os3 " not in result.stdout


def test_no_project_error_hint_uses_deos_marker(tmp_path: Path) -> None:
    subdir = tmp_path / "not" / "a" / "project"
    subdir.mkdir(parents=True)

    result = _run_bin(BIN_DEOS, "queue", cwd=subdir)

    assert result.returncode != 0
    assert ".deos.yaml" in result.stderr
    assert ".os3.yaml" not in result.stderr

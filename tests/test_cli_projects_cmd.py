"""Phase 2a Task 3: `os3 register` / `os3 projects` host-registry commands."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BIN_OS3 = REPO / "bin" / "deos"


def _env(host: Path) -> dict:
    return {**os.environ, "PYTHONPATH": str(REPO), "OS3_HOST_ROOT": str(host)}


def _run(host: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(BIN_OS3), *args],
        cwd=str(host),
        env=_env(host),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_register_then_projects_lists(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )

    r1 = _run(host, "register", "meation", "projects/meation")
    assert r1.returncode == 0, (r1.stdout, r1.stderr)
    assert (host / "devos" / "projects" / "meation.md").is_file()

    r2 = _run(host, "projects")
    assert r2.returncode == 0, (r2.stdout, r2.stderr)
    assert "meation" in r2.stdout


def test_projects_empty(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    r = _run(host, "projects")
    assert r.returncode == 0
    assert "no projects registered" in r.stdout

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


HOST_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_host_pytest_surface(host_root: Path, server_init: str = "") -> None:
    _write(host_root / "pytest.ini", (HOST_ROOT / "pytest.ini").read_text(encoding="utf-8"))
    _write(host_root / "conftest.py", (HOST_ROOT / "conftest.py").read_text(encoding="utf-8"))
    _write(host_root / "server" / "__init__.py", server_init)


def _collect(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def _run_pytest(cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )


def test_markerless_project_bare_pytest_collects_tests_scripts_under_host_config(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    project_root = host_root / "projects" / "markerless"
    _copy_host_pytest_surface(host_root)
    _write(project_root / "tests" / "test_top_level.py", "def test_top_level():\n    pass\n")
    _write(project_root / "tests" / "scripts" / "test_script_level.py", "def test_script_level():\n    pass\n")

    result = _collect(project_root)

    assert result.returncode == 0, result.stderr
    assert "projects/markerless/tests/test_top_level.py::test_top_level" in result.stdout
    assert "projects/markerless/tests/scripts/test_script_level.py::test_script_level" in result.stdout
    assert "2 tests collected" in result.stdout


def test_markerless_project_uses_its_own_server_package_under_host_conftest(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    project_root = host_root / "projects" / "markerless"
    _copy_host_pytest_surface(host_root, server_init='ORIGIN = "host"\n')
    _write(project_root / "server" / "__init__.py", 'ORIGIN = "project"\n')
    _write(
        project_root / "tests" / "test_server_origin.py",
        "import server\n\n\ndef test_server_origin():\n    assert server.ORIGIN == 'project'\n",
    )

    result = _run_pytest(project_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_host_root_collection_still_ignores_projects_tree(tmp_path: Path) -> None:
    host_root = tmp_path / "host"
    _copy_host_pytest_surface(host_root)
    _write(host_root / "tests" / "test_host.py", "def test_host():\n    pass\n")
    _write(host_root / "projects" / "markerless" / "tests" / "test_project.py", "def test_project():\n    pass\n")

    result = _collect(host_root)

    assert result.returncode == 0, result.stderr
    assert "tests/test_host.py::test_host" in result.stdout
    assert "projects/markerless/tests/test_project.py::test_project" not in result.stdout
    assert "1 test collected" in result.stdout


def test_pytest_configure_reports_namespace_server_package(monkeypatch: pytest.MonkeyPatch) -> None:
    import conftest as host_conftest
    import importlib.util

    def fake_find_spec(name: str) -> SimpleNamespace:
        assert name == "server"
        return SimpleNamespace(origin=None, submodule_search_locations=[str(HOST_ROOT / "server")])

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    with pytest.raises(RuntimeError, match="server.*namespace package.*origin is None"):
        host_conftest.pytest_configure(SimpleNamespace())

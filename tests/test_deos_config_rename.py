"""T-DEOS-02: Tests proving deos.yaml rename — deos.yaml / .deos.yaml only.

Legacy fallback tests (osn.yaml / .os3.yaml) removed after T-DEOS-CLEANUP:
those fallback branches no longer exist in server/config.py.

Covers:
- load_config() returns host config when deos.yaml exists (primary).
- resolve_project_root() detects .deos.yaml marker.
- resolve_project_root() raises when no .deos.yaml marker present.
- load_layered_config() uses deos.yaml as primary host config.
- load_layered_config() uses .deos.yaml project overlay.
- load_layered_config() raises when host deos.yaml absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.config import (
    ProjectResolutionError,
    load_config,
    load_layered_config,
    resolve_project_root,
)


# ── load_config ──────────────────────────────────────────────────────────────

def test_load_config_primary_deos_yaml(tmp_path, monkeypatch):
    """load_config() loads deos.yaml when it is the only config present."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "deos.yaml").write_text("project_root: '.'\nfrom: deos\n", encoding="utf-8")
    cfg = load_config(str(tmp_path / "deos.yaml"))
    assert cfg["from"] == "deos"


def test_load_config_explicit_path(tmp_path, monkeypatch):
    """load_config() loads the file at the explicit path given."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "deos.yaml").write_text("project_root: '.'\nfrom: explicit\n", encoding="utf-8")
    cfg = load_config(str(tmp_path / "deos.yaml"))
    assert cfg["from"] == "explicit"


def test_load_config_missing_raises(tmp_path):
    """load_config() raises FileNotFoundError when the file does not exist."""
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "deos.yaml"))


# ── resolve_project_root: .deos.yaml marker ──────────────────────────────────

def test_resolve_cwd_detects_deos_yaml_marker(tmp_path):
    """.deos.yaml in a project dir triggers project auto-detection (primary marker)."""
    host = tmp_path / "dev-os"
    proj = host / "projects" / "alpha"
    proj.mkdir(parents=True)
    (proj / ".deos.yaml").write_text("name: alpha\n", encoding="utf-8")
    result = resolve_project_root(None, cwd=proj, host=host)
    assert result == proj


def test_resolve_cwd_deos_marker_in_nested_subdir(tmp_path):
    """.deos.yaml marker is found by walking up from a nested subdir."""
    host = tmp_path / "dev-os"
    proj = host / "projects" / "delta"
    nested = proj / "apps" / "web"
    nested.mkdir(parents=True)
    (proj / ".deos.yaml").write_text("name: delta\n", encoding="utf-8")
    result = resolve_project_root(None, cwd=nested, host=host)
    assert result == proj


def test_resolve_cwd_no_marker_raises(tmp_path):
    """resolve_project_root raises ProjectResolutionError when no .deos.yaml found."""
    host = tmp_path / "dev-os"
    proj = host / "projects" / "no-marker"
    proj.mkdir(parents=True)
    with pytest.raises(ProjectResolutionError):
        resolve_project_root(None, cwd=proj, host=host)


# ── load_layered_config: deos.yaml host config + .deos.yaml overlay ──────────

def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_load_layered_config_uses_deos_yaml_as_host(tmp_path):
    """load_layered_config uses deos.yaml as the host config when present."""
    host = tmp_path / "dev-os"
    _write(host / "deos.yaml", "from: deos\ndispatch:\n  max_concurrent: 3\n")
    proj = host / "projects" / "p1"
    proj.mkdir(parents=True)
    cfg = load_layered_config(project_root=proj, host=host)
    assert cfg["from"] == "deos"
    assert cfg["dispatch"]["max_concurrent"] == 3


def test_load_layered_config_uses_deos_yaml_project_overlay(tmp_path):
    """load_layered_config merges .deos.yaml project overlay when present."""
    host = tmp_path / "dev-os"
    _write(host / "deos.yaml", "dispatch:\n  max_concurrent: 3\n")
    proj = host / "projects" / "p3"
    _write(proj / ".deos.yaml", "dispatch:\n  max_concurrent: 1\n")
    cfg = load_layered_config(project_root=proj, host=host)
    assert cfg["dispatch"]["max_concurrent"] == 1


def test_load_layered_config_no_overlay_uses_host_only(tmp_path):
    """load_layered_config works correctly when no project overlay (.deos.yaml) is present."""
    host = tmp_path / "dev-os"
    _write(host / "deos.yaml", "dispatch:\n  max_concurrent: 5\n")
    proj = host / "projects" / "p-no-overlay"
    proj.mkdir(parents=True)
    cfg = load_layered_config(project_root=proj, host=host)
    assert cfg["dispatch"]["max_concurrent"] == 5


def test_load_layered_config_missing_host_config_raises(tmp_path):
    """load_layered_config raises FileNotFoundError when deos.yaml does not exist."""
    host = tmp_path / "dev-os"
    host.mkdir()
    proj = host / "projects" / "x"
    proj.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        load_layered_config(project_root=proj, host=host)

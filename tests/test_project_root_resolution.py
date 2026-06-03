from pathlib import Path

import pytest

from server.config import (
    ProjectResolutionError,
    host_root,
    resolve_project_root,
)
from server.projects_registry import register_project


def test_host_root_is_repo_root_above_server_package(monkeypatch):
    # host_root() = the dir that contains the `server/` package (no env override)
    monkeypatch.delenv("OS3_HOST_ROOT", raising=False)
    expected = Path(__file__).resolve().parent.parent
    assert host_root() == expected


def test_host_root_env_override(tmp_path, monkeypatch):
    target = tmp_path / "dev-os"
    target.mkdir()
    monkeypatch.setenv("OS3_HOST_ROOT", str(target))
    assert host_root() == target.resolve()


def test_resolve_by_explicit_name(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    proj.mkdir(parents=True)
    assert resolve_project_root("meation", cwd=tmp_path, host=host) == proj


def test_resolve_by_name_missing_raises(tmp_path):
    host = tmp_path / "dev-os"
    (host / "projects").mkdir(parents=True)
    with pytest.raises(ProjectResolutionError, match="meation"):
        resolve_project_root("missing-meation", cwd=tmp_path, host=host)


def test_resolve_from_cwd_marker(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "corps"
    nested = proj / "apps" / "web"
    nested.mkdir(parents=True)
    (proj / ".deos.yaml").write_text("name: corps\n", encoding="utf-8")
    assert resolve_project_root(None, cwd=nested, host=host) == proj


def test_resolve_no_name_no_marker_raises(tmp_path):
    host = tmp_path / "dev-os"
    host.mkdir()
    with pytest.raises(ProjectResolutionError, match="no project"):
        resolve_project_root(None, cwd=tmp_path, host=host)


def test_resolve_walk_stops_at_host_ignores_marker_above(tmp_path):
    # A stray .os3.yaml ABOVE the host root must NOT be picked up.
    host = tmp_path / "dev-os"
    host.mkdir()
    (tmp_path / ".deos.yaml").write_text("name: stray\n", encoding="utf-8")
    with pytest.raises(ProjectResolutionError):
        resolve_project_root(None, cwd=host, host=host)


# ── DOD tests: registry-aware resolver unification ───────────────────────────


def test_resolve_by_name_uses_registry_absolute_repo_path(tmp_path):
    """DOD-1: explicit project name → registry repo_path (absolute) wins over host/projects."""
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    # Register project with absolute path outside host/projects
    external = tmp_path / "external" / "myapp"
    external.mkdir(parents=True)
    (external / ".deos.yaml").write_text("name: myapp\n", encoding="utf-8")
    register_project(host, "myapp", str(external))

    result = resolve_project_root("myapp", cwd=tmp_path, host=host)
    assert result == external.resolve()


def test_resolve_by_name_uses_registry_host_relative_repo_path(tmp_path):
    """DOD-1: explicit project name → registry repo_path (host-relative) wins over host/projects/<name>."""
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    # Register with a host-relative path (not host/projects/<name>)
    actual = host / "workspaces" / "myapp"
    actual.mkdir(parents=True)
    (actual / ".deos.yaml").write_text("name: myapp\n", encoding="utf-8")
    register_project(host, "myapp", "workspaces/myapp")

    result = resolve_project_root("myapp", cwd=tmp_path, host=host)
    assert result == actual.resolve()


def test_resolve_by_name_config_equals_launcher_absolute(tmp_path):
    """DOD-2: cross-command consistency — config and launcher return same root (absolute path case)."""
    from server.launcher import _resolve_project_dir

    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    external = tmp_path / "projects-elsewhere" / "alpha"
    external.mkdir(parents=True)
    register_project(host, "alpha", str(external))

    config_root = resolve_project_root("alpha", cwd=tmp_path, host=host)
    launcher_root = _resolve_project_dir(host, "alpha").resolve()
    assert config_root == launcher_root


def test_resolve_by_name_config_equals_launcher_host_relative(tmp_path):
    """DOD-2: cross-command consistency — config and launcher return same root (host-relative case)."""
    from server.launcher import _resolve_project_dir

    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    actual = host / "custom" / "beta"
    actual.mkdir(parents=True)
    register_project(host, "beta", "custom/beta")

    config_root = resolve_project_root("beta", cwd=tmp_path, host=host)
    launcher_root = _resolve_project_dir(host, "beta").resolve()
    assert config_root == launcher_root


def test_resolve_by_name_config_equals_launcher_fallback(tmp_path):
    """DOD-2: cross-command consistency — fallback (no registry) both return host/projects/<name>."""
    from server.launcher import _resolve_project_dir

    host = tmp_path / "dev-os"
    # No registry (devos/projects dir absent)
    proj = host / "projects" / "gamma"
    proj.mkdir(parents=True)

    config_root = resolve_project_root("gamma", cwd=tmp_path, host=host)
    launcher_root = _resolve_project_dir(host, "gamma").resolve()
    assert config_root == launcher_root


def test_resolve_by_name_empty_registry_repo_path_falls_back(tmp_path):
    """DOD-2: empty registry repo_path → fallback to host/projects/<name>, consistent with launcher."""
    from server.launcher import _resolve_project_dir

    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    proj = host / "projects" / "delta"
    proj.mkdir(parents=True)
    register_project(host, "delta", "")  # empty repo_path

    config_root = resolve_project_root("delta", cwd=tmp_path, host=host)
    launcher_root = _resolve_project_dir(host, "delta").resolve()
    assert config_root == launcher_root


def test_resolve_cwd_marker_uses_deosyaml_not_deosyaml_host(tmp_path):
    """DOD-3: cwd upward search uses .deos.yaml; deos.yaml (host config) must NOT trigger project detection."""
    host = tmp_path / "dev-os"
    host.mkdir()
    # Place deos.yaml (host config file) in a subdir — must NOT be treated as project marker
    subdir = host / "some-subdir"
    subdir.mkdir()
    (subdir / "deos.yaml").write_text("host: true\n", encoding="utf-8")

    # No .deos.yaml anywhere below host → must raise
    with pytest.raises(ProjectResolutionError):
        resolve_project_root(None, cwd=subdir, host=host)

from pathlib import Path

import pytest

from server.projects_registry import (
    RegistryError,
    list_projects,
    register_project,
)


def test_register_creates_record(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    rec = register_project(host, "meation", "projects/meation", status="active")
    assert rec["name"] == "meation"
    path = host / "devos" / "projects" / "meation.md"
    assert path.is_file()
    assert "repo_path: projects/meation" in path.read_text(encoding="utf-8")


def test_list_projects_returns_registered_sorted(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    register_project(host, "meation", "projects/meation")
    register_project(host, "corps", "projects/corps")
    names = [r["name"] for r in list_projects(host)]
    assert names == ["corps", "meation"]  # sorted by filename


@pytest.mark.parametrize("bad", ["../evil", "a/b", ".", "..", "", "x y"])
def test_register_rejects_bad_name(tmp_path, bad):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    with pytest.raises(RegistryError):
        register_project(host, bad, "x")


def test_list_ignores_malformed_frontmatter(tmp_path):
    host = tmp_path / "dev-os"
    reg = host / "devos" / "projects"
    reg.mkdir(parents=True)
    register_project(host, "good", "projects/good")
    # frontmatter that parses to a non-dict (YAML list) must be skipped, not crash
    (reg / "bad.md").write_text("---\n- a\n- b\n---\n# bad\n", encoding="utf-8")
    rows = list_projects(host)
    assert [r["name"] for r in rows] == ["good"]


def test_list_empty_returns_empty(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    assert list_projects(host) == []


def test_register_overwrite_updates_status(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    register_project(host, "meation", "projects/meation", status="active")
    register_project(host, "meation", "projects/meation", status="parked")
    rows = list_projects(host)
    assert len(rows) == 1
    assert rows[0]["status"] == "parked"

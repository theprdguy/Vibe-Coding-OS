from pathlib import Path

import pytest

from server.config import get_paths, load_layered_config


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_project_overrides_host_scalar_and_nested(tmp_path):
    host = tmp_path / "dev-os"
    _write(
        host / "deos.yaml",
        "project_root: '.'\n"
        "gates:\n"
        "  defaults:\n"
        "    - name: tests\n"
        "      run: python3 -m pytest tests/ -q\n"
        "dispatch:\n"
        "  max_concurrent: 2\n",
    )
    proj = host / "projects" / "meation"
    _write(
        proj / ".deos.yaml",
        "dispatch:\n  max_concurrent: 1\n",
    )
    cfg = load_layered_config(project_root=proj, host=host)
    # nested override wins
    assert cfg["dispatch"]["max_concurrent"] == 1
    # untouched host keys preserved
    assert cfg["gates"]["defaults"][0]["name"] == "tests"


def test_missing_project_overlay_returns_host_only(tmp_path):
    host = tmp_path / "dev-os"
    _write(host / "deos.yaml", "dispatch:\n  max_concurrent: 2\n")
    proj = host / "projects" / "bare"
    proj.mkdir(parents=True)
    cfg = load_layered_config(project_root=proj, host=host)
    assert cfg["dispatch"]["max_concurrent"] == 2


def test_missing_host_config_raises(tmp_path):
    host = tmp_path / "dev-os"
    host.mkdir()
    proj = host / "projects" / "x"
    proj.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        load_layered_config(project_root=proj, host=host)


def test_get_paths_explicit_root_overrides_config(tmp_path):
    cfg = {
        "project_root": ".",
        "devos_dir": "devos",
        "queue_file": "devos/tasks/QUEUE.yaml",
    }
    paths = get_paths(cfg, project_root=tmp_path)
    assert paths["root"] == tmp_path
    assert paths["queue"] == tmp_path / "devos/tasks/QUEUE.yaml"


def test_get_paths_without_explicit_root_uses_config():
    cfg = {"project_root": "."}
    paths = get_paths(cfg)
    assert str(paths["root"]) == "."

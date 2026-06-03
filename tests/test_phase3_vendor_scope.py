"""Phase 3 — vendor CLI scoping + host-single-sourced doctrine (β).

CODEX must be scoped to its cwd (no `--add-dir ".."` parent leak), and the
dispatcher orientation/doctrine must resolve from the HOST root, not the project.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from server.dispatcher import ORIENTATION_START_MARKER, Dispatcher

REPO = Path(__file__).resolve().parent.parent


def test_codex_command_has_no_parent_add_dir():
    cfg = yaml.safe_load((REPO / "deos.yaml").read_text(encoding="utf-8"))
    command = cfg["agents"]["CODEX"]["command"]
    assert ".." not in command, f"CODEX command leaks parent via add-dir: {command}"
    # if --add-dir is present at all, its argument must not be a relative parent
    if "--add-dir" in command:
        idx = command.index("--add-dir")
        target = command[idx + 1]
        assert not target.startswith(".."), target


def _dispatcher(host: Path, project_root: Path) -> Dispatcher:
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    return Dispatcher(
        config={
            "agents": {"CODEX": {"mode": "subprocess", "command": ["codex"], "timeout": 10}},
            "dispatch": {"orientation_files": [{"path": "devos/dispatch-header.yaml"}]},
        },
        paths={
            "root": project_root,
            "logs": project_root / "logs",
            "queue": project_root / "QUEUE.yaml",
        },
        host=host,
    )


def test_orientation_resolves_from_host_not_project(tmp_path):
    host = tmp_path / "dev-os"
    project = tmp_path / "dev-os" / "projects" / "meation"
    (host / "devos").mkdir(parents=True)
    (project / "devos").mkdir(parents=True)
    # host doctrine header — should be used
    (host / "devos" / "dispatch-header.yaml").write_text(
        "iron_laws:\n  - HOST DOCTRINE MARKER\n", encoding="utf-8"
    )
    # a different header at the project root — must be ignored under β
    (project / "devos" / "dispatch-header.yaml").write_text(
        "iron_laws:\n  - PROJECT LOCAL MARKER\n", encoding="utf-8"
    )

    header = _dispatcher(host, project)._build_orientation_header()
    assert ORIENTATION_START_MARKER in header
    assert "HOST DOCTRINE MARKER" in header
    assert "PROJECT LOCAL MARKER" not in header


def test_orientation_empty_when_host_header_missing(tmp_path):
    host = tmp_path / "dev-os"
    project = tmp_path / "dev-os" / "projects" / "meation"
    (host / "devos").mkdir(parents=True)
    (project / "devos").mkdir(parents=True)
    # header only at project (not host) -> β resolves from host -> missing -> empty
    (project / "devos" / "dispatch-header.yaml").write_text(
        "iron_laws:\n  - PROJECT LOCAL MARKER\n", encoding="utf-8"
    )
    assert _dispatcher(host, project)._build_orientation_header() == ""

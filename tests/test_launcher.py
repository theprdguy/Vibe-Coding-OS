import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.launcher import LauncherError, build_open_command
from server.projects_registry import register_project

REPO = Path(__file__).resolve().parent.parent
BIN_OS3 = REPO / "bin" / "deos"
REQUIRED_AGENTS = ("builder", "reviewer", "designer", "security")


def _write_host_agents(host: Path) -> None:
    agents_dir = host / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_AGENTS:
        tools = (
            "Read, Grep, Glob, Bash"
            if name == "reviewer"
            else "Read, Edit, Write, Bash"
        )
        (agents_dir / f"{name}.md").write_text(
            f"---\nname: {name}\ntools: {tools}\n---\n# {name}\n",
            encoding="utf-8",
        )


def test_build_command_includes_host_settings(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    proj.mkdir(parents=True)
    _write_host_agents(host)
    (host / ".claude").mkdir(parents=True, exist_ok=True)
    (host / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    cwd, argv = build_open_command(host, "meation")
    assert cwd == proj.resolve()
    assert argv[0] == "claude"
    assert "--settings" in argv
    assert str(host / ".claude" / "settings.json") in argv


def test_build_command_omits_settings_when_absent(tmp_path):
    host = tmp_path / "dev-os"
    (host / "projects" / "meation").mkdir(parents=True)
    _write_host_agents(host)
    cwd, argv = build_open_command(host, "meation")
    assert argv == ["claude"]  # no settings file -> plain claude


def test_build_command_does_not_create_project_agent_symlinks(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    (proj / ".claude").mkdir(parents=True)
    _write_host_agents(host)

    cwd, _argv = build_open_command(host, "meation")

    assert cwd == proj.resolve()
    assert not (proj / ".claude" / "agents").exists()


def test_build_command_still_does_not_create_agent_symlinks_on_repeated_calls(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    (proj / ".claude").mkdir(parents=True)
    _write_host_agents(host)

    build_open_command(host, "meation")
    assert not (proj / ".claude" / "agents").exists()
    build_open_command(host, "meation")

    assert not (proj / ".claude" / "agents").exists()


def test_build_command_leaves_existing_project_agent_copy_untouched(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    stale = proj / ".claude" / "agents" / "builder.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old project-local copy\n", encoding="utf-8")
    _write_host_agents(host)

    build_open_command(host, "meation")

    assert stale.is_file()
    assert not stale.is_symlink()
    assert stale.read_text(encoding="utf-8") == "old project-local copy\n"


def test_build_command_does_not_create_project_reviewer_agent(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    (proj / ".claude").mkdir(parents=True)
    _write_host_agents(host)

    build_open_command(host, "meation")

    reviewer = proj / ".claude" / "agents" / "reviewer.md"
    assert not reviewer.exists()


def test_build_command_does_not_require_host_agents_dir(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    proj.mkdir(parents=True)

    cwd, argv = build_open_command(host, "meation")

    assert cwd == proj.resolve()
    assert argv == ["claude"]


def test_build_command_does_not_require_complete_host_agent_set(tmp_path):
    host = tmp_path / "dev-os"
    proj = host / "projects" / "meation"
    proj.mkdir(parents=True)
    agents_dir = host / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "builder.md").write_text(
        "---\nname: builder\n---\n# builder\n",
        encoding="utf-8",
    )

    cwd, argv = build_open_command(host, "meation")

    assert cwd == proj.resolve()
    assert argv == ["claude"]


def test_build_command_uses_registry_repo_path(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    # actual project lives outside host/projects (pre-Phase-4 location)
    actual = tmp_path / "elsewhere" / "meation"
    actual.mkdir(parents=True)
    _write_host_agents(host)
    register_project(host, "meation", str(actual))

    cwd, _argv = build_open_command(host, "meation")
    assert cwd == actual.resolve()


def test_build_command_missing_dir_raises(tmp_path):
    host = tmp_path / "dev-os"
    host.mkdir()
    with pytest.raises(LauncherError):
        build_open_command(host, "ghost")


def test_empty_repo_path_falls_back_to_host_projects(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    _write_host_agents(host)
    register_project(host, "meation", "")  # empty repo_path
    (host / "projects" / "meation").mkdir(parents=True)
    cwd, _ = build_open_command(host, "meation")
    assert cwd == (host / "projects" / "meation").resolve()  # not the host dir


def test_handle_open_reports_missing_claude(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from server import launcher

    host = tmp_path / "dev-os"
    (host / "projects" / "meation").mkdir(parents=True)
    _write_host_agents(host)
    monkeypatch.setattr("server.config.host_root", lambda: host)

    def _raise(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(launcher.os, "execvp", _raise)
    monkeypatch.setattr(launcher.os, "chdir", lambda *_: None)
    rc = launcher.handle_open(SimpleNamespace(name="meation", print_cmd=False))
    assert rc == 1


def test_host_root_as_project_dir_does_not_corrupt_agent_files(tmp_path):
    """When repo_path resolves to host root, host agent .md files must not be mutated."""
    host = tmp_path / "dev-os"
    _write_host_agents(host)
    from server.projects_registry import register_project
    register_project(host, "self", str(host))

    agents_dir = host / ".claude" / "agents"
    original_stats = {
        name: (agents_dir / f"{name}.md").stat().st_ino
        for name in REQUIRED_AGENTS
    }

    cwd, argv = build_open_command(host, "self")

    assert cwd == host.resolve()
    assert argv == ["claude"]

    for name in REQUIRED_AGENTS:
        agent_path = agents_dir / f"{name}.md"
        assert agent_path.exists(), f"host agent {name}.md must still exist"
        assert not agent_path.is_symlink(), f"host agent {name}.md must NOT become a symlink"
        assert agent_path.stat().st_ino == original_stats[name], (
            f"host agent {name}.md inode changed — file was replaced"
        )


def test_host_root_as_project_dir_returns_command_without_agent_self_loop_error(tmp_path):
    host = tmp_path / "dev-os"
    _write_host_agents(host)
    from server.projects_registry import register_project
    register_project(host, "self", str(host))

    cwd, argv = build_open_command(host, "self")

    assert cwd == host.resolve()
    assert argv == ["claude"]


def test_actual_host_reviewer_md_is_read_only(tmp_path):
    """DOD-3: pin that the real host .claude/agents/reviewer.md has only
    Read/Grep/Glob/Bash in its tools allowlist; Edit/Write/NotebookEdit absent."""
    host_reviewer = Path(__file__).resolve().parent.parent / ".claude" / "agents" / "reviewer.md"
    assert host_reviewer.exists(), "host .claude/agents/reviewer.md must exist"
    assert not host_reviewer.is_symlink(), "host reviewer.md must not be a symlink itself"

    frontmatter = host_reviewer.read_text(encoding="utf-8").split("---", 2)[1]
    assert "tools:" in frontmatter, "reviewer.md frontmatter must contain 'tools:' key"
    assert "Read" in frontmatter
    assert "Grep" in frontmatter
    assert "Glob" in frontmatter
    assert "Bash" in frontmatter
    assert "Edit" not in frontmatter, "reviewer.md must NOT allow Edit"
    assert "Write" not in frontmatter, "reviewer.md must NOT allow Write"
    assert "NotebookEdit" not in frontmatter, "reviewer.md must NOT allow NotebookEdit"


def test_open_print_mode_e2e(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (host / "projects" / "meation").mkdir(parents=True)
    _write_host_agents(host)
    (host / ".claude").mkdir(parents=True, exist_ok=True)
    (host / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(REPO), "OS3_HOST_ROOT": str(host)}
    r = subprocess.run(
        [sys.executable, str(BIN_OS3), "open", "meation", "--print"],
        cwd=str(host), env=env, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "claude --settings" in r.stdout
    assert "projects/meation" in r.stdout

"""`deos open <name>` — single entry primitive for project sessions.

Resolves a project (registry repo_path, else host/projects/<name>), then launches
`claude` there with the host settings injected (`--settings <host>/.claude/settings.json`)
so settings/hooks attach even though Claude Code does not walk ancestors for settings.
Host-owned sub-agent definitions are intentionally not copied or linked into projects;
Claude Code discovers the host `.claude/agents` directory by walking ancestors from
project cwd, while settings still require explicit injection.
The command string is built by a pure function (testable); the handler execs it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


class LauncherError(RuntimeError):
    """Raised when a project session cannot be launched."""


def _resolve_project_dir(host: Path, name: str) -> Path:
    from server.config import _resolve_named_project_dir

    return _resolve_named_project_dir(Path(host), name)


def build_open_command(host: Path, name: str) -> tuple[Path, list[str]]:
    """Return (cwd, argv) for launching the project session. Raises if dir missing."""
    host = Path(host)
    project_dir = _resolve_project_dir(host, name).resolve()
    if not project_dir.is_dir():
        raise LauncherError(f"project dir not found: {project_dir}")
    argv = ["claude"]
    settings = host / ".claude" / "settings.json"
    if settings.is_file():
        argv += ["--settings", str(settings)]
    return project_dir, argv


def handle_open(args) -> int:
    from server.config import host_root

    try:
        cwd, argv = build_open_command(host_root(), args.name)
    except LauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if getattr(args, "print_cmd", False):
        print(f"cd {cwd} && {' '.join(argv)}")
        return 0
    os.chdir(cwd)
    try:
        os.execvp(argv[0], argv)  # replaces process; no return on success
    except FileNotFoundError:
        print(f"error: '{argv[0]}' not found in PATH", file=sys.stderr)
        return 1
    return 0  # pragma: no cover (unreachable unless execvp fails to raise)

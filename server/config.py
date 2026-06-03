"""Configuration loader for deos server."""
from __future__ import annotations

import os
from pathlib import Path

import yaml


def host_root() -> Path:
    """Return the engine install root.

    `OS3_HOST_ROOT` env overrides (used by the launcher/daemon and tests);
    otherwise the dir containing the `server/` package.
    """
    override = os.environ.get("OS3_HOST_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


class ProjectResolutionError(RuntimeError):
    """Raised when the target project root cannot be determined."""


def _resolve_named_project_dir(host: Path, name: str) -> Path:
    """Resolve a project directory for an explicit project name.

    Precedence:
    1. Registry record with a non-empty ``repo_path`` (absolute or host-relative).
    2. Fallback: ``host/projects/<name>`` (pre-registration / empty repo_path).

    This is the single source of truth shared by ``resolve_project_root`` and
    ``launcher._resolve_project_dir`` so that ``deos open`` and ``deos dispatch``
    always resolve to the same directory.
    """
    from server.projects_registry import list_projects

    for rec in list_projects(host):
        if rec.get("name") == name and rec.get("repo_path"):
            repo_path = rec["repo_path"]
            root = Path(repo_path)
            return root if root.is_absolute() else (host / repo_path)
    return host / "projects" / name  # fallback (pre-registration / empty repo_path)


def resolve_project_root(project: str | None, *, cwd: Path, host: Path) -> Path:
    """Resolve which project dir the engine operates on.

    Precedence:
    - Explicit name: registry repo_path (absolute/host-relative) → host/projects/<name> fallback.
    - No name: cwd upward marker search (stops at host root).
      Marker: .deos.yaml only.
    """
    if project:
        host = Path(host).resolve()
        candidate = _resolve_named_project_dir(host, project)
        if not candidate.is_dir():
            raise ProjectResolutionError(f"project not found: {project} ({candidate})")
        return candidate.resolve()
    cur = Path(cwd).resolve()
    host = Path(host).resolve()
    for d in (cur, *cur.parents):
        if (d / ".deos.yaml").is_file():
            return d
        if d == host:
            break  # stop at host root; project markers live under host/projects/
    raise ProjectResolutionError(
        "no project: pass --project <name> or run inside a project dir"
    )


def load_config(config_path: str = "deos.yaml") -> dict:
    """Load host configuration from deos.yaml."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as f:
        return yaml.safe_load(f)


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base. dicts merge; lists/scalars replace."""
    out = dict(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def load_layered_config(*, project_root: Path, host: Path) -> dict:
    """Load host config defaults, deep-merged with project overlay.

    Host config: deos.yaml only.
    Project overlay: .deos.yaml only.
    """
    host_cfg_path = host / "deos.yaml"
    if not host_cfg_path.is_file():
        raise FileNotFoundError(f"host config not found: {host / 'deos.yaml'}")
    with open(host_cfg_path) as f:
        config = yaml.safe_load(f) or {}
    overlay_path = project_root / ".deos.yaml"
    if overlay_path.is_file():
        with open(overlay_path) as f:
            overlay = yaml.safe_load(f) or {}
        config = _deep_merge(config, overlay)
    return config


def get_paths(config: dict, project_root: Path | None = None) -> dict:
    """Get key file paths. Explicit project_root overrides config['project_root']."""
    root = (
        Path(project_root)
        if project_root is not None
        else Path(config.get("project_root", "."))
    )
    return {
        "root": root,
        "devos": root / config.get("devos_dir", "devos"),
        "queue": root / config.get("queue_file", "devos/tasks/QUEUE.yaml"),
        "plans": root / config.get("plans_dir", "devos/plans"),
        "logs": root / config.get("logs_dir", "devos/logs"),
    }


def resolve_paths(project: str | None, *, cwd: Path) -> tuple[dict, dict]:
    """Resolve (config, paths) for the target project.

    With an explicit `project` name or a cwd `.deos.yaml` marker, load the layered
    host+project config rooted at that project. Otherwise fall back to the legacy
    cwd-relative loader (host-maintenance / pre-migration behavior).
    """
    host = host_root()
    try:
        root = resolve_project_root(project, cwd=cwd, host=host)
    except ProjectResolutionError:
        config = load_config()
        return config, get_paths(config)
    config = load_layered_config(project_root=root, host=host)
    return config, get_paths(config, project_root=root)

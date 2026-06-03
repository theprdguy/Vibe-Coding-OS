"""Gemini subcommand handlers for the unified OS CLI."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


def _validate_ticket_id_arg(ticket_id: str) -> str:
    from server._ticket_id import TicketIdError, validate_ticket_id

    try:
        validate_ticket_id(ticket_id)
    except TicketIdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    return ticket_id


def _resolve_project_root(args) -> Optional[Path]:
    """Resolve the project root from the outer CLI's --project flag.

    T-OS3-GEMINI-TEMPLATE-SYNC (DOD-2): propagate the resolved project_root
    from the outer `deos --project <name>` flag down to gemini_dispatcher._cli_main.
    Returns None when --project was not provided (env-based fallback applies).
    """
    project_name: Optional[str] = getattr(args, "project", None)
    if project_name is None:
        return None
    # Import inline to avoid circular imports at module load time.
    try:
        from server.config import ProjectResolutionError, resolve_paths
        from server.cli import _INVOCATION_CWD
        from pathlib import Path as _Path
        cwd = _INVOCATION_CWD if _INVOCATION_CWD is not None else _Path.cwd()
        _config, paths = resolve_paths(project_name, cwd=cwd)
        # paths["devos"] is <project_root>/devos; project_root is its parent.
        return Path(paths["devos"]).parent
    except Exception:
        # If resolution fails, let _cli_main fall back to env-based path.
        return None


def handle_gemini_pending(args):
    from server.gemini_handoff import _cli_main

    return _cli_main(["pending"])


def handle_gemini_next(args):
    from server.gemini_handoff import _cli_main

    return _cli_main(["next"])


def handle_gemini_ingest(args):
    from server.gemini_handoff import _cli_main

    return _cli_main(["ingest-stdin"])


def handle_gemini_status(args):
    from server.gemini_dispatcher import _cli_main

    return _cli_main(["status"])


def handle_gemini_dispatch(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    project_root = _resolve_project_root(args)
    from server.gemini_dispatcher import _cli_main

    return _cli_main(["dispatch", ticket_id], project_root=project_root)


def handle_gemini_smoke(args):
    from server.gemini_dispatcher import _cli_main

    return _cli_main(["smoke"])

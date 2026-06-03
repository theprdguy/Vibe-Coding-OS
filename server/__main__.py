"""deos server — legacy shim entrypoint.

DEPRECATED: Use `bin/deos` (server.cli) instead.
python3 -m server is a legacy host-only shim. All commands delegate to server.cli.main.

Canonical CLI: bin/deos <command> [--project <name>] [args...]
Full command list: bin/deos --help
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# format_queue_with_header canonical home is server.ssot.
# Re-exported here to maintain backward-compat for any existing import paths.
from server.ssot import _QUEUE_HEADER_STATUSES as QUEUE_HEADER_STATUSES  # noqa: F401
from server.ssot import format_queue_with_header  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("os3")

_LEGACY_NOTE = (
    "NOTE: `python3 -m server` is a legacy shim. "
    "Use `bin/deos` (or `deos`) for the full deos CLI."
)


def main() -> None:
    """Legacy shim: delegates all commands to server.cli.main (bin/deos path)."""
    from server.cli import main as _cli_main

    args = sys.argv[1:]

    if not args:
        # No command — show deprecation note + usage from cli help
        print(_LEGACY_NOTE)
        print("Run `bin/deos --help` for the full command list.")
        sys.exit(0)

    cmd = args[0]

    # Commands that cli.main supports: delegate directly.
    # server.cli.main accepts an argv list and returns an int exit code.
    _CLI_COMMANDS = {
        "queue", "status", "logs", "pending", "archive",
        "set-status", "approve", "reject", "verify", "owner",
        "cross-model-codex", "dispatch", "dispatch-all", "dispatch-next",
        "dispatch-codex", "resume", "next", "lookup", "user-review",
        "close", "pr-check", "cost-report", "pilot-status",
        "gemini",
    }

    if cmd in _CLI_COMMANDS:
        sys.exit(_cli_main(args) or 0)

    # Unknown command — show legacy guard message and exit nonzero
    print(f"Unknown command: {cmd}", file=sys.stderr)
    print(_LEGACY_NOTE, file=sys.stderr)
    print("Run `bin/deos --help` for the full command list.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()

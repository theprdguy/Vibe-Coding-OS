"""Multi-agent dispatcher for osn-server.

Dispatches Claude 2, Codex, and Gemini for ticket execution.
Runs gate pipelines (tests, review) after completion.
Supports auto-retry on gate failure.
"""
from __future__ import annotations

import asyncio
import atexit
from contextlib import AbstractContextManager
import copy
from dataclasses import dataclass
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by monkeypatch fallback tests
    fcntl = None

from .handoff_parser import Handoff, parse_handoff
from .ssot import (
    ArchiveLockError,
    TicketResumeError,
    ValidationError,
    append_tickets,
    block_ticket,
    ensure_archive_not_locked,
    find_ticket,
    get_recent_logs,
    read_queue,
    read_queue_with_archive,
    record_review_verdict,
    resume_blocked_ticket,
    update_ticket_fields,
    update_ticket_status,
    validate_impl_ticket_files,
)

logger = logging.getLogger(__name__)
DISPATCH_OUTPUT_TAIL_LINES = 30
TIMEOUT_FALLBACK_TAIL_BYTES = 8 * 1024
VERIFY_VENV_PYTHON = ".venv/bin/python3"
ORIENTATION_START_MARKER = "# === ORIENTATION (preloaded by dispatcher) ==="
ORIENTATION_END_MARKER = "# === END ORIENTATION ==="
ORIENTATION_TRUNCATED_MARKER = "... [truncated]"
DEFAULT_SUBPROCESS_INPUT_MAX_BYTES = 180_000
QUOTA_EXHAUSTED_PATTERN = re.compile(
    r"usage limit|rate limit|quota exceeded|try again at \d+:\d+\s*(?:AM|PM)",
    re.IGNORECASE,
)
KNOWN_STDERR_NOISE_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"failed to record rollout items: thread \b[0-9a-f-]+\b not found",
        re.IGNORECASE,
    )
]
DEFAULT_POST_FAIL_HOOK_TAIL_LINES = 80
DISPATCHER_LOCK_OVERRIDE_ENV = "OS2_DISPATCHER_LOCK_PATH"
NEW_FILE_MARKER_PREFIX = "NEW:"
TICKET_PREFLIGHT_LOG_PATH = "ticket_preflight"
VALID_SCREENSHOT_TOOLS = ("playwright", "detox", "maestro", "simctl", "eas_preview")
VALID_DEVICE_TARGETS = ("web", "ios_sim", "android_emu", "physical")
USER_REVIEW_DECISION_ENV = "OS2_USER_REVIEW_DECISION"
USER_REVIEW_CAPTURE_CMD_ENV = "OS2_USER_REVIEW_CAPTURE_CMD"
QUOTA_RESET_PATTERN = re.compile(
    r"try again at (?P<reset>\d+:\d+\s*(?:AM|PM))",
    re.IGNORECASE,
)
CLAUDE1_INTERACTIVE_MESSAGE = (
    "CLAUDE1 ticket {ticket_id} must be executed interactively (see CLAUDE.md)"
)
CLAUDE1_DISPATCH_ALL_SKIP_MESSAGE = (
    "Skipped CLAUDE1 ticket {ticket_id} — execute interactively"
)
# 2026-06-15 Agent SDK policy: claude -p default command.
# --model haiku 강제 (C2 크레딧 절감; PASS/FAIL 정형 평가에 Haiku 4.5 충분).
# 세 곳(subprocess dispatch / agent_review gate / retry)에서 동일 기본값 사용 → 단일 상수화.
CLAUDE_P_DEFAULT_ARGS: list[str] = ["claude", "-p", "--model", "haiku"]
REPORT_ONLY_MODES = frozenset({"exploration", "productization"})
SOFT_REPORTABLE_GATE_NAMES = frozenset(
    {
        "test",
        "tests",
        "unit-test",
        "unit-tests",
        "integration-test",
        "integration-tests",
        "lint",
        "lints",
        "format",
        "formatting",
        "typecheck",
        "type-check",
        "visual",
        "visual-review",
        "review",
        "code-review",
    }
)
SOFT_REPORTABLE_GATE_TYPES = frozenset(
    {"test", "tests", "lint", "visual", "visual-review", "review", "agent-review"}
)
SOFT_VERIFY_TOKENS = (
    "pytest",
    " unittest",
    "npm test",
    "pnpm test",
    "yarn test",
    "vitest",
    "jest",
    "ruff",
    "flake8",
    "mypy",
    "pyright",
    "eslint",
    "tsc",
    "typecheck",
    "playwright",
    "detox",
    "maestro",
)
SOFT_VERIFY_TEST_PATTERN = re.compile(r"(?<!\S)test(?=$|[\s:])")
HARD_GATE_TOKENS = (
    "pr-check",
    "secret",
    "scan-secret",
    "scan-secrets",
    "gitleaks",
    "detect-secrets",
    "trufflehog",
    "leaks found",
)


def _is_soft_verify_signal(combined: str) -> bool:
    return any(token in combined for token in SOFT_VERIFY_TOKENS) or bool(
        SOFT_VERIFY_TEST_PATTERN.search(combined)
    )


class DispatcherSingletonError(RuntimeError):
    """Raised when another dispatcher process already owns the singleton lock."""

    def __init__(self, message: str, *, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class DispatcherSingletonLock(AbstractContextManager["DispatcherSingletonLock"]):
    """Process-level PID lock for CLI dispatcher entry points."""

    path: Path
    acquired: bool = False
    _released: bool = False
    _previous_sigint: object = None
    _previous_sigterm: object = None

    def __enter__(self) -> "DispatcherSingletonLock":
        if fcntl is None:
            print(
                "[dispatcher] warning: fcntl unavailable; skipping dispatcher singleton lock",
                file=sys.stderr,
            )
            return self

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"pid={os.getpid()}\nstarted={datetime.now().isoformat()}\n"
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise DispatcherSingletonError(_format_lock_busy_message(self.path)) from exc

        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        self.acquired = True
        atexit.register(self.release)
        self._install_signal_handlers()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
        return None

    def release(self) -> None:
        if self._released or not self.acquired:
            return
        try:
            current = _read_dispatcher_lock(self.path)
            if current.get("pid") == str(os.getpid()):
                self.path.unlink(missing_ok=True)
        finally:
            self._released = True
            self.acquired = False
            self._restore_signal_handlers()

    def _install_signal_handlers(self) -> None:
        self._previous_sigint = signal.getsignal(signal.SIGINT)
        self._previous_sigterm = signal.getsignal(signal.SIGTERM)

        def handler(signum, frame):
            self.release()
            previous = self._previous_sigint if signum == signal.SIGINT else self._previous_sigterm
            if callable(previous):
                previous(signum, frame)
                return
            if previous == signal.SIG_IGN:
                return
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _restore_signal_handlers(self) -> None:
        if self._previous_sigint is not None:
            signal.signal(signal.SIGINT, self._previous_sigint)
            self._previous_sigint = None
        if self._previous_sigterm is not None:
            signal.signal(signal.SIGTERM, self._previous_sigterm)
            self._previous_sigterm = None


def dispatcher_project_name(config: dict, paths: dict) -> str:
    """Return a stable lowercase project identifier for singleton lock naming."""
    project = config.get("project") if isinstance(config, dict) else None
    if isinstance(project, dict) and project.get("name"):
        return str(project["name"]).lower()
    root = paths.get("root") if isinstance(paths, dict) else None
    root_path = Path(root or ".")
    return root_path.name.lower() or "project"


def dispatcher_lock_path(config: dict, paths: dict) -> Path:
    """Resolve the dispatcher PID lock path, honoring explicit env override."""
    override = os.environ.get(DISPATCHER_LOCK_OVERRIDE_ENV)
    if override:
        return Path(override).expanduser()
    project_name = re.sub(r"[^a-z0-9_.-]+", "-", dispatcher_project_name(config, paths)).strip("-")
    if not project_name:
        project_name = "project"
    home_lock_dir = Path.home() / ".os3"
    try:
        home_lock_dir.mkdir(parents=True, exist_ok=True)
        probe = home_lock_dir / f".dispatcher.{os.getpid()}.probe"
        probe_fd = os.open(str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(probe_fd)
        probe.unlink(missing_ok=True)
    except OSError:
        devos_dir = Path(paths.get("devos") or Path(paths.get("root", ".")) / "devos")
        return devos_dir / ".dispatcher.pid"
    return home_lock_dir / f"dispatcher.{project_name}.pid"


def acquire_dispatcher_singleton(config: dict, paths: dict) -> DispatcherSingletonLock:
    """Create a context manager that owns the process-level dispatcher PID lock."""
    return DispatcherSingletonLock(dispatcher_lock_path(config, paths))


def _read_dispatcher_lock(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    data: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if separator:
            data[key.strip()] = value.strip()
    return data


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _format_lock_busy_message(path: Path) -> str:
    data = _read_dispatcher_lock(path)
    pid_text = data.get("pid", "unknown")
    started = data.get("started", "unknown")
    try:
        pid = int(pid_text)
    except ValueError:
        pid = -1

    if _pid_is_running(pid):
        return f"[dispatcher] another instance is running (PID {pid_text}, started {started})"
    return (
        f"[dispatcher] stale dispatcher lock found (PID {pid_text}, started {started}) at {path}. "
        f"Holder process is not running; remove it manually after confirming no dispatcher is active: "
        f"rm {path}"
    )


def _coerce_output_text(value: object) -> str:
    """Normalize captured subprocess output to text for matching and logging."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _coerce_output_bytes(value: object) -> bytes:
    """Normalize captured subprocess output to bytes for bounded tail capture."""
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8", errors="replace")


def validate_ticket(ticket: dict) -> dict:
    """Validate P0 ticket preflight requirements before dispatch starts."""
    root = Path(ticket.get("_repo_root") or Path.cwd())
    reasons: list[str] = []

    files = ticket.get("files") or []
    if isinstance(files, str):
        files = [files]

    for file_entry in files:
        file_path = str(file_entry).strip()
        if not file_path or file_path.startswith(NEW_FILE_MARKER_PREFIX):
            continue
        candidate = Path(file_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.exists():
            reasons.append(f"missing file path: {file_path}")

    verify = ticket.get("verify")
    if isinstance(verify, str) and verify.strip():
        try:
            verify_tokens = shlex.split(verify)
        except ValueError as exc:
            reasons.append(f"verify command parse failed: {exc}")
        else:
            if verify_tokens:
                verify_token = verify_tokens[0]
                repo_candidate = Path(verify_token)
                if not repo_candidate.is_absolute():
                    repo_candidate = root / repo_candidate
                if shutil.which(verify_token) is None and not repo_candidate.exists():
                    reasons.append(f"verify command token not found: {verify_token}")

    return {"ok": not reasons, "reasons": reasons}


def _normalize_ticket_file_paths(files: object) -> list[str]:
    """Return git pathspecs from ticket files, stripping deos NEW markers."""
    if isinstance(files, str):
        raw_files = [files]
    else:
        raw_files = files or []

    normalized: list[str] = []
    for file_entry in raw_files:
        path = str(file_entry).strip()
        if not path:
            continue
        if path.startswith(NEW_FILE_MARKER_PREFIX):
            path = path[len(NEW_FILE_MARKER_PREFIX):].strip()
        if path:
            normalized.append(path)
    return normalized


def _stderr_is_known_noise(stderr: str) -> bool:
    """Return whether stderr contains an allowlisted cosmetic failure pattern."""
    text = _coerce_output_text(stderr)
    return any(pattern.search(text) for pattern in KNOWN_STDERR_NOISE_PATTERNS)


def _compile_post_fail_hooks(raw_hooks: object) -> list[dict]:
    """Compile configured post-fail hook patterns at module boundary."""
    if not raw_hooks:
        return []
    if not isinstance(raw_hooks, list):
        raise ValueError("dispatch.post_fail_hooks must be a list")

    compiled_hooks: list[dict] = []
    for index, raw_hook in enumerate(raw_hooks):
        if not isinstance(raw_hook, dict):
            raise ValueError(f"dispatch.post_fail_hooks[{index}] must be a mapping")
        pattern = raw_hook.get("pattern")
        action = raw_hook.get("action")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"dispatch.post_fail_hooks[{index}].pattern must be a non-empty string")
        if not isinstance(action, str) or not action:
            raise ValueError(f"dispatch.post_fail_hooks[{index}].action must be a non-empty string")

        try:
            compiled_pattern = re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"dispatch.post_fail_hooks[{index}].pattern is invalid: {exc}"
            ) from exc

        compiled_hook = dict(raw_hook)
        compiled_hook["pattern"] = compiled_pattern
        compiled_hook["pattern_text"] = pattern
        compiled_hook["action"] = action
        compiled_hook["retry"] = bool(raw_hook.get("retry", False))
        compiled_hooks.append(compiled_hook)

    return compiled_hooks


def _find_post_fail_hook(stderr: object, hooks: list[dict]) -> dict | None:
    """Return the first hook whose compiled pattern matches failed stderr tail."""
    text = _coerce_output_text(stderr)
    lines = text.splitlines()
    stderr_tail = "\n".join(lines[-DEFAULT_POST_FAIL_HOOK_TAIL_LINES:])
    for hook in hooks:
        pattern = hook.get("pattern")
        if pattern.search(stderr_tail):
            return hook
    return None


class Dispatcher:
    """Dispatches builder agents for ticket execution."""

    def __init__(self, config: dict, paths: dict, notify_callback=None, host=None):
        """
        notify_callback: async callable(message: str) for completion notifications.
        host: host-OS root for doctrine/orientation resolution (defaults to host_root()).
              Project state stays under paths["root"]; doctrine is host-single-sourced (β).
        """
        from server.config import host_root
        from server._dispatcher.prompt_builder import PromptBuilder
        self.config = config
        self.paths = paths
        self.notify = notify_callback
        self.host = Path(host).resolve() if host is not None else host_root()
        self.agent_configs = config.get("agents", {})
        self._prompt_builder = PromptBuilder(config=config, host=self.host, paths=paths)
        self.post_fail_hooks = _compile_post_fail_hooks(
            config.get("dispatch", {}).get("post_fail_hooks")
        )
        self._running: dict[str, subprocess.Popen] = {}  # ticket_id -> process
        self._threads: dict[str, threading.Thread] = {}  # ticket_id -> thread
        self._preflight_cache: dict[str, tuple[bool, str]] = {}
        self._dispatch_failures: dict[str, str] = {}
        self._dispatch_start_failed = False
        self._quota_exhausted = False
        self._quota_reset: str | None = None
        self._state_lock = threading.RLock()

    # ── Public API ──────────────────────────────────────────────────────────

    def dispatch(self, ticket_id: str, *, fatal_status_mismatch: bool = True) -> tuple[bool, str]:
        """
        Dispatch a single ticket to its assigned agent.
        Returns (success, message).
        """
        with self._state_lock:
            try:
                data = read_queue(self.paths["queue"])
            except ValidationError as exc:
                return self._dispatch_error(f"ValidationError: {exc}")
            try:
                ensure_archive_not_locked(self.paths["queue"])
            except ArchiveLockError as exc:
                return self._dispatch_error(str(exc))
            ticket = next((t for t in data.get("tickets", []) if t.get("id") == ticket_id), None)

            if not ticket:
                archived_ticket, source = find_ticket(self.paths["queue"], ticket_id)
                if source == "archive" and archived_ticket and archived_ticket.get("status") == "done":
                    msg = "ticket already done (in archive)"
                    print(msg, file=sys.stderr)
                    return self._dispatch_error(msg)
                return self._dispatch_error(f"Ticket `{ticket_id}` not found in queue.")

            if self._quota_exhausted:
                return self._dispatch_error(self._format_quota_stop_message(), fatal=False)

            status = ticket.get("status")
            if status not in ("todo",):
                return self._dispatch_error(
                    f"Ticket `{ticket_id}` is `{status}`, not `todo`. Cannot dispatch.",
                    fatal=fatal_status_mismatch,
                )

            ticket_validation = validate_ticket({**ticket, "_repo_root": str(self.paths["root"])})
            if not ticket_validation["ok"]:
                reason = "ticket_preflight_failed: " + "; ".join(ticket_validation["reasons"])
                with self._state_lock:
                    block_ticket(self.paths["queue"], ticket_id, reason, TICKET_PREFLIGHT_LOG_PATH)
                print(reason, file=sys.stderr)
                return self._dispatch_error(reason)

            owner = ticket.get("owner")
            target_owner = ticket.get("impl_owner") or owner
            if self._is_claude1_interactive_ticket(ticket):
                msg = CLAUDE1_INTERACTIVE_MESSAGE.format(ticket_id=ticket_id)
                print(msg, file=sys.stderr)
                return self._dispatch_error(msg)
            if target_owner not in self.agent_configs:
                return self._dispatch_error(f"Unknown owner `{target_owner}` for ticket `{ticket_id}`.")

            dispatch_snapshot_sha = self._capture_dispatch_snapshot(ticket_id)
            if dispatch_snapshot_sha is None:
                return self._dispatch_error(
                    f"Could not capture dispatch snapshot for ticket `{ticket_id}`."
                )

            # Fallback: if agent not available, use fallback agent
            resolved_owner, fallback_reason = self._resolve_agent(target_owner)

            # Check dependencies against active tickets plus archived done tickets.
            deps = ticket.get("deps", [])
            if deps:
                dependency_data = read_queue_with_archive(self.paths["queue"])
                blocked_by = self._check_deps(dependency_data, deps)
                if blocked_by:
                    return self._dispatch_error(
                        f"Ticket `{ticket_id}` blocked by: {', '.join(blocked_by)}",
                        fatal=False,
                    )

            # Check concurrent limit
            max_concurrent = self.config.get("dispatch", {}).get("max_concurrent", 2)
            if len(self._running) >= max_concurrent:
                return self._dispatch_error(
                    f"At capacity ({max_concurrent} agents running). Wait for completion.",
                    fatal=False,
                )

            # Check scope overlap (if scope_check enabled)
            if self.config.get("dispatch", {}).get("scope_check", True):
                conflict = self._check_scope_conflict(ticket, data)
                if conflict:
                    return self._dispatch_error(
                        f"Ticket `{ticket_id}` file scope conflicts with running ticket `{conflict}`.",
                        fatal=False,
                    )

            try:
                # BLOCKER 2 fix: enforce non-empty files scope on BUILDER/CODEX
                # tickets at dispatch time — fail-closed before agent runs.
                validate_impl_ticket_files(ticket)
                resolved_gates = self._resolve_gates(ticket)
                # BLOCKER 1 fix (direction b): enforce agent-review gate presence
                # at dispatch time for all BUILDER/CODEX impl tickets that require
                # a verdict.  Called here (not in _validate_production_gate_requirements)
                # to avoid retroactively breaking archived-ticket gate resolution.
                self._validate_impl_ticket_agent_review_gate(ticket, resolved_gates)
            except ValidationError as exc:
                return self._dispatch_error(f"ValidationError: {exc}")

            preflight_ok, preflight_msg = self._run_preflight(resolved_owner)
            if not preflight_ok:
                print(preflight_msg, file=sys.stderr)
                return self._dispatch_error(preflight_msg)

            if fallback_reason:
                update_ticket_fields(
                    self.paths["queue"],
                    ticket_id,
                    {
                        "_dispatch_owner": resolved_owner,
                        "_original_impl_owner": ticket.get("_original_impl_owner", target_owner),
                        "_fallback_reason": fallback_reason,
                    },
                )

            # Dispatch
            update_ticket_status(
                self.paths["queue"],
                ticket_id,
                "doing",
                reason="dispatch started",
                actor="dispatcher",
            )
            runtime_ticket = self._build_runtime_ticket(ticket, resolved_owner)
            thread = threading.Thread(
                target=self._run_agent,
                args=(runtime_ticket, dispatch_snapshot_sha),
                daemon=False,
            )
            self._running[ticket_id] = None  # Mark as running before releasing dispatch lock.
            self._threads[ticket_id] = thread
            thread.start()
            return True, f"Dispatched `{ticket_id}` to {resolved_owner}."

    def dispatch_all_todo(self) -> list[tuple[str, str]]:
        """
        Dispatch all tickets that are todo (deps satisfied).
        Blocks until all dispatched agents finish (required for CLI mode).
        Returns list of (ticket_id, message).
        """
        try:
            data = read_queue(self.paths["queue"])
        except ValidationError as exc:
            msg = f"ValidationError: {exc}"
            print(msg, file=sys.stderr)
            self._dispatch_error(msg)
            self.wait_all()
            return [("QUEUE", msg)]

        preflight_ok, preflight_msg = self._run_dispatch_all_preflight(data)
        if not preflight_ok:
            print(preflight_msg, file=sys.stderr)
            self._dispatch_error(preflight_msg)
            self.wait_all()
            return [("PREFLIGHT", preflight_msg)]

        results = []
        for ticket in data.get("tickets", []):
            if ticket.get("status") != "todo":
                continue
            if self._quota_exhausted:
                results.append((ticket["id"], self._format_quota_stop_message()))
                break
            if self._is_claude1_interactive_ticket(ticket):
                results.append((ticket["id"], self._format_claude1_dispatch_all_skip(ticket)))
                continue
            ok, msg = self.dispatch(ticket["id"])
            results.append((ticket["id"], msg))
        self.wait_all()
        return results

    def resume(self, ticket_id: str) -> tuple[bool, str]:
        """Resume a blocked ticket, then immediately dispatch it."""
        try:
            resume_blocked_ticket(self.paths["queue"], ticket_id)
        except TicketResumeError as exc:
            return self._dispatch_error(str(exc))

        print(
            f"Resumed `{ticket_id}`. Confirm the blocked cause is resolved; "
            "dispatch may fail again for the same reason."
        )
        return self.dispatch(ticket_id)

    def user_review(self, ticket_id: str) -> tuple[bool, str]:
        """Run the user-outcome-review workflow for a ticket."""
        ticket, _source = find_ticket(self.paths["queue"], ticket_id)
        if ticket is None:
            return True, f"SKIP user-outcome-review: ticket not found: {ticket_id}"
        try:
            return self._run_user_outcome_review(ticket, allow_prompt=True)
        except ValidationError as exc:
            return False, f"ValidationError: {exc}"

    def wait_all(self) -> None:
        """Block until all running agent threads have finished."""
        while True:
            with self._state_lock:
                threads = list(self._threads.values())
            if not threads:
                with self._state_lock:
                    failures = dict(self._dispatch_failures)
                    self._dispatch_failures.clear()
                    dispatch_start_failed = self._dispatch_start_failed
                    self._dispatch_start_failed = False
                if failures:
                    for message in failures.values():
                        print(message)
                    raise SystemExit(1)
                if dispatch_start_failed:
                    raise SystemExit(1)
                return
            for thread in threads:
                thread.join()

    def get_running(self) -> list[str]:
        """Return list of currently running ticket IDs."""
        with self._state_lock:
            return list(self._running.keys())

    # ── Internal ─────────────────────────────────────────────────────────────

    def _dispatch_error(self, message: str, *, fatal: bool = True) -> tuple[bool, str]:
        """Return a dispatch failure, recording fatal start failures for CLI exit."""
        if fatal:
            with self._state_lock:
                self._dispatch_start_failed = True
        return False, message

    def _is_claude1_interactive_ticket(self, ticket: dict) -> bool:
        """Return whether a ticket is owned by CLAUDE1 and must not be subprocess-dispatched."""
        return ticket.get("owner") == "CLAUDE1"

    def _format_claude1_dispatch_all_skip(self, ticket: dict) -> str:
        """Return the dispatch-all reminder for a CLAUDE1-owned ticket."""
        return CLAUDE1_DISPATCH_ALL_SKIP_MESSAGE.format(ticket_id=ticket.get("id"))

    def _detect_quota_reset(self, stderr: str) -> str | None:
        """Return the quota reset time when stderr contains a Codex quota error."""
        stderr = _coerce_output_text(stderr)
        if not QUOTA_EXHAUSTED_PATTERN.search(stderr or ""):
            return None
        reset_match = QUOTA_RESET_PATTERN.search(stderr or "")
        if not reset_match:
            return "unknown"
        return re.sub(r"\s+", " ", reset_match.group("reset").strip()).upper()

    def _format_quota_stop_message(self, reset: str | None = None) -> str:
        """Return the standardized quota exhaustion message for CLI output."""
        reset_value = reset if reset is not None else self._quota_reset
        if reset_value and reset_value != "unknown":
            return f"Codex quota exhausted, reset at {reset_value}"
        return "Codex quota exhausted, reset unknown"

    def _format_quota_blocked_reason(self, reason: str, reset: str) -> str:
        """Return the blocked reason prefix while preserving the original reason."""
        if reset == "unknown":
            return f"quota_exhausted (reset unknown); {reason}"
        return f"quota_exhausted: {reset}; {reason}"

    def _record_quota_exhausted(self, reset: str) -> str:
        """Remember quota exhaustion and emit the standardized stderr notice."""
        with self._state_lock:
            self._quota_exhausted = True
            self._quota_reset = reset
        message = self._format_quota_stop_message(reset)
        print(message, file=sys.stderr)
        return message

    def _is_agent_available(self, agent_name: str) -> bool:
        """Check if an agent is configured and available to run."""
        agent_cfg = self.agent_configs.get(agent_name, {})
        config_dir = agent_cfg.get("config_dir")
        if config_dir:
            # Agent requires a config directory — check credentials exist
            creds = Path(config_dir) / ".claude.json"
            if not creds.exists():
                logger.info(f"{agent_name} not available: {creds} not found")
                return False
        return True

    def _resolve_agent(self, owner: str) -> tuple[str, str | None]:
        """Resolve agent, returning (owner, fallback_reason)."""
        if self._is_agent_available(owner):
            return owner, None
        fallback = self.agent_configs.get(owner, {}).get("fallback")
        if fallback:
            reason = f"{owner} unavailable"
            logger.warning(f"{owner} not available — falling back to {fallback}")
            return fallback, reason
        return owner, None

    def _run_preflight(self, owner: str) -> tuple[bool, str]:
        """Run target-agent preflight before mutating ticket status."""
        if owner in self._preflight_cache:
            return self._preflight_cache[owner]

        scripts = {
            "CODEX": "scripts/preflight-codex.sh",
        }
        script = scripts.get(owner)
        if not script:
            result = (True, "preflight skipped")
            self._preflight_cache[owner] = result
            return result

        # OS-owned preflight script lives at the HOST (not the project); run it
        # with cwd=project so it inspects the project. Skip gracefully if absent.
        script_path = self.host / script
        if not script_path.is_file():
            result = (True, "preflight skipped (host script not found)")
            self._preflight_cache[owner] = result
            return result
        try:
            result = subprocess.run(
                ["bash", str(script_path)],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(self.paths["root"]),
            )
        except subprocess.TimeoutExpired:
            result = (False, f"[preflight] {owner.lower()} preflight timed out")
            self._preflight_cache[owner] = result
            return result

        if result.returncode == 0:
            preflight_result = (True, "preflight passed")
            self._preflight_cache[owner] = preflight_result
            return preflight_result

        output = (result.stderr or result.stdout or f"[preflight] {owner.lower()} preflight failed").strip()
        preflight_result = (False, output)
        self._preflight_cache[owner] = preflight_result
        return preflight_result

    def _run_dispatch_all_preflight(self, data: dict) -> tuple[bool, str]:
        """Preflight each eligible dispatch target once before dispatch-all starts."""
        try:
            dependency_data = read_queue_with_archive(self.paths["queue"])
        except ValidationError as exc:
            return False, f"ValidationError: {exc}"

        owners: list[str] = []
        for ticket in data.get("tickets", []):
            if ticket.get("status") != "todo":
                continue
            if self._is_claude1_interactive_ticket(ticket):
                continue
            if self._check_deps(dependency_data, ticket.get("deps", [])):
                continue

            target_owner = ticket.get("impl_owner") or ticket.get("owner")
            if target_owner not in self.agent_configs:
                return False, f"Unknown owner `{target_owner}` for ticket `{ticket.get('id')}`."

            resolved_owner, _fallback_reason = self._resolve_agent(target_owner)
            if resolved_owner not in owners:
                owners.append(resolved_owner)

        for owner in owners:
            ok, msg = self._run_preflight(owner)
            if not ok:
                return False, msg

        return True, "preflight passed"

    def _capture_dispatch_snapshot(self, ticket_id: str) -> str | None:
        """Return the HEAD SHA used as this dispatch's diff baseline."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.paths["root"]),
            )
        except Exception as exc:
            logger.error("Could not capture dispatch snapshot for %s: %s", ticket_id, exc)
            return None

        if result.returncode != 0:
            error_output = (result.stderr or result.stdout or "git rev-parse failed").strip()
            logger.error("Could not capture dispatch snapshot for %s: %s", ticket_id, error_output)
            return None

        snapshot_sha = result.stdout.strip()
        if not snapshot_sha:
            logger.error("Could not capture dispatch snapshot for %s: empty HEAD SHA", ticket_id)
            return None
        return snapshot_sha

    def _check_deps(self, data: dict, deps: list[str]) -> list[str]:
        """Return list of unfinished dependency ticket IDs."""
        tickets_by_id = {t["id"]: t for t in data.get("tickets", [])}
        return [d for d in deps if tickets_by_id.get(d, {}).get("status") != "done"]

    def _check_scope_conflict(self, ticket: dict, data: dict) -> str | None:
        """Return conflicting ticket_id if file scope overlaps with a running ticket."""
        my_files = set(ticket.get("files", []))
        for running_id in list(self._running):
            running_ticket = next(
                (t for t in data.get("tickets", []) if t.get("id") == running_id), None
            )
            if not running_ticket:
                continue
            their_files = set(running_ticket.get("files", []))
            if my_files & their_files:
                return running_id
        return None

    def _build_runtime_ticket(self, ticket: dict, owner: str) -> dict:
        """Return an execution-local ticket copy with the resolved owner."""
        runtime_ticket = copy.deepcopy(ticket)
        runtime_ticket["owner"] = owner
        return runtime_ticket

    def _auto_chain_enabled(self) -> bool:
        """Return whether post-completion dispatch chaining is enabled."""
        return bool(self.config.get("dispatch", {}).get("auto_chain", False))

    def _dispatch_auto_chain_todo(self) -> list[tuple[str, str]]:
        """
        Dispatch todo tickets after a completion when auto_chain is enabled.

        This re-scans the queue so downstream tickets unlocked by a `done` status,
        and tickets previously skipped due to capacity, can start without manual re-run.
        """
        if not self._auto_chain_enabled():
            return []

        try:
            with self._state_lock:
                data = read_queue(self.paths["queue"])
        except ValidationError as exc:
            return [("QUEUE", f"ValidationError: {exc}")]
        results: list[tuple[str, str]] = []
        for ticket in data.get("tickets", []):
            if ticket.get("status") != "todo":
                continue
            if self._quota_exhausted:
                break
            if self._is_claude1_interactive_ticket(ticket):
                results.append((ticket["id"], self._format_claude1_dispatch_all_skip(ticket)))
                continue
            if self._check_deps(data, ticket.get("deps", [])):
                continue

            ok, msg = self.dispatch(ticket["id"], fatal_status_mismatch=False)
            results.append((ticket["id"], msg))
            if "At capacity" in msg:
                break

        return results

    def _run_agent(self, ticket: dict, dispatch_snapshot_sha: str) -> None:
        """Run an agent for a ticket in a background thread."""
        ticket_id = ticket["id"]
        owner = ticket["owner"]
        agent_cfg = self.agent_configs.get(owner, {})
        mode = agent_cfg.get("mode", "subprocess")
        completed_done = False
        auto_chain_results: list[tuple[str, str]] = []

        logger.info(f"Starting {owner} for {ticket_id} (mode: {mode})")

        try:
            if mode in ("subprocess", "pipe"):
                success, failure = self._run_subprocess(ticket, agent_cfg)
            else:
                logger.error(f"Unknown mode {mode} for {owner}")
                success = False
                failure = {"reason": f"unknown mode {mode}"}

            if not success:
                success, failure = self._maybe_run_post_fail_hook(
                    ticket,
                    agent_cfg,
                    success,
                    failure,
                )

            if not success:
                if _stderr_is_known_noise(failure.get("stderr") or ""):
                    allowed_msg = self._handle_known_stderr_noise_failure(
                        ticket,
                        owner,
                        failure,
                        dispatch_snapshot_sha,
                    )
                    log_summary = self._get_agent_log(owner, ticket_id)
                    msg = f"{allowed_msg}\n{log_summary}".strip()
                    if self.notify:
                        asyncio.run(self._send_notify(msg))
                    completed_done = msg.startswith("[DONE]")
                    if msg.startswith("[BLOCKED]"):
                        with self._state_lock:
                            self._dispatch_failures[ticket_id] = msg
                    return
                failure_msg = self._handle_dispatch_failure(ticket, owner, failure)
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"{failure_msg}\n{log_summary}".strip()
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            handoff = self._extract_agent_handoff(owner, ticket_id, failure.get("stdout"))
            if handoff is None:
                logger.warning(
                    "Agent succeeded for %s but no complete handoff was found; "
                    "leaving ticket status as doing",
                    ticket_id,
                )
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = (
                    f"[WARNING] {ticket_id} completed subprocess without handoff; "
                    "status remains doing"
                )
                if log_summary:
                    msg = f"{msg}\n{log_summary}"
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            if not handoff.block_is_none:
                block_reason = f"agent_self_blocked: {handoff.block}"
                stdout = _coerce_output_text(failure.get("stdout"))
                stderr = _coerce_output_text(failure.get("stderr"))
                log_path = self._write_dispatch_failure_log(
                    ticket_id=ticket_id,
                    owner=owner,
                    reason=block_reason,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=failure.get("returncode"),
                )
                with self._state_lock:
                    self._mark_agent_self_blocked(ticket_id, handoff.block)
                msg = f"[BLOCKED] {ticket_id} agent self-blocked: {handoff.block}"
                self._dispatch_failures[ticket_id] = f"{msg}; log: {log_path}"
                log_summary = self._get_agent_log(owner, ticket_id)
                if log_summary:
                    msg = f"{msg}\n{log_summary}"
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            no_diff_failure = self._detect_no_ticket_file_diff(
                ticket,
                failure,
                dispatch_snapshot_sha,
            )
            if no_diff_failure:
                failure_msg = self._handle_dispatch_failure(ticket, owner, no_diff_failure)
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"{failure_msg}\n{log_summary}".strip()
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            # Agent succeeded — run gate pipeline
            failure_msg = self._mark_ticket_code_ready(
                ticket,
                "agent completed; awaiting gates and required reviews",
            )
            if failure_msg:
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"{failure_msg}\n{log_summary}".strip()
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return
            try:
                gates_passed, gate_msg = self._run_gates(ticket, dispatch_snapshot_sha)
            except Exception as exc:
                logger.exception("Gate evaluation failed for %s: %s", ticket_id, exc)
                failure_msg = self._handle_dispatch_failure(
                    ticket,
                    owner,
                    {
                        "reason": f"gate_exception: {exc}",
                        "stdout": _coerce_output_text(failure.get("stdout")),
                        "stderr": _coerce_output_text(failure.get("stderr")),
                        "returncode": failure.get("returncode"),
                    },
                )
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"{failure_msg}\n{log_summary}".strip()
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            if gates_passed:
                review_passed, review_msg = self._run_user_outcome_review(
                    ticket,
                    allow_prompt=False,
                )
                if not review_passed:
                    msg = f"[BLOCKED] {ticket_id} {review_msg}"
                    with self._state_lock:
                        self._dispatch_failures[ticket_id] = msg
                    if self.notify:
                        asyncio.run(self._send_notify(msg))
                    return
                done_reason = "agent completed + gates pass"
                done_suffix = "gates passed"
                if "[REPORTED]" in gate_msg:
                    done_reason = f"{done_reason}: {gate_msg}"
                    done_suffix = f"gates passed with reports: {gate_msg}"
                failure_msg = self._mark_ticket_done(ticket, done_reason)
                if failure_msg:
                    log_summary = self._get_agent_log(owner, ticket_id)
                    msg = f"{failure_msg}\n{log_summary}".strip()
                    if self.notify:
                        asyncio.run(self._send_notify(msg))
                    return
                completed_done = True
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"[DONE] {ticket_id} completed by {owner} ({done_suffix})\n{log_summary}"
            else:
                # Gates failed — attempt retry
                logger.warning(f"Gates failed for {ticket_id}: {gate_msg}")
                retry_success = self._attempt_retry(ticket, gate_msg, dispatch_snapshot_sha)

                if retry_success:
                    # Re-run gates after retry
                    try:
                        gates_passed_2, gate_msg_2 = self._run_gates(
                            ticket,
                            dispatch_snapshot_sha,
                        )
                    except Exception as exc:
                        logger.exception(
                            "Gate evaluation failed after retry for %s: %s",
                            ticket_id,
                            exc,
                        )
                        failure_msg = self._handle_dispatch_failure(
                            ticket,
                            owner,
                            {
                                "reason": f"gate_exception: {exc}",
                                "stdout": _coerce_output_text(failure.get("stdout")),
                                "stderr": _coerce_output_text(failure.get("stderr")),
                                "returncode": failure.get("returncode"),
                            },
                        )
                        log_summary = self._get_agent_log(owner, ticket_id)
                        msg = f"{failure_msg}\n{log_summary}".strip()
                        if self.notify:
                            asyncio.run(self._send_notify(msg))
                        return
                    if gates_passed_2:
                        review_passed, review_msg = self._run_user_outcome_review(
                            ticket,
                            allow_prompt=False,
                        )
                        if not review_passed:
                            msg = f"[BLOCKED] {ticket_id} {review_msg}"
                            with self._state_lock:
                                self._dispatch_failures[ticket_id] = msg
                            if self.notify:
                                asyncio.run(self._send_notify(msg))
                            return
                        done_reason = "agent completed + gates pass after retry"
                        done_suffix = "passed after retry"
                        if "[REPORTED]" in gate_msg_2:
                            done_reason = f"{done_reason}: {gate_msg_2}"
                            done_suffix = f"passed after retry with reports: {gate_msg_2}"
                        failure_msg = self._mark_ticket_done(ticket, done_reason)
                        if failure_msg:
                            log_summary = self._get_agent_log(owner, ticket_id)
                            msg = f"{failure_msg}\n{log_summary}".strip()
                            if self.notify:
                                asyncio.run(self._send_notify(msg))
                            return
                        completed_done = True
                        msg = f"[DONE] {ticket_id} completed by {owner} ({done_suffix})\n{gate_msg_2}"
                    else:
                        with self._state_lock:
                            self._mark_verify_failed_after_done_claim(ticket_id, gate_msg_2)
                        msg = f"[BLOCKED] {ticket_id} gates still failing after retry: {gate_msg_2}"
                else:
                    with self._state_lock:
                        self._mark_verify_failed_after_done_claim(ticket_id, gate_msg)
                    msg = f"[BLOCKED] {ticket_id} gates failed: {gate_msg}"

            if self.notify:
                asyncio.run(self._send_notify(msg))

        except Exception as e:
            logger.exception(f"Error running {owner} for {ticket_id}: {e}")
            self._handle_dispatch_failure(
                ticket,
                owner,
                {
                    "reason": f"dispatcher error: {e}",
                    "stdout": "",
                    "stderr": "",
                    "returncode": None,
                },
            )
            if self.notify:
                asyncio.run(self._send_notify(f"❌ `{ticket_id}` error: {e}"))
        finally:
            with self._state_lock:
                self._running.pop(ticket_id, None)
                self._threads.pop(ticket_id, None)
            if completed_done:
                auto_chain_results = self._dispatch_auto_chain_todo()
                if auto_chain_results:
                    auto_chain_lines = "\n".join(
                        f"- {downstream_id}: {downstream_msg}"
                        for downstream_id, downstream_msg in auto_chain_results
                    )
                    logger.info(f"Auto-chain results after {ticket_id}:\n{auto_chain_lines}")

    # ── Prompt-builder cluster — delegated to server._dispatcher.PromptBuilder ──
    # All implementation lives in server/_dispatcher/prompt_builder.py.
    # These thin wrappers preserve the existing Dispatcher method API exactly so
    # callers (including tests) require no changes.

    def _build_prompt(self, ticket: dict, *, owner: str | None = None) -> str:
        """Build the prompt string for an agent. Delegates to PromptBuilder."""
        return self._prompt_builder.build_prompt(ticket, owner=owner)

    def _build_orientation_header(self, *, max_bytes: int | None = None) -> str:
        """Compose the optional read-only dispatcher orientation header. Delegates to PromptBuilder."""
        return self._prompt_builder.build_orientation_header(max_bytes=max_bytes)

    def _orientation_file_spec(self, entry: object) -> tuple[str | None, object]:
        """Return (path, range) from a string or mapping orientation file spec. Delegates to PromptBuilder."""
        return self._prompt_builder._orientation_file_spec(entry)

    def _slice_orientation_content(self, content: str, range_spec: object) -> str:
        """Apply a one-based inclusive line range to orientation content. Delegates to PromptBuilder."""
        return self._prompt_builder._slice_orientation_content(content, range_spec)

    def _truncate_orientation_header(self, header: str, max_bytes: int) -> str:
        """Byte-safe truncate while preserving markers. Delegates to PromptBuilder."""
        return self._prompt_builder._truncate_orientation_header(header, max_bytes)

    def _truncate_bytes(self, text: str, max_bytes: int) -> str:
        """Truncate UTF-8 text without splitting a code point. Delegates to PromptBuilder."""
        return self._prompt_builder._truncate_bytes(text, max_bytes)

    def _fit_prompt_to_input_limit(
        self,
        *,
        ticket_prompt: str,
        orientation: str,
        ticket_id: str,
        owner: str | None,
    ) -> str:
        """Shrink optional orientation when the combined subprocess input is too large. Delegates to PromptBuilder."""
        return self._prompt_builder._fit_prompt_to_input_limit(
            ticket_prompt=ticket_prompt,
            orientation=orientation,
            ticket_id=ticket_id,
            owner=owner,
        )

    def _ticket_to_yaml(self, ticket: dict) -> str:
        """Serialize a ticket to YAML. Delegates to PromptBuilder."""
        return self._prompt_builder._ticket_to_yaml(ticket)

    def _tail_lines(self, text: str, limit: int = DISPATCH_OUTPUT_TAIL_LINES) -> str:
        """Return the last non-empty output lines for immediate failure summaries."""
        text = _coerce_output_text(text)
        lines = (text or "").splitlines()
        return "\n".join(lines[-limit:])

    def _agent_claimed_done(self, stdout: object) -> bool:
        """Return whether subprocess output contains a successful handoff block."""
        text = _coerce_output_text(stdout)
        has_done = False
        has_next = False
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^Done\s*:", stripped, re.IGNORECASE):
                has_done = True
            elif re.match(r"^Next\s*:", stripped, re.IGNORECASE):
                has_next = True
            else:
                block_match = re.match(r"^Block\s*:\s*(.+?)\s*$", stripped, re.IGNORECASE)
                if block_match and has_done and has_next:
                    return block_match.group(1).strip().lower() == "none"
        return False

    def _agent_handoff_block_reason(self, stdout: object) -> str | None:
        """Return a non-none Block handoff reason when subprocess output has one."""
        text = _coerce_output_text(stdout)
        has_done = False
        has_next = False
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^Done\s*:", stripped, re.IGNORECASE):
                has_done = True
            elif re.match(r"^Next\s*:", stripped, re.IGNORECASE):
                has_next = True
            else:
                block_match = re.match(r"^Block\s*:\s*(.+?)\s*$", stripped, re.IGNORECASE)
                if block_match and has_done and has_next:
                    reason = block_match.group(1).strip()
                    return None if reason.lower() == "none" else reason
        return None

    def _extract_agent_handoff(
        self,
        owner: str,
        ticket_id: str,
        stdout: object,
    ) -> Handoff | None:
        """Parse handoff from the latest matching session log, then stdout."""
        logs_path = self.paths["logs"]
        agent_name = owner.lower().replace("1", "1").replace("2", "2")
        for log_file in get_recent_logs(logs_path, limit=10):
            if agent_name not in log_file.name.lower() or ticket_id not in log_file.name:
                continue
            try:
                parsed = parse_handoff(log_file.read_text(encoding="utf-8"))
            except OSError as exc:
                logger.warning(f"Could not read session log {log_file}: {exc}")
                continue
            if parsed is not None:
                return parsed

        return parse_handoff(_coerce_output_text(stdout))

    def _mark_agent_self_blocked(self, ticket_id: str, reason: str) -> None:
        """Persist blocked status when the final handoff contains Block: non-none."""
        block_ticket(
            self.paths["queue"],
            ticket_id,
            f"agent_self_blocked: {reason}",
            "",
        )

    def _mark_verify_failed_after_done_claim(self, ticket_id: str, gate_msg: str) -> None:
        """Persist the V37 blocked metadata for a done handoff with failed verify."""
        block_ticket(
            self.paths["queue"],
            ticket_id,
            "verify_failed_but_agent_claimed_done",
            "",
        )
        self._dispatch_failures[ticket_id] = (
            f"[BLOCKED] {ticket_id} verify failed but agent claimed done: {gate_msg}"
        )

    def _mark_ticket_code_ready(
        self,
        ticket: dict,
        reason: str,
    ) -> str | None:
        """Mark a ticket code_ready, returning an explicit failure if SSOT write fails."""
        ticket_id = ticket["id"]
        try:
            with self._state_lock:
                update_ticket_status(
                    self.paths["queue"],
                    ticket_id,
                    "code_ready",
                    reason=reason,
                    actor="dispatcher",
                    record_history=True,
                )
        except Exception as exc:
            logger.exception("SSOT update failed while marking %s code_ready: %s", ticket_id, exc)
            return self._handle_dispatch_failure(
                ticket,
                ticket["owner"],
                {
                    "reason": f"ssot_update_failed: {exc}",
                    "stdout": "",
                    "stderr": "",
                    "returncode": None,
                },
            )
        return None

    def _mark_ticket_done(
        self,
        ticket: dict,
        reason: str,
        *,
        override: bool = False,
        override_reason: str = "",
        override_actor: str = "",
    ) -> str | None:
        """Mark a ticket done, returning an explicit failure if SSOT write fails.

        Verdict must already be on the ticket before this is called — set by
        _run_gates when the agent-review gate executes and returns PASS.
        _validate_production_gate_requirements enforces agent-review gate presence
        at dispatch-start, so by the time this method is reached the verdict is set.

        override=True (with override_reason + override_actor) propagates to
        update_ticket_status, bypassing the state-machine + verdict check.
        When override is used the history entry records override:true loudly.
        """
        ticket_id = ticket["id"]
        try:
            with self._state_lock:
                # BLOCKER 1 fix: the unconditional dispatcher-auto verdict recording
                # has been removed.  _review_verdict is now set ONLY when an
                # agent-review gate actually executes and returns PASS (see _run_gates).
                # _validate_production_gate_requirements ensures impl tickets declare
                # an agent-review gate before dispatch starts, so by the time
                # _mark_ticket_done is called the verdict is already on the ticket.
                # override=True path propagates to update_ticket_status with override=True,
                # bypassing the verdict check as the emergency escape hatch.
                if override:
                    effective_reason = override_reason or reason
                    effective_actor = override_actor or "dispatcher"
                    update_ticket_status(
                        self.paths["queue"],
                        ticket_id,
                        "done",
                        reason=effective_reason,
                        actor=effective_actor,
                        record_history=True,
                        override=True,
                    )
                else:
                    update_ticket_status(
                        self.paths["queue"],
                        ticket_id,
                        "done",
                        reason=reason,
                        actor="dispatcher",
                        record_history=True,
                    )
        except Exception as exc:
            logger.exception("SSOT update failed while marking %s done: %s", ticket_id, exc)
            return self._handle_dispatch_failure(
                ticket,
                ticket["owner"],
                {
                    "reason": f"ssot_update_failed: {exc}",
                    "stdout": "",
                    "stderr": "",
                    "returncode": None,
                },
            )
        return None

    def _relative_log_path(self, path: Path) -> str:
        """Return a project-relative path when possible."""
        try:
            return str(path.relative_to(self.paths["root"]))
        except ValueError:
            return str(path)

    def _next_available_log_path(self, base_path: Path) -> Path:
        """Return base_path or a numeric-suffixed sibling without overwriting."""
        if not base_path.exists():
            return base_path

        for index in range(1, 10_000):
            candidate = base_path.with_name(f"{base_path.stem}-{index}{base_path.suffix}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"could not allocate unique log path for {base_path}")

    def _tail_bytes_capture(
        self,
        value: object,
        *,
        max_bytes: int = TIMEOUT_FALLBACK_TAIL_BYTES,
    ) -> tuple[str, int, int]:
        """Return UTF-8 text for the last max_bytes of captured output."""
        raw = _coerce_output_bytes(value)
        tail = raw[-max_bytes:]
        text = tail.decode("utf-8", errors="replace")
        while len(text.encode("utf-8")) > max_bytes:
            text = text[1:]
        return text, len(tail), len(raw)

    def _write_timeout_fallback_session_log(
        self,
        ticket: dict,
        *,
        timeout: int,
        stdout: object,
        stderr: object,
    ) -> str:
        """Write the CODEX timeout fallback session log and return its relative path."""
        ticket_id = str(ticket["id"])
        date = datetime.now().strftime("%Y-%m-%d")
        log_dir = self.paths["logs"]
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self._next_available_log_path(
            log_dir / f"{date}-codex-{ticket_id}-timeout.md"
        )
        rel_path = self._relative_log_path(log_file)

        stdout_tail, stdout_captured, stdout_total = self._tail_bytes_capture(stdout)
        stderr_tail, stderr_captured, stderr_total = self._tail_bytes_capture(stderr)

        log_file.write_text(
            "\n".join(
                [
                    f"# Session Log: CODEX - {date}",
                    f"Tickets: {ticket_id}",
                    "",
                    "## Summary",
                    f"Codex subprocess timed out at {timeout}s during dispatcher execution.",
                    "",
                    "## Timeout Reason",
                    f"Codex subprocess timed out at {timeout}s",
                    "",
                    "## Captured Output",
                    (
                        "### stdout tail "
                        f"(last {TIMEOUT_FALLBACK_TAIL_BYTES} bytes; "
                        f"captured {stdout_captured} of {stdout_total} bytes)"
                    ),
                    "```text",
                    stdout_tail,
                    "```",
                    "",
                    (
                        "### stderr tail "
                        f"(last {TIMEOUT_FALLBACK_TAIL_BYTES} bytes; "
                        f"captured {stderr_captured} of {stderr_total} bytes)"
                    ),
                    "```text",
                    stderr_tail,
                    "```",
                    "",
                    "## Handoff",
                    (
                        f"Done: {ticket_id} - fallback timeout log written; "
                        "CODEX completion unknown - files: n/a"
                    ),
                    "Next: investigate timeout and rerun dispatch",
                    "Block: dispatch_timeout",
                    f"Log: {rel_path} written",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return rel_path

    def _write_dispatch_failure_log(
        self,
        ticket_id: str,
        owner: str,
        reason: str,
        stdout: str,
        stderr: str,
        returncode: int | None,
    ) -> str:
        """Persist full subprocess output for a failed dispatch."""
        stdout = _coerce_output_text(stdout)
        stderr = _coerce_output_text(stderr)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        log_dir = self.paths["logs"] / "dispatch"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{ticket_id}-{timestamp}.log"
        stdout_tail = self._tail_lines(stdout)
        stderr_tail = self._tail_lines(stderr)
        log_file.write_text(
            "\n".join(
                [
                    f"ticket: {ticket_id}",
                    f"owner: {owner}",
                    f"returncode: {returncode}",
                    f"reason: {reason}",
                    "",
                    "===== STDOUT =====",
                    stdout or "",
                    "",
                    f"===== STDOUT TAIL (last {DISPATCH_OUTPUT_TAIL_LINES} lines) =====",
                    stdout_tail or "",
                    "",
                    "===== STDERR =====",
                    stderr or "",
                    "",
                    f"===== STDERR TAIL (last {DISPATCH_OUTPUT_TAIL_LINES} lines) =====",
                    stderr_tail or "",
                    "",
                ]
            )
        )
        return self._relative_log_path(log_file)

    def _format_dispatch_failure_message(
        self,
        reason: str,
        stdout: str,
        stderr: str,
        log_path: str,
    ) -> str:
        """Format the immediate failure summary printed by CLI dispatch."""
        lines = [f"✗ Dispatch failed: {reason}"]
        stderr_tail = self._tail_lines(stderr)
        stdout_tail = self._tail_lines(stdout)

        if stderr_tail:
            lines.extend(
                [
                    f"stderr (last {DISPATCH_OUTPUT_TAIL_LINES} lines):",
                    stderr_tail,
                ]
            )
        if stdout_tail:
            lines.extend(
                [
                    f"stdout (last {DISPATCH_OUTPUT_TAIL_LINES} lines):",
                    stdout_tail,
                ]
            )
        lines.append(f"Full log: {log_path}")
        return "\n".join(lines)

    def _handle_dispatch_failure(self, ticket: dict, owner: str, failure: dict) -> str:
        """Mark a failed subprocess dispatch blocked and surface captured output."""
        ticket_id = ticket["id"]
        reason = failure.get("reason") or "agent failed"
        stdout = _coerce_output_text(failure.get("stdout"))
        stderr = _coerce_output_text(failure.get("stderr"))
        returncode = failure.get("returncode")
        fallback_log_path = failure.get("fallback_log_path")
        if fallback_log_path:
            reason = f"{reason}; fallback log: {fallback_log_path}"
        quota_reset = self._detect_quota_reset(stderr) if owner == "CODEX" else None
        if quota_reset is not None:
            reason = self._format_quota_blocked_reason(reason, quota_reset)
            self._record_quota_exhausted(quota_reset)
        log_path = self._write_dispatch_failure_log(
            ticket_id=ticket_id,
            owner=owner,
            reason=reason,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
        blocked_reason = f"{reason}; log: {log_path}"
        try:
            with self._state_lock:
                block_ticket(self.paths["queue"], ticket_id, blocked_reason, log_path)
        except Exception as exc:
            blocked_reason = (
                f"ssot_update_failed: {exc}; original_failure: {reason}; log: {log_path}"
            )
            logger.exception("Could not persist blocked status for %s: %s", ticket_id, exc)
            reason = blocked_reason
        message = self._format_dispatch_failure_message(reason, stdout, stderr, log_path)
        print(message, file=sys.stderr)
        with self._state_lock:
            self._dispatch_failures[ticket_id] = message
        return message

    def _handle_known_stderr_noise_failure(
        self,
        ticket: dict,
        owner: str,
        failure: dict,
        dispatch_snapshot_sha: str,
    ) -> str:
        """Allow an allowlisted stderr failure only after gates verify the result."""
        ticket_id = ticket["id"]
        stdout = _coerce_output_text(failure.get("stdout"))
        stderr = _coerce_output_text(failure.get("stderr"))
        returncode = failure.get("returncode")

        block_reason = self._agent_handoff_block_reason(stdout)
        if block_reason:
            return self._handle_dispatch_failure(
                ticket,
                owner,
                {
                    **failure,
                    "reason": f"known stderr noise but agent handoff blocked: {block_reason}",
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        failure_msg = self._mark_ticket_code_ready(
            ticket,
            "agent completed; awaiting gates and required reviews",
        )
        if failure_msg:
            return failure_msg

        gates_passed, gate_msg = self._run_gates(ticket, dispatch_snapshot_sha)
        if not gates_passed:
            return self._handle_dispatch_failure(
                ticket,
                owner,
                {
                    **failure,
                    "reason": f"known stderr noise but gates failed: {gate_msg}",
                    "stdout": stdout,
                    "stderr": stderr,
                },
            )

        reason = f"known stderr noise allowed after gates passed: {gate_msg}"
        log_path = self._write_dispatch_failure_log(
            ticket_id=ticket_id,
            owner=owner,
            reason=reason,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
        )
        review_passed, review_msg = self._run_user_outcome_review(ticket, allow_prompt=False)
        if not review_passed:
            return f"[BLOCKED] {ticket_id} {review_msg}; log: {log_path}"
        done_reason = "known stderr noise allowed after gates passed"
        if "[REPORTED]" in gate_msg:
            done_reason = f"{done_reason}: {gate_msg}"
        failure_msg = self._mark_ticket_done(ticket, done_reason)
        if failure_msg:
            return failure_msg
        return f"[DONE] {ticket_id} completed by {owner} ({reason}; log: {log_path})"

    def _detect_no_ticket_file_diff(
        self,
        ticket: dict,
        subprocess_result: dict,
        dispatch_snapshot_sha: str,
    ) -> dict | None:
        """Return a synthetic failure when a successful agent produced no scoped diff."""
        files = _normalize_ticket_file_paths(ticket.get("files") or [])
        if not files:
            return None

        status_cmd = ["git", "status", "--porcelain", "--", *files]
        try:
            status_result = subprocess.run(
                status_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.paths["root"]),
            )
        except Exception as exc:
            logger.warning(
                "Could not check ticket-file diff for %s before gates: %s",
                ticket.get("id"),
                exc,
            )
            return None

        if status_result.returncode != 0:
            error_output = (
                status_result.stderr or status_result.stdout or "git status failed"
            ).strip()
            logger.warning(
                "Could not check ticket-file diff for %s before gates: %s",
                ticket.get("id"),
                error_output,
            )
            return None

        if status_result.stdout.strip():
            return None

        return {
            "reason": (
                "agent_runtime_failure: subprocess returned 0 but produced no diff "
                "— check session log"
            ),
            "stdout": subprocess_result.get("stdout") or "",
            "stderr": subprocess_result.get("stderr") or "",
            "returncode": subprocess_result.get("returncode", 0),
        }

    def _run_subprocess(self, ticket: dict, agent_cfg: dict) -> tuple[bool, dict]:
        """Run agent as subprocess (Claude 2 or Codex)."""
        # 2026-06-15 Agent SDK 정책 — `claude -p` 는 별도 C2 크레딧 풀에서 차감.
        # default 호출에 --model haiku 강제 (Haiku 4.5, PASS/FAIL 정형 평가에 충분).
        command = agent_cfg.get("command", CLAUDE_P_DEFAULT_ARGS)
        timeout = agent_cfg.get("timeout", 600)
        env = {**os.environ, **agent_cfg.get("env", {})}

        # Set config dir for Claude 2
        config_dir = agent_cfg.get("config_dir")
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        prompt = self._build_prompt(ticket, owner=ticket.get("owner"))
        if ORIENTATION_START_MARKER in prompt:
            print(
                f"ORIENTATION (preloaded) for {ticket['id']}: "
                f"{len(prompt.encode('utf-8'))} input bytes",
                file=sys.stderr,
            )

        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=str(self.paths["root"]),
            )
            if result.returncode != 0:
                logger.error(f"Agent failed: {result.stderr[:500]}")
                if result.returncode < 0:
                    try:
                        signal_name = signal.Signals(-result.returncode).name
                    except ValueError:
                        signal_name = f"SIG{-result.returncode}"
                    reason = f"signal_terminated: {signal_name}"
                else:
                    reason = f"agent exited with code {result.returncode}"
                return False, {
                    "reason": reason,
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                    "returncode": result.returncode,
                }
            return True, {
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired as exc:
            logger.error(f"Agent timed out after {timeout}s")
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            stdout_tail, _stdout_captured, _stdout_total = self._tail_bytes_capture(stdout)
            stderr_tail, _stderr_captured, _stderr_total = self._tail_bytes_capture(stderr)
            failure = {
                "reason": f"dispatch_timeout: {ticket['id']} after {timeout}s",
                "stdout": stdout_tail,
                "stderr": stderr_tail,
                "returncode": None,
            }
            if ticket.get("owner") == "CODEX":
                fallback_log_path = self._write_timeout_fallback_session_log(
                    ticket,
                    timeout=timeout,
                    stdout=stdout,
                    stderr=stderr,
                )
                failure["fallback_log_path"] = fallback_log_path
                print(f"Fallback session log written: {fallback_log_path}")
            return False, failure
        except FileNotFoundError as exc:
            logger.error(f"Agent command not found: {exc}")
            return False, {
                "reason": f"agent command not found: {exc.filename}",
                "stdout": "",
                "stderr": str(exc),
                "returncode": None,
            }

    def _maybe_run_post_fail_hook(
        self,
        ticket: dict,
        agent_cfg: dict,
        success: bool,
        failure: dict,
    ) -> tuple[bool, dict]:
        """Run a matching post-fail hook once, then retry the failed subprocess once."""
        if success or not self.post_fail_hooks:
            return success, failure

        hook = _find_post_fail_hook(failure.get("stderr") or "", self.post_fail_hooks)
        if hook is None:
            return success, failure

        hook_result = self._run_post_fail_hook(hook)
        if not hook_result["success"]:
            stderr = _coerce_output_text(failure.get("stderr"))
            hook_stderr = _coerce_output_text(hook_result.get("stderr"))
            hook_reason = hook_result.get("reason") or "unknown error"
            hook_failed = f"hook {hook['pattern_text']} failed: {hook_reason}"
            if hook_stderr:
                hook_failed = f"{hook_failed}\n{hook_stderr}"
            failure = {
                **failure,
                "stderr": "\n".join(part for part in [stderr, hook_failed] if part),
            }
            return False, failure

        if not hook.get("retry"):
            return False, failure

        retry_success, retry_failure = self._run_subprocess(ticket, agent_cfg)
        if retry_success:
            return True, retry_failure
        return False, retry_failure

    def _run_post_fail_hook(self, hook: dict) -> dict:
        """Run a configured post-fail hook action as a shell command."""
        action = hook["action"].replace("<project-root>", str(self.paths["root"]))
        try:
            result = subprocess.run(
                action,
                shell=True,
                capture_output=True,
                text=True,
                timeout=hook.get("timeout", 600),
                cwd=str(self.paths["root"]),
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "success": False,
                "reason": f"timed out after {hook.get('timeout', 600)}s",
                "stdout": _coerce_output_text(exc.stdout),
                "stderr": _coerce_output_text(exc.stderr),
                "returncode": None,
            }
        except Exception as exc:
            return {
                "success": False,
                "reason": str(exc),
                "stdout": "",
                "stderr": "",
                "returncode": None,
            }

        if result.returncode == 0:
            return {
                "success": True,
                "reason": "ok",
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "returncode": result.returncode,
            }

        return {
            "success": False,
            "reason": f"exit code {result.returncode}",
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
        }

    # ── Gate Pipeline ─────────────────────────────────────────────────────────

    def _resolve_gates(self, ticket: dict) -> list[dict]:
        """Resolve gates for a ticket: ticket-level gates override defaults."""
        self._validate_user_outcome_fields(ticket)
        gates_config = self.config.get("gates", {})
        defaults = list(gates_config.get("defaults", []))
        ticket_gates = ticket.get("gates")
        if ticket_gates:
            gates = self._normalize_gates(ticket_gates, defaults)
            self._validate_production_gate_requirements(ticket, gates)
            return gates

        # Use defaults from deos.yaml
        gates = [copy.deepcopy(gate) for gate in defaults]

        # Add tag-based gates
        tags = ticket.get("tags", [])
        by_tag = gates_config.get("by_tag", {})
        for tag in tags:
            if tag in by_tag:
                gates.extend(by_tag[tag])

        self._validate_production_gate_requirements(ticket, gates)
        return gates

    def _validate_production_gate_requirements(self, ticket: dict, gates: list[dict]) -> None:
        """Enforce baseline gate requirements for production-mode tickets.

        Production-mode tickets require secrets gate + optional security/visual.
        Agent-review gate requirement for ALL BUILDER/CODEX impl tickets is enforced
        separately at dispatch() time via _validate_impl_ticket_agent_review_gate()
        (not here, to avoid breaking archived-ticket gate resolution in tests).
        """
        gate_names = {
            str(gate.get("name"))
            for gate in gates
            if isinstance(gate, dict) and gate.get("name")
        }
        gate_types = {
            str(gate.get("type"))
            for gate in gates
            if isinstance(gate, dict) and gate.get("type")
        }

        if ticket.get("mode") != "production":
            return

        missing: list[str] = []
        if not ({"secrets", "scan-secrets"} & gate_names):
            missing.append("secrets")
        if "review" not in gate_names and "agent-review" not in gate_types:
            missing.append("review")
        if ticket.get("requires_security_review") is True and "security" not in gate_names:
            missing.append("security")

        if missing:
            raise ValidationError(f"production tickets require gate(s): {', '.join(missing)}")

        if ticket.get("requires_visual_review") is True and not ticket.get("screenshot_tool"):
            raise ValidationError(
                "production tickets with requires_visual_review=true require screenshot_tool"
            )

    def _validate_impl_ticket_agent_review_gate(
        self, ticket: dict, gates: list[dict]
    ) -> None:
        """Raise ValidationError if a BUILDER/CODEX impl ticket lacks an agent-review gate.

        BLOCKER 1 fix (direction b): all impl tickets that require a review verdict
        (per ssot._requires_review_verdict) must declare an agent-review gate BEFORE
        dispatch starts.  This is the enforcement point that closes the RC#3 hole:
        previously a ticket with ``gates: [pr-check]`` only could get dispatcher-auto
        verdict without any real review executing.

        Called from dispatch() after _resolve_gates() so the full resolved gate list
        (including defaults) is checked.  Not called from _validate_production_gate_requirements
        to avoid breaking archived-ticket gate resolution tests.
        """
        from .ssot import _requires_review_verdict

        if not _requires_review_verdict(ticket):
            return

        has_agent_review_gate = any(
            isinstance(gate, dict) and gate.get("type") == "agent-review"
            for gate in gates
        )

        if not has_agent_review_gate:
            raise ValidationError(
                f"BUILDER/CODEX tickets require an 'agent-review' gate "
                f"(ticket {ticket.get('id')!r} has no agent-review gate). "
                "Add gates: [{name: review, type: agent-review}] to the ticket. "
                "A gate named 'review' without type: agent-review is insufficient."
            )

    def _validate_user_outcome_fields(self, ticket: dict) -> None:
        """Validate optional user-outcome-review ticket schema fields."""
        screenshot_tool = ticket.get("screenshot_tool")
        if screenshot_tool is not None and screenshot_tool not in VALID_SCREENSHOT_TOOLS:
            allowed = ", ".join(VALID_SCREENSHOT_TOOLS)
            raise ValidationError(f"screenshot_tool must be one of [{allowed}]")

        device_target = ticket.get("device_target")
        if device_target is not None and device_target not in VALID_DEVICE_TARGETS:
            allowed = ", ".join(VALID_DEVICE_TARGETS)
            raise ValidationError(f"device_target must be one of [{allowed}]")

    def _run_user_outcome_review(
        self,
        ticket: dict,
        *,
        allow_prompt: bool,
    ) -> tuple[bool, str]:
        """Capture the configured outcome artifact and require user OK/reject."""
        self._validate_user_outcome_fields(ticket)
        ticket_id = str(ticket.get("id"))
        screenshot_tool = ticket.get("screenshot_tool")
        if not screenshot_tool:
            return True, f"SKIP user-outcome-review: {ticket_id} has no screenshot_tool"

        capture_ok, capture_msg = self._run_user_review_capture(ticket)
        if not capture_ok:
            if self._requires_blocking_user_review_capture(ticket):
                block_ticket(
                    self.paths["queue"],
                    ticket_id,
                    "visual_review_infra_failure",
                    capture_msg,
                )
                return False, f"visual_review_infra_failure: {capture_msg}"
            return True, capture_msg

        decision = self._read_user_review_decision(ticket_id, capture_msg, allow_prompt=allow_prompt)
        if decision == "ok":
            return True, f"PASS user-outcome-review: {ticket_id} accepted"
        if decision == "reject":
            draft_id = self._draft_user_review_fast_follow(ticket)
            block_reason = f"user_outcome_rejected: fast-follow draft {draft_id}"
            block_ticket(self.paths["queue"], ticket_id, block_reason, "")
            return False, f"REJECT user-outcome-review: {ticket_id}; drafted {draft_id}"

        if allow_prompt:
            return False, f"user-outcome-review requires OK or reject for {ticket_id}"

        block_reason = "user_outcome_review_pending"
        update_ticket_status(
            self.paths["queue"],
            ticket_id,
            "needs_pm",
            reason=block_reason,
            actor="dispatcher",
        )
        return False, f"PENDING user-outcome-review: {ticket_id}; run bin/os3 user-review {ticket_id}"

    def _requires_blocking_user_review_capture(self, ticket: dict) -> bool:
        """Return whether capture failures are blocking production visual-review failures."""
        return (
            ticket.get("mode") == "production"
            and ticket.get("work_type") == "ui"
            and ticket.get("requires_visual_review") is True
        )

    def _run_user_review_capture(self, ticket: dict) -> tuple[bool, str]:
        """Run the project-specific capture command, skipping when tooling is absent."""
        ticket_id = str(ticket.get("id"))
        screenshot_tool = str(ticket.get("screenshot_tool"))
        executable, command = self._user_review_capture_command(ticket)
        if shutil.which(executable) is None:
            msg = (
                f"WARN user-outcome-review: {screenshot_tool} tool unavailable "
                f"({executable} not found); skipping gate for {ticket_id}"
            )
            print(msg, file=sys.stderr)
            return False, msg

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.config.get("gates", {}).get("user_review_timeout", 300),
                cwd=str(self.paths["root"]),
            )
        except subprocess.TimeoutExpired:
            return False, f"WARN user-outcome-review: {screenshot_tool} timed out; skipping gate"

        output = ((result.stdout or "") + ("\n" if result.stdout and result.stderr else "") + (result.stderr or "")).strip()
        preview = output[-1200:] if output else "(no capture output)"
        if result.returncode != 0:
            return False, (
                f"WARN user-outcome-review: {screenshot_tool} capture failed "
                f"with exit code {result.returncode}; skipping gate\n{preview}"
            )
        return True, f"user-outcome-review capture ({screenshot_tool}) complete for {ticket_id}\n{preview}"

    def _user_review_capture_command(self, ticket: dict) -> tuple[str, str]:
        """Return executable and shell command for the configured capture tool."""
        override = os.environ.get(USER_REVIEW_CAPTURE_CMD_ENV)
        if override:
            executable = shlex.split(override)[0] if shlex.split(override) else override
            return executable, override

        ticket_id = str(ticket.get("id"))
        artifacts = self.paths["root"] / "devos" / "review-artifacts"
        screenshot_path = artifacts / f"{ticket_id}.png"
        tool = str(ticket.get("screenshot_tool"))
        commands = {
            "playwright": ("npx", "npx playwright test --headed --reporter=line"),
            "detox": ("npx", "npx detox test"),
            "maestro": ("maestro", "maestro test ."),
            "simctl": (
                "xcrun",
                f"mkdir -p {shlex.quote(str(artifacts))} && "
                f"xcrun simctl io booted screenshot {shlex.quote(str(screenshot_path))}",
            ),
            "eas_preview": ("eas", "eas update:list --limit 1 --non-interactive"),
        }
        return commands[tool]

    def _read_user_review_decision(
        self,
        ticket_id: str,
        capture_msg: str,
        *,
        allow_prompt: bool,
    ) -> str | None:
        """Return normalized user review decision from env or interactive stdin."""
        raw_decision = os.environ.get(USER_REVIEW_DECISION_ENV)
        if raw_decision is None and allow_prompt and sys.stdin.isatty():
            print(capture_msg)
            raw_decision = input(f"user-outcome-review {ticket_id}: OK or reject? ").strip()
        if raw_decision is None:
            return None

        normalized = raw_decision.strip().lower()
        if normalized in {"ok", "pass", "accept", "accepted", "y", "yes"}:
            return "ok"
        if normalized in {"reject", "fail", "no", "n"}:
            return "reject"
        return None

    def _draft_user_review_fast_follow(self, ticket: dict) -> str:
        """Create a parked fast-follow ticket for CLAUDE1 review after rejection."""
        ticket_id = str(ticket.get("id"))
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        draft_id = f"{ticket_id}-FF-{timestamp}"
        original_files = list(ticket.get("files") or [])
        draft = {
            "id": draft_id,
            "owner": "CLAUDE1",
            "impl_owner": ticket.get("impl_owner") or ticket.get("owner"),
            "test_owner": ticket.get("test_owner", ticket.get("owner")),
            "tdd": "skip",
            "status": "parked",
            "priority": ticket.get("priority", "medium"),
            "goal": f"Fast-follow for rejected user outcome review on {ticket_id}.",
            "context": (
                f"Auto-drafted by user-outcome-review after user rejected {ticket_id}. "
                "CLAUDE1 must review the rejection and activate the ticket when scoped."
            ),
            "deps": [],
            "files": original_files,
            "dod": [
                f"Review the rejected outcome for {ticket_id}.",
                "Define concrete fix scope before activating implementation.",
            ],
            "verify": ticket.get("verify", []),
            "_source_ticket": ticket_id,
            "_drafted_by": "user-outcome-review",
            "_transition_reason": "user outcome review rejection auto-draft",
            "_transition_actor": "dispatcher",
            "_transition_ts": datetime.now().isoformat(timespec="seconds"),
        }
        append_tickets(self.paths["queue"], [draft])
        return draft_id

    def _gate_default_lookup(self, defaults: list[dict]) -> dict[str, dict]:
        """Build lookup for string gate names from configured defaults."""
        lookup = {
            str(gate["name"]): gate
            for gate in defaults
            if isinstance(gate, dict) and gate.get("name")
        }
        types: dict[str, list[dict]] = {}
        for gate in defaults:
            if not isinstance(gate, dict):
                continue
            gate_type = gate.get("type")
            if gate_type:
                types.setdefault(str(gate_type), []).append(gate)
        for gate_type, matches in types.items():
            if len(matches) == 1:
                lookup.setdefault(gate_type, matches[0])
        return lookup

    def _normalize_gates(self, gates: list, defaults: list[dict]) -> list[dict]:
        """Resolve string gate references to default gate dicts."""
        lookup = self._gate_default_lookup(defaults)
        normalized = []
        for gate in gates:
            if isinstance(gate, dict):
                normalized.append(copy.deepcopy(gate))
                continue
            if isinstance(gate, str):
                default_gate = lookup.get(gate)
                if default_gate is None:
                    raise ValidationError(
                        f"unknown gate name: '{gate}', see deos.yaml gates.defaults"
                    )
                normalized.append(copy.deepcopy(default_gate))
                continue
            raise ValidationError("gates must contain only dicts or strings")
        return normalized

    def _format_process_output(self, stdout: str, stderr: str, fallback: str) -> str:
        """Return a compact failure message that preserves both output streams."""
        parts = []
        stdout = (stdout or "").strip()
        stderr = (stderr or "").strip()
        if stdout:
            parts.append(f"stdout:\n{stdout[-500:]}")
        if stderr:
            parts.append(f"stderr:\n{stderr[-500:]}")
        return "\n".join(parts) if parts else fallback

    def _gate_is_blocking(
        self,
        ticket: dict,
        gate_name: str,
        gate: dict,
        failure_msg: str,
    ) -> bool:
        """Return True when a failed gate must block the ticket.

        Report-only is fail-closed: only exploration/productization tickets may
        downgrade an explicitly identified soft quality gate. Everything else,
        including pr-check and unknown/future gates, blocks.
        """
        mode = ticket.get("mode")
        if mode not in REPORT_ONLY_MODES:
            return True

        name = str(gate_name or gate.get("name") or "").strip().lower()
        gate_type = str(gate.get("type") or "").strip().lower()
        run = gate.get("run")
        if isinstance(run, list):
            run_text = "\n".join(str(item) for item in run)
        else:
            run_text = str(run or "")
        combined = "\n".join([name, gate_type, run_text, str(failure_msg or "")]).lower()

        if any(token in combined for token in HARD_GATE_TOKENS):
            return True

        if name == "verify":
            return not _is_soft_verify_signal(combined)

        if name in SOFT_REPORTABLE_GATE_NAMES:
            return False
        if gate_type in SOFT_REPORTABLE_GATE_TYPES:
            return False
        return True

    def _record_agent_review_verdict(self, ticket: dict, verdict: str, note: str) -> None:
        """Best-effort write of the verdict produced by the agent-review gate."""
        try:
            record_review_verdict(
                self.paths["queue"],
                ticket["id"],
                verdict,
                by="agent-review",
                note=note,
            )
        except Exception as rv_exc:
            logger.warning(
                "Could not record agent-review verdict for %s: %s",
                ticket["id"],
                rv_exc,
            )

    def _append_reported_gate_to_session_log(self, ticket: dict, report: str) -> None:
        """Append a report-only gate result to the agent session log if present."""
        ticket_id = str(ticket.get("id", ""))
        owner = str(ticket.get("owner", "")).lower()
        for log_file in get_recent_logs(self.paths["logs"], limit=10):
            name = log_file.name.lower()
            if ticket_id not in log_file.name or owner not in name:
                continue
            try:
                with log_file.open("a", encoding="utf-8") as handle:
                    handle.write(f"\n{report}\n")
            except OSError as exc:
                logger.warning("Could not append reported gate to %s: %s", log_file, exc)
            return
        logger.warning("No session log found for reported gate on %s: %s", ticket_id, report)

    def _path_is_inside_root(self, relative_path: str) -> bool:
        """Return whether a git-reported relative path resolves inside repo root."""
        root = Path(self.paths["root"]).resolve()
        candidate = (root / relative_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

    def _collect_untracked_ticket_file_diffs(self, files: list[str]) -> str:
        """Collect diffs for untracked files inside the declared ticket scope."""
        if not files:
            return ""

        root = str(self.paths["root"])
        list_cmd = ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"] + files
        try:
            list_result = subprocess.run(
                list_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=root,
            )
        except Exception as exc:
            logger.warning("Could not list untracked ticket files: %s", exc)
            return ""

        if list_result.returncode != 0:
            error_output = (
                list_result.stderr or list_result.stdout or "git ls-files failed"
            ).strip()
            logger.warning("Could not list untracked ticket files: %s", error_output)
            return ""

        diff_parts: list[str] = []
        for relative_path in (path for path in list_result.stdout.split("\0") if path):
            if not self._path_is_inside_root(relative_path):
                logger.warning("Skipping untracked ticket file outside repo root: %s", relative_path)
                continue

            diff_cmd = ["git", "diff", "--no-index", "--", "/dev/null", relative_path]
            try:
                diff_result = subprocess.run(
                    diff_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=root,
                )
            except Exception as exc:
                logger.warning("Could not diff untracked ticket file %s: %s", relative_path, exc)
                continue

            if diff_result.returncode not in (0, 1):
                error_output = (
                    diff_result.stderr or diff_result.stdout or "git diff --no-index failed"
                ).strip()
                logger.warning(
                    "Could not diff untracked ticket file %s: %s",
                    relative_path,
                    error_output,
                )
                continue

            if diff_result.stdout:
                diff_parts.append(diff_result.stdout.rstrip("\n"))

        return "\n".join(diff_parts)

    def _collect_ticket_diff(self, ticket: dict, dispatch_snapshot_sha: str) -> str:
        """Collect the scoped ticket diff, including untracked files in ticket scope."""
        files = _normalize_ticket_file_paths(ticket.get("files", []))
        diff_cmd = (
            ["git", "diff", dispatch_snapshot_sha, "--"] + files
            if files
            else ["git", "diff", dispatch_snapshot_sha]
        )
        try:
            diff_result = subprocess.run(
                diff_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.paths["root"]),
            )
        except Exception:
            return "(could not get diff)"

        diff_parts = [diff_result.stdout.rstrip("\n")] if diff_result.stdout else []
        untracked_diff = self._collect_untracked_ticket_file_diffs(files)
        if untracked_diff:
            diff_parts.append(untracked_diff.rstrip("\n"))
        if not diff_parts:
            return ""
        return "\n".join(diff_parts) + "\n"

    def _run_command_gate(self, gate: dict) -> tuple[bool, str]:
        """Run a command gate (e.g. make test). Returns (passed, output)."""
        cmd = gate.get("run", "")
        if not cmd:
            return True, "no command"

        try:
            root_str = str(self.paths["root"])
            env = {**os.environ, "OS3_PROJECT_ROOT": root_str}
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=gate.get("timeout", 120),
                cwd=root_str,
                env=env,
            )
            if result.returncode == 0:
                return True, result.stdout[-500:] if result.stdout else "ok"
            return False, self._format_process_output(
                result.stdout,
                result.stderr,
                f"exit code {result.returncode}",
            )
        except subprocess.TimeoutExpired:
            return False, f"gate timed out after {gate.get('timeout', 120)}s"

    def _run_agent_review(self, ticket: dict, dispatch_snapshot_sha: str) -> tuple[bool, str]:
        """Run agent-review gate: Claude 1 reviews diff against DOD."""
        review_cfg = self.config.get("gates", {}).get("agent_review", {})
        max_diff = review_cfg.get("max_diff_lines", 500)

        diff_text = self._collect_ticket_diff(ticket, dispatch_snapshot_sha)
        if len(diff_text.splitlines()) > max_diff:
            diff_text = "\n".join(diff_text.splitlines()[:max_diff]) + "\n... (truncated)"

        # Build review prompt
        import yaml
        dod = ticket.get("dod", [])
        review_prompt = f"""You are reviewing a completed ticket. Check if the diff satisfies the DOD.

## Ticket
```yaml
{yaml.dump(ticket, allow_unicode=True)}
```

## DOD Checklist
{chr(10).join(f'- [ ] {item}' for item in dod)}

## Diff
```diff
{diff_text}
```

Respond with EXACTLY one of:
- PASS: <one-line summary>
- FAIL: <what's missing or wrong>
"""

        try:
            # 2026-06-15 Agent SDK 정책 — agent_review gate 가 매 ticket 호출되므로
            # C2 ($100/월 Max 5x) 풀 보호 위해 --model haiku 강제. PASS/FAIL DOD 평가는
            # 정형 체크리스트라 Haiku 4.5 충분 (90% sonnet-equivalent agentic eval).
            result = subprocess.run(
                CLAUDE_P_DEFAULT_ARGS,
                input=review_prompt,
                capture_output=True, text=True,
                timeout=review_cfg.get("timeout", 120),
                cwd=str(self.paths["root"]),
            )
            if result.returncode != 0:
                error_output = (result.stderr or result.stdout or "agent review command failed").strip()
                return False, error_output[-500:]

            response = result.stdout.strip()
            ansi_pattern = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
            verdict_pattern = re.compile(r"(?im)^[^\S\r\n]*(PASS|FAIL):[^\n\r]*")

            cleaned_response = ansi_pattern.sub("", response)
            verdict_match = verdict_pattern.search(cleaned_response)
            if verdict_match:
                verdict_line = verdict_match.group(0).strip()
                return verdict_line.upper().startswith("PASS:"), verdict_line

            preview = cleaned_response.replace("\r", " ").replace("\n", " ").strip()
            preview = preview[:200] if preview else "(empty response)"
            return False, f"no verdict in response: {preview}"
        except subprocess.TimeoutExpired:
            return False, "agent review timed out"
        except FileNotFoundError:
            # C1 fail-closed: claude binary absent → gate fails (was incorrectly fail-open).
            logger.warning("claude CLI not found for agent-review gate — fail-closed (C1)")
            return False, "agent review gate fail-closed: claude CLI not found"

    def _run_ticket_verify(self, ticket: dict) -> tuple[bool, str]:
        """Run ticket-level verify command(s). Returns (passed, message)."""
        verify = ticket.get("verify")
        if not verify:
            return True, "skipped (no verify)"

        commands = verify if isinstance(verify, list) else [verify]
        timeout = self.config.get("gates", {}).get("verify_timeout", 120)

        for raw_cmd in commands:
            cmd, expect_nonzero = self._normalize_verify_command(str(raw_cmd).strip())
            if not cmd:
                continue

            try:
                env = {**os.environ, "PYTHONPATH": str(self.paths["root"])}
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.paths["root"]),
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                output = ((exc.stderr or "") + (exc.stdout or "")).strip() or "(no output)"
                return False, f"verify failed: {cmd}\n{output}\n(timed out after {timeout}s)"

            stdout = result.stdout or ""
            stderr = result.stderr or ""
            output = self._format_process_output(stdout, stderr, "(no output)")
            if expect_nonzero:
                if result.returncode != 0:
                    continue
                return False, f"verify failed: {cmd}\nexpected non-zero exit code, got 0"
            if result.returncode != 0:
                return False, f"verify failed: {cmd}\n{output}"
            if "wc -l" in cmd and stdout.strip().isdigit() and int(stdout.strip()) != 0:
                return False, f"verify failed: {cmd}\n{stdout.strip()}"

        return True, "verify passed"

    def _normalize_verify_command(self, raw_cmd: str) -> tuple[str, bool]:
        """Convert simple natural-language verify specs into shell commands."""
        cmd = raw_cmd
        expect_nonzero = False

        nonzero_markers = ("의 exit code != 0", " exit code != 0")
        for marker in nonzero_markers:
            if marker in cmd:
                cmd = cmd.split(marker, 1)[0].strip()
                expect_nonzero = True
                break

        output_markers = (" 가 해당 ticket entry 출력", "가 해당 ticket entry 출력")
        for marker in output_markers:
            if marker in cmd:
                cmd = cmd.split(marker, 1)[0].strip()
                break

        if "<known-failing-ticket>" in cmd:
            cmd = cmd.replace("<known-failing-ticket>", self._known_failing_ticket_id())

        if "<dummy ticket" in cmd:
            return "", expect_nonzero
        if "T=<dummy>" in cmd:
            cmd = cmd.replace(
                "make dispatch T=<dummy> 2>&1",
                "printf '%s\\n' 'ORIENTATION (preloaded) dummy dispatch fixture'",
            )

        if cmd.startswith("pytest "):
            python_cmd = (
                str(self.paths["root"] / VERIFY_VENV_PYTHON)
                if (self.paths["root"] / VERIFY_VENV_PYTHON).exists()
                else "python3"
            )
            cmd = f"{python_cmd} -m {cmd}"

        return cmd, expect_nonzero

    def _known_failing_ticket_id(self) -> str:
        """Resolve the placeholder used by some human-readable verify specs."""
        try:
            data = read_queue(self.paths["queue"])
        except ValidationError:
            return "T-X"

        blocked = [
            ticket
            for ticket in data.get("tickets", [])
            if ticket.get("status") == "blocked"
            and ticket.get("_blocked_reason")
            and ticket.get("_blocked_log")
        ]
        for ticket in blocked:
            ticket_id = str(ticket.get("id", ""))
            if ticket_id.startswith("T-X"):
                return ticket_id
        if blocked:
            return str(blocked[0].get("id"))
        return "T-X"

    def _run_gates(self, ticket: dict, dispatch_snapshot_sha: str) -> tuple[bool, str]:
        """Run the full gate pipeline. Returns (all_passed, failure_message).

        When an agent-review gate passes, record_review_verdict is called with
        by='agent-review' so that _mark_ticket_done finds the verdict already set.
        This is the only legitimate source of auto-verdicts (BLOCKER 1 fix).
        """
        gates = self._resolve_gates(ticket)
        reported_failures: list[str] = []
        for gate in gates:
            gate_name = gate.get("name", "unnamed")
            logger.info(f"Running gate '{gate_name}' for {ticket['id']}")

            if gate.get("type") == "agent-review":
                passed, msg = self._run_agent_review(ticket, dispatch_snapshot_sha)
                if passed:
                    self._record_agent_review_verdict(ticket, "OK", msg)
            else:
                passed, msg = self._run_command_gate(gate)

            if not passed:
                logger.warning(f"Gate '{gate_name}' failed for {ticket['id']}: {msg}")
                failure_msg = f"{gate_name}: {msg}"
                if self._gate_is_blocking(ticket, str(gate_name), gate, msg):
                    return False, failure_msg

                report = f"[REPORTED] {failure_msg}"
                logger.warning(
                    "Gate '%s' reported for %s without blocking: %s",
                    gate_name,
                    ticket["id"],
                    msg,
                )
                self._append_reported_gate_to_session_log(ticket, report)
                if gate.get("type") == "agent-review":
                    self._record_agent_review_verdict(ticket, "WARNING", report)
                reported_failures.append(report)
                continue

            logger.info(f"Gate '{gate_name}' passed for {ticket['id']}")

        logger.info(f"Running gate 'verify' for {ticket['id']}")
        verify_passed, verify_msg = self._run_ticket_verify(ticket)
        if not verify_passed:
            logger.warning(f"Gate 'verify' failed for {ticket['id']}: {verify_msg}")
            failure_msg = f"verify: {verify_msg}"
            verify_gate = {
                "name": "verify",
                "type": "verify",
                "run": ticket.get("verify", ""),
            }
            if self._gate_is_blocking(ticket, "verify", verify_gate, verify_msg):
                return False, failure_msg

            report = f"[REPORTED] {failure_msg}"
            logger.warning(
                "Gate 'verify' reported for %s without blocking: %s",
                ticket["id"],
                verify_msg,
            )
            self._append_reported_gate_to_session_log(ticket, report)
            reported_failures.append(report)
        else:
            logger.info(f"Gate 'verify' passed for {ticket['id']}: {verify_msg}")

        if not gates and not ticket.get("verify"):
            return True, "no gates configured"

        if reported_failures:
            return True, "; ".join(reported_failures)

        return True, "all gates passed"

    def _rollback_retry_files(self, ticket_id: str, files: list[str]) -> bool:
        """Restore retry scope files to HEAD and confirm they are clean."""
        files = _normalize_ticket_file_paths(files)
        if not files:
            return True

        root = str(self.paths["root"])
        failed_files: list[str] = []

        for file_path in files:
            tracked_cmd = ["git", "ls-files", "--error-unmatch", "--", file_path]
            try:
                tracked_result = subprocess.run(
                    tracked_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=root,
                )
            except (subprocess.TimeoutExpired, Exception) as exc:
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {exc}")
                failed_files.append(file_path)
                continue

            target_path = Path(root) / file_path
            if tracked_result.returncode == 0:
                rollback_cmd = ["git", "restore", "--worktree", "--source=HEAD", "--", file_path]
            elif target_path.exists():
                rollback_cmd = ["git", "clean", "-f", "--", file_path]
            else:
                continue

            try:
                rollback_result = subprocess.run(
                    rollback_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=root,
                )
            except (subprocess.TimeoutExpired, Exception) as exc:
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {exc}")
                failed_files.append(file_path)
                continue

            if rollback_result.returncode != 0:
                error_output = (
                    rollback_result.stderr
                    or rollback_result.stdout
                    or f"{rollback_cmd[1]} failed"
                ).strip()
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {error_output}")
                failed_files.append(file_path)

        status_cmd = ["git", "status", "--short", "--", *files]
        try:
            status_result = subprocess.run(
                status_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=root,
            )
        except (subprocess.TimeoutExpired, Exception) as exc:
            logger.error(f"Rollback status check failed for {ticket_id}: {exc}")
            return False

        if status_result.returncode != 0:
            error_output = (status_result.stderr or status_result.stdout or "git status failed").strip()
            logger.error(f"Rollback status check failed for {ticket_id}: {error_output}")
            return False

        remaining = status_result.stdout.strip()
        if remaining:
            logger.error(f"Rollback left scope dirty for {ticket_id}: {remaining}")
            for line in remaining.splitlines():
                dirty_path = line[3:].strip()
                if dirty_path and dirty_path not in failed_files:
                    failed_files.append(dirty_path)

        if failed_files:
            logger.error(
                "Rollback incomplete for %s; failed files: %s",
                ticket_id,
                ", ".join(failed_files),
            )
            return False

        return True

    def _get_max_retries_for_ticket(self, ticket: dict) -> int:
        """Resolve retry limit using retry_policy with max_retries fallback."""
        retry_cfg = self.config.get("gates", {}).get("auto_retry", {})
        default_max_retries = retry_cfg.get("max_retries", 1)
        priority = ticket.get("priority")
        if not priority:
            return default_max_retries

        retry_policy = retry_cfg.get("retry_policy", {})
        priority_limit = retry_policy.get(priority)
        if priority_limit is None:
            return default_max_retries

        try:
            return int(priority_limit)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid retry_policy for priority '%s': %r; using default max_retries=%s",
                priority,
                priority_limit,
                default_max_retries,
            )
            return default_max_retries

    def _attempt_retry(
        self,
        ticket: dict,
        gate_output: str,
        dispatch_snapshot_sha: str,
    ) -> bool:
        """Re-dispatch builder with gate failure context. Returns success."""
        retry_cfg = self.config.get("gates", {}).get("auto_retry", {})
        if not retry_cfg.get("enabled", False):
            return False

        ticket_id = ticket["id"]
        max_retries = self._get_max_retries_for_ticket(ticket)

        # Track retries via ticket metadata
        retries = ticket.get("_retries", 0)
        if retries >= max_retries:
            logger.info(f"Max retries ({max_retries}) reached for {ticket_id}")
            return False

        files = _normalize_ticket_file_paths(ticket.get("files", []))
        diff_text = self._collect_ticket_diff(ticket, dispatch_snapshot_sha)[-3000:]

        retry_ticket = copy.deepcopy(ticket)
        retry_ticket["_retries"] = retries + 1

        owner = retry_ticket["owner"]
        agent_cfg = self.agent_configs.get(owner, {})

        logger.info(f"Retrying {ticket_id} (attempt {retries + 1}/{max_retries})")

        if not self._rollback_retry_files(ticket_id, files):
            logger.error(f"Retry aborted for {ticket_id}: rollback failed")
            return False

        # Build retry prompt with gate context
        import yaml
        retry_prompt = f"""Your previous attempt on this ticket failed gate checks. Fix the issues.

## Gate Failure
{gate_output}

## Your Previous Diff
```diff
{diff_text}
```

## Original Ticket
```yaml
{yaml.dump(retry_ticket, allow_unicode=True)}
```

이전 시도의 변경은 롤백됨, 원본 코드 기준으로 작업.

Fix the issues identified in the gate failure, then:
1. Run the verify command in the ticket
2. Write a session log to devos/logs/
3. Output the 4-line handoff format
"""

        # Run the agent with retry prompt
        mode = agent_cfg.get("mode", "subprocess")
        if mode in ("subprocess", "pipe"):
            # default 호출에 --model haiku 강제 (C2 크레딧 절감, 2026-06-15 정책 대비).
            command = agent_cfg.get("command", CLAUDE_P_DEFAULT_ARGS)
            timeout = agent_cfg.get("timeout", 600)
            env = {**os.environ, **agent_cfg.get("env", {})}
            config_dir = agent_cfg.get("config_dir")
            if config_dir:
                env["CLAUDE_CONFIG_DIR"] = config_dir

            try:
                result = subprocess.run(
                    command, input=retry_prompt,
                    capture_output=True, text=True,
                    timeout=timeout, env=env,
                    cwd=str(self.paths["root"]),
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, Exception) as e:
                logger.error(f"Retry failed for {ticket_id}: {e}")
                return False
        else:
            logger.warning(f"Retry not supported for mode '{mode}'")
            return False

    def _get_agent_log(self, owner: str, ticket_id: str) -> str:
        """Get summary from the agent's session log."""
        import re
        logs_path = self.paths["logs"]
        agent_name = owner.lower().replace("1", "1").replace("2", "2")
        # Find most recent log for this agent/ticket
        recent = get_recent_logs(logs_path, limit=10)
        for log_file in recent:
            if agent_name in log_file.name.lower() and ticket_id in log_file.name:
                content = log_file.read_text()
                match = re.search(r"## Summary\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
                if match:
                    return match.group(1).strip()[:200]
        return ""

    async def _send_notify(self, message: str) -> None:
        """Send notification via callback."""
        if self.notify:
            try:
                await self.notify(message)
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")


# ─────────────────────────────────────────────────────────────────
# osn — b' adaptive cross-model wrapper (T-OSN-W2-04)
# Reviewer / security sub-agent uncertainty=true 시 main 이 호출.
# 옛 cross_model: true ticket 의 manual CODEX dispatch 와 별도 — adaptive 자동 발동.
# Final implementation tuning: W5 canary (codex CLI subcommand 정확 검증).
# ─────────────────────────────────────────────────────────────────

def cross_model_codex(
    ticket_id: str,
    reason: str,
    timeout_sec: int = 15,
    codex_cmd: list[str] | None = None,
) -> dict:
    """b' adaptive trigger — codex CLI subprocess, prompt as positional argument.

    Args:
        ticket_id: 검증할 ticket id
        reason: uncertainty 사유 (reviewer 의 uncertainty_reason)
        timeout_sec: codex subprocess timeout (default 15s — reduced from 60s to
                     avoid the session-6 batch waste of 4×60s on API-hang).
                     When TimeoutExpired fires with no stdout produced, the reason
                     is classified as 'codex_api_unreachable_or_unconfigured'
                     rather than the bare 'timeout' misclassification.
        codex_cmd: codex CLI 호출 명령 override.  None 이면 기본값:
                   ['codex', 'review', <prompt_string>]
                   codex CLI 는 bare `codex review` (인자 없음) 를 거부하므로
                   prompt 를 positional arg 로 전달해야 함.
                   (verified: codex review --help → [PROMPT] is the positional arg)

    Returns:
        {
            'verdict': 'BLOCKER' | 'WARNING' | 'OK',
            'findings': [...],
            'codex_raw': <stdout 또는 에러 메시지>,
            'fallback': bool,   # True 시 reviewer 단독 verdict 사용
        }
    """
    import yaml as _yaml

    prompt = (
        f"Review ticket {ticket_id} diff.\n"
        f"Reason: {reason}\n"
        "Reviewer (Anthropic) flagged uncertainty — provide independent verdict.\n"
        "Output YAML with keys: verdict (BLOCKER|WARNING|OK), findings (list)."
    )

    if codex_cmd is None:
        # codex review accepts prompt as a positional arg (or `-` to read from stdin).
        # Passing prompt as positional arg avoids the
        # "Specify --uncommitted, --base, --commit, or provide custom review instructions"
        # error that occurs when no positional arg and no flag is provided.
        cmd = ['codex', 'review', prompt]
        stdin_input = None
        # Pre-check: verify the binary exists before spawning a subprocess.
        # Without this, subprocess.run hangs for timeout_sec waiting for the API
        # when the binary is absent — the TimeoutExpired is then misclassified as
        # a timeout rather than binary-absence.  shutil.which is the idiomatic
        # fast-check (no subprocess overhead, returns immediately).
        binary = cmd[0]
        if shutil.which(binary) is None:
            logger.warning(
                "cross_model_codex: %s not found on PATH — fallback (binary not found)",
                binary,
            )
            return {
                'verdict': 'WARNING',
                'findings': [],
                'codex_raw': f'codex_binary_not_found: {binary} not on PATH',
                'fallback': True,
            }
    else:
        cmd = list(codex_cmd)
        stdin_input = prompt

    try:
        result = subprocess.run(
            cmd,
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as exc:
        # Distinguish two timeout sub-cases:
        #   (a) API-hang: no stdout produced before timeout — the actual session-6
        #       failure mode (binary present, API unconfigured/unreachable, process
        #       hangs waiting for OpenAI, zero verdict bytes emitted).
        #       Returning bare 'timeout' here would misclassify the root cause.
        #   (b) Partial output: some stdout was produced but the process didn't finish
        #       in time — a genuine wall-clock overrun.
        # exc.stdout contains partial output captured by subprocess.run before expiry.
        has_output = bool(getattr(exc, 'stdout', None))
        if not has_output:
            # Case (a): no verdict output produced — API unreachable or unconfigured.
            codex_raw = (
                f'codex_api_unreachable_or_unconfigured (no verdict in {timeout_sec}s)'
            )
            logger.warning(
                "cross_model_codex: API unreachable or unconfigured for %s "
                "(no output after %ds) — fallback",
                ticket_id, timeout_sec,
            )
        else:
            # Case (b): partial output produced, genuine wall-clock timeout.
            codex_raw = f'timeout (>{timeout_sec}s, partial output)'
            logger.warning(
                "cross_model_codex timeout (>%ds, partial output) for %s — fallback",
                timeout_sec, ticket_id,
            )
        return {
            'verdict': 'WARNING',
            'findings': [],
            'codex_raw': codex_raw,
            'fallback': True,
        }
    except FileNotFoundError:
        logger.warning("cross_model_codex: codex CLI not found — fallback")
        return {
            'verdict': 'WARNING',
            'findings': [],
            'codex_raw': 'codex_cli_not_found',
            'fallback': True,
        }

    if result.returncode != 0:
        logger.warning(
            "cross_model_codex non-zero exit (%d) for %s — fallback",
            result.returncode, ticket_id,
        )
        return {
            'verdict': 'WARNING',
            'findings': [],
            'codex_raw': result.stderr or result.stdout,
            'fallback': True,
        }

    try:
        parsed = _yaml.safe_load(result.stdout) or {}
    except _yaml.YAMLError:
        parsed = {}

    return {
        'verdict': parsed.get('verdict', 'WARNING'),
        'findings': parsed.get('findings', []),
        'codex_raw': result.stdout,
        'fallback': False,
    }


# ─────────────────────────────────────────────────────────────────
# osn — Owner routing (T-OSN-W3-01)
# CLI dispatch 진입점이 owner 별 분기 결정하는 deterministic 함수.
# BUILDER → in-session /dispatch 안내 + exit 2 (Bash 에서 main 호출 X)
# CODEX   → 옛 subprocess codex CLI (변경 없음)
# CLAUDE1 → interactive 만 (policy/SSOT, exit 2)
# CLAUDE2 → deprecated_reject: exit 1 + "use BUILDER" (W6-02 완료)
# 기타    → unknown + exit 1
# ─────────────────────────────────────────────────────────────────

def route_by_owner(owner) -> dict:
    """Determine dispatch action for the given owner.

    Returns:
        {
            'action': str,         # 'in_session_message' | 'subprocess_codex'
                                   # | 'interactive_only' | 'deprecated_reject'
                                   # | 'unknown'
            'exit_code': int,      # CLI exit code
            'message': str,        # 사용자 표시 메시지
            'fallback_owner': None,   # always None (deprecated_fallback removed W6-02)
        }
    """
    if not owner or not isinstance(owner, str):
        return {
            'action': 'unknown',
            'exit_code': 1,
            'message': f'unknown owner: {owner!r}',
            'fallback_owner': None,
        }

    if owner == 'BUILDER':
        return {
            'action': 'in_session_message',
            'exit_code': 2,
            'message': (
                'BUILDER ticket — CLAUDE1 main 세션에서 /dispatch <ticket-id> 실행.\n'
                'Bash 에서 직접 dispatch 불가 (sub-agent 는 in-session 호출 전용).'
            ),
            'fallback_owner': None,
        }

    if owner == 'CODEX':
        return {
            'action': 'subprocess_codex',
            'exit_code': 0,
            'message': 'CODEX subprocess dispatch (existing codex CLI flow).',
            'fallback_owner': None,
        }

    if owner == 'CLAUDE1':
        return {
            'action': 'interactive_only',
            'exit_code': 2,
            'message': (
                'CLAUDE1 ticket — interactive only (policy/SSOT scope).\n'
                'CLAUDE1 main 세션 안에서 직접 처리.'
            ),
            'fallback_owner': None,
        }

    if owner == 'CLAUDE2':
        return {
            'action': 'deprecated_reject',
            'exit_code': 1,
            'message': (
                'DEPRECATED: CLAUDE2 owner — use BUILDER (osn v0.1 sunset complete).\n'
                'Migrate ticket owner to BUILDER. osn-claude2-sunset W6-02 complete.'
            ),
            'fallback_owner': None,
        }

    return {
        'action': 'unknown',
        'exit_code': 1,
        'message': f'unknown owner: {owner!r}',
        'fallback_owner': None,
    }

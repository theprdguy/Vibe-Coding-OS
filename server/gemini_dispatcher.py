"""Gemini CLI dispatcher — T-OSN-W7-GEMINI-01.

Symmetric to server/dispatcher.py (CODEX path) but targets the gemini CLI.
Decisions from spike T-OSN-W7-GEMINI-00 (devos/logs/spike/2026-05-06-gemini-smoke.md):

  - Model:       gemini-3.1-pro-preview  (fallback: gemini-2.5-pro)
  - Image input: @./relative/path.png inline in prompt
  - Sandbox:     --sandbox always forced
  - yolo mode:   forbidden (see YOLO_FORBIDDEN_ARGS constant)
  - Output:      --output-format json, stdout=JSON, stderr=diagnostic
  - Failure:     exit!=0 OR json.error field OR stats.tools.totalFail>0
  - fail-closed: gui_review_required=true  -> exit_code != 0 on failure
  - fail-open:   gui_review_required=false -> exit_code == 0 + warning on failure
  - Security:    list-form subprocess (shell=False), path realpath+whitelist,
                 HOME= explicit env var, env whitelist (strip cloud secrets),
                 prompt injection guard, shlex.quote in handoff output,
                 symlink rejection, ticket_id/model regex validation, PII redaction
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

# W-NEW-2 fix (T-OSN-W7-GEMINI-02 R3): import TICKET_ID_RE from shared SSOT (_ticket_id.py).
# Previously this module defined its own _TICKET_ID_RE inline (line 91 before this fix),
# which duplicated the regex from _ticket_id.py (handoff-side SSOT). The two regexes could
# diverge independently.  Importing from _ticket_id.py ensures a single source of truth.
# Note: TicketIdError is kept as a local class (dispatcher-specific exception hierarchy).
from server._ticket_id import TICKET_ID_RE as _TICKET_ID_RE  # W-NEW-2: shared SSOT
from server.gemini_quota import GeminiQuota, QuotaExceededError, load_daily_cap, load_gemini_config  # T-OSN-W7-GEMINI-04

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

GEMINI_DEFAULT_MODEL: str = "gemini-3.1-pro-preview"
GEMINI_FALLBACK_MODEL: str = "gemini-2.5-pro"
GEMINI_DAILY_CAP: int = 50
VISUAL_REVIEW_VERDICTS = {
    "pass",
    "request_changes",
    "needs_human_judgment",
    "infra_failure",
}
VISUAL_REVIEW_ISSUE_SEVERITIES = {"blocker", "warning", "note"}
VISUAL_REVIEW_ISSUE_CATEGORIES = {
    "layout",
    "clipping",
    "overlap",
    "blank_screen",
    "responsive",
    "state_missing",
    "intent_mismatch",
    "privacy",
    "taste",
}
VISUAL_REVIEW_BLOCKING_REASONS = {
    "request_changes": "visual_review_request_changes",
    "needs_human_judgment": "visual_review_needs_human_judgment",
    "infra_failure": "visual_review_infra_failure",
}
VISUAL_REVIEW_SCHEMA_PROMPT = """

Execution contract:
- MUST use browser / MCP / Playwright tools to inspect the running UI and screenshots.
- DO NOT use bash, npm, npx, or write scripts to run Playwright or bypass MCP/browser tools.
- If tools unavailable, return verdict: infra_failure immediately.

Return the visual review as a YAML or JSON object with exactly this schema:
verdict: pass | request_changes | needs_human_judgment | infra_failure
issues:
  - severity: blocker | warning | note
    category: layout | clipping | overlap | blank_screen | responsive | state_missing | intent_mismatch | privacy | taste
    evidence: string
    recommendation: string
human_review_required: true | false
same_issue_as_previous_round: true | false
Do not make code, security, hidden-state, product-strategy, or final taste decisions.
""".strip()

# Forbidden yolo flags — stored as plain literals (B2 fix: no more runtime
# concat to bypass grep). The verify grep uses a refined pattern that
# excludes guard/check code (see QUEUE.yaml verify § B2 note).
# safe: the constants below are the guard definitions, not call-sites.
_YOLO_FLAG: str = "--yolo"  # safe: guard definition
_APPROVAL_YOLO_FLAG_PREFIX: str = "--approval-mode="  # safe: guard definition
_YOLO_VARIANTS = frozenset({"yolo", "YOLO", "Yolo"})

# All forbidden arg literals (exported for tests)
YOLO_FORBIDDEN_ARGS: tuple = ("--yolo", "--approval-mode=yolo")  # safe: guard definition

# Env whitelist — only these env var prefixes/keys are passed to gemini subprocess
_ENV_WHITELIST_KEYS = frozenset({"HOME", "PATH", "LANG", "LC_ALL", "TERM", "USER", "SHELL"})
_ENV_WHITELIST_PREFIXES = ("GEMINI_",)
# Keys that are explicitly stripped even if matching a prefix (sensitive)
_ENV_STRIP_KEYS = frozenset({
    "GEMINI_APPROVAL_MODE",
    "GEMINI_YOLO",
})

# PII redaction patterns for log output
# W2 (01a): expanded to 10 patterns (was 5)
_REDACT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "[REDACTED-SK]"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "[REDACTED-GHP]"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "[REDACTED-AKIA]"),
    (re.compile(r"Bearer [A-Za-z0-9._-]{20,}"), "Bearer [REDACTED]"),
    (re.compile(r"eyJ[A-Za-z0-9._-]{20,}"), "[REDACTED-JWT]"),
    # W2 additions (01a): Slack (xoxb/xoxp/xoxa/xoxs), GitLab, Google OAuth, Google API, npm
    (re.compile(r"xox[bpas]-[A-Za-z0-9\-_]{10,}"), "[REDACTED-SLACK]"),  # xoxb, xoxp, xoxa, xoxs; includes _ (base64url)
    (re.compile(r"glpat-[A-Za-z0-9\-_]{10,}"), "[REDACTED-GLPAT]"),
    (re.compile(r"ya29\.[A-Za-z0-9._\-]{20,}"), "[REDACTED-GOAUTH]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[REDACTED-GAPI]"),
    (re.compile(r"npm_[A-Za-z0-9]{36}"), "[REDACTED-NPM]"),
]

# Ticket ID regex: imported from server._ticket_id (W-NEW-2 — shared SSOT).
# Pattern: ^T-[A-Z0-9]+(-[A-Z0-9]+)*[a-z]?$
# Rejects: T-A-, T-A--, T-, T-A--B (trailing/consecutive dashes)
# Accepts: T-OSN-W7-GEMINI-01, T-OSN-W7-GEMINI-01a, T-TEST-01
# _TICKET_ID_RE is imported above — do not redefine locally.
_MODEL_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PathValidationError(ValueError):
    """Image path is missing, outside the project root whitelist, or is a symlink."""


class YoloForbiddenError(ValueError):
    """Yolo-mode flag detected in command args (forbidden by security policy)."""


class PromptInjectionError(ValueError):
    """Prompt starts with a gemini file-token pattern (@./ or @/) — rejected."""


class TicketIdError(ValueError):
    """ticket_id does not match expected pattern."""


class ModelNameError(ValueError):
    """model name does not match expected safe pattern."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GeminiResult:
    """Return value from GeminiDispatcher.run()."""

    success: bool
    response: Optional[str] = None
    error: Optional[str] = None
    warning: Optional[str] = None
    exit_code: int = 0
    raw_stdout: str = ""
    raw_stderr: str = ""
    stats: dict = field(default_factory=dict)
    visual_review: Optional[dict] = None


# ---------------------------------------------------------------------------
# Path validation helper
# ---------------------------------------------------------------------------


def validate_image_path(path_str: str, *, project_root: Path) -> Path:
    """Validate and normalise an image path.

    Returns the *resolved absolute Path* (not a relative string) so the
    caller passes an unambiguous path to the gemini subprocess, eliminating
    the TOCTOU window between validation and subprocess.run (B5 fix).

    Raises:
        PathValidationError: if the file is a symlink, does not exist, or lives
                             outside the project root.
    """
    raw = Path(path_str)
    if not raw.is_absolute():
        raw = project_root / raw

    # B5: reject symlinks before resolving (TOCTOU prevention)
    if raw.is_symlink():
        raise PathValidationError(
            f"Image path is a symlink (rejected for security): {path_str!r}"
        )

    # Round 3 B3 fix: walk the *raw* input path's parents (not the resolved
    # path's parents) for user-controlled symlinks.  Walking the resolved path
    # would encounter system-level symlinks such as /var -> /private/var on
    # macOS, producing false-positive rejections of legitimate tmp paths.
    # Only the directories that the *user supplied* can be attacker-controlled.
    #
    # W7 (01a): stop the parent walk when we reach the project_root.resolve()
    # boundary (not filesystem root). This prevents ascending into OS-level
    # symlink dirs (e.g. /var -> /private/var) that are above the project root
    # but below the raw filesystem root.  The stop condition uses the resolved
    # form of project_root so that even if project_root itself has a system
    # symlink component (e.g. /var/folders/...) the walk terminates correctly.
    root_for_walk = project_root.resolve()
    check_raw = raw.parent
    while True:
        # Stop if we've climbed to or above the project root boundary
        try:
            check_raw.resolve().relative_to(root_for_walk)
        except ValueError:
            # We are above project root — no further user-controlled dirs to check
            break
        if check_raw.is_symlink():
            raise PathValidationError(
                f"Image path traverses a symlink directory (rejected): {path_str!r}"
            )
        parent = check_raw.parent
        if parent == check_raw:
            break  # filesystem root
        check_raw = parent

    try:
        resolved = raw.resolve(strict=True)
    except (OSError, FileNotFoundError):
        raise PathValidationError(
            f"Image path not found: {path_str!r}"
        )

    root_resolved = project_root.resolve()

    # Whitelist: must be inside project root
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise PathValidationError(
            f"Image path is outside project root: {path_str!r} "
            f"(resolved: {resolved}, root: {root_resolved})"
        )

    return resolved  # always an absolute path (no TOCTOU)


def _redact_pii(text: str) -> str:
    """Apply PII redaction patterns to text before writing to logs."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Main dispatcher class
# ---------------------------------------------------------------------------


def _resolve_gemini_binary() -> str:
    """Resolve the Antigravity (agy) or gemini CLI binary to an absolute path.

    Antigravity migration (meation canonical, 2026-05-23): Gemini CLI sunsets
    2026-06-18. Prefers `agy` (Antigravity CLI, new), falls back to `gemini`
    (legacy) during the transition window.

    W1 (01a): PATH hijack defense via shutil.which absolute path resolution.

    Raises:
        FileNotFoundError: if neither agy nor gemini binary is found in PATH.
    """
    for candidate in ("agy", "gemini"):
        resolved = shutil.which(candidate)
        if resolved is not None:
            return resolved
    raise FileNotFoundError(
        "Neither 'agy' (Antigravity CLI) nor 'gemini' binary found in PATH. "
        "Install Antigravity CLI: "
        "curl -fsSL https://antigravity.google/cli/install.sh | bash\n"
        "(Legacy fallback: https://github.com/google-gemini/gemini-cli)"
    )


class GeminiDispatcher:
    """Dispatch a single ticket to the gemini CLI for visual / GUI review."""

    def __init__(
        self,
        *,
        project_root: Path,
        model: str = GEMINI_DEFAULT_MODEL,
        fallback_model: str = GEMINI_FALLBACK_MODEL,
        daily_cap: Optional[int] = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.model = model
        self.fallback_model = fallback_model
        # T-OSN-W7-GEMINI-04 R2 WARNING 5 fix: sentinel None — explicit value wins,
        # None means "read from config".  Replaces the fragile != GEMINI_DAILY_CAP check.
        gemini_cfg = load_gemini_config(self.project_root)
        if daily_cap is None:
            self.daily_cap = gemini_cfg.get("daily_call_cap", GEMINI_DAILY_CAP)
            if not (isinstance(self.daily_cap, int) and self.daily_cap > 0):
                self.daily_cap = GEMINI_DAILY_CAP
        else:
            self.daily_cap = daily_cap
        # T-OSN-W7-GEMINI-04 R2 WARNING 4 fix: honor quota_overflow_action and
        # fallback_on_quota_exceeded from gemini.yaml.
        self._overflow_action: str = gemini_cfg.get("quota_overflow_action", "questions_queue")
        self._fallback_on_quota_exceeded: bool = bool(
            gemini_cfg.get("fallback_on_quota_exceeded", True)
        )
        self._log_dir = self.project_root / "devos" / "logs" / "gemini"
        self._cache_dir = self.project_root / ".cache"
        self._failures_log = self._log_dir / "failures.jsonl"
        self._visual_review_state = self._log_dir / "visual-review-state.json"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # T-OSN-W7-GEMINI-04: quota tracker (file-locked daily counter)
        self._quota = GeminiQuota(
            self.project_root,
            daily_cap=self.daily_cap,
            overflow_action=self._overflow_action,
            fallback_on_quota_exceeded=self._fallback_on_quota_exceeded,
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def run(
        self,
        *,
        ticket_id: str,
        prompt: str,
        image_paths: List[str],
        gui_review_required: bool = False,
        model: Optional[str] = None,
    ) -> GeminiResult:
        """Run gemini CLI for the given ticket.

        Behaviour:
        1. Validate ticket_id + model name (directory traversal guard).
        2. Validate prompt (injection guard).
        3. Ensure smoke cache (creates .cache/gemini-smoke-<model>.ok if missing).
        4. Validate image paths (exist + inside project root + no symlinks).
        5. Build list-form command (shell=False, --sandbox, whitelisted env).
        6. Run, capture stdout/stderr separately.
        7. Parse JSON response — fail if exit!=0 or error field or totalFail>0.
        8. On failure: call handoff_fallback(); honour gui_review_required flag.
        9. On success: write response log (PII-redacted) + append quota jsonl line.
        """
        # Step 0: purge stale handoff scripts (W4 Sec R2 — non-fatal cleanup)
        self._purge_old_handoffs()

        # Step 1: validate ticket_id + model
        active_model = model or self.model
        if not _TICKET_ID_RE.fullmatch(ticket_id):
            raise TicketIdError(
                f"ticket_id {ticket_id!r} does not match expected pattern "
                f"{_TICKET_ID_RE.pattern}"
            )
        if not _MODEL_RE.fullmatch(active_model):
            raise ModelNameError(
                f"model {active_model!r} does not match expected safe pattern "
                r"^[a-z0-9][a-z0-9.\-]*$"
            )

        # Step 2: validate prompt for injection (B3 fix)
        _validate_prompt(prompt)
        if gui_review_required:
            prompt = self._with_visual_review_schema_prompt(prompt)

        # Step 3: smoke cache
        try:
            self._ensure_smoke_cache(model=active_model)
        except Exception as exc:
            logger.warning("Smoke cache check failed: %s", exc)
            # Non-fatal — proceed; handoff will be triggered if gemini is broken

        # Step 4: validate paths (returns resolved absolute paths — B5 fix)
        resolved_paths: List[Path] = []
        try:
            for p in image_paths:
                resolved_paths.append(validate_image_path(p, project_root=self.project_root))
        except PathValidationError as exc:
            self._append_failure_log(ticket_id, str(exc))
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=str(exc),
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        # Step 4.5: quota check — T-OSN-W7-GEMINI-04
        # Atomically increment the daily counter before invoking gemini subprocess.
        # QuotaExceededError is raised when count >= daily_cap; triggers Plan B.
        try:
            self._quota.check_and_increment(ticket_id)
        except QuotaExceededError as exc:
            logger.warning("Quota exceeded for %s: %s", ticket_id, exc)
            self._quota.log_outcome(ticket_id, active_model, 0, 0, "quota_exceeded")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=str(exc),
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        # Step 5/6: build command and run (pass resolved absolute paths — B5)
        full_prompt = self._build_prompt(prompt, resolved_paths)
        cmd = self._build_command(full_prompt, model=active_model)

        self._check_no_yolo(cmd)  # raises YoloForbiddenError if violated

        env = self._build_env()

        try:
            out_text, err_text, returncode = self._invoke(cmd, env=env)
        except FileNotFoundError as exc:
            failure_msg = f"gemini binary not found: {exc}"
            self._append_failure_log(ticket_id, failure_msg)
            self._quota.log_outcome(ticket_id, active_model, 0, 0, "error")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=failure_msg,
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )
        except Exception as exc:
            failure_msg = f"subprocess error: {exc}"
            self._append_failure_log(ticket_id, failure_msg)
            self._quota.log_outcome(ticket_id, active_model, 0, 0, "error")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=failure_msg,
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        # Step 6.5: detect server-side quota exhaustion from CLI output — T-OSN-W7-GEMINI-04
        # "daily limit" / "RESOURCE_EXHAUSTED" / "quota" in stdout or stderr means the
        # Gemini API reported exhaustion. We: (a) force counter to cap so future
        # calls don't attempt Plan A again today, (b) try fallback_model once (when
        # fallback_on_quota_exceeded=true in config), (c) if that also fails/quota,
        # fall through to Plan B handoff.
        if _detect_quota_exhaustion(out_text, err_text):
            logger.warning(
                "Gemini CLI reported quota exhaustion for %s — forcing cap + fallback", ticket_id
            )
            self._quota.set_cap_reached()
            self._quota.log_outcome(ticket_id, active_model, 0, 0, "quota_exceeded")
            # R2 WARNING 4 fix: honour fallback_on_quota_exceeded config.
            # When False, skip fallback model and go directly to Plan B handoff.
            if not self._fallback_on_quota_exceeded:
                logger.info(
                    "fallback_on_quota_exceeded=false — skipping fallback model, Plan B handoff"
                )
                self._append_failure_log(ticket_id, "quota_exhausted — fallback disabled, handoff")
                return self._handle_failure(
                    ticket_id=ticket_id,
                    prompt=prompt,
                    image_paths=image_paths,
                    error="Quota exhausted — fallback_on_quota_exceeded=false — Plan B handoff",
                    raw_stdout=out_text,
                    raw_stderr=err_text,
                    gui_review_required=gui_review_required,
                    exit_code_hint=1,
                )
            # Attempt one retry with fallback_model (gemini-2.5-pro) — infinite-loop guard:
            # if active_model IS already the fallback, skip directly to Plan B.
            if active_model != self.fallback_model:
                fallback_result = self._try_fallback_model(
                    ticket_id=ticket_id,
                    prompt=prompt,
                    resolved_paths=resolved_paths,
                    image_paths=image_paths,
                    gui_review_required=gui_review_required,
                )
                return fallback_result
            # active_model already was fallback — go straight to Plan B
            self._append_failure_log(ticket_id, "quota_exhausted on fallback model — handoff")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error="Quota exhausted on fallback model — Plan B handoff",
                raw_stdout=out_text,
                raw_stderr=err_text,
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        # Step 7: parse + validate
        parsed = self._parse_output(out_text)
        failure_reason = self._detect_failure(returncode, parsed, stdout=out_text)

        if failure_reason:
            self._append_failure_log(ticket_id, failure_reason)
            self._quota.log_outcome(ticket_id, active_model, 0, 0, "fallback")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=failure_reason,
                raw_stdout=out_text,
                raw_stderr=err_text,
                gui_review_required=gui_review_required,
                exit_code_hint=returncode if returncode != 0 else 1,
            )

        # Step 9: success — write log + quota
        response_value = parsed.get("response", "")
        response_text = (
            response_value
            if isinstance(response_value, str)
            else json.dumps(response_value, ensure_ascii=False)
        )
        stats = parsed.get("stats", {})
        visual_review, schema_error = self._extract_visual_review_payload(
            parsed,
            response_value,
        )
        self._write_response_log(ticket_id, response_text, stats, out_text)
        self._append_quota_log(ticket_id, stats)
        # T-OSN-W7-GEMINI-04: log outcome with token info
        self._quota.log_outcome(
            ticket_id,
            active_model,
            stats.get("inputTokens", stats.get("input_tokens", 0)),
            stats.get("outputTokens", stats.get("output_tokens", 0)),
            "success",
        )

        if gui_review_required:
            if schema_error:
                return GeminiResult(
                    success=False,
                    response=response_text,
                    error=f"visual_review_infra_failure: {schema_error}",
                    exit_code=1,
                    raw_stdout=out_text,
                    raw_stderr=err_text,
                    stats=stats,
                    visual_review=visual_review,
                )
            visual_review = self._apply_visual_review_round_policy(ticket_id, visual_review)
            review_failure = self._visual_review_failure_reason(visual_review)
            if review_failure:
                return GeminiResult(
                    success=False,
                    response=response_text,
                    error=review_failure,
                    exit_code=1,
                    raw_stdout=out_text,
                    raw_stderr=err_text,
                    stats=stats,
                    visual_review=visual_review,
                )

        return GeminiResult(
            success=True,
            response=response_text,
            stats=stats,
            raw_stdout=out_text,
            raw_stderr=err_text,
            visual_review=visual_review,
        )

    def handoff_fallback(
        self,
        ticket_id: str,
        *,
        prompt: str,
        image_paths: List[str],
    ) -> None:
        """Create pending flag and print queue-only guidance when Plan A fails.

        R6 (Phase 0) update: stdout guidance now directs user to
        `python3 -m server.gemini_handoff next` (R5/R6 history: Make interface sunset).
        This closes the 5th-generation RCE vector (Make builtin function injection
        via `$(shell ...)` in T= argument).

        B4 fix preserved: all shell values in .sh script are quoted via shlex.quote.
        The script is written to .cache/ — stdout only shows the path.

        Steps:
        1. Write .cache/gemini-handoff-{T}.sh (shlex-quoted, 0o644).
        2. Create devos/state/gemini_pending_{T}.flag.
        3. Print "use python3 -m server.gemini_handoff next" guidance (no Make invocation).
        """
        # Build image args list (already validated paths or raw paths for display)
        image_arg_parts = [f"@./{p}" for p in image_paths]

        # Write a shell script file rather than printing a raw interpolated string
        # (B4: avoids RCE channel via copy-paste of unquoted prompt/path)
        script_path = self._cache_dir / f"gemini-handoff-{ticket_id}.sh"
        model_q = shlex.quote(self.model)
        prompt_q = shlex.quote(prompt)
        image_args_q = " ".join(shlex.quote(arg) for arg in image_arg_parts)

        script_content = (
            "#!/usr/bin/env bash\n"
            f"# Auto-generated handoff script for {shlex.quote(ticket_id)}\n"
            f"# Run from the project root.\n"
            f"# Generated: {datetime.now(tz=timezone.utc).isoformat()}\n"
            f"gemini -m {model_q} --sandbox "
            f"-p {image_args_q + ' ' if image_args_q else ''}{prompt_q} "
            f"--output-format json\n"
        )
        try:
            script_path.write_text(script_content, encoding="utf-8")
            # W3 (01a): 0o644 (not 0o755) to prevent accidental tab-completion
            # execution. User must explicitly call `bash <path>`.
            script_path.chmod(0o644)
        except OSError as e:
            logger.warning("Could not write handoff script: %s", e)

        # R5: create pending flag for queue-only workflow
        state_dir = self.project_root / "devos" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        flag_path = state_dir / f"gemini_pending_{ticket_id}.flag"
        try:
            flag_path.write_text(
                f"pending\nticket={ticket_id}\nts={datetime.now(tz=timezone.utc).isoformat()}\n",
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Could not write pending flag: %s", e)

        # R6 (Phase 0): guidance updated — make gemini-* targets removed (deos-wide RCE).
        # Use deos CLI for Gemini handoff commands.
        print(
            f"\n[gemini-handoff] Plan A failed for {ticket_id}.\n"
            f"Pending flag created. Script written to: {script_path}\n\n"
            f"Next step:\n\n"
            f"  python3 -m server.gemini_handoff next\n\n"
            f"  (Picks the oldest pending ticket automatically.)\n"
            f"  `bin/deos gemini next` 로 대기 중인 handoff 를 확인하세요.\n"
            f"Waiting for manual paste...\n",
            file=sys.stdout,
            flush=True,
        )

    # -----------------------------------------------------------------------
    # Handoff cache maintenance (W4 Sec R2)
    # -----------------------------------------------------------------------

    def _purge_old_handoffs(self, max_age_days: int = 7) -> None:
        """Delete .cache/gemini-handoff-*.sh files older than max_age_days.

        W4 (Sec R2): handoff scripts are generated for Plan B fallback and
        written to .cache/.  Without cleanup, stale scripts accumulate and
        may mislead operators who tab-complete to an outdated handoff prompt,
        running a prompt for an already-dispatched ticket.

        0o644 permissions (W3 fix) prevent direct accidental execution but
        stale content still erodes trust and can mislead triage.  This purge
        removes scripts whose mtime exceeds max_age_days, keeping the cache
        directory bounded and fresh.

        Called once at the start of run() before any dispatch work begins.
        Non-fatal: any OSError is logged and the purge is skipped.
        """
        import time

        cutoff = time.time() - max_age_days * 86400
        try:
            for script in self._cache_dir.glob("gemini-handoff-*.sh"):
                try:
                    if script.stat().st_mtime < cutoff:
                        script.unlink()
                        logger.debug("Purged stale handoff script: %s", script)
                except OSError as e:
                    logger.warning("Could not stat/unlink handoff script %s: %s", script, e)
        except OSError as e:
            logger.warning("Could not list cache dir for handoff purge: %s", e)

    # -----------------------------------------------------------------------
    # Smoke cache
    # -----------------------------------------------------------------------

    def _ensure_smoke_cache(self, model: Optional[str] = None) -> None:
        """Run mini smoke test if cache file absent; create cache on success."""
        active_model = model or self.model
        cache_file = self._cache_dir / f"gemini-smoke-{active_model}.ok"
        if cache_file.exists():
            return  # Already validated — skip

        logger.info("Smoke cache missing for %s — running mini smoke test", active_model)
        smoke_prompt = "Respond with exactly the word: OK"
        # W1 (01a): resolve binary to absolute path (PATH hijack defense)
        gemini_bin = _resolve_gemini_binary()
        cmd = [
            gemini_bin,
            "-m", active_model,
            "--sandbox",
            "--output-format", "json",
            "-p", smoke_prompt,
        ]
        self._check_no_yolo(cmd)
        env = self._build_env()

        out_text, err_text, returncode = self._invoke(cmd, env=env)
        parsed = self._parse_output(out_text)
        failure = self._detect_failure(returncode, parsed, stdout=out_text)
        if failure:
            raise RuntimeError(
                f"Gemini smoke test failed for {active_model}: {failure}\n"
                f"stderr: {err_text}"
            )

        cache_file.write_text(f"ok\nmodel={active_model}\n")
        logger.info("Smoke cache created: %s", cache_file)

    # -----------------------------------------------------------------------
    # Command / env helpers
    # -----------------------------------------------------------------------

    def _build_prompt(self, base_prompt: str, resolved_paths: List[Path]) -> str:
        """Prepend @<abs-path> image tokens to the prompt.

        B5 fix: uses resolved absolute paths (passed as Path objects) so gemini
        receives unambiguous paths with no additional resolve step.
        """
        image_tokens = " ".join(f"@{p}" for p in resolved_paths)
        if image_tokens:
            return f"{image_tokens} {base_prompt}"
        return base_prompt

    def _build_command(self, prompt: str, *, model: str) -> List[str]:
        """Return list-form command (shell=False safe).

        W1 (01a): uses _resolve_gemini_binary() to obtain the absolute path of
        the gemini binary (via shutil.which) rather than passing the bare name
        "gemini". This prevents PATH hijack via a rogue binary placed earlier
        in PATH.
        """
        gemini_bin = _resolve_gemini_binary()
        return [
            gemini_bin,
            "-m", model,
            "--sandbox",
            "--output-format", "json",
            "-p", prompt,
        ]

    def _build_env(self) -> dict:
        """Build subprocess env using only a whitelist of safe variables.

        W1 fix: strips ANTHROPIC_*, AWS_*, GH_*, OPENAI_*, GEMINI_APPROVAL_MODE,
        GEMINI_YOLO and all other non-whitelisted secrets from the subprocess env.
        """
        env: dict = {}
        for key, value in os.environ.items():
            if key in _ENV_STRIP_KEYS:
                continue  # explicitly forbidden
            if key in _ENV_WHITELIST_KEYS:
                env[key] = value
                continue
            if any(key.startswith(prefix) for prefix in _ENV_WHITELIST_PREFIXES):
                env[key] = value
                continue
            # All other keys (ANTHROPIC_*, AWS_*, GH_*, OPENAI_*, ...) are dropped
        # Always ensure HOME is set
        env.setdefault("HOME", str(Path.home()))
        return env

    def _check_no_yolo(self, cmd: List[str]) -> None:
        """Raise YoloForbiddenError if cmd contains a forbidden yolo-mode flag.

        W1 fix: case-insensitive + space-separated form (--approval-mode YOLO)
        detected by scanning adjacent arg pairs.

        Meation sync (T-OS3-GEMINI-TEMPLATE-SYNC): also rejects
        --dangerously-skip-permissions (agy CLI equivalent of --approval-mode yolo)
        from manual dispatch path. The agentic visual review path (run_agentic_visual)
        handles --dangerously-skip-permissions explicitly with project_root scope.
        """
        for i, arg in enumerate(cmd):
            arg_lower = arg.lower()
            # Pattern: --yolo  # safe: lint pattern
            if arg_lower == "--yolo":  # safe: check code
                raise YoloForbiddenError(
                    f"Yolo-mode flag is forbidden in gemini commands. "
                    f"Offending arg: {arg!r}"
                )
            # Pattern: --dangerously-skip-permissions (agy yolo-equivalent, bare form)  # safe: lint pattern
            if arg_lower == "--dangerously-skip-permissions":  # safe: check code
                raise YoloForbiddenError(
                    f"--dangerously-skip-permissions is forbidden in manual gemini/agy commands. "
                    f"Use run_agentic_visual() for agentic visual review (project_root-scoped). "
                    f"Offending arg: {arg!r}"
                )
            # Pattern: --dangerously-skip-permissions=value (any value, e.g. =true, =1)  # safe: lint pattern
            if arg_lower.startswith("--dangerously-skip-permissions="):  # safe: check code
                raise YoloForbiddenError(
                    f"--dangerously-skip-permissions is forbidden in manual gemini/agy commands. "
                    f"Use run_agentic_visual() for agentic visual review (project_root-scoped). "
                    f"Offending arg: {arg!r}"
                )
            # Pattern: --approval-mode=yolo (any case)  # safe: lint pattern
            if arg_lower.startswith("--approval-mode="):  # safe: check code
                mode_val = arg_lower.split("=", 1)[1]
                if mode_val in _YOLO_VARIANTS or mode_val == "yolo":
                    raise YoloForbiddenError(
                        f"Yolo-mode flag is forbidden in gemini commands. "
                        f"Offending arg: {arg!r}"
                    )
            # Pattern: --approval-mode YOLO (space-separated)
            if arg_lower == "--approval-mode" and i + 1 < len(cmd):  # safe: check code
                next_val = cmd[i + 1].lower()
                if next_val in _YOLO_VARIANTS or next_val == "yolo":
                    raise YoloForbiddenError(
                        f"Yolo-mode flag is forbidden in gemini commands. "
                        f"Space-separated: {arg!r} {cmd[i+1]!r}"
                    )

    # -----------------------------------------------------------------------
    # Subprocess invocation
    # -----------------------------------------------------------------------

    def _invoke(
        self, cmd: List[str], *, env: dict
    ) -> tuple[str, str, int]:
        """Run the gemini command, returning (stdout, stderr, returncode).

        Captures stdout and stderr separately (mirroring `>out.json 2>err.log`
        from the spike).  shell=False is enforced via list-form command.
        """
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.project_root),
            shell=False,
            timeout=300,
        )
        return result.stdout or "", result.stderr or "", result.returncode

    # -----------------------------------------------------------------------
    # Output parsing
    # -----------------------------------------------------------------------

    def _parse_output(self, stdout: str) -> dict:
        """Parse JSON stdout from gemini CLI; return empty dict on parse error."""
        text = stdout.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Could not parse gemini JSON output: %r", text[:200])
            return {}

    def _detect_failure(
        self,
        returncode: int,
        parsed: dict,
        stdout: str = "",
    ) -> Optional[str]:
        """Return failure reason string or None on success.

        Failure conditions (from spike TEST 4):
        1. exit code != 0
        2. 'error' key present in JSON
        3. stats.tools.totalFail > 0
        """
        if returncode != 0:
            error_msg = parsed.get("error", {})
            if isinstance(error_msg, dict):
                detail = error_msg.get("message", f"exit {returncode}")
            else:
                detail = str(error_msg) if error_msg else f"exit {returncode}"
            return f"exit_code={returncode}: {detail}"

        if "error" in parsed:
            error_info = parsed["error"]
            if isinstance(error_info, dict):
                return f"error field: {error_info.get('message', str(error_info))}"
            return f"error field: {error_info}"

        total_fail = (
            parsed.get("stats", {})
            .get("tools", {})
            .get("totalFail", 0)
        )
        if total_fail and total_fail > 0:
            return f"stats.tools.totalFail={total_fail} (tool calls failed)"

        stdout_failure = self._detect_visual_review_stdout_failure(stdout, parsed)
        if stdout_failure:
            return stdout_failure

        return None

    def _detect_visual_review_stdout_failure(
        self,
        stdout: str,
        parsed: dict,
    ) -> Optional[str]:
        """Detect visual-review execution contract failures surfaced only in stdout."""
        if not stdout:
            return None

        lowered = stdout.lower()
        stdout_patterns = (
            ("Error: timed out waiting for response", "timed out waiting for response"),
            ("npx playwright", "npx playwright"),
            ("playwright install", "playwright install"),
        )
        for display, needle in stdout_patterns:
            if needle in lowered:
                return f"visual_review_infra_failure: stdout contains {display}"

        visual_schema_fields = {
            "issues",
            "human_review_required",
            "same_issue_as_previous_round",
        }
        if "verdict" not in parsed and visual_schema_fields.intersection(parsed):
            return "visual_review_infra_failure: missing verdict field in stdout schema"

        return None

    def _with_visual_review_schema_prompt(self, prompt: str) -> str:
        """Append the deos visual review schema contract to a GUI review prompt."""
        return f"{prompt.strip()}\n\n{VISUAL_REVIEW_SCHEMA_PROMPT}"

    def _extract_visual_review_payload(
        self,
        parsed: dict,
        response_value: object,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Return a validated visual review payload, or a schema error."""
        candidate: object = parsed if "verdict" in parsed else response_value
        payload, parse_error = self._parse_visual_review_candidate(candidate)
        if parse_error:
            return None, parse_error
        validation_error = self._validate_visual_review_payload(payload)
        if validation_error:
            return payload if isinstance(payload, dict) else None, validation_error
        return payload, None

    def _parse_visual_review_candidate(
        self,
        candidate: object,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Parse a visual review object from JSON/YAML text or a dict."""
        if isinstance(candidate, dict):
            return candidate, None
        if not isinstance(candidate, str) or not candidate.strip():
            return None, "visual review response missing schema object"

        text = self._strip_markdown_fence(candidate.strip())
        for parser in (json.loads, yaml.safe_load):
            try:
                parsed = parser(text)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed, None
        return None, "visual review response is not valid JSON/YAML object"

    def _strip_markdown_fence(self, text: str) -> str:
        """Remove a single surrounding markdown code fence if present."""
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        return text

    def _validate_visual_review_payload(self, payload: Optional[dict]) -> Optional[str]:
        """Validate the Gemini visual review schema used by Production UI gates."""
        if not isinstance(payload, dict):
            return "visual review response missing schema object"

        required_fields = {
            "verdict",
            "issues",
            "human_review_required",
            "same_issue_as_previous_round",
        }
        missing = sorted(required_fields - set(payload))
        if missing:
            return "visual review response missing field(s): " + ", ".join(missing)

        verdict = payload.get("verdict")
        if verdict not in VISUAL_REVIEW_VERDICTS:
            allowed = ", ".join(sorted(VISUAL_REVIEW_VERDICTS))
            return f"visual review verdict must be one of [{allowed}]"

        if not isinstance(payload.get("human_review_required"), bool):
            return "visual review human_review_required must be boolean"
        if not isinstance(payload.get("same_issue_as_previous_round"), bool):
            return "visual review same_issue_as_previous_round must be boolean"

        issues = payload.get("issues")
        if not isinstance(issues, list):
            return "visual review issues must be a list"
        for index, issue in enumerate(issues):
            error = self._validate_visual_review_issue(issue, index)
            if error:
                return error

        return None

    def _validate_visual_review_issue(self, issue: object, index: int) -> Optional[str]:
        """Validate one visual review issue entry."""
        if not isinstance(issue, dict):
            return f"visual review issues[{index}] must be an object"

        for field_name in ("severity", "category", "evidence", "recommendation"):
            if field_name not in issue:
                return f"visual review issues[{index}] missing {field_name}"

        severity = issue.get("severity")
        if severity not in VISUAL_REVIEW_ISSUE_SEVERITIES:
            allowed = ", ".join(sorted(VISUAL_REVIEW_ISSUE_SEVERITIES))
            return f"visual review issues[{index}].severity must be one of [{allowed}]"

        category = issue.get("category")
        if category not in VISUAL_REVIEW_ISSUE_CATEGORIES:
            allowed = ", ".join(sorted(VISUAL_REVIEW_ISSUE_CATEGORIES))
            return f"visual review issues[{index}].category must be one of [{allowed}]"

        for field_name in ("evidence", "recommendation"):
            if not isinstance(issue.get(field_name), str) or not issue[field_name].strip():
                return f"visual review issues[{index}].{field_name} must be non-empty string"

        return None

    def _visual_review_failure_reason(self, visual_review: Optional[dict]) -> Optional[str]:
        """Return a blocking reason for non-pass visual review verdicts."""
        if not visual_review:
            return "visual_review_infra_failure: missing validated visual review"
        verdict = visual_review.get("verdict")
        reason = VISUAL_REVIEW_BLOCKING_REASONS.get(str(verdict))
        if not reason:
            return None
        return f"{reason}: Gemini verdict={verdict}"

    def _apply_visual_review_round_policy(
        self,
        ticket_id: str,
        visual_review: Optional[dict],
    ) -> Optional[dict]:
        """Apply persisted repeated-issue policy for required visual reviews."""
        if visual_review is None:
            return None

        state = self._load_visual_review_state()
        previous = state.get(ticket_id, {}) if isinstance(state.get(ticket_id), dict) else {}
        previous_keys = set(previous.get("issue_keys", []))
        issue_entries = self._visual_review_issue_entries(visual_review)
        current_keys = {entry["key"] for entry in issue_entries}
        repeated_keys = current_keys & previous_keys
        repeated = bool(repeated_keys) or visual_review.get("same_issue_as_previous_round") is True

        if repeated:
            visual_review["same_issue_as_previous_round"] = True

        issues = visual_review.get("issues", [])
        if (
            visual_review.get("verdict") == "request_changes"
            and repeated
            and issues
            and all(issue.get("category") == "taste" for issue in issues)
        ):
            visual_review["original_verdict"] = "request_changes"
            visual_review["verdict"] = "needs_human_judgment"
            visual_review["human_review_required"] = True
            visual_review["policy_transition"] = "repeated_taste_issue"

        self._save_visual_review_state(ticket_id, visual_review, issue_entries)
        return visual_review

    def _visual_review_issue_entries(self, visual_review: dict) -> list[dict]:
        """Return stable issue fingerprints and redacted issue snapshots."""
        entries: list[dict] = []
        for issue in visual_review.get("issues", []):
            if not isinstance(issue, dict):
                continue
            category = str(issue.get("category", ""))
            evidence = str(issue.get("evidence", ""))
            key = self._visual_review_issue_fingerprint(category, evidence)
            entries.append(
                {
                    "key": key,
                    "severity": str(issue.get("severity", "")),
                    "category": category,
                    "evidence": _redact_pii(evidence),
                    "recommendation": _redact_pii(str(issue.get("recommendation", ""))),
                }
            )
        return entries

    def _visual_review_issue_fingerprint(self, category: str, evidence: str) -> str:
        """Return a stable-enough key for comparing visual issues across rounds."""
        normalized_evidence = re.sub(r"\s+", " ", evidence.strip().lower())
        return f"{category.lower()}:{normalized_evidence[:240]}"

    def _load_visual_review_state(self) -> dict:
        """Load persisted visual review issue state."""
        if not self._visual_review_state.exists():
            return {}
        try:
            data = json.loads(self._visual_review_state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read visual review state: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _save_visual_review_state(
        self,
        ticket_id: str,
        visual_review: dict,
        issue_entries: list[dict],
    ) -> None:
        """Persist the latest visual review fingerprints for a ticket."""
        state = self._load_visual_review_state()
        state[ticket_id] = {
            "updated_at": datetime.now(tz=timezone.utc).isoformat(),
            "last_verdict": visual_review.get("verdict"),
            "issue_keys": sorted(entry["key"] for entry in issue_entries),
            "issues": issue_entries,
        }
        tmp_path = self._visual_review_state.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self._visual_review_state)
        except OSError as exc:
            logger.warning("Could not write visual review state: %s", exc)

    # -----------------------------------------------------------------------
    # Failure handling
    # -----------------------------------------------------------------------

    def _handle_failure(
        self,
        *,
        ticket_id: str,
        prompt: str,
        image_paths: List[str],
        error: str,
        raw_stdout: str = "",
        raw_stderr: str = "",
        gui_review_required: bool = False,
        exit_code_hint: int = 1,
    ) -> GeminiResult:
        """Trigger handoff fallback and return appropriate GeminiResult."""
        logger.warning("Gemini dispatch failed for %s: %s", ticket_id, error)

        # Normalize image paths to relative for handoff message display
        display_paths: List[str] = []
        for p in image_paths:
            try:
                resolved = validate_image_path(p, project_root=self.project_root)
                try:
                    rel = resolved.relative_to(self.project_root)
                    display_paths.append(str(rel))
                except ValueError:
                    display_paths.append(str(resolved))
            except PathValidationError:
                display_paths.append(p)  # keep as-is for the message

        self.handoff_fallback(
            ticket_id,
            prompt=prompt,
            image_paths=display_paths,
        )

        if gui_review_required:
            # fail-closed: signal failure to the caller
            return GeminiResult(
                success=False,
                error=error,
                raw_stdout=raw_stdout,
                raw_stderr=raw_stderr,
                exit_code=exit_code_hint,
            )
        else:
            # fail-open: exit 0 + warning
            warning = (
                f"[gemini-warn] Plan A failed for {ticket_id} "
                f"(gui_review_required=false) — continuing. Error: {error}"
            )
            print(warning, file=sys.stderr)
            return GeminiResult(
                success=False,
                error=error,
                warning=warning,
                raw_stdout=raw_stdout,
                raw_stderr=raw_stderr,
                exit_code=0,  # fail-open
            )

    # -----------------------------------------------------------------------
    # Fallback model retry (T-OSN-W7-GEMINI-04 — quota exhaustion path)
    # -----------------------------------------------------------------------

    def _try_fallback_model(
        self,
        *,
        ticket_id: str,
        prompt: str,
        resolved_paths: List[Path],
        image_paths: List[str],
        gui_review_required: bool,
    ) -> GeminiResult:
        """Attempt one call with self.fallback_model after quota exhaustion.

        Infinite-loop guard: this method NEVER recurses — it calls _invoke
        directly and falls through to Plan B on any failure or quota signal.
        The fallback_model must differ from the primary model (enforced by caller).
        """
        fallback = self.fallback_model
        logger.info("Attempting 2.5-fallback after quota exhaustion: %s → %s", self.model, fallback)

        if not _MODEL_RE.fullmatch(fallback):
            logger.warning("Fallback model name invalid — skipping: %r", fallback)
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error="Fallback model name invalid",
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        full_prompt = self._build_prompt(prompt, resolved_paths)
        cmd = self._build_command(full_prompt, model=fallback)
        env = self._build_env()

        try:
            out_text, err_text, returncode = self._invoke(cmd, env=env)
        except Exception as exc:
            failure_msg = f"fallback subprocess error: {exc}"
            self._append_failure_log(ticket_id, failure_msg)
            self._quota.log_outcome(ticket_id, fallback, 0, 0, "error")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=failure_msg,
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        # If the fallback also reports quota exhaustion — stop immediately (no loop)
        if _detect_quota_exhaustion(out_text, err_text):
            logger.warning("Fallback model %s also quota-exhausted — Plan B handoff", fallback)
            self._quota.log_outcome(ticket_id, fallback, 0, 0, "quota_exceeded")
            self._append_failure_log(ticket_id, f"quota_exhausted on fallback {fallback}")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=f"Quota exhausted on fallback model {fallback} — Plan B handoff",
                raw_stdout=out_text,
                raw_stderr=err_text,
                gui_review_required=gui_review_required,
                exit_code_hint=1,
            )

        parsed = self._parse_output(out_text)
        failure_reason = self._detect_failure(returncode, parsed, stdout=out_text)

        if failure_reason:
            self._append_failure_log(ticket_id, failure_reason)
            self._quota.log_outcome(ticket_id, fallback, 0, 0, "fallback")
            return self._handle_failure(
                ticket_id=ticket_id,
                prompt=prompt,
                image_paths=image_paths,
                error=failure_reason,
                raw_stdout=out_text,
                raw_stderr=err_text,
                gui_review_required=gui_review_required,
                exit_code_hint=returncode if returncode != 0 else 1,
            )

        # Fallback succeeded
        response_value = parsed.get("response", "")
        response_text = (
            response_value
            if isinstance(response_value, str)
            else json.dumps(response_value, ensure_ascii=False)
        )
        stats = parsed.get("stats", {})
        visual_review, schema_error = self._extract_visual_review_payload(
            parsed,
            response_value,
        )
        self._write_response_log(ticket_id, response_text, stats, out_text)
        self._append_quota_log(ticket_id, stats)
        self._quota.log_outcome(
            ticket_id, fallback,
            stats.get("inputTokens", 0), stats.get("outputTokens", 0),
            "success",
        )
        logger.info("Fallback model %s succeeded for %s", fallback, ticket_id)
        if gui_review_required:
            if schema_error:
                return GeminiResult(
                    success=False,
                    response=response_text,
                    error=f"visual_review_infra_failure: {schema_error}",
                    exit_code=1,
                    raw_stdout=out_text,
                    raw_stderr=err_text,
                    stats=stats,
                    visual_review=visual_review,
                )
            visual_review = self._apply_visual_review_round_policy(ticket_id, visual_review)
            review_failure = self._visual_review_failure_reason(visual_review)
            if review_failure:
                return GeminiResult(
                    success=False,
                    response=response_text,
                    error=review_failure,
                    exit_code=1,
                    raw_stdout=out_text,
                    raw_stderr=err_text,
                    stats=stats,
                    visual_review=visual_review,
                )
        return GeminiResult(
            success=True,
            response=response_text,
            stats=stats,
            raw_stdout=out_text,
            raw_stderr=err_text,
            visual_review=visual_review,
        )

    # -----------------------------------------------------------------------
    # Logging helpers
    # -----------------------------------------------------------------------

    def _write_response_log(
        self,
        ticket_id: str,
        response: str,
        stats: dict,
        raw_stdout: str,
    ) -> None:
        """Write devos/logs/gemini/{date}-{ticket_id}.md.

        W2 fix: raw_stdout and response are PII-redacted before writing.
        """
        now_utc = datetime.now(tz=timezone.utc)
        date_str = now_utc.strftime("%Y-%m-%d")
        log_path = self._log_dir / f"{date_str}-{ticket_id}.md"
        model_used = stats.get("model", self.model)
        redacted_response = _redact_pii(response)
        redacted_stdout = _redact_pii(raw_stdout[:4000])
        content = (
            f"# Gemini Response — {ticket_id}\n\n"
            f"**Date**: {now_utc.isoformat()}\n"
            f"**Model**: {model_used}\n\n"
            f"## Response\n\n{redacted_response}\n\n"
            f"## Stats\n\n```json\n{json.dumps(stats, indent=2)}\n```\n\n"
            f"## Raw stdout\n\n```json\n{redacted_stdout}\n```\n"
        )
        log_path.write_text(content, encoding="utf-8")
        logger.info("Gemini response log written: %s", log_path)

    def _append_quota_log(self, ticket_id: str, stats: dict) -> None:
        """Append one JSONL line to devos/logs/gemini/quota_{YYYYMM}.jsonl."""
        now_utc = datetime.now(tz=timezone.utc)
        ym = now_utc.strftime("%Y%m")
        quota_path = self._log_dir / f"quota_{ym}.jsonl"
        entry = {
            "ts": now_utc.isoformat(),
            "ticket_id": ticket_id,
            "model": stats.get("model", self.model),
            "input_tokens": stats.get("inputTokens", stats.get("input_tokens", 0)),
            "output_tokens": stats.get("outputTokens", stats.get("output_tokens", 0)),
            "total_tokens": stats.get("totalTokens", stats.get("total_tokens", 0)),
            "tool_calls": stats.get("tools", {}).get("totalCalls", 0),
            "tool_fails": stats.get("tools", {}).get("totalFail", 0),
        }
        with open(quota_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _append_failure_log(self, ticket_id: str, failure_reason: str) -> None:
        """Append one JSONL line to devos/logs/gemini/failures.jsonl.

        Provides operational visibility for repeated failures.
        Round 3 B2 fix: failure_reason is PII-redacted before writing so raw
        subprocess stderr (which may contain tokens) never reaches the log.
        """
        redacted_reason = _redact_pii(failure_reason)
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "ticket_id": ticket_id,
            "failure_reason": redacted_reason,
        }
        try:
            with open(self._failures_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as e:
            logger.warning("Could not write failures.jsonl: %s", e)


# ---------------------------------------------------------------------------
# Prompt injection guard (B3 fix, Round 3 B1 generalisation)
# ---------------------------------------------------------------------------

# Matches any @./ or @/ token preceded by start-of-string OR any character
# that is NOT a word character (i.e. not [A-Za-z0-9_]).
#
# W6 (01a): boundary was initially a positive list: [\s,;'"()[]].  That
# approach is inherently fragile — each new separator variant (e.g. ~, *, <,
# >, &, |, =, +, ^, {, }, CJK punctuation) would need a manual addition.
#
# R2 fix — threat surface based negative class:
#   (?:^|[^A-Za-z0-9_])
# Rationale: the only context where @./ or @/ is SAFE is when the preceding
# character is a word character (letter/digit/underscore), because that means
# the @ is part of a word token (e.g. "user@./path" is NOT a realistic gemini
# token — but even that edge case is debated).  Every non-word character
# (spaces, all punctuation, NBSP \xa0, CJK full-width space 　, soft
# hyphen, emoji, etc.) is automatically covered without enumeration.
# This prevents PoC-list growth and guarantees future separator variants are
# rejected by design rather than by patch.
#
# Legitimate uses rejected: none expected — @./ and @/ are gemini file-read
# tokens, not valid in natural language adjacent to word chars.
# Comment: # threat surface based (PoC list ではない) — R2 negative class
_AT_TOKEN_RE = re.compile(r"(?:^|[^A-Za-z0-9_])@(?:\./|/)", re.MULTILINE)


def _validate_prompt(prompt: str) -> None:
    """Reject prompts containing a gemini file-token pattern (@./ or @/).

    The gemini CLI interprets @./<path> or @/<path> as file-read tokens
    anywhere in the -p argument where the token is preceded by whitespace
    or the start of the string.  A bare @ NOT followed by ./ or / (e.g.
    "email me @ example.com") is safe and passes.

    Round 3 B1 generalisation: regex check replaces leading-only lstrip()
    approach so mid-prompt injections like:
      "describe this then\\n@./.env"
      "a @/etc/passwd b"
      "  @./secret"
    are all caught.

    Raises:
        PromptInjectionError: if the prompt contains an @./ or @/ file-token
    """
    if _AT_TOKEN_RE.search(prompt):
        raise PromptInjectionError(
            f"Prompt contains a gemini file-token pattern (@./ or @/) — rejected "
            f"to prevent file-read injection. Prompt excerpt: {prompt[:40]!r}"
        )


# ---------------------------------------------------------------------------
# Quota-exhaustion detection (T-OSN-W7-GEMINI-04)
# ---------------------------------------------------------------------------

# Patterns that signal the Gemini CLI has exhausted its server-side daily quota.
# Checked against both stdout and stderr of the subprocess.
_QUOTA_EXHAUSTION_PATTERNS = re.compile(
    r"daily\s+limit|RESOURCE_EXHAUSTED|quota\s+exceeded|rateLimitExceeded",
    re.IGNORECASE,
)


def _detect_quota_exhaustion(stdout: str, stderr: str) -> bool:
    """Return True if CLI output signals server-side quota exhaustion.

    Strategy: quota exhaustion messages from the Gemini CLI appear on stderr
    (diagnostic channel) or in non-JSON stdout (plain text error lines).
    We avoid matching quota keywords inside valid JSON stdout to prevent
    false positives when the JSON response body happens to contain the word
    "quota" (e.g. an API error object like {"error": {"message": "Quota exceeded"}}
    that is handled by the JSON parsing path in _detect_failure).

    Detection order:
    1. Always check stderr — CLI diagnostics always go there.
    2. Check stdout only if it does NOT parse as valid JSON (i.e., it is a
       plain-text error response from the CLI, not a structured API response).
    """
    if _QUOTA_EXHAUSTION_PATTERNS.search(stderr):
        return True
    # Check stdout only when it is not valid JSON (plain-text CLI error)
    stdout_stripped = stdout.strip()
    if stdout_stripped:
        try:
            json.loads(stdout_stripped)
            # Valid JSON — let _detect_failure handle it; don't intercept here.
            return False
        except (json.JSONDecodeError, ValueError):
            # Plain-text output from CLI — check for quota keywords.
            return bool(_QUOTA_EXHAUSTION_PATTERNS.search(stdout_stripped))
    return False


# ---------------------------------------------------------------------------
# Ticket YAML reader (B1 fix — CLI dispatch reads ticket for images/prompt)
# ---------------------------------------------------------------------------

def _load_ticket_from_yaml(ticket_id: str, project_root: Path) -> Optional[dict]:
    """Load a ticket dict from QUEUE.yaml or ARCHIVE.yaml.

    Returns None if not found or yaml unavailable.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None

    for yaml_path in [
        project_root / "devos" / "tasks" / "QUEUE.yaml",
        project_root / "devos" / "tasks" / "ARCHIVE.yaml",
    ]:
        if not yaml_path.exists():
            continue
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for ticket in data.get("tickets", []):
            if ticket.get("id") == ticket_id:
                return ticket
    return None


# ---------------------------------------------------------------------------
# CLI entry point (called by `make dispatch-gemini T=<id>`)
# ---------------------------------------------------------------------------


def _cli_main(
    argv: list[str] | None = None,
    *,
    project_root: Optional[Path] = None,
) -> int:
    """Minimal CLI wrapper for make dispatch-gemini.

    B1 fix: dispatch subcommand reads ticket YAML for gui_review.images +
    prompt when --prompt/--images are not provided explicitly.

    R4 fix (BLOCKER — 4th generation): dispatch-env subcommand reads T from
    os.environ['GEMINI_T'].  Make export directive sets GEMINI_T directly in the
    child process env block before any shell runs.  The recipe body contains no
    $(T) textual substitution — textual substitution surface is zero.
    Attack strings (backtick, $(), single-quote, double-quote, newline) arrive as
    opaque byte strings — never evaluated by shell.

    T-OS3-GEMINI-TEMPLATE-SYNC (DOD-2): project_root kwarg allows callers (e.g.
    cli_gemini.py) to pass an explicit project root resolved from --project flag,
    bypassing the OS3_PROJECT_ROOT / OS2_PROJECT_ROOT env-only path. When
    project_root is None, falls back to the env-based resolution (existing
    behaviour preserved for subprocess/Make callers).

    Usage: python -m server.gemini_dispatcher dispatch <ticket_id>
           python -m server.gemini_dispatcher dispatch-env   # GEMINI_T from env (Make export)
           python -m server.gemini_dispatcher smoke
    """
    import argparse

    parser = argparse.ArgumentParser(prog="gemini_dispatcher")
    sub = parser.add_subparsers(dest="command")

    dispatch_p = sub.add_parser("dispatch", help="Dispatch a ticket to gemini")
    dispatch_p.add_argument("ticket_id")
    dispatch_p.add_argument(
        "--prompt", default=None,
        help="Prompt text (overrides ticket yaml; required if ticket has no gui_review.prompt)"
    )
    dispatch_p.add_argument(
        "--images", nargs="*", default=None,
        help="Image paths (overrides ticket yaml gui_review.images)"
    )
    dispatch_p.add_argument(
        "--gui-review-required", action="store_true", default=False
    )
    dispatch_p.add_argument("--model", default=GEMINI_DEFAULT_MODEL)

    # dispatch-env subcommand (R4 fix):
    # Reads T from os.environ['GEMINI_T'] — set by Make export directive.
    # Make export sets GEMINI_T in the child process env block before any shell runs.
    # $(T) textual substitution does NOT appear in the recipe body — zero quoting surface.
    # Attack strings (backtick, $(), single-quote, double-quote, newline) arrive as
    # opaque byte strings in the env — never evaluated by shell.
    dispatch_env_p = sub.add_parser(
        "dispatch-env",
        help="Dispatch ticket — reads T from env var GEMINI_T (Make export, shell-injection-proof)",
    )
    dispatch_env_p.add_argument(
        "--gui-review-required", action="store_true", default=False
    )
    dispatch_env_p.add_argument("--model", default=GEMINI_DEFAULT_MODEL)

    sub.add_parser("smoke", help="Force re-run smoke test (ignores cache)")
    # W5 (01a): operational status summary subcommand
    sub.add_parser("status", help="Show failures.jsonl + quota summary (last 24h)")

    args = parser.parse_args(argv)
    # DOD-2 (T-OS3-GEMINI-TEMPLATE-SYNC): explicit project_root kwarg wins over env.
    # This closes the wiring gap where --project from the outer CLI was ignored.
    if project_root is not None:
        project_root = project_root.resolve()
    else:
        project_root = Path(
            os.environ.get("OS3_PROJECT_ROOT") or os.environ.get("OS2_PROJECT_ROOT", ".")
        ).resolve()

    if args.command == "status":
        return _gemini_status(project_root)

    if args.command == "smoke":
        dispatcher = GeminiDispatcher(project_root=project_root)
        # Delete existing cache to force re-run
        for f in (project_root / ".cache").glob("gemini-smoke-*.ok"):
            f.unlink()
        try:
            dispatcher._ensure_smoke_cache()
            print("[smoke-gemini] PASS — cache created")
            return 0
        except Exception as exc:
            print(f"[smoke-gemini] FAIL: {exc}", file=sys.stderr)
            return 1

    if args.command in ("dispatch", "dispatch-env"):
        # Check gemini binary present
        import shutil as _shutil
        if not _shutil.which("gemini"):
            print(
                "[dispatch-gemini] ERROR: gemini binary not found. "
                "Install gemini CLI first.",
                file=sys.stderr,
            )
            return 1

        # R4 fix: dispatch-env reads ticket_id from os.environ['GEMINI_T'].
        # Make export directive sets GEMINI_T directly in the child process env block —
        # no shell quoting surface: $(T) textual substitution does NOT appear in the
        # recipe body.  The env var arrives here as a plain string — never evaluated.
        if args.command == "dispatch-env":
            ticket_id = os.environ.get("GEMINI_T", "")
            if not ticket_id:
                print(
                    "[dispatch-gemini] ERROR: T env var is empty. "
                    "Usage: make dispatch-gemini T=T-001",
                    file=sys.stderr,
                )
                return 1
            prompt = None
            image_paths = None
            gui_review_required = args.gui_review_required
            model = args.model
        else:
            ticket_id = args.ticket_id
            prompt = args.prompt
            image_paths = args.images  # may be None
            gui_review_required = args.gui_review_required
            model = args.model

        # B1: resolve prompt + images from ticket YAML when not provided via CLI
        if prompt is None or image_paths is None:
            ticket = _load_ticket_from_yaml(ticket_id, project_root)
            if ticket is not None:
                gui_review = ticket.get("gui_review") or {}
                if prompt is None:
                    prompt = gui_review.get("prompt", "")
                if image_paths is None:
                    image_paths = gui_review.get("images", [])
            else:
                # ticket not found — fall back to empty
                if prompt is None:
                    prompt = ""
                if image_paths is None:
                    image_paths = []

        if not prompt:
            print(
                f"[dispatch-gemini] ERROR: no prompt found for {ticket_id}. "
                "Provide --prompt or add gui_review.prompt to the ticket YAML.",
                file=sys.stderr,
            )
            return 1

        dispatcher = GeminiDispatcher(project_root=project_root, model=model)
        result = dispatcher.run(
            ticket_id=ticket_id,
            prompt=prompt,
            image_paths=image_paths or [],
            gui_review_required=gui_review_required,
        )

        if result.success:
            print(f"[dispatch-gemini] DONE {ticket_id}")
            return 0

        if result.exit_code != 0:
            return result.exit_code
        return 0  # fail-open

    parser.print_help()
    return 1


# ---------------------------------------------------------------------------
# Operational status summary (W5 — python3 -m server.gemini_dispatcher status)
# ---------------------------------------------------------------------------


def _gemini_status(project_root: Path) -> int:
    """Print a summary of failures.jsonl and quota_*.jsonl for the last 24 hours.

    W5 (01a): operational visibility target. Called by `python3 -m server.gemini_dispatcher status`.
    T-OSN-W7-GEMINI-04: also reads the daily counter file (server/state/gemini_quota_{date}.json)
    for accurate "today's calls" / "cap remaining" output.

    Output includes:
    - Daily cap (from config) and today's call count (from counter file)
    - Daily cap remaining (counter-based, accurate even if JSONL lags)
    - Total calls in the current month (from quota_*.jsonl)
    - Failures in last 24h (from failures.jsonl)
    - 24h failure rate
    - Confirmation that failures.jsonl is NOT git-tracked

    Returns exit code 0 (always — status is informational).
    """
    log_dir = project_root / "devos" / "logs" / "gemini"
    failures_log = log_dir / "failures.jsonl"

    now_utc = datetime.now(tz=timezone.utc)
    cutoff_24h = now_utc.timestamp() - 86400

    # ---- daily counter (T-OSN-W7-GEMINI-04: counter file is ground truth) ----
    resolved_cap = load_daily_cap(project_root)
    quota = GeminiQuota(project_root, daily_cap=resolved_cap)
    calls_today = quota.get_today_count()
    daily_cap_remaining = max(0, resolved_cap - calls_today)

    # ---- failures.jsonl ----
    failures_24h: list[dict] = []
    total_failures = 0
    if failures_log.exists():
        for line in failures_log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total_failures += 1
                ts_str = entry.get("ts", "")
                if ts_str:
                    try:
                        ts_dt = datetime.fromisoformat(ts_str)
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                        if ts_dt.timestamp() >= cutoff_24h:
                            failures_24h.append(entry)
                    except ValueError:
                        pass
            except json.JSONDecodeError:
                pass

    # ---- quota_*.jsonl ----
    ym = now_utc.strftime("%Y%m")
    quota_path = log_dir / f"quota_{ym}.jsonl"
    total_calls_month = 0
    calls_24h = 0
    if quota_path.exists():
        for line in quota_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                total_calls_month += 1
                ts_str = entry.get("ts", "")
                if ts_str:
                    try:
                        ts_dt = datetime.fromisoformat(ts_str)
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                        if ts_dt.timestamp() >= cutoff_24h:
                            calls_24h += 1
                    except ValueError:
                        pass
            except json.JSONDecodeError:
                pass

    # ---- git-ignore check ----
    import subprocess as _sp
    gi_result = _sp.run(
        ["git", "check-ignore", "-q", str(failures_log)],
        cwd=str(project_root),
        capture_output=True,
    )
    gitignore_status = "OK (not tracked)" if gi_result.returncode == 0 else "WARN: may be tracked!"

    # ---- failure rate ----
    total_attempts_24h = calls_24h + len(failures_24h)
    if total_attempts_24h > 0:
        failure_rate_24h = len(failures_24h) / total_attempts_24h * 100
    else:
        failure_rate_24h = 0.0

    print(
        f"\n=== gemini-status ===\n"
        f"  Daily cap:           {resolved_cap}\n"
        f"  Calls today (UTC):   {calls_today}\n"
        f"  Daily cap remaining: {daily_cap_remaining}\n"
        f"  Calls (last 24h):    {calls_24h}\n"
        f"  Calls (this month):  {total_calls_month}\n"
        f"  Failures (last 24h): {len(failures_24h)}\n"
        f"  Failures (total):    {total_failures}\n"
        f"  Failure rate (24h):  {failure_rate_24h:.1f}%\n"
        f"  failures.jsonl:      {gitignore_status}\n"
    )
    if failures_24h:
        print("  Recent failures (last 24h):")
        for f in failures_24h[-5:]:  # show last 5
            print(f"    [{f.get('ts', '?')}] {f.get('ticket_id', '?')}: "
                  f"{f.get('failure_reason', '')[:80]}")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())

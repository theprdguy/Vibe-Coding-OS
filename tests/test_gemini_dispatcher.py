"""T-OSN-W7-GEMINI-01 — GeminiDispatcher test suite.

TDD: tests written first, implementation in server/gemini_dispatcher.py.

Coverage (Round 1 — 26 tests):
- smoke cache creation and re-use
- path validation (exists + whitelist)
- --yolo / --approval-mode=yolo rejection guard
- HOME= env var present in subprocess args
- success path: exit 0 + response field + no error field + totalFail==0
- failure paths: exit !=0, error field, totalFail > 0
- gui_review_required=true  → fail-closed (exit != 0)
- gui_review_required=false (default) → fail-open (exit 0 + warning)
- handoff fallback invocation on failure
- daily cap hook

Coverage (Round 2 — BLOCKER/WARNING fix tests):
B1: CLI end-to-end reads ticket YAML for prompt/images → log file created
B2: literal yolo token lint test (ast-walk / precise grep)
B3: prompt injection rejection (@./ and @/ prefix), mid-sentence @ pass
B4: handoff shlex.quote — shell metachar in prompt/path not unquoted in output
B5: symlink rejection in validate_image_path
W1: case-insensitive yolo guard + space-separated --approval-mode YOLO
W2: PII redaction in log file (API key pattern stripped)
W3: ticket_id / model regex validation
W4: failure path assertion specificity
W5: run() integration test (cache absent → mocked success → cache created)

Coverage (Round 3 — BLOCKER fix generalisation):
R3-B1: mid-prompt @./ and @/ rejection (not just leading position)
R3-B2: failures.jsonl PII redaction + .gitignore covers gemini logs
R3-B3: macOS /private/var tmp path accepted (system symlink not rejected)
R3-B3: user-created symlink directory in path still rejected
R3-B4: all yolo literals in source have # safe: marker (grep lint)
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from server.gemini_dispatcher import (
    GeminiDispatcher,
    GeminiResult,
    GEMINI_DAILY_CAP,
    GEMINI_DEFAULT_MODEL,
    GEMINI_FALLBACK_MODEL,
    PathValidationError,
    PromptInjectionError,
    TicketIdError,
    ModelNameError,
    YoloForbiddenError,
    _validate_prompt,
    _load_ticket_from_yaml,
    _resolve_gemini_binary,
    _gemini_status,
    validate_image_path,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """A minimal project root with .cache dir and a dummy image."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    img = cache / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    logs = tmp_path / "devos" / "logs" / "gemini"
    logs.mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def dispatcher(project_root: Path) -> GeminiDispatcher:
    return GeminiDispatcher(project_root=project_root)


# ---------------------------------------------------------------------------
# Constants guard
# ---------------------------------------------------------------------------

def test_default_model_id():
    assert GEMINI_DEFAULT_MODEL == "gemini-3.1-pro-preview"


def test_fallback_model_id():
    assert GEMINI_FALLBACK_MODEL == "gemini-2.5-pro"


def test_daily_cap_default():
    assert GEMINI_DAILY_CAP == 50


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def test_validate_path_exists(project_root: Path):
    img = project_root / ".cache" / "test.png"
    result = validate_image_path(str(img), project_root=project_root)
    # Round 2: returns absolute Path (B5 fix)
    assert result.is_absolute()
    assert result == img.resolve()


def test_validate_path_missing_raises(project_root: Path):
    with pytest.raises(PathValidationError, match="not found"):
        validate_image_path(
            str(project_root / ".cache" / "nonexistent.png"),
            project_root=project_root,
        )


def test_validate_path_outside_project_raises(project_root: Path, tmp_path_factory):
    """Outside-project paths must be rejected (W4: use isolated tmp dir)."""
    outside_root = tmp_path_factory.mktemp("outside-root")
    outside = outside_root / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(PathValidationError, match="outside"):
        validate_image_path(str(outside), project_root=project_root)


def test_validate_relative_path_resolved(project_root: Path):
    """Relative paths resolved against project_root return absolute path."""
    result = validate_image_path(".cache/test.png", project_root=project_root)
    assert result.is_absolute()
    assert result.name == "test.png"


# ---------------------------------------------------------------------------
# B5 — Symlink rejection
# ---------------------------------------------------------------------------

def test_validate_path_symlink_rejected(project_root: Path, tmp_path_factory):
    """Input path that is a symlink must be rejected (B5 TOCTOU fix)."""
    # Create a real file and a symlink to it inside project_root
    real_img = project_root / ".cache" / "real.png"
    real_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    link_img = project_root / ".cache" / "link.png"
    link_img.symlink_to(real_img)

    with pytest.raises(PathValidationError, match="symlink"):
        validate_image_path(str(link_img), project_root=project_root)


# ---------------------------------------------------------------------------
# --yolo / approval-mode=yolo guard (Round 1 + W1 enhancements)
# ---------------------------------------------------------------------------

def test_yolo_forbidden_raises(dispatcher: GeminiDispatcher):
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(["gemini", "--yolo", "-p", "test"])


def test_approval_mode_yolo_forbidden_raises(dispatcher: GeminiDispatcher):
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(["gemini", "--approval-mode=yolo", "-p", "test"])


def test_safe_args_pass(dispatcher: GeminiDispatcher):
    # Should not raise
    dispatcher._check_no_yolo(["gemini", "--sandbox", "-p", "test"])


# W1: case-insensitive yolo guard
def test_yolo_case_insensitive_uppercase(dispatcher: GeminiDispatcher):
    """--YOLO (uppercase) must be caught (W1 fix)."""
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(["gemini", "--YOLO", "-p", "test"])


def test_approval_mode_yolo_mixed_case(dispatcher: GeminiDispatcher):
    """--approval-mode=YOLO must be caught (W1 fix)."""
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(["gemini", "--approval-mode=YOLO", "-p", "test"])


def test_approval_mode_yolo_space_separated(dispatcher: GeminiDispatcher):
    """--approval-mode YOLO (space-separated) must be caught (W1 fix)."""
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(
            ["gemini", "--approval-mode", "YOLO", "-p", "test"]
        )


def test_approval_mode_yolo_space_separated_lowercase(dispatcher: GeminiDispatcher):
    """--approval-mode yolo (space-separated lowercase) must be caught (W1 fix)."""
    with pytest.raises(YoloForbiddenError):
        dispatcher._check_no_yolo(
            ["gemini", "--approval-mode", "yolo", "-p", "test"]
        )


# ---------------------------------------------------------------------------
# W1 — env whitelist (no cloud secrets leak)
# ---------------------------------------------------------------------------

def test_build_env_strips_anthropic_keys(dispatcher: GeminiDispatcher):
    """ANTHROPIC_* keys must not appear in subprocess env (W1 fix)."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test123"}):
        env = dispatcher._build_env()
    assert "ANTHROPIC_API_KEY" not in env


def test_build_env_strips_aws_keys(dispatcher: GeminiDispatcher):
    """AWS_* keys must not appear in subprocess env (W1 fix)."""
    with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "secret123"}):
        env = dispatcher._build_env()
    assert "AWS_SECRET_ACCESS_KEY" not in env


def test_build_env_strips_gemini_yolo(dispatcher: GeminiDispatcher):
    """GEMINI_YOLO must be stripped from env (W1 fix)."""
    with patch.dict(os.environ, {"GEMINI_YOLO": "true"}):
        env = dispatcher._build_env()
    assert "GEMINI_YOLO" not in env


def test_build_env_strips_gemini_approval_mode(dispatcher: GeminiDispatcher):
    """GEMINI_APPROVAL_MODE must be stripped from env (W1 fix)."""
    with patch.dict(os.environ, {"GEMINI_APPROVAL_MODE": "yolo"}):
        env = dispatcher._build_env()
    assert "GEMINI_APPROVAL_MODE" not in env


def test_build_env_includes_home(dispatcher: GeminiDispatcher):
    """HOME must always be set in env."""
    env = dispatcher._build_env()
    assert "HOME" in env


# ---------------------------------------------------------------------------
# HOME= env var in subprocess command (Round 1)
# ---------------------------------------------------------------------------

def test_home_in_subprocess_env(dispatcher: GeminiDispatcher, project_root: Path):
    """HOME= must be explicitly present in the env passed to subprocess."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "looks good",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=success_payload,
            stderr="",
        )
        dispatcher.run(
            ticket_id="T-TEST-01",
            prompt="describe this image",
            image_paths=[str(img)],
        )
        assert mock_run.called
        _, kwargs = mock_run.call_args
        env = kwargs.get("env") or {}
        assert "HOME" in env, "HOME must be explicitly set in subprocess env"


# ---------------------------------------------------------------------------
# B3 — Prompt injection guard
# ---------------------------------------------------------------------------

def test_prompt_injection_at_dot_slash_rejected():
    """Prompt starting with @./ must be rejected (B3 fix)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("@./../../etc/passwd describe this")


def test_prompt_injection_at_absolute_rejected():
    """Prompt starting with @/ must be rejected (B3 fix)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("@/etc/passwd read this file")


def test_prompt_mid_sentence_at_allowed():
    """Prompt with @ in the middle (not a file-token) must pass (B3 fix)."""
    # Should not raise
    _validate_prompt("describe @ symbol meaning")
    _validate_prompt("email me @ example.com for details")


def test_prompt_leading_whitespace_then_injection_rejected():
    """Leading whitespace before @./ must still be caught (B3 fix)."""
    with pytest.raises(PromptInjectionError):
        _validate_prompt("   @./secret.txt read this")


# ---------------------------------------------------------------------------
# W3 — ticket_id / model regex validation
# ---------------------------------------------------------------------------

def test_invalid_ticket_id_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """ticket_id with directory traversal must be rejected (W3 fix)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError):
        dispatcher.run(
            ticket_id="../etc/passwd",
            prompt="describe",
            image_paths=[str(img)],
        )


def test_invalid_model_name_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """model with shell metachar must be rejected (W3 fix)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(ModelNameError):
        dispatcher.run(
            ticket_id="T-TEST-01",
            prompt="describe",
            image_paths=[str(img)],
            model="gemini; rm -rf ~",
        )


def test_valid_ticket_id_format(dispatcher: GeminiDispatcher, project_root: Path):
    """Standard ticket IDs like T-OSN-W7-01 must pass regex (W3 fix)."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        # Should not raise TicketIdError
        result = dispatcher.run(
            ticket_id="T-OSN-W7-01",
            prompt="describe",
            image_paths=[str(img)],
        )
    assert result.success is True


# ---------------------------------------------------------------------------
# Success path (Round 1)
# ---------------------------------------------------------------------------

def test_run_success_creates_log(dispatcher: GeminiDispatcher, project_root: Path):
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "image shows gradient",
        "stats": {"tools": {"totalCalls": 1, "totalFail": 0}},
        "session_id": "abc123",
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-TEST-02",
            prompt="describe",
            image_paths=[str(img)],
        )

    assert result.success is True
    # Log file must exist
    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-TEST-02*.md"))
    assert len(logs) == 1, f"Expected 1 log file, found: {logs}"


def test_run_success_result_fields(dispatcher: GeminiDispatcher, project_root: Path):
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "gradient image",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-TEST-03",
            prompt="describe",
            image_paths=[str(img)],
        )

    assert result.success is True
    assert result.response == "gradient image"
    assert result.error is None


def _visual_review_response(verdict: str, *, issues: list[dict] | None = None) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "issues": issues or [],
            "human_review_required": verdict == "needs_human_judgment",
            "same_issue_as_previous_round": False,
        }
    )


def test_required_visual_review_pass_schema_succeeds(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    payload = json.dumps({
        "response": _visual_review_response("pass"),
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-VISUAL-PASS",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert result.success is True
    assert result.visual_review is not None
    assert result.visual_review["verdict"] == "pass"


def test_required_visual_review_request_changes_blocks_without_handoff(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    issue = {
        "severity": "blocker",
        "category": "overlap",
        "evidence": "Primary button overlaps the footer at 390px width.",
        "recommendation": "Fix the mobile layout before release.",
    }
    payload = json.dumps({
        "response": _visual_review_response("request_changes", issues=[issue]),
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run, patch.object(
        dispatcher,
        "handoff_fallback",
    ) as mock_handoff:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-VISUAL-BLOCK",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert result.success is False
    assert result.exit_code == 1
    assert result.error is not None
    assert "visual_review_request_changes" in result.error
    assert result.visual_review is not None
    assert result.visual_review["issues"][0]["category"] == "overlap"
    mock_handoff.assert_not_called()


def test_required_visual_review_invalid_schema_blocks_as_infra_failure(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    payload = json.dumps({
        "response": "looks good",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-VISUAL-SCHEMA",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert result.success is False
    assert result.exit_code == 1
    assert result.error is not None
    assert "visual_review_infra_failure" in result.error


def test_non_required_visual_review_request_changes_is_report_only(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    issue = {
        "severity": "warning",
        "category": "taste",
        "evidence": "The hero image feels less aligned with the brand.",
        "recommendation": "Ask PM whether to adjust the image direction.",
    }
    payload = json.dumps({
        "response": _visual_review_response("request_changes", issues=[issue]),
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-VISUAL-REPORT",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=False,
        )

    assert result.success is True
    assert result.visual_review is not None
    assert result.visual_review["verdict"] == "request_changes"


def test_repeated_taste_issue_moves_required_visual_review_to_pm_judgment(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    issue = {
        "severity": "warning",
        "category": "taste",
        "evidence": "The card spacing feels too airy for a dense dashboard.",
        "recommendation": "Ask PM whether to keep the roomier spacing.",
    }
    payload = json.dumps({
        "response": _visual_review_response("request_changes", issues=[issue]),
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        first = dispatcher.run(
            ticket_id="T-VISUAL-TASTE",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )
        second = dispatcher.run(
            ticket_id="T-VISUAL-TASTE",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert first.success is False
    assert first.error is not None
    assert "visual_review_request_changes" in first.error
    assert second.success is False
    assert second.error is not None
    assert "visual_review_needs_human_judgment" in second.error
    assert second.visual_review is not None
    assert second.visual_review["verdict"] == "needs_human_judgment"
    assert second.visual_review["original_verdict"] == "request_changes"
    assert second.visual_review["same_issue_as_previous_round"] is True
    assert second.visual_review["human_review_required"] is True


def test_repeated_objective_issue_continues_to_block_required_visual_review(
    dispatcher: GeminiDispatcher,
    project_root: Path,
):
    img = project_root / ".cache" / "test.png"
    issue = {
        "severity": "blocker",
        "category": "overlap",
        "evidence": "The primary button overlaps the checkout total on mobile.",
        "recommendation": "Fix the mobile layout before release.",
    }
    payload = json.dumps({
        "response": _visual_review_response("request_changes", issues=[issue]),
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")
        dispatcher.run(
            ticket_id="T-VISUAL-OBJECTIVE",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )
        second = dispatcher.run(
            ticket_id="T-VISUAL-OBJECTIVE",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert second.success is False
    assert second.error is not None
    assert "visual_review_request_changes" in second.error
    assert second.visual_review is not None
    assert second.visual_review["verdict"] == "request_changes"
    assert second.visual_review["same_issue_as_previous_round"] is True


# ---------------------------------------------------------------------------
# Failure: exit != 0 (W4: specific substring assertions)
# ---------------------------------------------------------------------------

def test_run_nonzero_exit_is_failure(dispatcher: GeminiDispatcher, project_root: Path):
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({
        "error": {"type": "Error", "message": "ModelNotFoundError"},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=error_payload, stderr="model not found"
        )
        result = dispatcher.run(
            ticket_id="T-FAIL-01",
            prompt="describe",
            image_paths=[str(img)],
        )

    assert result.success is False
    # W4: specific error content check
    assert result.error is not None
    assert "exit_code=1" in result.error


# ---------------------------------------------------------------------------
# Failure: error field present (exit 0 but error field) (W4)
# ---------------------------------------------------------------------------

def test_run_error_field_is_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """exit 0 but JSON has error field — must still be treated as failure."""
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({
        "session_id": "xyz",
        "error": {"type": "Error", "message": "Quota exceeded"},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=error_payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-FAIL-02",
            prompt="describe",
            image_paths=[str(img)],
        )

    assert result.success is False
    # W4: specific error substring
    assert result.error is not None
    assert "error field" in result.error


# ---------------------------------------------------------------------------
# Failure: stats.tools.totalFail > 0 (W4)
# ---------------------------------------------------------------------------

def test_run_total_fail_is_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """exit 0 + no error field, but totalFail > 0 — must be failure."""
    img = project_root / ".cache" / "test.png"
    payload = json.dumps({
        "response": "partial",
        "stats": {"tools": {"totalCalls": 2, "totalFail": 1}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-FAIL-03",
            prompt="describe",
            image_paths=[str(img)],
        )

    assert result.success is False
    # W4: specific error substring
    assert result.error is not None
    assert "totalFail" in result.error


# ---------------------------------------------------------------------------
# gui_review_required: fail-closed vs fail-open (Round 1)
# ---------------------------------------------------------------------------

def test_fail_closed_on_gui_required_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """gui_review_required=true + failure → GeminiResult.exit_code != 0."""
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({
        "error": {"type": "Error", "message": "OAuth failed"},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=error_payload, stderr="OAuth error"
        )
        result = dispatcher.run(
            ticket_id="T-FAILCLOSED-01",
            prompt="review GUI",
            image_paths=[str(img)],
            gui_review_required=True,
        )

    assert result.success is False
    assert result.exit_code != 0


def test_fail_open_on_non_gui_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """gui_review_required=False (default) + failure → exit 0 + warning."""
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({
        "error": {"type": "Error", "message": "network error"},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=error_payload, stderr="network error"
        )
        result = dispatcher.run(
            ticket_id="T-FAILOPEN-01",
            prompt="review",
            image_paths=[str(img)],
            gui_review_required=False,
        )

    assert result.success is False
    assert result.exit_code == 0  # fail-open
    assert result.warning is not None


# ---------------------------------------------------------------------------
# Handoff fallback invocation (Round 1)
# ---------------------------------------------------------------------------

def test_handoff_called_on_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """On failure, handoff_fallback() must be called."""
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({"error": {"message": "gemini not found"}})

    with patch("subprocess.run") as mock_run, \
         patch.object(dispatcher, "handoff_fallback") as mock_handoff:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=error_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-HANDOFF-01",
            prompt="review",
            image_paths=[str(img)],
        )

    mock_handoff.assert_called_once()
    args = mock_handoff.call_args[0]
    assert "T-HANDOFF-01" in args[0] or args[0] == "T-HANDOFF-01"


def test_handoff_prints_paste_instructions(dispatcher: GeminiDispatcher, project_root: Path, capsys):
    """handoff_fallback() must print a paste-waiting message to stdout."""
    img = project_root / ".cache" / "test.png"
    dispatcher.handoff_fallback("T-HANDOFF-02", prompt="review", image_paths=[".cache/test.png"])
    out = capsys.readouterr().out
    assert "paste" in out.lower() or "manual" in out.lower()


# ---------------------------------------------------------------------------
# B4 — handoff shlex.quote (shell metachar injection prevention)
# ---------------------------------------------------------------------------

def test_handoff_quotes_shell_metachar_in_prompt(
    dispatcher: GeminiDispatcher, project_root: Path, capsys
):
    """Prompt with shell metachar must be quoted — no literal ; in handoff output."""
    dispatcher.handoff_fallback(
        "T-HANDOFF-SEC",
        prompt="; rm -rf ~ #",
        image_paths=["screenshot.png"],
    )
    out = capsys.readouterr().out
    # The raw metachar should not appear unquoted in any bash command context.
    # After shlex.quote, the semicolon will be inside quoted string (won't appear as bare ;)
    # Check that the script file was written with shlex.quote applied
    script = project_root / ".cache" / "gemini-handoff-T-HANDOFF-SEC.sh"
    assert script.exists(), "Handoff script file must be created"
    content = script.read_text()
    # The dangerous string "; rm -rf ~ #" should not appear unquoted
    # shlex.quote wraps it in single quotes: "'; rm -rf ~ #'"
    assert "; rm -rf ~ #" not in content or "'; rm -rf ~ #'" in content, (
        "Shell metachar in prompt must be quoted in handoff script"
    )


def test_handoff_quotes_shell_metachar_in_image_path(
    dispatcher: GeminiDispatcher, project_root: Path, capsys
):
    """Image path with shell metachar must be quoted in handoff script (B4 fix).

    shlex.quote wraps paths in single quotes so $(echo) inside single quotes
    is not subject to shell expansion — that IS the safe form.
    """
    dispatcher.handoff_fallback(
        "T-HANDOFF-IMG-SEC",
        prompt="describe",
        image_paths=["path with spaces/image$(echo).png"],
    )
    script = project_root / ".cache" / "gemini-handoff-T-HANDOFF-IMG-SEC.sh"
    assert script.exists(), "Handoff script must be created"
    content = script.read_text()
    # Acceptable forms: the metachar is inside single quotes (shell-safe)
    # or double-quoted. Unquoted bare $( is NOT acceptable.
    # shlex.quote produces single-quoted form: '@./path with spaces/image$(echo).png'
    # Inside single quotes $(...) is literal — this is the correct safe form.
    if "$(echo)" in content:
        # Must be inside single quotes to be safe
        import re
        # Find all single-quoted tokens containing $(echo)
        safe_occurrences = re.findall(r"'[^']*\$\(echo\)[^']*'", content)
        assert len(safe_occurrences) > 0, (
            "$(echo) found in handoff script outside of single-quoted context — "
            "this is a shell injection risk. content:\n" + content
        )


# ---------------------------------------------------------------------------
# Smoke cache (Round 1)
# ---------------------------------------------------------------------------

def test_smoke_cache_created_on_first_run(dispatcher: GeminiDispatcher, project_root: Path):
    """First run without cache → smoke test runs → cache file created."""
    cache_dir = project_root / ".cache"
    # Ensure no existing cache
    for f in cache_dir.glob("gemini-smoke-*.ok"):
        f.unlink()

    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        dispatcher._ensure_smoke_cache()

    ok_files = list(cache_dir.glob("gemini-smoke-*.ok"))
    assert len(ok_files) >= 1, "Smoke cache file must be created"


def test_smoke_cache_not_re_run_if_present(dispatcher: GeminiDispatcher, project_root: Path):
    """If cache file exists, smoke is NOT re-run (subprocess.run not called for smoke)."""
    cache_dir = project_root / ".cache"
    cache_file = cache_dir / f"gemini-smoke-{GEMINI_DEFAULT_MODEL}.ok"
    cache_file.write_text("ok\n")

    with patch("subprocess.run") as mock_run:
        dispatcher._ensure_smoke_cache()
        # subprocess.run should NOT have been called for the smoke
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# W5 — run() integration test: cache-absent → mocked success → cache created
# ---------------------------------------------------------------------------

def test_run_triggers_smoke_and_creates_cache(
    dispatcher: GeminiDispatcher, project_root: Path
):
    """run() with no cache → smoke runs (via _ensure_smoke_cache) → cache file created
    and on mocked subprocess success the log file is also created (W5 fix)."""
    cache_dir = project_root / ".cache"
    # Ensure no existing cache
    for f in cache_dir.glob("gemini-smoke-*.ok"):
        f.unlink()

    img = cache_dir / "test.png"
    success_payload = json.dumps({
        "response": "all good",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-SMOKE-INT-01",
            prompt="check",
            image_paths=[str(img)],
        )

    # Smoke cache must be created
    ok_files = list(cache_dir.glob("gemini-smoke-*.ok"))
    assert len(ok_files) >= 1, "Smoke cache file must be created after run()"

    # Main run must succeed
    assert result.success is True

    # Log file must exist
    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-SMOKE-INT-01*.md"))
    assert len(logs) == 1, "Log file must be created on success"


def test_run_smoke_fail_triggers_handoff(
    dispatcher: GeminiDispatcher, project_root: Path
):
    """run() with no cache + smoke fails → handoff_fallback triggered (W5 fix)."""
    cache_dir = project_root / ".cache"
    for f in cache_dir.glob("gemini-smoke-*.ok"):
        f.unlink()

    img = cache_dir / "test.png"
    # First call (smoke) returns error, second call (main run) also fails
    fail_payload = json.dumps({"error": {"message": "auth failed"}})

    with patch("subprocess.run") as mock_run, \
         patch.object(dispatcher, "handoff_fallback") as mock_handoff:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=fail_payload, stderr="auth fail"
        )
        result = dispatcher.run(
            ticket_id="T-SMOKE-INT-FAIL-01",
            prompt="check",
            image_paths=[str(img)],
        )

    # handoff must be triggered (smoke failure is non-fatal but main run fails)
    mock_handoff.assert_called_once()
    assert result.success is False


# ---------------------------------------------------------------------------
# --sandbox forced (Round 1)
# ---------------------------------------------------------------------------

def test_sandbox_flag_in_command(dispatcher: GeminiDispatcher, project_root: Path):
    """--sandbox must always appear in the gemini command."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-SANDBOX-01",
            prompt="check",
            image_paths=[str(img)],
        )
        assert mock_run.called
        args, _ = mock_run.call_args
        cmd = args[0]
        assert "--sandbox" in cmd, f"--sandbox missing from command: {cmd}"


# ---------------------------------------------------------------------------
# shell=True forbidden (Round 1)
# ---------------------------------------------------------------------------

def test_shell_false_in_subprocess(dispatcher: GeminiDispatcher, project_root: Path):
    """subprocess.run must be called with shell=False (list-form command)."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-SHELL-01",
            prompt="check",
            image_paths=[str(img)],
        )
        _, kwargs = mock_run.call_args
        assert kwargs.get("shell") is not True, "shell=True is forbidden"


# ---------------------------------------------------------------------------
# Quota log creation (Round 1)
# ---------------------------------------------------------------------------

def test_quota_log_appended_on_success(dispatcher: GeminiDispatcher, project_root: Path):
    """Each run appends a line to quota_{YYYYMM}.jsonl."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {
            "tools": {"totalCalls": 1, "totalFail": 0},
            "inputTokens": 1000,
            "outputTokens": 50,
        },
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-QUOTA-01",
            prompt="check",
            image_paths=[str(img)],
        )

    from datetime import datetime
    ym = datetime.now().strftime("%Y%m")
    quota_file = project_root / "devos" / "logs" / "gemini" / f"quota_{ym}.jsonl"
    assert quota_file.exists(), f"Quota log not found: {quota_file}"
    lines = quota_file.read_text().strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[-1])
    assert entry["ticket_id"] == "T-QUOTA-01"


# ---------------------------------------------------------------------------
# gemini binary not found (Round 1)
# ---------------------------------------------------------------------------

def test_gemini_not_found_triggers_handoff(dispatcher: GeminiDispatcher, project_root: Path):
    """FileNotFoundError (gemini not installed) triggers handoff_fallback."""
    img = project_root / ".cache" / "test.png"

    with patch("subprocess.run", side_effect=FileNotFoundError("gemini not found")), \
         patch.object(dispatcher, "handoff_fallback") as mock_handoff:
        result = dispatcher.run(
            ticket_id="T-NOTFOUND-01",
            prompt="check",
            image_paths=[str(img)],
        )

    assert result.success is False
    mock_handoff.assert_called_once()


# ---------------------------------------------------------------------------
# W2 — PII redaction in log file
# ---------------------------------------------------------------------------

def test_log_redacts_api_key(dispatcher: GeminiDispatcher, project_root: Path):
    """API key patterns must be redacted before writing to log file (W2 fix)."""
    img = project_root / ".cache" / "test.png"
    # Response contains a simulated API key
    success_payload = json.dumps({
        "response": "The secret key is sk-1234567890abcdefghijklmnop and should not leak",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        result = dispatcher.run(
            ticket_id="T-REDACT-01",
            prompt="check",
            image_paths=[str(img)],
        )

    assert result.success is True
    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-REDACT-01*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    # The raw API key pattern must not appear in the log
    assert "sk-1234567890abcdefghijklmnop" not in content
    # The redaction placeholder must be present
    assert "[REDACTED-SK]" in content


def test_log_redacts_github_token(dispatcher: GeminiDispatcher, project_root: Path):
    """GitHub token pattern must be redacted in log file (W2 fix)."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "Token: ghp_abcdefghijklmnopqrstuvwxyz123456",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-REDACT-02",
            prompt="check",
            image_paths=[str(img)],
        )

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-REDACT-02*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in content
    assert "[REDACTED-GHP]" in content


# ---------------------------------------------------------------------------
# B2 — literal yolo token lint test (AST-based)
# ---------------------------------------------------------------------------

def test_no_yolo_call_site_in_source():
    """The gemini_dispatcher source must not pass literal yolo tokens to subprocess
    (call-site guard). Uses AST walk to find subprocess.run argv containing yolo.

    B2 fix: this test replaces the fragile grep-bypass (_DD + 'yolo') with a
    structured check that the guard constants are defined but never passed as
    subprocess argv. The verify grep in QUEUE.yaml should be updated to use
    a refined pattern (see session log B2 note).
    """
    import server.gemini_dispatcher as mod
    source_path = Path(mod.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    yolo_call_sites: list[int] = []

    for node in ast.walk(tree):
        # Look for subprocess.run([..., "--yolo", ...]) call patterns
        if not isinstance(node, ast.Call):
            continue
        # Check if this is subprocess.run / subprocess.Popen etc.
        func = node.func
        is_subprocess_call = (
            (isinstance(func, ast.Attribute) and func.attr in {"run", "Popen", "call", "check_call", "check_output"})
            or (isinstance(func, ast.Name) and func.id in {"run", "Popen"})
        )
        if not is_subprocess_call:
            continue
        # Look for list literal first argument containing yolo strings
        if not node.args:
            continue
        first_arg = node.args[0]
        if isinstance(first_arg, ast.List):
            for elt in first_arg.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    val = elt.value.lower()
                    if val in {"--yolo", "--approval-mode=yolo"}:
                        yolo_call_sites.append(node.lineno)

    assert yolo_call_sites == [], (
        f"Found yolo literal passed directly to subprocess at lines: {yolo_call_sites}. "
        "Yolo flags must only appear in guard/check constants, not as subprocess argv."
    )


# ---------------------------------------------------------------------------
# B1 — CLI end-to-end: ticket YAML with gui_review.images → log file created
# ---------------------------------------------------------------------------

def test_cli_dispatch_reads_ticket_yaml(project_root: Path):
    """_cli_main dispatch reads ticket YAML for prompt/images (B1 fix).

    Fixture ticket T-DUMMY-GEMINI-FIXTURE in a temp QUEUE.yaml with
    gui_review.images pointing to .cache/gemini-spike-test.png.
    CLI invocation with only ticket_id → log file created.
    """
    # Create fixture image
    fixture_img = project_root / ".cache" / "gemini-spike-test.png"
    fixture_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # Create minimal QUEUE.yaml with fixture ticket
    tasks_dir = project_root / "devos" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    queue_yaml = tasks_dir / "QUEUE.yaml"
    queue_yaml.write_text(
        "tickets:\n"
        "  - id: T-DUMMY-GEMINI-FIXTURE\n"
        "    status: todo\n"
        "    owner: BUILDER\n"
        "    goal: test fixture\n"
        "    gui_review:\n"
        "      prompt: 'Describe the gradient in this test image'\n"
        "      images:\n"
        f"        - .cache/gemini-spike-test.png\n",
        encoding="utf-8",
    )

    success_payload = json.dumps({
        "response": "test passed",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    import shutil as _shutil
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=success_payload, stderr=""
        )
        from server.gemini_dispatcher import _cli_main
        exit_code = _cli_main(["dispatch", "T-DUMMY-GEMINI-FIXTURE"])

    assert exit_code == 0, f"CLI should exit 0 on success, got {exit_code}"

    # Log file must be created
    logs = list(
        (project_root / "devos" / "logs" / "gemini").glob(
            "*T-DUMMY-GEMINI-FIXTURE*.md"
        )
    )
    assert len(logs) == 1, f"Expected 1 log file after CLI dispatch, found: {logs}"


def test_cli_dispatch_no_prompt_exits_error(project_root: Path):
    """CLI dispatch with ticket that has no prompt must exit 1 with error message."""
    tasks_dir = project_root / "devos" / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    queue_yaml = tasks_dir / "QUEUE.yaml"
    queue_yaml.write_text(
        "tickets:\n"
        "  - id: T-NO-PROMPT-01\n"
        "    status: todo\n"
        "    owner: BUILDER\n"
        "    goal: test fixture\n",
        encoding="utf-8",
    )

    import shutil as _shutil
    with patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.dict(os.environ, {"OS2_PROJECT_ROOT": str(project_root)}):
        from server.gemini_dispatcher import _cli_main
        exit_code = _cli_main(["dispatch", "T-NO-PROMPT-01"])

    assert exit_code == 1, "CLI should exit 1 when no prompt available"


# ---------------------------------------------------------------------------
# failures.jsonl append on failure
# ---------------------------------------------------------------------------

def test_failures_log_appended_on_failure(dispatcher: GeminiDispatcher, project_root: Path):
    """Each failure appends a line to failures.jsonl."""
    img = project_root / ".cache" / "test.png"
    error_payload = json.dumps({"error": {"message": "auth error"}})

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=error_payload, stderr=""
        )
        dispatcher.run(
            ticket_id="T-FAILLOG-01",
            prompt="check",
            image_paths=[str(img)],
        )

    failures_log = project_root / "devos" / "logs" / "gemini" / "failures.jsonl"
    assert failures_log.exists(), "failures.jsonl must be created on failure"
    lines = failures_log.read_text().strip().splitlines()
    assert len(lines) >= 1
    entry = json.loads(lines[-1])
    assert entry["ticket_id"] == "T-FAILLOG-01"
    assert "failure_reason" in entry


# ---------------------------------------------------------------------------
# Round 3 — B1: mid-prompt @./ bypass generalisation
# ---------------------------------------------------------------------------

def test_prompt_mid_prompt_at_dot_slash_rejected():
    """@./ token mid-prompt (after text) must be rejected (Round 3 B1)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("hi @./../etc/passwd")


def test_prompt_newline_at_dot_slash_rejected():
    """@./ token on second line must be rejected (Round 3 B1)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("describe this then\n@./.env")


def test_prompt_mid_sentence_at_abs_rejected():
    """@/etc/passwd mid-sentence must be rejected (Round 3 B1)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("a @/etc/passwd b")


def test_prompt_leading_whitespace_at_dot_slash_rejected():
    """Leading whitespace before @./ must be rejected (Round 3 B1, confirms lstrip fix)."""
    with pytest.raises(PromptInjectionError):
        _validate_prompt("  @./secret")


def test_prompt_tab_at_abs_rejected():
    """Tab before @/ must be rejected (Round 3 B1)."""
    with pytest.raises(PromptInjectionError):
        _validate_prompt("\t@/abs/path")


def test_prompt_bare_at_email_mid_allowed():
    """Bare @ not followed by ./ or / mid-sentence must pass (Round 3 B1)."""
    # Should not raise
    _validate_prompt("email me @ example.com")


def test_prompt_bare_at_symbol_description_allowed():
    """@ symbol description mid-prompt must pass (Round 3 B1)."""
    # Should not raise
    _validate_prompt("describe @ symbol")


def test_prompt_clean_text_allowed():
    """Plain text with no @ must pass (Round 3 B1)."""
    # Should not raise
    _validate_prompt("hi")


# ---------------------------------------------------------------------------
# Round 3 — B2: failures.jsonl PII redaction
# ---------------------------------------------------------------------------

def test_failures_log_redacts_sk_token(dispatcher: GeminiDispatcher, project_root: Path):
    """Raw sk-* token in failure_reason must be redacted in failures.jsonl (Round 3 B2)."""
    img = project_root / ".cache" / "test.png"
    # Inject a raw error message that looks like a subprocess stderr with a token
    raw_error_msg = "auth failure: sk-test123abcdefghijklmnopqrstuvwxyz"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps({"error": {"message": raw_error_msg}}),
            stderr=raw_error_msg,
        )
        dispatcher.run(
            ticket_id="T-R3B2-SK-01",
            prompt="check",
            image_paths=[str(img)],
        )

    failures_log = project_root / "devos" / "logs" / "gemini" / "failures.jsonl"
    assert failures_log.exists()
    lines = failures_log.read_text().strip().splitlines()
    last_entry = json.loads(lines[-1])
    assert last_entry["ticket_id"] == "T-R3B2-SK-01"
    # The raw sk- token must not appear in the log
    assert "sk-test123abcdefghijklmnopqrstuvwxyz" not in last_entry["failure_reason"], (
        "sk-* token must be redacted in failures.jsonl"
    )
    assert "[REDACTED-SK]" in last_entry["failure_reason"], (
        "Expected [REDACTED-SK] placeholder in failures.jsonl"
    )


def test_failures_log_redacts_bearer_token(dispatcher: GeminiDispatcher, project_root: Path):
    """Bearer token in failure_reason must be redacted (Round 3 B2)."""
    img = project_root / ".cache" / "test.png"
    raw_error = "HTTP 401: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload.signature"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps({"error": {"message": raw_error}}),
            stderr=raw_error,
        )
        dispatcher.run(
            ticket_id="T-R3B2-BEARER-01",
            prompt="check",
            image_paths=[str(img)],
        )

    failures_log = project_root / "devos" / "logs" / "gemini" / "failures.jsonl"
    lines = failures_log.read_text().strip().splitlines()
    matching = [json.loads(l) for l in lines if json.loads(l)["ticket_id"] == "T-R3B2-BEARER-01"]
    assert len(matching) == 1
    entry = matching[0]
    assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in entry["failure_reason"], (
        "JWT token must be redacted in failures.jsonl"
    )


def test_failures_log_redacts_ghp_token(dispatcher: GeminiDispatcher, project_root: Path):
    """ghp_* token in failure_reason must be redacted (Round 3 B2)."""
    img = project_root / ".cache" / "test.png"
    raw_error = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx leaked in stderr"

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=json.dumps({"error": {"message": raw_error}}),
            stderr=raw_error,
        )
        dispatcher.run(
            ticket_id="T-R3B2-GHP-01",
            prompt="check",
            image_paths=[str(img)],
        )

    failures_log = project_root / "devos" / "logs" / "gemini" / "failures.jsonl"
    lines = failures_log.read_text().strip().splitlines()
    matching = [json.loads(l) for l in lines if json.loads(l)["ticket_id"] == "T-R3B2-GHP-01"]
    assert len(matching) == 1
    assert "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" not in matching[0]["failure_reason"], (
        "ghp_* token must be redacted in failures.jsonl"
    )
    assert "[REDACTED-GHP]" in matching[0]["failure_reason"]


def test_gitignore_covers_gemini_jsonl():
    """devos/logs/gemini/*.jsonl must be ignored by git (Round 3 B2)."""
    import subprocess as sp
    result = sp.run(
        ["git", "check-ignore", "-q", "devos/logs/gemini/failures.jsonl"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    assert result.returncode == 0, (
        "devos/logs/gemini/failures.jsonl must be covered by .gitignore "
        "(exit code was non-zero — not ignored)"
    )


def test_gitignore_covers_gemini_md():
    """devos/logs/gemini/*.md must be ignored by git (Round 3 B2)."""
    import subprocess as sp
    result = sp.run(
        ["git", "check-ignore", "-q", "devos/logs/gemini/2026-05-06-T-TEST.md"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )
    assert result.returncode == 0, (
        "devos/logs/gemini/*.md must be covered by .gitignore "
        "(exit code was non-zero — not ignored)"
    )


# ---------------------------------------------------------------------------
# Round 3 — B3: macOS /private/var symlink walk fix
# ---------------------------------------------------------------------------

def test_validate_path_accepts_private_var_tmp(tmp_path_factory):
    """Files under /private/var/... (macOS pytest tmp) must be accepted as project
    root when project_root itself is that path (Round 3 B3).

    Uses tmp_path_factory to obtain a real macOS tmp directory that may be
    under /private/var/folders/... and validates that the symlink walk no
    longer rejects it due to /var -> /private/var system symlink.
    """
    # Use a fresh tmp dir as both image location and project root
    base = tmp_path_factory.mktemp("macos_tmp")
    # Create required subdirs that GeminiDispatcher needs
    (base / ".cache").mkdir(exist_ok=True)
    (base / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)

    img = base / ".cache" / "test_macos.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # validate_image_path must NOT raise even if base is under /private/var/...
    result = validate_image_path(str(img), project_root=base)
    assert result.is_absolute()
    assert result.name == "test_macos.png"


def test_validate_path_symlink_dir_in_raw_path_rejected(tmp_path_factory):
    """User-created symlink directory in the raw input path must still be rejected
    (Round 3 B3 — regression guard for original B5 fix).
    """
    base = tmp_path_factory.mktemp("symlinktest")
    (base / ".cache").mkdir(exist_ok=True)
    (base / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)

    # Create a real subdirectory and a symlink directory pointing to it
    real_subdir = base / "real_images"
    real_subdir.mkdir()
    real_img = real_subdir / "image.png"
    real_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    sym_subdir = base / "sym_images"
    sym_subdir.symlink_to(real_subdir)

    # Path that goes through the symlink directory must be rejected
    with pytest.raises(PathValidationError, match="symlink"):
        validate_image_path(str(sym_subdir / "image.png"), project_root=base)


# ---------------------------------------------------------------------------
# Round 3 — B4: all yolo literals in source have # safe: marker
# ---------------------------------------------------------------------------

def test_all_yolo_literals_have_safe_marker():
    """Every line in gemini_dispatcher.py matching (--yolo|approval-mode=yolo) must
    have a '# safe:' comment marker (Round 3 B4 lint test).

    This is the verify gate equivalent in test form.
    """
    import server.gemini_dispatcher as mod
    source_path = Path(mod.__file__)
    source_lines = source_path.read_text(encoding="utf-8").splitlines()

    import re
    pattern = re.compile(r"(--yolo|approval-mode=yolo)")
    violations: list[tuple[int, str]] = []

    for lineno, line in enumerate(source_lines, start=1):
        if pattern.search(line) and "# safe:" not in line:
            violations.append((lineno, line.rstrip()))

    assert violations == [], (
        "Found yolo literals without '# safe:' marker:\n"
        + "\n".join(f"  line {n}: {l}" for n, l in violations)
    )


# ===========================================================================
# T-OSN-W7-GEMINI-01a — W1–W7 security hardening tests
# ===========================================================================

# ---------------------------------------------------------------------------
# W1 — PATH hijack defense: shutil.which + absolute path
# ---------------------------------------------------------------------------

def test_build_command_uses_absolute_path(dispatcher: GeminiDispatcher, project_root: Path):
    """_build_command must use the absolute path of gemini (not bare 'gemini').

    W1 (01a): shutil.which resolution prevents PATH hijack.
    """
    fake_abs = "/usr/local/bin/gemini"
    with patch("shutil.which", return_value=fake_abs):
        cmd = dispatcher._build_command("test prompt", model="gemini-2.5-pro")
    assert cmd[0] == fake_abs, (
        f"Expected absolute path {fake_abs!r} as first cmd arg, got {cmd[0]!r}"
    )
    assert cmd[0] != "gemini", "Bare 'gemini' name must not be used (PATH hijack risk)"


def test_build_command_raises_when_gemini_not_found(dispatcher: GeminiDispatcher):
    """_build_command must raise FileNotFoundError when gemini not in PATH (W1)."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError, match="gemini"):
            dispatcher._build_command("test", model="gemini-2.5-pro")


def test_resolve_gemini_binary_returns_absolute(tmp_path: Path):
    """_resolve_gemini_binary must return the absolute path found by shutil.which.

    W1: PoC test — fake shim placed earlier in PATH is the one resolved,
    confirming that whichever binary appears first in PATH, we get its
    absolute path (preventing a *different* resolution at subprocess.run time).
    """
    # Create a fake gemini shim in a temp dir
    shim_dir = tmp_path / "fake_bin"
    shim_dir.mkdir()
    fake_gemini = shim_dir / "gemini"
    fake_gemini.write_text("#!/bin/sh\necho fake")
    fake_gemini.chmod(0o755)

    with patch("shutil.which", return_value=str(fake_gemini)):
        result = _resolve_gemini_binary()

    assert result == str(fake_gemini), (
        f"Expected fake shim path {fake_gemini!r}, got {result!r}"
    )


def test_resolve_gemini_binary_variant_path_with_spaces(tmp_path: Path):
    """_resolve_gemini_binary handles paths with spaces (W1 variant test)."""
    shim_dir = tmp_path / "my bin dir"
    shim_dir.mkdir()
    fake_gemini = shim_dir / "gemini"
    fake_gemini.write_text("#!/bin/sh\necho fake")
    fake_gemini.chmod(0o755)

    with patch("shutil.which", return_value=str(fake_gemini)):
        result = _resolve_gemini_binary()

    assert result == str(fake_gemini)
    assert " " in result  # confirm spaces in path handled correctly


def test_resolve_gemini_binary_variant_none_raises():
    """_resolve_gemini_binary must raise FileNotFoundError when shutil.which returns None."""
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError):
            _resolve_gemini_binary()


# ---------------------------------------------------------------------------
# W2 — PII redaction patterns expanded (5 new patterns)
# ---------------------------------------------------------------------------

def test_log_redacts_slack_token(dispatcher: GeminiDispatcher, project_root: Path):
    """Slack xoxb-* token must be redacted in log file (W2 01a)."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "token xoxb-1234567890-abcdefghijklmnop-xyz was found",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-SLACK-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-SLACK-01*.md"))
    assert len(logs) == 1
    content = logs[0].read_text()
    assert "xoxb-1234567890-abcdefghijklmnop-xyz" not in content
    assert "[REDACTED-SLACK]" in content


def test_log_redacts_slack_xoxp_token(dispatcher: GeminiDispatcher, project_root: Path):
    """Slack xoxp-* token must be redacted (W2 variant — xoxp type)."""
    img = project_root / ".cache" / "test.png"
    slack_token = "xoxp-111111111111-222222222222-abcdefghijkl"
    success_payload = json.dumps({
        "response": f"found token {slack_token}",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-XOXP-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-XOXP-01*.md"))
    content = logs[0].read_text()
    assert slack_token not in content
    assert "[REDACTED-SLACK]" in content


def test_log_redacts_gitlab_token(dispatcher: GeminiDispatcher, project_root: Path):
    """GitLab glpat-* token must be redacted (W2 01a)."""
    img = project_root / ".cache" / "test.png"
    glpat = "glpat-abc123def456ghi789jkl"
    success_payload = json.dumps({
        "response": f"gitlab token: {glpat}",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-GLPAT-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-GLPAT-01*.md"))
    content = logs[0].read_text()
    assert glpat not in content
    assert "[REDACTED-GLPAT]" in content


def test_log_redacts_gitlab_token_variant(dispatcher: GeminiDispatcher, project_root: Path):
    """GitLab glpat token with underscores (W2 variant)."""
    img = project_root / ".cache" / "test.png"
    glpat = "glpat-xxxx_yyyy_zzzz_aaaa_bb"
    success_payload = json.dumps({
        "response": f"key={glpat} used for auth",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-GLPAT-02", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-GLPAT-02*.md"))
    content = logs[0].read_text()
    assert glpat not in content


def test_log_redacts_google_oauth_token(dispatcher: GeminiDispatcher, project_root: Path):
    """Google OAuth ya29.* token must be redacted (W2 01a)."""
    img = project_root / ".cache" / "test.png"
    ya29_token = "ya29.a0AfH6SMC_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    success_payload = json.dumps({
        "response": f"oauth token: {ya29_token}",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-YA29-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-YA29-01*.md"))
    content = logs[0].read_text()
    assert ya29_token not in content
    assert "[REDACTED-GOAUTH]" in content


def test_log_redacts_google_api_key(dispatcher: GeminiDispatcher, project_root: Path):
    """Google API AIza* key must be redacted (W2 01a)."""
    img = project_root / ".cache" / "test.png"
    # AIza + exactly 35 alphanum chars = 39 total chars
    api_key = "AIza" + "S" * 35
    success_payload = json.dumps({
        "response": f"api_key={api_key}",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-AIZA-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-AIZA-01*.md"))
    content = logs[0].read_text()
    assert api_key not in content
    assert "[REDACTED-GAPI]" in content


def test_log_redacts_npm_token(dispatcher: GeminiDispatcher, project_root: Path):
    """npm_* token must be redacted (W2 01a)."""
    img = project_root / ".cache" / "test.png"
    # npm_ + exactly 36 alphanum chars
    npm_token = "npm_" + "A" * 36
    success_payload = json.dumps({
        "response": f"npm token: {npm_token}",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        dispatcher.run(ticket_id="T-W2-NPM-01", prompt="check", image_paths=[str(img)])

    logs = list((project_root / "devos" / "logs" / "gemini").glob("*T-W2-NPM-01*.md"))
    content = logs[0].read_text()
    assert npm_token not in content
    assert "[REDACTED-NPM]" in content


# ---------------------------------------------------------------------------
# W3 — handoff .sh must be 0o644 (not 0o755)
# ---------------------------------------------------------------------------

def test_handoff_script_permission_is_0o644(dispatcher: GeminiDispatcher, project_root: Path):
    """Handoff .sh file must have permissions 0o644 — not executable (W3 01a).

    PoC: directly call handoff_fallback and check the script file mode.
    """
    dispatcher.handoff_fallback(
        "T-W3-PERM-01",
        prompt="describe the screen",
        image_paths=["screenshot.png"],
    )
    script = project_root / ".cache" / "gemini-handoff-T-W3-PERM-01.sh"
    assert script.exists(), "Handoff script must be created"
    mode = script.stat().st_mode & 0o777
    assert mode == 0o644, (
        f"Expected 0o644 (not executable), got 0o{mode:03o}. "
        "Executable handoff scripts risk accidental tab-completion execution."
    )


def test_handoff_script_permission_variant_different_ticket(
    dispatcher: GeminiDispatcher, project_root: Path
):
    """Handoff .sh for different ticket ID must also be 0o644 (W3 variant)."""
    dispatcher.handoff_fallback(
        "T-W3-PERM-02",
        prompt="check UI layout",
        image_paths=["ui.png"],
    )
    script = project_root / ".cache" / "gemini-handoff-T-W3-PERM-02.sh"
    assert script.exists()
    mode = script.stat().st_mode & 0o777
    assert mode == 0o644, f"Expected 0o644, got 0o{mode:03o}"


def test_handoff_fallback_r6_guidance(
    dispatcher: GeminiDispatcher, project_root: Path, capsys
):
    """R6 update: handoff_fallback must print python CLI guidance (make targets removed).

    R6 removes make gemini-* targets (osn-wide RCE surface). The fallback message
    now directs users to `python3 -m server.gemini_handoff next` instead of
    `make gemini-next`. The .sh script is still written (0o644).
    """
    dispatcher.handoff_fallback(
        "T-W3-MSG-01",
        prompt="review the image",
        image_paths=["img.png"],
    )
    out = capsys.readouterr().out
    # R6: must mention python3 CLI (not make target)
    assert "server.gemini_handoff" in out, (
        f"R6: handoff_fallback must mention 'server.gemini_handoff'. Got: {out[:300]!r}"
    )
    assert "next" in out, (
        f"R6: handoff_fallback must mention 'next' subcommand. Got: {out[:300]!r}"
    )
    # Must mention that a flag or script was created (so user knows Plan B is active)
    assert "pending" in out.lower() or "script" in out.lower() or "flag" in out.lower(), (
        f"R6: handoff_fallback must mention pending flag or script. Got: {out[:300]!r}"
    )


# ---------------------------------------------------------------------------
# W4 — ticket_id regex tightened: no trailing/consecutive dashes
# ---------------------------------------------------------------------------

def test_ticket_id_trailing_dash_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """T-A- (trailing dash) must be rejected by tightened regex (W4 01a, PoC)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError):
        dispatcher.run(ticket_id="T-A-", prompt="describe", image_paths=[str(img)])


def test_ticket_id_double_trailing_dash_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """T-A-- (double trailing dash) must be rejected (W4 variant)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError):
        dispatcher.run(ticket_id="T-A--", prompt="describe", image_paths=[str(img)])


def test_ticket_id_bare_T_dash_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """T- (just T-) must be rejected (W4 variant)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError):
        dispatcher.run(ticket_id="T-", prompt="describe", image_paths=[str(img)])


def test_ticket_id_consecutive_dashes_rejected(dispatcher: GeminiDispatcher, project_root: Path):
    """T-A--B (consecutive dashes) must be rejected (W4 variant)."""
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError):
        dispatcher.run(ticket_id="T-A--B", prompt="describe", image_paths=[str(img)])


def test_ticket_id_valid_osn_gemini_id_passes(dispatcher: GeminiDispatcher, project_root: Path):
    """T-OSN-W7-GEMINI-01 must still pass the tightened regex (W4 regression guard)."""
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-OSN-W7-GEMINI-01",
            prompt="describe",
            image_paths=[str(img)],
        )
    assert result.success is True


def test_ticket_id_valid_with_suffix_a_passes(dispatcher: GeminiDispatcher, project_root: Path):
    """T-OSN-W7-GEMINI-01a — single lowercase suffix letter — must pass (W4 spec).

    The regex ^T-[A-Z0-9]+(-[A-Z0-9]+)*[a-z]?$ allows an optional single lowercase
    letter at the end as a sub-variant marker (e.g. -01a).
    """
    img = project_root / ".cache" / "test.png"
    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })
    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        result = dispatcher.run(
            ticket_id="T-OSN-W7-GEMINI-01a",
            prompt="describe",
            image_paths=[str(img)],
        )
    assert result.success is True


# ---------------------------------------------------------------------------
# W5 — make gemini-status: failures.jsonl + quota summary
# ---------------------------------------------------------------------------

def test_gemini_status_no_files(project_root: Path, capsys):
    """gemini_status with no logs must still run without error (W5 01a, PoC)."""
    # Ensure no log files exist
    log_dir = project_root / "devos" / "logs" / "gemini"
    log_dir.mkdir(parents=True, exist_ok=True)

    exit_code = _gemini_status(project_root)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "gemini-status" in out
    assert "Daily cap" in out


def test_gemini_status_counts_failures_in_24h(project_root: Path, capsys):
    """gemini_status must count failures within 24h from failures.jsonl (W5 variant)."""
    from datetime import datetime as _dt, timezone, timedelta

    log_dir = project_root / "devos" / "logs" / "gemini"
    log_dir.mkdir(parents=True, exist_ok=True)
    failures_log = log_dir / "failures.jsonl"

    now_utc = _dt.now(tz=timezone.utc)
    recent_ts = now_utc.isoformat()
    old_ts = (now_utc - timedelta(hours=48)).isoformat()

    # Write 2 recent + 1 old failure
    entries = [
        {"ts": recent_ts, "ticket_id": "T-F1", "failure_reason": "err1"},
        {"ts": recent_ts, "ticket_id": "T-F2", "failure_reason": "err2"},
        {"ts": old_ts, "ticket_id": "T-F3", "failure_reason": "old error"},
    ]
    failures_log.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )

    exit_code = _gemini_status(project_root)
    out = capsys.readouterr().out

    assert exit_code == 0
    # Should show 2 failures in last 24h (not 3)
    assert "Failures (last 24h):  2" in out or "Failures (last 24h): 2" in out, (
        f"Expected 2 failures in 24h. Output: {out}"
    )
    assert "Failures (total):     3" in out or "Failures (total):    3" in out, (
        f"Expected 3 total failures. Output: {out}"
    )


def test_gemini_status_quota_counts(project_root: Path, capsys):
    """gemini_status must count calls from quota_*.jsonl (W5 variant)."""
    from datetime import timezone

    log_dir = project_root / "devos" / "logs" / "gemini"
    log_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime as dt2
    ym = dt2.now().strftime("%Y%m")
    quota_path = log_dir / f"quota_{ym}.jsonl"

    now_utc = dt2.now(tz=timezone.utc)
    entries = [
        {
            "ts": now_utc.isoformat(),
            "ticket_id": f"T-Q{i}",
            "model": "gemini-2.5-pro",
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "tool_calls": 0,
            "tool_fails": 0,
        }
        for i in range(3)
    ]
    quota_path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )

    exit_code = _gemini_status(project_root)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Calls (this month):  3" in out or "Calls (this month):   3" in out, (
        f"Expected 3 calls this month. Output: {out}"
    )
    assert "Calls (last 24h):    3" in out or "Calls (last 24h):   3" in out, (
        f"Expected 3 calls in last 24h. Output: {out}"
    )


# ---------------------------------------------------------------------------
# W6 — _AT_TOKEN_RE boundary expanded (comma/semicolon/quote/paren/bracket)
# ---------------------------------------------------------------------------

def test_prompt_comma_at_dot_slash_rejected():
    """,@./path — comma-prefixed @./ token must be rejected (W6 01a, PoC)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt(",@./etc/passwd")


def test_prompt_semicolon_at_slash_rejected():
    """;@/abs — semicolon-prefixed @/ token must be rejected (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt(";@/abs/path")


def test_prompt_single_quote_at_dot_slash_rejected():
    """'@./path — single-quote-prefixed @./ token must be rejected (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("'@./secret.txt")


def test_prompt_double_quote_at_dot_slash_rejected():
    """"@./path — double-quote-prefixed token must be rejected (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt('"@./secret.txt describe')


def test_prompt_open_paren_at_slash_rejected():
    """(@/path — open-paren-prefixed @/ token must be rejected (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("(@/etc/hosts)")


def test_prompt_open_bracket_at_dot_slash_rejected():
    """[@./path — open-bracket-prefixed token must be rejected (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("[@./config.json]")


def test_prompt_comma_at_slash_variant_rejected():
    """Comma before @/ variant (W6 variant — comma + abs path)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("list all,@/etc/passwd,done")


def test_prompt_semicolon_at_dot_slash_variant_rejected():
    """Semicolon + @./ mid-sentence (W6 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("step1;@./secret step2")


def test_prompt_no_injection_clean_text_still_allowed():
    """Clean text without any @./ or @/ must pass (W6 regression guard)."""
    _validate_prompt("Describe the UI in detail")
    _validate_prompt("What is the color scheme? Check @email or #tag")
    _validate_prompt("this,has,commas but no @-file tokens")


def test_prompt_email_with_at_symbol_still_allowed():
    """@ in email context (user@example.com) must still pass (W6 regression guard)."""
    _validate_prompt("send results to user@example.com")


# ---------------------------------------------------------------------------
# W7 — validate_image_path works when project_root is under /var/folders
# ---------------------------------------------------------------------------

def test_validate_image_path_var_folders_project_root(tmp_path_factory):
    """When project_root itself is under a path that resolves through system
    symlinks (simulated by using a resolved tmp path as project_root), image
    validation must still succeed (W7 01a, PoC).

    This extends the R3-B3 test to also verify the W7 parent walk
    stop-at-project-root logic when project_root is passed as raw (not pre-resolved).
    """
    # Obtain a real tmp path (may be /private/var/folders/... on macOS)
    base = tmp_path_factory.mktemp("w7_var_test")
    (base / ".cache").mkdir(exist_ok=True)
    (base / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)

    img = base / ".cache" / "screenshot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    # Pass the raw (possibly /var/folders/) path as project_root — not pre-resolved
    result = validate_image_path(str(img), project_root=base)
    assert result.is_absolute()
    assert result.name == "screenshot.png"


def test_validate_image_path_var_folders_variant_subdir(tmp_path_factory):
    """Image in a subdirectory under a /var/folders/-style root must pass (W7 variant)."""
    base = tmp_path_factory.mktemp("w7_subdir")
    subdir = base / "assets" / "screenshots"
    subdir.mkdir(parents=True)
    (base / ".cache").mkdir(exist_ok=True)
    (base / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)

    img = subdir / "login.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    result = validate_image_path(str(img), project_root=base)
    assert result.is_absolute()
    assert result.name == "login.png"


def test_validate_image_path_var_folders_user_symlink_still_rejected(tmp_path_factory):
    """User-created symlink dir in path must still be rejected even under /var/folders root
    (W7 regression guard — W7 must not weaken B5/B3 protections).
    """
    base = tmp_path_factory.mktemp("w7_symlink_guard")
    (base / ".cache").mkdir(exist_ok=True)
    (base / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)

    real_dir = base / "real_imgs"
    real_dir.mkdir()
    real_img = real_dir / "img.png"
    real_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)

    sym_dir = base / "sym_imgs"
    sym_dir.symlink_to(real_dir)

    with pytest.raises(PathValidationError, match="symlink"):
        validate_image_path(str(sym_dir / "img.png"), project_root=base)


# ---------------------------------------------------------------------------
# R2 — W1 (Reviewer): NBSP / CJK full-width space as @./ boundary
# ---------------------------------------------------------------------------

def test_prompt_nbsp_at_dot_slash_rejected():
    """NBSP (\\xa0) before @./ — must be rejected (R2-W1 PoC, NBSP boundary).

    The negative-class regex (?:^|[^A-Za-z0-9_]) covers all non-word chars
    including NBSP \\xa0, so this is rejected by the threat-surface-based class
    without needing an explicit enumeration.
    """
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("\xa0@./.env")


def test_prompt_nbsp_at_slash_rejected():
    """NBSP before @/ absolute path — must be rejected (R2-W1 variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("\xa0@/etc/passwd")


def test_prompt_cjk_fullwidth_space_at_dot_slash_rejected():
    """CJK full-width space (U+3000 　) before @./ — must be rejected (R2-W1 variant).

    CJK ideographic space is a common injection vector in East-Asian text context.
    Covered automatically by the negative word-char class.
    """
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("　@./.env")


# ---------------------------------------------------------------------------
# R2 — W2+W3 (Reviewer+Sec): TicketIdError message reflects active regex
# ---------------------------------------------------------------------------

def test_ticket_id_error_message_contains_active_pattern(dispatcher: GeminiDispatcher, project_root: Path):
    """TicketIdError message must include the active _TICKET_ID_RE.pattern (R2-W2+W3 PoC).

    This ensures operators see the *real* constraint when debugging — not a
    stale hardcoded string that diverged from the implementation.
    """
    from server.gemini_dispatcher import _TICKET_ID_RE
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError, match=re.escape(_TICKET_ID_RE.pattern)):
        dispatcher.run(ticket_id="T-INVALID-", prompt="describe", image_paths=[str(img)])


def test_ticket_id_error_message_does_not_contain_stale_pattern(dispatcher: GeminiDispatcher, project_root: Path):
    """TicketIdError message must NOT contain the old stale pattern ^T-[A-Z0-9][A-Z0-9-]*$ (R2-W2+W3 variant).

    The old pattern was hardcoded as a raw string and diverged from the active regex.
    This test guards against regression to that stale string.
    """
    img = project_root / ".cache" / "test.png"
    with pytest.raises(TicketIdError) as exc_info:
        dispatcher.run(ticket_id="T-INVALID-", prompt="describe", image_paths=[str(img)])
    assert "^T-[A-Z0-9][A-Z0-9-]*$" not in str(exc_info.value), (
        "TicketIdError message still contains stale regex pattern"
    )


# ---------------------------------------------------------------------------
# R2 — W1 (Sec): Slack token with underscore is fully redacted
# ---------------------------------------------------------------------------

def test_redact_slack_token_with_underscore(dispatcher: GeminiDispatcher, project_root: Path):
    """Slack token containing _ (base64url char) must be fully redacted (R2-W1-Sec PoC).

    Real Slack tokens use base64url alphabet which includes _ as well as -.
    xoxb-1234-abc_def-xyz — the _def segment was not redacted before the fix.
    """
    from server.gemini_dispatcher import _redact_pii

    token = "xoxb-1234-abc_def-xyz-and-more-chars"
    redacted = _redact_pii(f"Use token {token} for auth")
    assert token not in redacted, "Full Slack token must be redacted"
    assert "[REDACTED-SLACK]" in redacted


def test_redact_slack_xoxp_token_with_underscore():
    """xoxp token (user token) with underscore must be redacted (R2-W1-Sec variant).

    Tested without 'Bearer ' prefix to avoid the Bearer pattern firing first.
    The Slack pattern must match xoxp tokens that include _ directly.
    """
    from server.gemini_dispatcher import _redact_pii

    token = "xoxp-9999-someid_withunder_score-trailing"
    redacted = _redact_pii(f"token={token}")
    assert token not in redacted
    assert "[REDACTED-SLACK]" in redacted


def test_redact_slack_xoxa_token_with_underscore():
    """xoxa token (legacy app token) with underscore must be redacted (R2-W1-Sec variant)."""
    from server.gemini_dispatcher import _redact_pii

    token = "xoxa-2-abcdefgh_ijklmnop-1234567890"
    redacted = _redact_pii(f"token={token}")
    assert token not in redacted
    assert "[REDACTED-SLACK]" in redacted


# ---------------------------------------------------------------------------
# R2 — W3 (Sec): threat-surface-based negative class covers 12+ separators
# ---------------------------------------------------------------------------
# Rationale for negative class over positive list:
#   The previous [\s,;'"()[] list required manual updates for each new separator.
#   The negative-class [^A-Za-z0-9_] covers ALL non-word chars by definition —
#   including future characters — without enumeration. This is the "threat surface
#   based" approach, not a PoC list.

def test_prompt_tilde_at_dot_slash_rejected():
    """~ before @./ — rejected by negative class (R2-W3-Sec PoC, tilde separator)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("~@./.env")


def test_prompt_asterisk_at_dot_slash_rejected():
    """* before @./ — rejected by negative class (R2-W3-Sec variant, glob metachar)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("*@./.env")


def test_prompt_less_than_at_slash_rejected():
    """< before @/ — rejected by negative class (R2-W3-Sec variant, redirect char)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("<@/etc/passwd")


def test_prompt_greater_than_at_dot_slash_rejected():
    """> before @./ — rejected by negative class (R2-W3-Sec variant, redirect char)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt(">@./.env")


def test_prompt_ampersand_at_dot_slash_rejected():
    """& before @./ — rejected by negative class (R2-W3-Sec variant, shell background)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("&@./.env")


def test_prompt_pipe_at_slash_rejected():
    """| before @/ — rejected by negative class (R2-W3-Sec variant, shell pipe)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("|@/etc/passwd")


def test_prompt_equals_at_dot_slash_rejected():
    """= before @./ — rejected by negative class (R2-W3-Sec variant, assignment)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("=@./.env")


def test_prompt_plus_at_dot_slash_rejected():
    """+ before @./ — rejected by negative class (R2-W3-Sec variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("+@./.env")


def test_prompt_caret_at_slash_rejected():
    """^ before @/ — rejected by negative class (R2-W3-Sec variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("^@/etc/passwd")


def test_prompt_open_brace_at_dot_slash_rejected():
    """{ before @./ — rejected by negative class (R2-W3-Sec variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("{@./.env}")


def test_prompt_close_brace_at_dot_slash_rejected():
    """} before @./ — rejected by negative class (R2-W3-Sec variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("}@./.env")


def test_prompt_cjk_period_at_dot_slash_rejected():
    """CJK ideographic period (。) before @./ — rejected by negative class (R2-W3-Sec CJK variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("。@./.env")


def test_prompt_cjk_comma_at_dot_slash_rejected():
    """CJK ideographic comma (、) before @./ — rejected by negative class (R2-W3-Sec CJK variant)."""
    with pytest.raises(PromptInjectionError, match="file-token"):
        _validate_prompt("、@./.env")


def test_prompt_existing_separators_still_rejected_regression():
    """Original 8 positive-class separators still rejected after negative-class switch (R2-W3 regression).

    Guards that the migration from positive list to negative class did not
    accidentally relax coverage for the originally tested separators.
    """
    for char, label in [
        (",", "comma"),
        (";", "semicolon"),
        ("'", "single-quote"),
        ('"', "double-quote"),
        ("(", "open-paren"),
        ("[", "open-bracket"),
        (" ", "space"),
        ("\t", "tab"),
    ]:
        try:
            with pytest.raises(PromptInjectionError, match="file-token"):
                _validate_prompt(f"{char}@./.env")
        except Exception as exc:
            raise AssertionError(f"{label} separator should still be rejected") from exc


# ---------------------------------------------------------------------------
# R2 — W4 (Sec): _purge_old_handoffs deletes stale scripts, keeps recent
# ---------------------------------------------------------------------------

def test_purge_old_handoffs_removes_stale(dispatcher: GeminiDispatcher):
    """Handoff scripts older than 7 days are purged; recent ones are kept (R2-W4-Sec PoC)."""
    import time

    cache_dir = dispatcher._cache_dir

    # Create a "stale" script (mtime = 8 days ago)
    stale = cache_dir / "gemini-handoff-T-OLD-01.sh"
    stale.write_text("#!/usr/bin/env bash\necho old\n", encoding="utf-8")
    stale_mtime = time.time() - 8 * 86400
    os.utime(stale, (stale_mtime, stale_mtime))

    # Create a "recent" script (mtime = 1 day ago)
    recent = cache_dir / "gemini-handoff-T-NEW-01.sh"
    recent.write_text("#!/usr/bin/env bash\necho new\n", encoding="utf-8")
    recent_mtime = time.time() - 1 * 86400
    os.utime(recent, (recent_mtime, recent_mtime))

    dispatcher._purge_old_handoffs(max_age_days=7)

    assert not stale.exists(), "Stale handoff script (8d old) must be deleted"
    assert recent.exists(), "Recent handoff script (1d old) must be preserved"


def test_purge_old_handoffs_does_not_touch_non_handoff_files(dispatcher: GeminiDispatcher):
    """_purge_old_handoffs must only touch gemini-handoff-*.sh files (R2-W4-Sec variant).

    Other cache files (smoke cache, etc.) must be preserved regardless of age.
    """
    import time

    cache_dir = dispatcher._cache_dir

    # Old non-handoff file
    smoke = cache_dir / "gemini-smoke-gemini-2.0-flash.ok"
    smoke.write_text("ok", encoding="utf-8")
    old_mtime = time.time() - 30 * 86400
    os.utime(smoke, (old_mtime, old_mtime))

    dispatcher._purge_old_handoffs(max_age_days=7)

    assert smoke.exists(), "Non-handoff cache files must not be purged"


def test_purge_old_handoffs_custom_max_age(dispatcher: GeminiDispatcher):
    """max_age_days parameter controls purge threshold (R2-W4-Sec variant)."""
    import time

    cache_dir = dispatcher._cache_dir

    # Script that is 3 days old — stale with max_age=2, fresh with max_age=7
    script = cache_dir / "gemini-handoff-T-MID-01.sh"
    script.write_text("#!/usr/bin/env bash\necho mid\n", encoding="utf-8")
    mtime = time.time() - 3 * 86400
    os.utime(script, (mtime, mtime))

    dispatcher._purge_old_handoffs(max_age_days=2)
    assert not script.exists(), "Script older than custom threshold must be purged"


# ---------------------------------------------------------------------------
# R2 — INFO3: datetime.now() in log writes uses UTC timezone
# ---------------------------------------------------------------------------

def test_quota_log_timestamp_is_utc(dispatcher: GeminiDispatcher):
    """_append_quota_log must write UTC ISO timestamps (R2-INFO3 PoC).

    The 24h window in _gemini_status compares timestamps with UTC.now().
    If quota log wrote naive local time, the window calculation is wrong in
    non-UTC timezones. UTC timestamps are identifiable by the +00:00 suffix.
    """
    from datetime import timezone as _tz

    dispatcher._append_quota_log("T-TEST-01", {
        "model": "gemini-2.0-flash",
        "inputTokens": 10,
        "outputTokens": 20,
        "totalTokens": 30,
        "tools": {"totalCalls": 0, "totalFail": 0},
    })
    from datetime import datetime as _dt
    import json as _json

    log_dir = dispatcher._log_dir
    ym = _dt.now(tz=_tz.utc).strftime("%Y%m")
    quota_path = log_dir / f"quota_{ym}.jsonl"
    assert quota_path.exists()
    line = quota_path.read_text().strip().splitlines()[-1]
    entry = _json.loads(line)
    ts = entry["ts"]
    # UTC ISO timestamps contain +00:00 or end with Z
    assert "+00:00" in ts or ts.endswith("Z"), (
        f"Quota log timestamp must be UTC (got: {ts!r})"
    )


def test_failure_log_timestamp_is_utc(dispatcher: GeminiDispatcher):
    """_append_failure_log must write UTC ISO timestamps (R2-INFO3 variant)."""
    from datetime import timezone as _tz
    import json as _json

    dispatcher._append_failure_log("T-TEST-01", "connection refused")
    lines = dispatcher._failures_log.read_text().strip().splitlines()
    last = _json.loads(lines[-1])
    ts = last["ts"]
    assert "+00:00" in ts or ts.endswith("Z"), (
        f"Failure log timestamp must be UTC (got: {ts!r})"
    )


# ---------------------------------------------------------------------------
# W-NEW-2 (R3): dispatcher imports _TICKET_ID_RE from _ticket_id.py SSOT
# ---------------------------------------------------------------------------

def test_dispatcher_ticket_id_re_imported_from_ssot():
    """_TICKET_ID_RE in gemini_dispatcher must be imported from _ticket_id.py (W-NEW-2 fix).

    Previously dispatcher defined its own _TICKET_ID_RE inline (regex duplication).
    R3 fix: import from server._ticket_id — single source of truth.
    Verify: the regex object in dispatcher is the same object as in _ticket_id.
    """
    import server.gemini_dispatcher as _disp
    import server._ticket_id as _tid

    assert _disp._TICKET_ID_RE is _tid.TICKET_ID_RE, (
        "gemini_dispatcher._TICKET_ID_RE must be the same object as "
        "server._ticket_id.TICKET_ID_RE (W-NEW-2 SSOT import fix). "
        "A local re.compile() copy indicates the fix was not applied."
    )


def test_dispatcher_ticket_id_re_pattern_matches_ssot():
    """Dispatcher ticket_id regex pattern must match _ticket_id.py pattern (W-NEW-2 regression)."""
    import server.gemini_dispatcher as _disp
    import server._ticket_id as _tid

    assert _disp._TICKET_ID_RE.pattern == _tid.TICKET_ID_RE.pattern, (
        f"Dispatcher _TICKET_ID_RE pattern {_disp._TICKET_ID_RE.pattern!r} "
        f"does not match _ticket_id.TICKET_ID_RE pattern {_tid.TICKET_ID_RE.pattern!r}. "
        "Regex divergence — W-NEW-2 SSOT fix not applied."
    )


def test_dispatcher_ticket_id_re_accepts_valid_ids():
    """Dispatcher _TICKET_ID_RE must accept standard ticket IDs (W-NEW-2 regression)."""
    from server.gemini_dispatcher import _TICKET_ID_RE

    valid_ids = [
        "T-OSN-W7-GEMINI-01",
        "T-OSN-W7-GEMINI-01a",
        "T-TEST-01",
        "T-A0B1C2",
        "T-OSN-W5-02b",
    ]
    for tid in valid_ids:
        assert _TICKET_ID_RE.fullmatch(tid), (
            f"Dispatcher _TICKET_ID_RE must accept valid ticket ID: {tid!r}"
        )


def test_dispatcher_ticket_id_re_rejects_invalid_ids():
    """Dispatcher _TICKET_ID_RE must reject invalid ticket IDs (W-NEW-2 regression)."""
    from server.gemini_dispatcher import _TICKET_ID_RE

    invalid_ids = [
        "T-A-",          # trailing dash
        "T-A--",         # consecutive dashes
        "T-",            # no segment
        "../etc",        # path traversal
        "T-PROJ/EVIL",   # slash
        "",              # empty
        "t-proj-01",     # lowercase
    ]
    for tid in invalid_ids:
        assert not _TICKET_ID_RE.fullmatch(tid), (
            f"Dispatcher _TICKET_ID_RE must reject invalid ticket ID: {tid!r}"
        )


# ===========================================================================
# T-OS3-GEMINI-TEMPLATE-SYNC — DOD-2: --project propagation + DOD-3: security
# ===========================================================================

# ---------------------------------------------------------------------------
# DOD-2: _cli_main(dispatch) uses explicit project_root when provided
# ---------------------------------------------------------------------------

def test_cli_dispatch_explicit_project_root_used(tmp_path_factory):
    """_cli_main dispatch must use the explicitly passed project_root, not cwd
    or OS3_PROJECT_ROOT env, when project_root is given directly.

    DOD-2: gemini dispatch uses explicit project_root (not cwd) as the target.
    """
    project_a = tmp_path_factory.mktemp("project_a")
    project_b = tmp_path_factory.mktemp("project_b")

    for p in (project_a, project_b):
        (p / ".cache").mkdir(exist_ok=True)
        (p / "devos" / "logs" / "gemini").mkdir(parents=True)
        (p / "devos" / "tasks").mkdir(parents=True)

    # Create a ticket in project_a
    fixture_img = project_a / ".cache" / "test.png"
    fixture_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    queue_yaml = project_a / "devos" / "tasks" / "QUEUE.yaml"
    queue_yaml.write_text(
        "tickets:\n"
        "  - id: T-PROJ-DISPATCH-01\n"
        "    status: todo\n"
        "    owner: BUILDER\n"
        "    goal: test project_root propagation\n"
        "    gui_review:\n"
        "      prompt: 'Describe the image'\n"
        "      images:\n"
        "        - .cache/test.png\n",
        encoding="utf-8",
    )

    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.dict(os.environ, {"OS3_PROJECT_ROOT": str(project_b)}, clear=False):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        from server.gemini_dispatcher import _cli_main
        # Pass project_root explicitly — must override OS3_PROJECT_ROOT (project_b)
        exit_code = _cli_main(
            ["dispatch", "T-PROJ-DISPATCH-01"],
            project_root=project_a,
        )

    assert exit_code == 0, f"Expected exit 0, got {exit_code}"

    # Log must appear in project_a — NOT project_b
    logs_a = list((project_a / "devos" / "logs" / "gemini").glob("*T-PROJ-DISPATCH-01*.md"))
    logs_b = list((project_b / "devos" / "logs" / "gemini").glob("*T-PROJ-DISPATCH-01*.md"))
    assert len(logs_a) == 1, (
        f"Log must be written to project_a (explicit root), found in project_a: {logs_a}"
    )
    assert len(logs_b) == 0, (
        f"Log must NOT be written to project_b (OS3_PROJECT_ROOT), found in project_b: {logs_b}"
    )


def test_cli_dispatch_project_root_defaults_to_env_when_not_provided(tmp_path_factory):
    """When no explicit project_root is provided, _cli_main falls back to
    OS3_PROJECT_ROOT env var (existing behaviour preserved — regression guard).

    DOD-2 regression guard.
    """
    project_env = tmp_path_factory.mktemp("project_env")
    (project_env / ".cache").mkdir(exist_ok=True)
    (project_env / "devos" / "logs" / "gemini").mkdir(parents=True)
    (project_env / "devos" / "tasks").mkdir(parents=True)

    fixture_img = project_env / ".cache" / "env_test.png"
    fixture_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    queue_yaml = project_env / "devos" / "tasks" / "QUEUE.yaml"
    queue_yaml.write_text(
        "tickets:\n"
        "  - id: T-ENV-ROOT-01\n"
        "    status: todo\n"
        "    owner: BUILDER\n"
        "    goal: test env fallback\n"
        "    gui_review:\n"
        "      prompt: 'Describe'\n"
        "      images:\n"
        "        - .cache/env_test.png\n",
        encoding="utf-8",
    )

    success_payload = json.dumps({
        "response": "ok",
        "stats": {"tools": {"totalCalls": 0, "totalFail": 0}},
    })

    with patch("subprocess.run") as mock_run, \
         patch("shutil.which", return_value="/usr/local/bin/gemini"), \
         patch.dict(os.environ, {"OS3_PROJECT_ROOT": str(project_env)}, clear=False):
        mock_run.return_value = MagicMock(returncode=0, stdout=success_payload, stderr="")
        from server.gemini_dispatcher import _cli_main
        exit_code = _cli_main(["dispatch", "T-ENV-ROOT-01"])

    assert exit_code == 0, f"Expected exit 0, got {exit_code}"
    logs = list((project_env / "devos" / "logs" / "gemini").glob("*T-ENV-ROOT-01*.md"))
    assert len(logs) == 1, (
        f"Log must be written to project_env (OS3_PROJECT_ROOT env), found: {logs}"
    )


# ---------------------------------------------------------------------------
# DOD-3: yolo / --dangerously-skip-permissions security — project_root bound
# ---------------------------------------------------------------------------

def test_yolo_check_blocks_dangerously_skip_permissions(dispatcher: GeminiDispatcher):
    """--dangerously-skip-permissions must be treated as a yolo-equivalent and
    rejected by the manual dispatch path (_check_no_yolo).

    DOD-3: yolo path permission boundary — host dispatcher must not allow the
    dangerously-skip flag outside the explicitly scoped agentic path.
    """
    with pytest.raises(YoloForbiddenError, match="dangerously-skip-permissions"):
        dispatcher._check_no_yolo(
            ["agy", "--dangerously-skip-permissions", "--print", "test"]
        )


def test_validate_image_path_rejects_path_outside_explicit_project_root(tmp_path_factory):
    """Image path validation must reject files outside the *explicit* project_root,
    even when a different (larger) OS3_PROJECT_ROOT env var is set.

    DOD-3: permission boundary is project_root, not OS3_PROJECT_ROOT env.
    """
    project_a = tmp_path_factory.mktemp("security_a")
    project_b = tmp_path_factory.mktemp("security_b")

    (project_a / ".cache").mkdir(exist_ok=True)
    (project_b / ".cache").mkdir(exist_ok=True)

    # Create image inside project_b — not inside project_a
    img_b = project_b / ".cache" / "outside.png"
    img_b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # project_root is project_a — image in project_b must be rejected
    with pytest.raises(PathValidationError, match="outside"):
        validate_image_path(str(img_b), project_root=project_a)


def test_validate_image_path_accepts_path_within_explicit_project_root(tmp_path_factory):
    """Image inside the explicit project_root must still pass validation.

    DOD-3 regression guard.
    """
    project = tmp_path_factory.mktemp("security_pass")
    (project / ".cache").mkdir(exist_ok=True)
    (project / "devos" / "logs" / "gemini").mkdir(parents=True)

    img = project / ".cache" / "inside.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    result = validate_image_path(str(img), project_root=project)
    assert result.is_absolute()
    assert result.name == "inside.png"


# ---------------------------------------------------------------------------
# Security medium fix: --dangerously-skip-permissions =value + space-separated
# ---------------------------------------------------------------------------

def test_yolo_check_blocks_dangerously_skip_permissions_equals_true(dispatcher: GeminiDispatcher):
    """--dangerously-skip-permissions=true must be rejected by _check_no_yolo.

    Security medium fix: =value form was not previously checked.
    """
    with pytest.raises(YoloForbiddenError, match="dangerously-skip-permissions"):
        dispatcher._check_no_yolo(
            ["agy", "--dangerously-skip-permissions=true", "--print", "test"]
        )


def test_yolo_check_blocks_dangerously_skip_permissions_equals_one(dispatcher: GeminiDispatcher):
    """--dangerously-skip-permissions=1 must be rejected by _check_no_yolo.

    Security medium fix: =value form with numeric value.
    """
    with pytest.raises(YoloForbiddenError, match="dangerously-skip-permissions"):
        dispatcher._check_no_yolo(
            ["agy", "--dangerously-skip-permissions=1"]
        )


def test_yolo_check_blocks_dangerously_skip_permissions_space_separated(dispatcher: GeminiDispatcher):
    """--dangerously-skip-permissions followed by a value token must be rejected.

    Security medium fix: space-separated form (bare flag is already caught;
    this confirms the flag token itself triggers the guard regardless of next token).
    """
    with pytest.raises(YoloForbiddenError, match="dangerously-skip-permissions"):
        dispatcher._check_no_yolo(
            ["agy", "--dangerously-skip-permissions", "true"]
        )


# ---------------------------------------------------------------------------
# BLOCKER 1 fix: parser plumbing — --project propagated to gemini subcommands
# ---------------------------------------------------------------------------

def test_cli_gemini_dispatch_receives_project_from_outer_flag():
    """os3 gemini dispatch T-XYZ --project NAME must propagate project to handler.

    Regression guard for DOD-2 (BLOCKER 1 fix): --project flag on the gemini
    subcommand (via parents=[common]) must be accessible as args.project inside
    handle_gemini_dispatch. Before the fix, the gemini subparser was created
    without parents=[common], causing "unrecognized arguments: --project".

    Accepted syntaxes after fix:
    - os3 gemini dispatch T-X --project NAME  (flag after ticket_id)
    - os3 gemini dispatch --project NAME T-X  (flag before ticket_id)
    """
    from server.cli import _build_parser

    parser = _build_parser()

    # Syntax 1: flag after positional
    args = parser.parse_args(["gemini", "dispatch", "T-FOO-BAR-01", "--project", "myproject"])
    assert getattr(args, "project", None) == "myproject", (
        f"args.project must be 'myproject' (flag-after-positional), "
        f"got: {getattr(args, 'project', 'MISSING')!r}"
    )
    assert getattr(args, "ticket_id", None) == "T-FOO-BAR-01", (
        f"args.ticket_id must be 'T-FOO-BAR-01', got: {getattr(args, 'ticket_id', 'MISSING')!r}"
    )

    # Syntax 2: flag before positional (gemini dispatch level)
    args2 = parser.parse_args(["gemini", "dispatch", "--project", "myproject", "T-FOO-BAR-01"])
    assert getattr(args2, "project", None) == "myproject", (
        f"args.project must be 'myproject' (flag-before-positional), "
        f"got: {getattr(args2, 'project', 'MISSING')!r}"
    )

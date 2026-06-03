"""W2-04 — cross_model_codex stub tests.

b' adaptive trigger 의 fallback 동작 검증. real codex 호출은 W5 canary 시.
T-OS3-BPRIME-CODEX-TIMEOUT-DIAGNOSE: binary-absent fast-fail + real-verdict parsing.
"""
from __future__ import annotations

import subprocess
import time
from unittest.mock import patch

import pytest

from server.dispatcher import cross_model_codex


def test_cross_model_codex_returns_fallback_on_codex_not_found():
    """codex CLI 미설치 시 fallback=True + verdict=WARNING."""
    result = cross_model_codex(
        ticket_id="T-OSN-MOCK",
        reason="dry-run",
        codex_cmd=["nonexistent_codex_cli_xyz_999"],
    )
    assert result["fallback"] is True
    assert result["verdict"] == "WARNING"
    assert "codex_cli_not_found" in result["codex_raw"]
    assert result["findings"] == []


def test_cross_model_codex_returns_fallback_on_timeout():
    """timeout 발생 시 fallback=True.

    Fix-v2: A no-output timeout (stdout=None) is now classified as
    'codex_api_unreachable_or_unconfigured' — NOT bare 'timeout'.
    This is the actual session-6 failure mode.
    """
    with patch("subprocess.run") as mock_run:
        exc = subprocess.TimeoutExpired(cmd=["codex"], timeout=1)
        exc.stdout = None  # no output produced — API-hang classification applies
        mock_run.side_effect = exc
        result = cross_model_codex(
            ticket_id="T-OSN-MOCK",
            reason="dry-run",
            timeout_sec=1,
        )
    assert result["fallback"] is True
    assert result["verdict"] == "WARNING"
    # Must NOT be the bare 'timeout' misclassification
    assert result["codex_raw"] != "timeout", (
        f"No-output timeout must not return bare 'timeout', got: {result['codex_raw']!r}"
    )
    assert "unreachable" in result["codex_raw"] or "unconfigured" in result["codex_raw"], (
        f"Expected API-unreachable description, got: {result['codex_raw']!r}"
    )


def test_cross_model_codex_returns_fallback_on_nonzero_exit():
    """codex 가 non-zero exit 시 fallback=True."""
    mock_result = subprocess.CompletedProcess(
        args=["codex"], returncode=1, stdout="", stderr="codex error"
    )
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", return_value=mock_result):
        result = cross_model_codex(
            ticket_id="T-OSN-MOCK",
            reason="dry-run",
        )
    assert result["fallback"] is True
    assert result["verdict"] == "WARNING"
    assert "codex error" in result["codex_raw"]


def test_cross_model_codex_parses_valid_yaml_output():
    """codex 가 정상 YAML 반환 시 verdict 정확 추출."""
    yaml_output = "verdict: BLOCKER\nfindings:\n  - {category: security, detail: 'sql injection'}\n"
    mock_result = subprocess.CompletedProcess(
        args=["codex"], returncode=0, stdout=yaml_output, stderr=""
    )
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", return_value=mock_result):
        result = cross_model_codex(
            ticket_id="T-OSN-MOCK",
            reason="reviewer flagged uncertainty",
        )
    assert result["fallback"] is False
    assert result["verdict"] == "BLOCKER"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["category"] == "security"


def test_cross_model_codex_handles_invalid_yaml_gracefully():
    """codex 가 YAML 아닌 출력 시 verdict=WARNING (default), fallback=False."""
    mock_result = subprocess.CompletedProcess(
        args=["codex"], returncode=0, stdout="this is not yaml: : :\n", stderr=""
    )
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", return_value=mock_result):
        result = cross_model_codex(
            ticket_id="T-OSN-MOCK",
            reason="dry-run",
        )
    # YAML 파싱 실패 → verdict default 'WARNING', fallback=False (codex 는 호출됨)
    assert result["verdict"] == "WARNING"
    assert result["fallback"] is False


# ── F5: codex CLI invocation format (OPT-07) ─────────────────────────────


def test_cross_model_codex_default_cmd_includes_prompt_as_positional_arg():
    """F5: default codex_cmd must not be bare ['codex', 'review'] — prompt must be passed
    as positional argument (codex review <PROMPT>) or via --uncommitted flag.

    codex CLI requires: codex review [--uncommitted|--base|--commit] OR codex review <PROMPT>.
    Bare `codex review` with prompt only on stdin is rejected by codex CLI.
    """
    captured_calls: list[dict] = []

    def capture_run(cmd, **kwargs):
        captured_calls.append({"cmd": cmd, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="verdict: OK\nfindings: []\n", stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", side_effect=capture_run):
        cross_model_codex(ticket_id="T-OSN-FORMAT-TEST", reason="test invocation")

    assert len(captured_calls) == 1
    cmd = captured_calls[0]["cmd"]
    # Must be at least ['codex', 'review', <something>]
    assert len(cmd) >= 3, f"codex_cmd must have >= 3 elements, got: {cmd}"
    assert cmd[0] == "codex"
    assert cmd[1] == "review"
    # Third element must be a flag or prompt string (not just stdin-only invocation)
    # Valid forms: ['codex', 'review', '--uncommitted', ...]
    #              ['codex', 'review', '--base', 'main']
    #              ['codex', 'review', '<prompt string>']
    third = cmd[2]
    assert third, "Third argument to codex review must be non-empty"


def test_cross_model_codex_default_cmd_passes_prompt_content():
    """F5: prompt text must appear somewhere in the invocation (positional or instructions flag)."""
    captured_calls: list[dict] = []
    test_reason = "reviewer flagged uncertainty for invocation check"

    def capture_run(cmd, **kwargs):
        captured_calls.append({"cmd": cmd, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="verdict: OK\nfindings: []\n", stderr="")

    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run", side_effect=capture_run):
        cross_model_codex(ticket_id="T-OSN-PROMPT-TEST", reason=test_reason)

    assert len(captured_calls) == 1
    cmd = captured_calls[0]["cmd"]
    kwargs = captured_calls[0]["kwargs"]

    # The prompt content (ticket_id + reason) should be in cmd args or stdin input
    full_invocation = " ".join(str(x) for x in cmd)
    stdin_input = kwargs.get("input", "")
    combined = full_invocation + " " + (stdin_input or "")

    assert "T-OSN-PROMPT-TEST" in combined, (
        f"ticket_id missing from invocation. cmd={cmd}, input={stdin_input!r}"
    )


def test_cross_model_codex_custom_cmd_override_respected():
    """F5: custom codex_cmd override must be used as-is (no prompt injection into cmd)."""
    captured_calls: list[dict] = []

    def capture_run(cmd, **kwargs):
        captured_calls.append({"cmd": cmd})
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="verdict: OK\nfindings: []\n", stderr="")

    custom_cmd = ["my-codex", "check", "--uncommitted"]
    with patch("subprocess.run", side_effect=capture_run):
        cross_model_codex(
            ticket_id="T-OSN-CUSTOM",
            reason="custom cmd test",
            codex_cmd=custom_cmd,
        )

    assert captured_calls[0]["cmd"] == custom_cmd


# ── DOD: T-OS3-BPRIME-CODEX-TIMEOUT-DIAGNOSE ─────────────────────────────────
# DOD item 2: binary absent → <5s, fallback=True, reason='binary not found'
# DOD item 3: binary responds normally (mock) → fallback=False + real verdict


def test_cross_model_codex_binary_absent_returns_fast():
    """DOD-2: When codex binary is absent from PATH, returns within <5s
    (NOT 60s timeout) with fallback=True and reason containing 'binary not found'
    or equivalent, without misclassifying absence as a timeout.

    Reproduces the session-6 symptom: codex IS on PATH but
    cross_model_codex returns 'timeout (>60s)' — this test forces the
    pre-check path that catches absence BEFORE spawning the subprocess.
    """
    with patch("shutil.which", return_value=None):
        start = time.monotonic()
        result = cross_model_codex(
            ticket_id="T-ABSENT-BINARY",
            reason="b-prime trigger",
            timeout_sec=60,  # timeout is long but should never be reached
        )
        elapsed = time.monotonic() - start

    # Must return fast — no 60s wait
    assert elapsed < 5.0, (
        f"binary-absent fallback took {elapsed:.2f}s — expected <5s. "
        "Likely waiting for subprocess timeout instead of failing fast."
    )
    assert result["fallback"] is True, "Expected fallback=True when binary is absent"
    # reason must NOT be 'timeout' — that would be the misclassification bug
    assert result["codex_raw"] != "timeout", (
        "codex_raw='timeout' is the misclassification bug: absence must not look like timeout"
    )
    # Should contain a clear 'not found' / 'binary' signal
    raw = result["codex_raw"].lower()
    assert any(kw in raw for kw in ("not found", "missing", "absent", "no codex", "binary")), (
        f"codex_raw should describe absence clearly, got: {result['codex_raw']!r}"
    )


def test_cross_model_codex_normal_response_returns_real_verdict():
    """DOD-3: When codex binary responds normally (mock), cross_model_codex
    returns fallback=False + parses the real verdict (OK/WARNING/BLOCKER).

    Covers all three valid verdict values from a mock subprocess.
    """
    for expected_verdict in ("OK", "WARNING", "BLOCKER"):
        yaml_output = (
            f"verdict: {expected_verdict}\n"
            "findings:\n"
            "  - {category: review, detail: 'mocked finding'}\n"
        )
        mock_result = subprocess.CompletedProcess(
            args=["codex", "review", "prompt"],
            returncode=0,
            stdout=yaml_output,
            stderr="",
        )
        with patch("shutil.which", return_value="/usr/local/bin/codex"), \
             patch("subprocess.run", return_value=mock_result):
            result = cross_model_codex(
                ticket_id="T-MOCK-VERDICT",
                reason="b-prime trigger",
            )

        assert result["fallback"] is False, (
            f"Expected fallback=False for successful mock, got True. verdict={expected_verdict}"
        )
        assert result["verdict"] == expected_verdict, (
            f"Expected verdict={expected_verdict!r}, got {result['verdict']!r}"
        )
        assert len(result["findings"]) == 1, "Expected 1 finding from mock output"


def test_cross_model_codex_binary_absent_via_which_not_subprocess():
    """DOD-2 (variant): The pre-check uses shutil.which, not a subprocess call.

    When shutil.which returns None, subprocess.run must NOT be called at all
    (i.e. the function short-circuits before spawning any process).
    """
    call_count = {"subprocess_run": 0}

    def no_run(*args, **kwargs):
        call_count["subprocess_run"] += 1
        raise AssertionError("subprocess.run should NOT be called when binary is absent")

    with patch("shutil.which", return_value=None), \
         patch("subprocess.run", side_effect=no_run):
        result = cross_model_codex(
            ticket_id="T-NO-SUBPROCESS",
            reason="pre-check test",
            timeout_sec=60,
        )

    assert call_count["subprocess_run"] == 0, "subprocess.run was called despite absent binary"
    assert result["fallback"] is True


# ── Fix v2: API-hang path — accurate no-output timeout classification ──────────
# DOD addition: binary PRESENT but API hangs/produces no verdict within timeout
# → cross_model_codex returns with an ACCURATE reason (NOT bare 'timeout'),
#   fallback=True.  Simulated via TimeoutExpired with no stdout.


def test_cross_model_codex_api_hang_no_output_returns_accurate_reason():
    """Fix-v2: When codex binary is PRESENT but the API hangs and produces no
    stdout output before the timeout, cross_model_codex must NOT return bare
    'timeout' — it must return an accurate reason string indicating that the
    API is unreachable/unconfigured.

    This reproduces the ACTUAL session-6 failure:
      - codex IS on PATH (/usr/local/bin/codex)
      - API key is absent/stale → subprocess hangs waiting for OpenAI
      - TimeoutExpired fires after 60s with zero verdict bytes produced
      - Old code returned codex_raw='timeout' — misclassified as wall-clock overrun

    Expected: codex_raw contains 'api' or 'unreachable' or 'unconfigured',
              fallback=True, verdict='WARNING', NOT bare 'timeout'.
    """
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run") as mock_run:
        # Simulate TimeoutExpired with no stdout produced (API hung from the start)
        exc = subprocess.TimeoutExpired(cmd=["codex", "review", "prompt"], timeout=15)
        exc.stdout = None  # no output produced before timeout
        exc.stderr = "OpenAI Codex v0.133.0\nworkdir: /some/path\n"  # banner only
        mock_run.side_effect = exc

        result = cross_model_codex(
            ticket_id="T-API-HANG",
            reason="b-prime trigger",
            timeout_sec=15,
        )

    assert result["fallback"] is True, "Expected fallback=True for API-hang timeout"
    assert result["verdict"] == "WARNING", "Expected verdict=WARNING for API-hang timeout"
    # The key assertion: must NOT be the bare misclassified 'timeout' string
    assert result["codex_raw"] != "timeout", (
        "codex_raw='timeout' is the misclassification bug: "
        "API-hang with no output must not look like a plain timeout. "
        f"Got: {result['codex_raw']!r}"
    )
    # Must contain a signal that points to API/unreachable/unconfigured
    raw = result["codex_raw"].lower()
    assert any(kw in raw for kw in ("api", "unreachable", "unconfigured", "no verdict", "no output")), (
        f"codex_raw should describe API-hang cause clearly, got: {result['codex_raw']!r}"
    )


def test_cross_model_codex_api_hang_empty_stdout_returns_accurate_reason():
    """Fix-v2 (variant): TimeoutExpired with empty string stdout (not None) —
    same accurate-reason requirement.  Covers both None and '' empty cases.
    """
    with patch("shutil.which", return_value="/usr/local/bin/codex"), \
         patch("subprocess.run") as mock_run:
        exc = subprocess.TimeoutExpired(cmd=["codex", "review", "prompt"], timeout=15)
        exc.stdout = ""   # empty string — no verdict produced
        exc.stderr = None
        mock_run.side_effect = exc

        result = cross_model_codex(
            ticket_id="T-API-HANG-EMPTY",
            reason="b-prime trigger",
            timeout_sec=15,
        )

    assert result["fallback"] is True
    assert result["codex_raw"] != "timeout", (
        f"Empty-stdout timeout must not return bare 'timeout', got: {result['codex_raw']!r}"
    )
    raw = result["codex_raw"].lower()
    assert any(kw in raw for kw in ("api", "unreachable", "unconfigured", "no verdict", "no output")), (
        f"Expected API-hang description, got: {result['codex_raw']!r}"
    )

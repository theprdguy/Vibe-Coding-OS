"""Failing tests for T-OS3-AVR-EXECUTION-CONTRACT.

These tests assert that ``_detect_failure`` (or its successor) flags three
stdout signatures as ``infra_failure``:
  1. "Error: timed out waiting for response"
  2. "npx playwright" / "playwright install" (MCP bypass)
  3. Missing ``verdict`` field (schema parse failure)

The implementation may extend the existing ``_detect_failure`` signature
to receive stdout, or add a sibling helper — either is acceptable per the
ticket constraint (do not break the existing 3 checks).
"""
from __future__ import annotations

from server.gemini_dispatcher import GeminiDispatcher


def _make_dispatcher(tmp_path) -> GeminiDispatcher:
    return GeminiDispatcher(project_root=tmp_path)


def test_detect_failure_flags_timeout_stdout_as_infra_failure(tmp_path):
    dispatcher = _make_dispatcher(tmp_path)
    stdout = "Error: timed out waiting for response\n"

    reason = dispatcher._detect_failure(  # type: ignore[call-arg]
        returncode=0,
        parsed={"verdict": "pass"},
        stdout=stdout,
    )

    assert reason is not None
    assert reason.startswith("visual_review_infra_failure:")
    assert "timed out waiting for response" in reason


def test_detect_failure_flags_npx_playwright_stdout_as_infra_failure(tmp_path):
    dispatcher = _make_dispatcher(tmp_path)
    stdout = "running: npx playwright install chromium\n"

    reason = dispatcher._detect_failure(  # type: ignore[call-arg]
        returncode=0,
        parsed={"verdict": "pass"},
        stdout=stdout,
    )

    assert reason is not None
    assert reason.startswith("visual_review_infra_failure:")
    assert "npx playwright" in reason


def test_detect_failure_flags_playwright_install_stdout_as_infra_failure(tmp_path):
    dispatcher = _make_dispatcher(tmp_path)
    stdout = "browser setup: playwright install --with-deps\n"

    reason = dispatcher._detect_failure(  # type: ignore[call-arg]
        returncode=0,
        parsed={"verdict": "pass"},
        stdout=stdout,
    )

    assert reason is not None
    assert reason.startswith("visual_review_infra_failure:")
    assert "playwright install" in reason


def test_detect_failure_flags_missing_verdict_as_infra_failure(tmp_path):
    dispatcher = _make_dispatcher(tmp_path)
    stdout = "{\"issues\": []}"

    reason = dispatcher._detect_failure(  # type: ignore[call-arg]
        returncode=0,
        parsed={"issues": []},
        stdout=stdout,
    )

    assert reason is not None
    assert reason.startswith("visual_review_infra_failure:")
    assert "missing verdict" in reason

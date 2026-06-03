"""T-OS3-DISPATCHER-REFACTOR — CLAUDE_P_DEFAULT_ARGS constant deduplication test.

Verifies that:
1. CLAUDE_P_DEFAULT_ARGS constant is defined and has the expected value.
2. No raw list literal ["claude", "-p", "--model", "haiku"] appears in dispatcher.py
   as a hardcoded duplicate (only the single constant definition is allowed).
3. _run_subprocess, _run_agent_review, and _attempt_retry all reference the constant
   (not separate literals).
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

DISPATCHER_PATH = Path(__file__).parent.parent / "server" / "dispatcher.py"


def test_constant_exists_and_correct_value():
    """CLAUDE_P_DEFAULT_ARGS must be importable and equal to the expected command."""
    from server.dispatcher import CLAUDE_P_DEFAULT_ARGS

    assert CLAUDE_P_DEFAULT_ARGS == ["claude", "-p", "--model", "haiku"], (
        f"Unexpected value: {CLAUDE_P_DEFAULT_ARGS!r}"
    )


def test_no_duplicate_literal_in_source():
    """The raw list literal must appear exactly once — as the constant definition.

    This ensures the 3 former hardcoded sites now use the constant.
    """
    source = DISPATCHER_PATH.read_text(encoding="utf-8")

    # Count occurrences of the literal in source text.
    literal = '"claude", "-p", "--model", "haiku"'
    count = source.count(literal)

    assert count == 1, (
        f"Expected exactly 1 occurrence of the literal in dispatcher.py "
        f"(the constant definition), found {count}. "
        "All call sites must reference CLAUDE_P_DEFAULT_ARGS."
    )


def test_run_subprocess_uses_constant():
    """_run_subprocess default command must reference CLAUDE_P_DEFAULT_ARGS."""
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    # Find _run_subprocess block and verify it uses the constant name
    assert "CLAUDE_P_DEFAULT_ARGS" in source

    # The literal must NOT appear inside _run_subprocess method body
    # (parse the method to check)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_subprocess":
            # Verify no bare list literal ["claude", "-p", "--model", "haiku"] in this method
            func_source = ast.get_source_segment(source, node) or ""
            assert '"claude", "-p", "--model", "haiku"' not in func_source, (
                "_run_subprocess still contains hardcoded literal; must use CLAUDE_P_DEFAULT_ARGS"
            )
            break
    else:
        pytest.fail("_run_subprocess method not found in dispatcher.py")


def test_run_agent_review_uses_constant():
    """_run_agent_review gate must reference CLAUDE_P_DEFAULT_ARGS, not a literal."""
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run_agent_review":
            func_source = ast.get_source_segment(source, node) or ""
            assert '"claude", "-p", "--model", "haiku"' not in func_source, (
                "_run_agent_review still contains hardcoded literal; must use CLAUDE_P_DEFAULT_ARGS"
            )
            break
    else:
        pytest.fail("_run_agent_review method not found in dispatcher.py")


def test_attempt_retry_uses_constant():
    """_attempt_retry must reference CLAUDE_P_DEFAULT_ARGS, not a literal."""
    source = DISPATCHER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_attempt_retry":
            func_source = ast.get_source_segment(source, node) or ""
            assert '"claude", "-p", "--model", "haiku"' not in func_source, (
                "_attempt_retry still contains hardcoded literal; must use CLAUDE_P_DEFAULT_ARGS"
            )
            break
    else:
        pytest.fail("_attempt_retry method not found in dispatcher.py")

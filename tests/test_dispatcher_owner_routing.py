"""W3-01 — owner routing 분기 테스트.

route_by_owner(owner) 가 각 owner 별 정확한 action 반환.
- BUILDER: action='in_session_message', exit_code=2
- CODEX:   action='subprocess_codex', exit_code=0 (실 dispatch 는 기존 경로)
- CLAUDE1: action='interactive_only', exit_code=2
- CLAUDE2: action='deprecated_reject', exit_code=1 (W6-02 완료 — 옛 .claude-b 분기 제거)
- 기타:    action='unknown', exit_code=1
"""
from __future__ import annotations

import pytest

from server.dispatcher import route_by_owner


def test_route_builder_returns_in_session_message():
    result = route_by_owner("BUILDER")
    assert result["action"] == "in_session_message"
    assert result["exit_code"] == 2
    assert "/dispatch" in result["message"].lower() or "claude1" in result["message"].lower()


def test_route_codex_returns_subprocess_codex():
    result = route_by_owner("CODEX")
    assert result["action"] == "subprocess_codex"
    assert result["exit_code"] == 0
    assert result.get("fallback_owner") is None


def test_route_claude1_returns_interactive_only():
    result = route_by_owner("CLAUDE1")
    assert result["action"] == "interactive_only"
    assert result["exit_code"] == 2
    assert "interactive" in result["message"].lower() or "policy" in result["message"].lower()


def test_route_claude2_returns_deprecated_reject():
    """W6-02 완료: CLAUDE2 owner 는 deprecated_reject + exit_code=1 (fallback 없음)."""
    result = route_by_owner("CLAUDE2")
    assert result["action"] == "deprecated_reject"
    assert result["exit_code"] == 1
    assert "deprecated" in result["message"].lower()
    assert result.get("fallback_owner") is None   # 옛 .claude-b subprocess 분기 제거


def test_route_unknown_owner_returns_unknown():
    result = route_by_owner("UNKNOWN_AGENT_XYZ")
    assert result["action"] == "unknown"
    assert result["exit_code"] == 1
    assert "unknown" in result["message"].lower()


def test_route_empty_owner_returns_unknown():
    result = route_by_owner("")
    assert result["action"] == "unknown"
    assert result["exit_code"] == 1


def test_route_none_owner_returns_unknown():
    result = route_by_owner(None)   # type: ignore[arg-type]
    assert result["action"] == "unknown"
    assert result["exit_code"] == 1


def test_route_case_sensitive_owner():
    """owner 는 정확히 대문자 매칭 — 'builder' (소문자) 는 unknown."""
    result = route_by_owner("builder")
    assert result["action"] == "unknown"

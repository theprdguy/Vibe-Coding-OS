"""T-OSN-W6-02 — CLAUDE2 owner 완전 제거 검증 (cross-test fast-path).

failing test 형태로 작성:
- test_claude2_owner_emits_deprecation: route_by_owner('CLAUDE2') 가
  action='deprecated_reject', exit_code=1, stderr 에 'DEPRECATED: CLAUDE2' 포함
- test_claude2_no_subprocess_call: route_by_owner('CLAUDE2') 결과에
  '.claude-b' 또는 'preflight-claude2' 문자열 없음
- test_builder_routing_intact: BUILDER 정상 라우팅 회귀 X
- test_codex_routing_intact: CODEX 정상 라우팅 회귀 X
- test_claude1_routing_intact: CLAUDE1 정상 라우팅 회귀 X
- test_cli_claude2_dispatch_rejects_with_exit_1: cli.main(['dispatch','T=T-MOCK-CLAUDE2']) 가
  exit code 1 을 반환하고 stderr 에 'DEPRECATED: CLAUDE2' 포함 — caller chain 전체 traverse.
"""
from __future__ import annotations

import io
import sys

import pytest

from server.dispatcher import route_by_owner


def test_claude2_owner_emits_deprecation():
    """CLAUDE2 owner 는 deprecated_reject action + exit_code=1 + 'DEPRECATED: CLAUDE2' 메시지."""
    result = route_by_owner("CLAUDE2")
    assert result["action"] == "deprecated_reject", (
        f"expected action='deprecated_reject', got {result['action']!r}"
    )
    assert result["exit_code"] == 1, (
        f"expected exit_code=1, got {result['exit_code']}"
    )
    assert "DEPRECATED: CLAUDE2" in result["message"], (
        f"'DEPRECATED: CLAUDE2' not found in message: {result['message']!r}"
    )
    assert "use BUILDER" in result["message"].lower() or "use builder" in result["message"].lower() or "BUILDER" in result["message"], (
        f"'BUILDER' migration hint not found in message: {result['message']!r}"
    )


def test_claude2_no_subprocess_references():
    """route_by_owner('CLAUDE2') 결과에 '.claude-b' / 'preflight-claude2' 문자열 없음."""
    result = route_by_owner("CLAUDE2")
    message = result.get("message", "")
    assert ".claude-b" not in message, (
        f"'.claude-b' found in message — subprocess fallback reference must be removed: {message!r}"
    )
    assert "preflight-claude2" not in message, (
        f"'preflight-claude2' found in message — subprocess fallback reference must be removed: {message!r}"
    )
    assert result.get("fallback_owner") is None, (
        f"fallback_owner should be None, got {result.get('fallback_owner')!r}"
    )


def test_claude2_deprecated_reject_is_hard_exit():
    """deprecated_reject 는 fallback 없이 종료 — fallback_owner=None, exit_code=1."""
    result = route_by_owner("CLAUDE2")
    assert result["exit_code"] == 1
    assert result.get("fallback_owner") is None


def test_builder_routing_intact():
    """BUILDER 정상 라우팅 회귀 X."""
    result = route_by_owner("BUILDER")
    assert result["action"] == "in_session_message"
    assert result["exit_code"] == 2
    assert result.get("fallback_owner") is None


def test_codex_routing_intact():
    """CODEX 정상 라우팅 회귀 X."""
    result = route_by_owner("CODEX")
    assert result["action"] == "subprocess_codex"
    assert result["exit_code"] == 0
    assert result.get("fallback_owner") is None


def test_claude1_routing_intact():
    """CLAUDE1 정상 라우팅 회귀 X."""
    result = route_by_owner("CLAUDE1")
    assert result["action"] == "interactive_only"
    assert result["exit_code"] == 2
    assert result.get("fallback_owner") is None


def test_cli_claude2_dispatch_rejects_with_exit_1(monkeypatch, capsys):
    """cli.main(['dispatch', 'T-MOCK-C2']) 가 exit code 1 반환 +
    stderr 에 'DEPRECATED: CLAUDE2' 포함 — caller chain 전체 (route → _handle_dispatch → main) traverse.
    """
    fake_queue = {
        "tickets": [
            {"id": "T-MOCK-C2", "owner": "CLAUDE2", "status": "todo", "goal": "mock"}
        ]
    }

    # Monkeypatch read_queue_with_archive 를 fake queue 반환으로 교체.
    # cli.py 의 _handle_dispatch 는 server.ssot.read_queue_with_archive 를 직접 import.
    import server.ssot as ssot_mod
    monkeypatch.setattr(ssot_mod, "read_queue_with_archive", lambda *_a, **_kw: fake_queue)

    stderr_capture = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr_capture)

    from server.cli import main
    exit_code = main(["dispatch", "T-MOCK-C2"])

    assert exit_code == 1, (
        f"expected exit code 1 for CLAUDE2 owner ticket, got {exit_code}"
    )
    stderr_output = stderr_capture.getvalue()
    assert "DEPRECATED: CLAUDE2" in stderr_output, (
        f"'DEPRECATED: CLAUDE2' not found in stderr: {stderr_output!r}"
    )

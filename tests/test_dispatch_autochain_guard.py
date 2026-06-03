"""T-OS3-DISPATCH-AUTOCHAIN-GUARD — auto_chain guard + C1 invariant regression tests.

DOD coverage:
1. auto_chain=false (default): single dispatch does NOT cascade into _dispatch_auto_chain_todo
   (or _auto_chain_enabled returns False, so _dispatch_auto_chain_todo is a no-op).
2. auto_chain=true: each chained ticket must pass C1 review-gate invariant — ticket without
   _review_verdict cannot transition to done (unreviewed cascade is structurally impossible).
3. dispatch_all_todo (explicit batch) regression — dispatches all todo tickets normally.
4. auto_chain=true + impl ticket without agent-review gate → ValidationError at dispatch entry
   (C1 BLOCKER 1 regression test as part of this guard suite).
5. _auto_chain_enabled reflects osn.yaml auto_chain field; false is the default.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from server.dispatcher import Dispatcher
from server.ssot import (
    ValidationError,
    record_review_verdict,
    update_ticket_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_queue(queue_path: Path, tickets: list[dict]) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )


def _impl_ticket_todo(tid: str) -> dict:
    """Minimal valid BUILDER impl ticket in todo status."""
    return {
        "id": tid,
        "owner": "BUILDER",
        "impl_owner": "BUILDER",
        "status": "todo",
        "_transition_reason": "seed",
        "_transition_actor": "test",
        "_transition_ts": "2026-01-01T00:00:00Z",
        "files": ["apps/foo.py"],
        "gates": [{"name": "review", "type": "agent-review"}],
    }


def _impl_ticket_done(tid: str) -> dict:
    """Minimal valid BUILDER impl ticket in done status (simulates a completed prerequisite)."""
    ticket = _impl_ticket_todo(tid)
    ticket["status"] = "done"
    ticket["_review_verdict"] = {
        "by": "agent-review",
        "verdict": "OK",
        "confidence": 0.9,
        "ts": "2026-01-01T00:00:00Z",
    }
    return ticket


def _make_dispatcher(tmp_path: Path, *, auto_chain: bool = False) -> tuple[Dispatcher, Path]:
    """Create a Dispatcher with configurable auto_chain setting."""
    logs = tmp_path / "logs"
    logs.mkdir()
    queue_path = tmp_path / "QUEUE.yaml"
    config = {
        "dispatch": {
            "auto_chain": auto_chain,
        },
        "agents": {
            "BUILDER": {"mode": "pipe", "command": ["echo", "done"]},
        },
    }
    dispatcher = Dispatcher(
        config=config,
        paths={"root": tmp_path, "logs": logs, "queue": queue_path},
    )
    return dispatcher, queue_path


# ---------------------------------------------------------------------------
# DOD 1 — auto_chain=false: single dispatch does NOT chain into backlog
# ---------------------------------------------------------------------------


class TestAutoChainFalseNoCascade:
    """DOD 1: auto_chain=false (default) means _dispatch_auto_chain_todo is a no-op."""

    def test_auto_chain_enabled_returns_false_when_not_set(self, tmp_path: Path) -> None:
        """_auto_chain_enabled returns False when auto_chain not in config."""
        dispatcher, _ = _make_dispatcher(tmp_path)
        assert dispatcher._auto_chain_enabled() is False

    def test_auto_chain_enabled_returns_false_when_explicitly_false(self, tmp_path: Path) -> None:
        """_auto_chain_enabled returns False when auto_chain: false explicitly."""
        dispatcher, _ = _make_dispatcher(tmp_path, auto_chain=False)
        assert dispatcher._auto_chain_enabled() is False

    def test_auto_chain_enabled_returns_true_when_set(self, tmp_path: Path) -> None:
        """_auto_chain_enabled returns True when auto_chain: true."""
        dispatcher, _ = _make_dispatcher(tmp_path, auto_chain=True)
        assert dispatcher._auto_chain_enabled() is True

    def test_dispatch_auto_chain_todo_returns_empty_when_disabled(self, tmp_path: Path) -> None:
        """_dispatch_auto_chain_todo returns [] immediately when auto_chain=false."""
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=False)
        _write_queue(queue_path, [_impl_ticket_todo("T-CHAIN-A"), _impl_ticket_todo("T-CHAIN-B")])

        result = dispatcher._dispatch_auto_chain_todo()

        assert result == [], (
            f"Expected no auto-chain with auto_chain=false, got: {result!r}. "
            "Single dispatch must NOT cascade into remaining backlog."
        )

    def test_single_dispatch_does_not_trigger_chain_on_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOD 1 end-to-end: _run_agent with auto_chain=false never calls _dispatch_auto_chain_todo.

        When completed_done=True in _run_agent, _dispatch_auto_chain_todo is still called,
        but because auto_chain=false it immediately returns [] without dispatching anything.
        This ensures no cascade even if the finally-block triggers the helper.
        """
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=False)
        tid = "T-SINGLE-DISPATCH"
        _write_queue(queue_path, [_impl_ticket_todo(tid), _impl_ticket_todo("T-SIBLING")])

        chain_dispatch_calls: list[str] = []

        original_auto_chain = dispatcher._dispatch_auto_chain_todo

        def spy_auto_chain():
            result = original_auto_chain()
            chain_dispatch_calls.extend(r[0] for r in result)
            return result

        monkeypatch.setattr(dispatcher, "_dispatch_auto_chain_todo", spy_auto_chain)
        monkeypatch.setattr(
            dispatcher,
            "_run_subprocess",
            lambda ticket, cfg: (
                True,
                {
                    "stdout": (
                        f"Done: {tid} - completed\n"
                        "Next: waiting\n"
                        "Block: none\n"
                    )
                },
            ),
        )
        monkeypatch.setattr(
            dispatcher, "_run_gates", lambda ticket, sha: (True, "gates passed")
        )

        # Patch _mark_ticket_done to avoid needing a full review verdict on the ticket
        monkeypatch.setattr(dispatcher, "_mark_ticket_done", lambda ticket, reason, **kw: None)

        ticket = {**_impl_ticket_todo(tid), "status": "doing"}
        dispatcher._run_agent(ticket, "HEAD")

        # _dispatch_auto_chain_todo was called (in the finally block) but returned []
        # so no sibling tickets were dispatched
        assert chain_dispatch_calls == [], (
            f"auto_chain=false: no sibling ticket should be dispatched, got: {chain_dispatch_calls!r}"
        )


# ---------------------------------------------------------------------------
# DOD 2 — auto_chain=true: review-gate invariant blocks unreviewed done transition
# ---------------------------------------------------------------------------


class TestAutoChainTrueReviewGateInvariant:
    """DOD 2: auto_chain=true does NOT bypass C1 review-gate invariant.

    Even when auto_chain fires, each chained ticket must pass the agent-review gate
    before transitioning to done.  _validate_review_verdict_for_done raises if no
    verdict is set, making unreviewed cascade structurally impossible.
    """

    def test_impl_ticket_without_verdict_cannot_transition_to_done(self, tmp_path: Path) -> None:
        """A BUILDER ticket with no _review_verdict raises ValidationError on done transition.

        This is the ssot-level invariant (C1 BLOCKER 1) that auto_chain cannot bypass:
        every impl ticket must have a real agent-review verdict before reaching done.
        """
        from server.ssot import _validate_review_verdict_for_done

        ticket = _impl_ticket_todo("T-NO-VERDICT")
        ticket["status"] = "code_ready"

        # No _review_verdict set on ticket — must raise
        with pytest.raises(ValidationError, match="_review_verdict"):
            _validate_review_verdict_for_done(ticket, override=False)

    def test_chain_ticket_without_verdict_mark_done_fails(self, tmp_path: Path) -> None:
        """_mark_ticket_done on a chained ticket without verdict returns a failure (not None).

        This simulates what happens in an auto_chain scenario: the chained ticket
        completes but has no review verdict.  _mark_ticket_done must fail, preventing
        the unreviewed done transition.
        """
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=True)
        ticket = _impl_ticket_todo("T-CHAIN-NO-VERDICT")
        ticket["status"] = "code_ready"
        _write_queue(queue_path, [ticket])

        failure = dispatcher._mark_ticket_done(ticket, "chained agent completed")

        assert failure is not None, (
            "REGRESSION: auto_chain=true chained ticket reached done without review verdict. "
            "RC#3 cascade hole re-opened."
        )
        saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
        assert saved["status"] != "done", (
            "Chained ticket transitioned to done without agent-review verdict — "
            "unreviewed cascade is now possible."
        )

    def test_chain_ticket_with_verdict_can_transition_to_done(self, tmp_path: Path) -> None:
        """_mark_ticket_done succeeds when agent-review verdict is present.

        Confirms the happy path: auto_chain CAN produce done transitions when each
        chained ticket properly passed its agent-review gate.
        """
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=True)
        ticket = _impl_ticket_todo("T-CHAIN-WITH-VERDICT")
        ticket["status"] = "code_ready"
        ticket["_review_verdict"] = {
            "by": "agent-review",
            "verdict": "OK",
            "confidence": 0.9,
            "ts": "2026-01-01T00:00:00Z",
        }
        _write_queue(queue_path, [ticket])

        failure = dispatcher._mark_ticket_done(ticket, "chained + reviewed")

        assert failure is None, (
            f"Chained ticket with valid verdict should reach done, got failure: {failure!r}"
        )
        saved = yaml.safe_load(queue_path.read_text(encoding="utf-8"))["tickets"][0]
        assert saved["status"] == "done"

    def test_auto_chain_dispatch_calls_dispatch_which_enforces_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOD 2 structural: _dispatch_auto_chain_todo calls self.dispatch() for each ticket.

        dispatch() calls _validate_impl_ticket_agent_review_gate (C1 BLOCKER 1).
        Therefore auto_chain cannot bypass the gate — the same enforcement path runs
        for chained tickets as for manual single-dispatch.
        """
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=True)

        chain_ticket = _impl_ticket_todo("T-CHAIN-AUTO")
        _write_queue(queue_path, [chain_ticket])

        dispatch_calls: list[str] = []

        def fake_dispatch(ticket_id: str, *, fatal_status_mismatch: bool = True):
            dispatch_calls.append(ticket_id)
            return True, f"Dispatched {ticket_id}"

        monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)

        dispatcher._dispatch_auto_chain_todo()

        assert "T-CHAIN-AUTO" in dispatch_calls, (
            "_dispatch_auto_chain_todo must call self.dispatch() for each chained ticket, "
            "which is where C1 gate enforcement lives."
        )


# ---------------------------------------------------------------------------
# DOD 3 — dispatch_all_todo regression: explicit batch dispatch works normally
# ---------------------------------------------------------------------------


class TestDispatchAllTodoRegression:
    """DOD 3: dispatch_all_todo (explicit batch) is unaffected by auto_chain setting."""

    def test_dispatch_all_todo_dispatches_all_todo_tickets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dispatch_all_todo dispatches every todo ticket regardless of auto_chain value."""
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=False)

        tickets = [
            _impl_ticket_todo("T-ALL-01"),
            _impl_ticket_todo("T-ALL-02"),
            _impl_ticket_todo("T-ALL-03"),
        ]
        _write_queue(queue_path, tickets)

        dispatched: list[str] = []

        def fake_dispatch(ticket_id: str, *, fatal_status_mismatch: bool = True):
            dispatched.append(ticket_id)
            # Update status so wait_all does not hang
            update_ticket_status(
                queue_path, ticket_id, "doing",
                reason="dispatch started", actor="dispatcher",
            )
            update_ticket_status(
                queue_path, ticket_id, "done",
                reason="mocked done", actor="test",
                override=True,
            )
            return True, f"Dispatched {ticket_id}"

        monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
        monkeypatch.setattr(dispatcher, "wait_all", lambda: None)

        results = dispatcher.dispatch_all_todo()

        result_ids = [r[0] for r in results]
        assert "T-ALL-01" in result_ids
        assert "T-ALL-02" in result_ids
        assert "T-ALL-03" in result_ids
        assert len(result_ids) == 3, (
            f"dispatch_all_todo must dispatch all 3 todo tickets, got: {result_ids!r}"
        )

    def test_dispatch_all_todo_skips_non_todo_tickets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dispatch_all_todo only processes todo tickets, skipping done/blocked/doing."""
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=False)

        todo_ticket = _impl_ticket_todo("T-ONLY-TODO")
        done_ticket = _impl_ticket_done("T-ALREADY-DONE")

        _write_queue(queue_path, [todo_ticket, done_ticket])

        dispatched: list[str] = []

        def fake_dispatch(ticket_id: str, *, fatal_status_mismatch: bool = True):
            dispatched.append(ticket_id)
            return True, f"Dispatched {ticket_id}"

        monkeypatch.setattr(dispatcher, "dispatch", fake_dispatch)
        monkeypatch.setattr(dispatcher, "wait_all", lambda: None)

        dispatcher.dispatch_all_todo()

        assert "T-ONLY-TODO" in dispatched, "todo ticket must be dispatched"
        assert "T-ALREADY-DONE" not in dispatched, "done ticket must not be re-dispatched"


# ---------------------------------------------------------------------------
# DOD 4 — auto_chain=true + impl ticket missing agent-review gate → ValidationError
# ---------------------------------------------------------------------------


class TestAutoChainImplTicketGateRequired:
    """DOD 4: C1 BLOCKER 1 regression locked in for auto_chain context.

    Even when auto_chain=true, dispatch() enforces agent-review gate presence on
    all BUILDER/CODEX impl tickets.  This is a regression test ensuring the C1
    invariant (_validate_impl_ticket_agent_review_gate) applies in the auto-chain path.
    """

    def test_impl_ticket_without_agent_review_gate_raises(self, tmp_path: Path) -> None:
        """BUILDER ticket with files but no agent-review gate → ValidationError.

        Regression test (C1 BLOCKER 1): _validate_impl_ticket_agent_review_gate must
        raise regardless of auto_chain setting.
        """
        dispatcher, _ = _make_dispatcher(tmp_path, auto_chain=True)

        ticket = {
            "id": "T-NO-AR-GATE",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["apps/bar.py"],
            # No agent-review gate — BLOCKER 1 should fire
        }
        gates: list[dict] = [{"name": "pr-check", "run": "make pr-check"}]

        with pytest.raises(ValidationError, match="agent-review"):
            dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_impl_ticket_with_agent_review_gate_does_not_raise(self, tmp_path: Path) -> None:
        """BUILDER ticket with proper agent-review gate → no error, auto_chain=true."""
        dispatcher, _ = _make_dispatcher(tmp_path, auto_chain=True)

        ticket = {
            "id": "T-WITH-AR-GATE",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["apps/bar.py"],
            "gates": [{"name": "review", "type": "agent-review"}],
        }
        gates: list[dict] = [
            {"name": "pr-check", "run": "make pr-check"},
            {"name": "review", "type": "agent-review"},
        ]

        # Must not raise
        dispatcher._validate_impl_ticket_agent_review_gate(ticket, gates)

    def test_auto_chain_dispatch_call_validates_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOD 4 structural: when _dispatch_auto_chain_todo calls dispatch(), gate validation fires.

        The ticket in the queue lacks an agent-review gate.  We stub git snapshot
        capture and ticket file preflight so those earlier checks pass; the gate check
        (_validate_impl_ticket_agent_review_gate) is then the first rejection point.
        Without the agent-review gate, ValidationError is raised and surfaced as a failure
        tuple — preventing the chained ticket from running unreviewed.
        """
        dispatcher, queue_path = _make_dispatcher(tmp_path, auto_chain=True)

        # Create the scoped file so validate_ticket preflight passes
        scoped_file = tmp_path / "apps" / "baz.py"
        scoped_file.parent.mkdir(parents=True, exist_ok=True)
        scoped_file.write_text("# placeholder\n", encoding="utf-8")

        # Stub git snapshot capture — tmp_path is not a git repo
        monkeypatch.setattr(
            dispatcher, "_capture_dispatch_snapshot", lambda ticket_id: "abc1234"
        )

        ticket_no_gate = {
            "id": "T-CHAIN-NO-GATE",
            "owner": "BUILDER",
            "impl_owner": "BUILDER",
            "status": "todo",
            "_transition_reason": "seed",
            "_transition_actor": "test",
            "_transition_ts": "2026-01-01T00:00:00Z",
            "files": ["apps/baz.py"],
            # No gates declared — will use defaults from config (which has no agent-review gate)
            # → _validate_impl_ticket_agent_review_gate fires → ValidationError
        }
        _write_queue(queue_path, [ticket_no_gate])

        # The dispatcher config has no gate defaults (minimal config), so the
        # impl ticket has no agent-review gate → dispatch must return failure
        results = dispatcher._dispatch_auto_chain_todo()

        assert len(results) == 1, f"Expected 1 result for 1 ticket, got: {results!r}"
        ticket_id, msg = results[0]
        assert ticket_id == "T-CHAIN-NO-GATE"
        assert "ValidationError" in msg or "agent-review" in msg, (
            f"Expected ValidationError about agent-review gate in result message, got: {msg!r}. "
            "C1 BLOCKER 1 must fire even in auto_chain path."
        )


# ---------------------------------------------------------------------------
# DOD 5 — deos.yaml auto_chain default is false (policy enforcement test)
# ---------------------------------------------------------------------------


class TestOsnYamlAutoChainPolicy:
    """DOD 5: deos.yaml dispatch.auto_chain=false is the hardened default.

    These tests ensure the policy is not silently reverted by config changes.
    """

    def test_osn_yaml_auto_chain_is_false(self) -> None:
        """deos.yaml dispatch.auto_chain must be false (2026-05-28 incident remediation).

        This test will FAIL if auto_chain is changed back to true without a deliberate
        policy decision, alerting the team to the regression.
        """
        import yaml as yaml_lib

        deos_path = Path(__file__).parent.parent / "deos.yaml"
        config = yaml_lib.safe_load(deos_path.read_text(encoding="utf-8"))
        auto_chain = config.get("dispatch", {}).get("auto_chain", False)
        assert auto_chain is False, (
            f"deos.yaml dispatch.auto_chain must be false (got {auto_chain!r}). "
            "2026-05-28 incident: auto_chain=true caused 9-ticket unreviewed cascade. "
            "Change this only with explicit policy decision and test update."
        )

    def test_auto_chain_default_is_false_in_dispatcher(self, tmp_path: Path) -> None:
        """Dispatcher._auto_chain_enabled defaults to False when key is absent from config."""
        dispatcher, _ = _make_dispatcher(tmp_path)
        # Explicitly test with empty dispatch config
        dispatcher.config = {"dispatch": {}}
        assert dispatcher._auto_chain_enabled() is False, (
            "auto_chain must default to False when not explicitly set in config."
        )

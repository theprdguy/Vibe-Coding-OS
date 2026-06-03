from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.dispatcher import Dispatcher
from server.ssot import ValidationError, append_tickets, read_queue


def _write_queue(tmp_path: Path, tickets: list[dict]) -> Path:
    queue_path = tmp_path / "QUEUE.yaml"
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )
    return queue_path


@pytest.mark.parametrize("tdd_value", ["required", "skip", "self-evident"])
def test_read_queue_accepts_all_valid_tdd_values(tmp_path: Path, tdd_value: str) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            {
                "id": f"T-{tdd_value}",
                "owner": "CODEX",
                "status": "todo",
                "goal": "schema validation",
                "files": ["tests/unit/test_queue_schema.py"],
                "verify": "pytest",
                "deps": [],
                "tdd": tdd_value,
            }
        ],
    )

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["tdd"] == tdd_value


def test_read_queue_rejects_invalid_tdd_value(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            {
                "id": "T-invalid",
                "owner": "CODEX",
                "status": "todo",
                "goal": "schema validation",
                "files": ["tests/unit/test_queue_schema.py"],
                "verify": "pytest",
                "deps": [],
                "tdd": "foo",
            }
        ],
    )

    with pytest.raises(ValidationError, match="tdd must be one of"):
        read_queue(queue_path)


def test_read_queue_applies_default_tdd_and_owner_fallbacks(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            {
                "id": "T-defaults",
                "owner": "CODEX",
                "status": "todo",
                "goal": "schema defaults",
                "files": ["tests/unit/test_queue_schema.py"],
                "verify": "pytest",
                "deps": [],
            }
        ],
    )

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["tdd"] == "skip"
    assert ticket["test_owner"] == "CODEX"
    assert ticket["impl_owner"] == "CODEX"


def _production_ticket(**overrides: object) -> dict:
    ticket = {
        "id": "T-PRODUCTION",
        "owner": "CODEX",
        "status": "todo",
        "mode": "production",
        "user_outcome": "User can complete the production workflow safely.",
        "risk_level": "medium",
        "work_type": "api",
        "policy_class": "hard",
        "goal": "schema validation",
        "dod": [
            "Valid request returns 200 with expected payload",
            "Invalid request returns 400 with validation error",
        ],
        "files": ["server/ssot.py", "tests/unit/test_queue_schema.py"],
        "verify": "pytest tests/unit/test_queue_schema.py",
        "deps": [],
    }
    ticket.update(overrides)
    return ticket


def _waiver(**overrides: object) -> dict:
    waiver = {
        "id": "W-20260515-001",
        "ticket": "T-WAIVED",
        "mode": "production",
        "policy": "required_visual_review",
        "requested_by": "CODEX",
        "approved_by": "PM",
        "decision": "accept_with_waiver",
        "reason": "PM accepts visual review deferral for this production ticket.",
        "risk_accepted": "A visual regression could be missed until follow-up review.",
        "expires": "after_ticket",
        "follow_up_ticket": "T-FOLLOW-UP",
        "evidence": ["docs/policy/WAIVER_FORMAT.md"],
        "created_at": "2026-05-15T00:00:00Z",
    }
    waiver.update(overrides)
    return waiver


def test_read_queue_keeps_legacy_tickets_without_mode_compatible(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            {
                "id": "T-LEGACY",
                "owner": "CODEX",
                "status": "todo",
                "goal": "legacy ticket",
            }
        ],
    )

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["id"] == "T-LEGACY"
    assert "mode" not in ticket


def test_read_queue_rejects_invalid_policy_enum(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [_production_ticket(mode="ship-it")])

    with pytest.raises(ValidationError, match="mode must be one of"):
        read_queue(queue_path)


def test_read_queue_rejects_production_ticket_without_user_outcome(tmp_path: Path) -> None:
    ticket = _production_ticket()
    ticket.pop("user_outcome")
    queue_path = _write_queue(tmp_path, [ticket])

    with pytest.raises(ValidationError, match="user_outcome is required for production tickets"):
        read_queue(queue_path)


def test_read_queue_requires_visual_review_for_production_ui_without_waiver(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                work_type="ui",
                requires_visual_review=False,
            )
        ],
    )

    with pytest.raises(
        ValidationError,
        match="production UI tickets require requires_visual_review=true or a valid required_visual_review waiver",
    ):
        read_queue(queue_path)


def test_read_queue_allows_production_ui_visual_review_or_valid_waiver(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                id="T-VISUAL",
                work_type="ui",
                requires_visual_review=True,
                reviewers={"visual": "gemini", "code": "reviewer", "security": "none"},
            ),
            _production_ticket(
                id="T-WAIVED",
                work_type="ui",
                requires_visual_review=False,
                waivers=[_waiver()],
            ),
        ],
    )

    tickets = read_queue(queue_path)["tickets"]

    assert tickets[0]["requires_visual_review"] is True
    assert tickets[0]["reviewers"]["visual"] == "gemini"
    assert tickets[1]["waivers"][0]["id"] == "W-20260515-001"


def test_string_waiver_id_is_reference_only_for_production_policy_exception(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                work_type="ui",
                requires_visual_review=False,
                waivers=["W-20260515-001"],
            )
        ],
    )

    with pytest.raises(ValidationError, match="valid required_visual_review waiver"):
        read_queue(queue_path)


def test_read_queue_rejects_bad_waiver_id_format(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [_production_ticket(waivers=["W-BAD"])])

    with pytest.raises(ValidationError, match="waiver id must match W-YYYYMMDD-001"):
        read_queue(queue_path)


def test_read_queue_rejects_incomplete_waiver_record(tmp_path: Path) -> None:
    waiver = _waiver()
    waiver.pop("risk_accepted")
    queue_path = _write_queue(tmp_path, [_production_ticket(waivers=[waiver])])

    with pytest.raises(ValidationError, match="waiver missing required fields: risk_accepted"):
        read_queue(queue_path)


def test_read_queue_rejects_non_waivable_policy(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                id="T-WAIVED",
                waivers=[_waiver(policy="secret_exposure")],
            )
        ],
    )

    with pytest.raises(ValidationError, match="secret_exposure is non-waivable"):
        read_queue(queue_path)


def test_read_queue_rejects_waiver_without_expiry_or_follow_up(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                id="T-WAIVED",
                waivers=[_waiver(expires="never", follow_up_ticket="none")],
            )
        ],
    )

    with pytest.raises(ValidationError, match="waiver requires expiry or follow_up_ticket"):
        read_queue(queue_path)


def test_requires_security_review_sets_legacy_security_audit_flag(tmp_path: Path) -> None:
    queue_path = _write_queue(
        tmp_path,
        [
            _production_ticket(
                requires_security_review=True,
                reviewers={"security": "security"},
            )
        ],
    )

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["requires_security_review"] is True
    assert ticket["security_audit"] is True


def test_append_tickets_validates_new_production_ticket_policy_fields(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [])
    ticket = _production_ticket()
    ticket.pop("policy_class")

    with pytest.raises(ValidationError, match="policy_class is required for production tickets"):
        append_tickets(queue_path, [ticket])


def test_resolve_agent_uses_impl_owner_when_present() -> None:
    dispatcher = Dispatcher(
        config={"agents": {"CODEX": {}, "CLAUDE2": {}}},
        paths={"queue": Path("devos/tasks/QUEUE.yaml")},
    )
    ticket = {"owner": "CODEX", "impl_owner": "CLAUDE2"}

    resolved_owner, fallback_reason = dispatcher._resolve_agent(
        ticket.get("impl_owner") or ticket["owner"]
    )

    assert resolved_owner == "CLAUDE2"
    assert fallback_reason is None


def test_resolve_agent_falls_back_to_owner_when_impl_owner_missing() -> None:
    dispatcher = Dispatcher(
        config={"agents": {"CODEX": {}, "CLAUDE2": {}}},
        paths={"queue": Path("devos/tasks/QUEUE.yaml")},
    )
    ticket = {"owner": "CODEX"}

    resolved_owner, fallback_reason = dispatcher._resolve_agent(
        ticket.get("impl_owner") or ticket["owner"]
    )

    assert resolved_owner == "CODEX"
    assert fallback_reason is None

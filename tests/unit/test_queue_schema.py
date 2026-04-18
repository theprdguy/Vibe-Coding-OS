from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.dispatcher import Dispatcher
from server.ssot import ValidationError, read_queue


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

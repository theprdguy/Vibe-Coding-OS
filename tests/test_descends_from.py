from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.ssot import ValidationError, format_queue_with_header, read_queue


def _write_queue(tmp_path: Path, tickets: list[dict]) -> Path:
    queue_path = tmp_path / "QUEUE.yaml"
    queue_path.write_text(
        yaml.safe_dump({"version": "3.0", "tickets": tickets}, sort_keys=False),
        encoding="utf-8",
    )
    return queue_path


def _ticket(**overrides: object) -> dict:
    ticket = {
        "id": "T-CHILD",
        "owner": "CODEX",
        "status": "todo",
        "goal": "promote exploration ticket into production",
    }
    ticket.update(overrides)
    return ticket


def test_read_queue_accepts_string_descends_from(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [_ticket(descends_from="T-PARENT")])

    ticket = read_queue(queue_path)["tickets"][0]

    assert ticket["descends_from"] == "T-PARENT"


def test_read_queue_accepts_missing_descends_from(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [_ticket()])

    ticket = read_queue(queue_path)["tickets"][0]

    assert "descends_from" not in ticket


@pytest.mark.parametrize("bad_value", [123, ["T-PARENT"]])
def test_read_queue_rejects_non_string_descends_from(
    tmp_path: Path, bad_value: object
) -> None:
    queue_path = _write_queue(tmp_path, [_ticket(descends_from=bad_value)])

    with pytest.raises(ValidationError, match="descends_from must be a string ticket id"):
        read_queue(queue_path)


def test_queue_output_shows_descends_from_relationship(tmp_path: Path) -> None:
    queue_path = _write_queue(tmp_path, [_ticket(descends_from="T-PARENT")])

    output = format_queue_with_header(queue_path)

    assert "T-CHILD" in output
    assert "descends_from=T-PARENT" in output

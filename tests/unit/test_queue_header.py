from __future__ import annotations

from pathlib import Path

import yaml

from server.__main__ import format_queue_with_header


def test_queue_header_counts_policy_statuses_without_other_bucket(tmp_path: Path) -> None:
    queue_path = tmp_path / "QUEUE.yaml"
    queue_path.write_text(
        yaml.safe_dump(
            {
                "version": "3.0",
                "tickets": [
                    {"id": "T-TODO", "status": "todo", "owner": "CODEX", "goal": "todo"},
                    {"id": "T-CODE", "status": "code_ready", "owner": "CODEX", "goal": "code"},
                    {"id": "T-PM", "status": "needs_pm", "owner": "CODEX", "goal": "pm"},
                    {"id": "T-DONE", "status": "done", "owner": "CODEX", "goal": "done"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    summary = format_queue_with_header(queue_path).splitlines()[0]

    assert "todo: 1" in summary
    assert "code_ready: 1" in summary
    assert "needs_pm: 1" in summary
    assert "other:" not in summary

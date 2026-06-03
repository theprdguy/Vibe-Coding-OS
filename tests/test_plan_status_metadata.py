from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.dispatcher import DISPATCHER_LOCK_OVERRIDE_ENV
from server.ssot import approve_plan, read_plan, reject_plan


ISO8601_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def write_queue(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version: '3.0'\ntickets: []\n")


def write_plan(path: Path, plan_id: str, ticket_id: str = "T-PLAN-001") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"id: {plan_id}",
                "source: PRD",
                "summary: |",
                "  First line",
                "  Second line",
                "tickets:",
                f"- id: {ticket_id}",
                "  owner: CLAUDE1",
                "  status: todo",
                "  priority: low",
                "  goal: |",
                "    Preserve plan metadata while approving.",
                "  files:",
                "  - server/ssot.py",
                "  verify:",
                "  - pytest tests/test_plan_status_metadata.py -v",
                "  deps: []",
                "",
            ]
        )
    )


def cli_env(repo: Path) -> dict[str, str]:
    return {
        "PYTHONPATH": str(Path.cwd()),
        DISPATCHER_LOCK_OVERRIDE_ENV: str(repo / "devos/logs/dispatcher-test.pid"),
    }


def test_approve_plan_writes_status_and_utc_timestamp(tmp_path: Path) -> None:
    plans_path = tmp_path / "devos/plans"
    queue_path = tmp_path / "devos/tasks/QUEUE.yaml"
    write_queue(queue_path)
    write_plan(plans_path / "pending/P-13.yaml", "P-13")

    assert approve_plan(plans_path, "P-13", queue_path) is True

    approved_file = plans_path / "approved/P-13.yaml"
    approved = yaml.safe_load(approved_file.read_text())
    assert approved["status"] == "approved"
    assert ISO8601_UTC_RE.match(approved["approved_at"])
    assert "summary: |\n  First line\n  Second line\n" in approved_file.read_text()


def test_reject_plan_writes_status_and_utc_timestamp(tmp_path: Path) -> None:
    plans_path = tmp_path / "devos/plans"
    write_plan(plans_path / "pending/P-13.yaml", "P-13")

    assert reject_plan(plans_path, "P-13", "needs revision") is True

    rejected = yaml.safe_load((plans_path / "rejected/P-13.yaml").read_text())
    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "needs revision"
    assert ISO8601_UTC_RE.match(rejected["rejected_at"])


@pytest.mark.parametrize(
    ("directory", "expected_status"),
    [
        ("pending", "pending"),
        ("approved", "approved"),
        ("rejected", "rejected"),
    ],
)
def test_read_plan_infers_missing_status_from_plan_directory(
    tmp_path: Path,
    directory: str,
    expected_status: str,
) -> None:
    plan_file = tmp_path / "devos/plans" / directory / "P-13.yaml"
    write_plan(plan_file, "P-13")

    assert read_plan(plan_file)["status"] == expected_status
    assert "status" not in yaml.safe_load(plan_file.read_text())


def test_approve_plan_rejects_second_approval_as_already_approved(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "devos/tasks").mkdir(parents=True)
    (repo / "devos/plans/pending").mkdir(parents=True)
    (repo / "devos/plans/approved").mkdir(parents=True)
    (repo / "devos/logs").mkdir(parents=True)
    (repo / "deos.yaml").write_text(
        "\n".join(
            [
                "devos_dir: devos",
                "queue_file: devos/tasks/QUEUE.yaml",
                "plans_dir: devos/plans",
                "logs_dir: devos/logs",
                "",
            ]
        )
    )
    write_queue(repo / "devos/tasks/QUEUE.yaml")
    write_plan(repo / "devos/plans/pending/2026-04-30-P-13.yaml", "P-13", "T-PLAN-CLI")

    first = subprocess.run(
        [sys.executable, "-m", "server", "approve", "P-13"],
        cwd=repo,
        env=cli_env(repo),
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr

    second = subprocess.run(
        [sys.executable, "-m", "server", "approve", "P-13"],
        cwd=repo,
        env=cli_env(repo),
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 1
    assert "already approved" in second.stderr

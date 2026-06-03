from __future__ import annotations

from pathlib import Path

from server.cli_reports import (
    REQUIRED_PILOT_POLICY_ARTIFACTS,
    build_pilot_status,
    format_pilot_status,
    pilot_status_exit_code,
)


def _write_pilot_project(root: Path, *, missing_artifact: str | None = None) -> None:
    pilot_doc = root / "docs" / "OS3_E2E_PILOT.md"
    pilot_doc.parent.mkdir(parents=True, exist_ok=True)
    pilot_doc.write_text("# OS3 E2E Pilot\nStatus: ready\n", encoding="utf-8")

    for rel_path in REQUIRED_PILOT_POLICY_ARTIFACTS:
        if rel_path == missing_artifact:
            continue
        artifact = root / rel_path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(f"# {artifact.name}\n", encoding="utf-8")


def _pilot_queue(*, ticket_status: str = "code_ready") -> dict:
    return {
        "tickets": [
            {
                "id": "T-OS3-PILOT-SYNTHETIC-01",
                "owner": "CODEX",
                "status": ticket_status,
                "mode": "production",
                "requires_pm_acceptance": True,
            }
        ]
    }


def test_format_pilot_status_ready_renders_doc_and_next_step(tmp_path: Path) -> None:
    _write_pilot_project(tmp_path)

    report = build_pilot_status(tmp_path, _pilot_queue(ticket_status="code_ready"))
    output = format_pilot_status(report)

    assert "Pilot doc: OK docs/OS3_E2E_PILOT.md (status: ready)" in output
    assert (
        "Next evidence step: Run independent reviewer/PM acceptance, "
        "then mark the pilot ticket done."
    ) in output
    assert "Strict readiness: PASS" in output
    assert pilot_status_exit_code(report, strict=True) == 0


def test_format_pilot_status_missing_artifact_renders_doc_and_next_step(tmp_path: Path) -> None:
    missing_artifact = "docs/policy/WAIVER_FORMAT.md"
    _write_pilot_project(tmp_path, missing_artifact=missing_artifact)

    report = build_pilot_status(tmp_path, _pilot_queue(ticket_status="code_ready"))
    output = format_pilot_status(report)

    assert "Pilot doc: OK docs/OS3_E2E_PILOT.md (status: ready)" in output
    assert "MISSING docs/policy/WAIVER_FORMAT.md" in output
    assert (
        "Next evidence step: Restore missing policy artifacts before final pilot acceptance."
    ) in output
    assert "Strict readiness: FAIL" in output
    assert pilot_status_exit_code(report, strict=True) == 1

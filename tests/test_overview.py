import os
import subprocess
import sys
from pathlib import Path

from server.overview import build_overview, format_overview
from server.projects_registry import register_project

REPO = Path(__file__).resolve().parent.parent
BIN_OS3 = REPO / "bin" / "deos"


def _make_project_queue(host: Path, name: str, statuses: list[str]):
    proj = host / "projects" / name
    (proj / "devos" / "tasks").mkdir(parents=True)
    tickets = "\n".join(
        f"  - id: T-{name.upper()}-{i:02d}\n    owner: CODEX\n    status: {s}"
        for i, s in enumerate(statuses)
    )
    (proj / "devos" / "tasks" / "QUEUE.yaml").write_text(
        f"tickets:\n{tickets}\n", encoding="utf-8"
    )
    register_project(host, name, f"projects/{name}")


def test_overview_counts_statuses(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    _make_project_queue(host, "meation", ["todo", "todo", "doing", "blocked", "done"])
    rows = {r["name"]: r for r in build_overview(host)}
    assert rows["meation"]["todo"] == 2
    assert rows["meation"]["doing"] == 1
    assert rows["meation"]["blocked"] == 1


def test_overview_missing_queue_is_zero_not_error(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    register_project(host, "bare", "projects/bare")  # no QUEUE on disk
    row = build_overview(host)[0]
    assert row["error"] is None
    assert (row["todo"], row["doing"], row["blocked"]) == (0, 0, 0)


def test_overview_bad_project_does_not_break_others(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    _make_project_queue(host, "good", ["todo"])
    # malformed QUEUE for another project -> error captured, good project still counted
    bad = host / "projects" / "bad"
    (bad / "devos" / "tasks").mkdir(parents=True)
    (bad / "devos" / "tasks" / "QUEUE.yaml").write_text(
        "tickets:\n  - this is not a valid ticket mapping\n", encoding="utf-8"
    )
    register_project(host, "bad", "projects/bad")
    rows = {r["name"]: r for r in build_overview(host)}
    assert rows["good"]["todo"] == 1
    assert rows["bad"]["error"] is not None  # captured, not raised


def test_format_overview_empty():
    assert format_overview([]) == "no projects registered"


def test_overview_cli_e2e(tmp_path):
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    _make_project_queue(host, "meation", ["todo", "doing"])
    env = {**os.environ, "PYTHONPATH": str(REPO), "OS3_HOST_ROOT": str(host)}
    r = subprocess.run(
        [sys.executable, str(BIN_OS3), "overview"],
        cwd=str(host), env=env, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "meation" in r.stdout and "project\tstatus" in r.stdout

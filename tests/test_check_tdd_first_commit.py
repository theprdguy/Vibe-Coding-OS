from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
TDD_SCRIPT = REPO / "scripts" / "check-tdd-first-commit.sh"


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _git(repo: Path, *args: str) -> None:
    result = _run(["git", *args], cwd=repo)
    assert result.returncode == 0, result.stderr


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_repo(tmp_path: Path, ticket_id: str) -> Path:
    repo = tmp_path / ticket_id.lower()
    (repo / "devos" / "tasks").mkdir(parents=True)
    (repo / "devos" / "logs").mkdir(parents=True)
    (repo / "apps" / "api").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    _write(
        repo / "devos" / "tasks" / "QUEUE.yaml",
        "\n".join(
            [
                "version: '3.0'",
                "tickets:",
                f"- id: {ticket_id}",
                "  owner: CODEX",
                "  status: doing",
                "  tdd: required",
                "  files:",
                "  - apps/api/foo.py",
                "  - tests/test_foo.py",
                "",
            ]
        ),
    )
    _write(repo / "apps" / "api" / "foo.py", "print('baseline')\n")
    _write(repo / "tests" / ".gitkeep", "")

    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _commit(repo: Path, ticket_id: str, path: str, content: str, suffix: str) -> None:
    _write(repo / path, content)
    _git(repo, "add", path)
    _git(repo, "commit", "-qm", f"{ticket_id} {suffix}")


def _run_tdd_gate(repo: Path) -> subprocess.CompletedProcess:
    return _run(
        ["bash", str(TDD_SCRIPT), str(repo)],
        cwd=repo,
        env={"AGENT_NAME": "CODEX"},
    )


def test_tdd_first_commit_skips_devos_only_ticket_filing_commit(tmp_path: Path) -> None:
    ticket_id = "T-TDD-FIRST-SKIP-FILING"
    repo = _make_repo(tmp_path, ticket_id)

    _commit(
        repo,
        ticket_id,
        "devos/tasks/QUEUE.yaml",
        (repo / "devos" / "tasks" / "QUEUE.yaml").read_text(encoding="utf-8")
        + "  _transition_reason: filed\n",
        "ticket filing",
    )
    _commit(repo, ticket_id, "tests/test_foo.py", "def test_foo():\n    assert True\n", "add tests")
    _commit(repo, ticket_id, "apps/api/foo.py", "print('impl')\n", "implement")

    result = _run_tdd_gate(repo)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert f"PASS tdd-first-commit: {ticket_id} first commit includes test files" in output
    assert "first commit lacks test files" not in output


def test_tdd_first_commit_still_fails_when_first_real_commit_lacks_tests(tmp_path: Path) -> None:
    ticket_id = "T-TDD-FIRST-REAL-VIOLATION"
    repo = _make_repo(tmp_path, ticket_id)

    _commit(repo, ticket_id, "apps/api/foo.py", "print('impl only')\n", "implement before tests")
    _commit(repo, ticket_id, "tests/test_foo.py", "def test_foo():\n    assert True\n", "add tests late")

    result = _run_tdd_gate(repo)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert f"FAIL tdd-first-commit: {ticket_id} first commit lacks test files" in output


def test_tdd_first_commit_does_not_skip_mixed_devos_and_code_commit(tmp_path: Path) -> None:
    ticket_id = "T-TDD-FIRST-MIXED-VIOLATION"
    repo = _make_repo(tmp_path, ticket_id)

    _write(
        repo / "devos" / "tasks" / "QUEUE.yaml",
        (repo / "devos" / "tasks" / "QUEUE.yaml").read_text(encoding="utf-8")
        + "  _transition_reason: filed with code\n",
    )
    _write(repo / "apps" / "api" / "foo.py", "print('impl mixed with devos')\n")
    _git(repo, "add", "devos/tasks/QUEUE.yaml", "apps/api/foo.py")
    _git(repo, "commit", "-qm", f"{ticket_id} mixed commit")

    result = _run_tdd_gate(repo)
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert f"FAIL tdd-first-commit: {ticket_id} first commit lacks test files" in output

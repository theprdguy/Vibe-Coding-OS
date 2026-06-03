from __future__ import annotations

import subprocess
from pathlib import Path

from server.dispatcher import CLAUDE_P_DEFAULT_ARGS, Dispatcher


def _init_repo(tmp_path: Path) -> str:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _dispatcher(root: Path) -> Dispatcher:
    return Dispatcher(
        config={"gates": {"agent_review": {"timeout": 5}}},
        paths={"root": root, "logs": root / "logs", "queue": root / "QUEUE.yaml"},
    )


def _run_review_and_capture_prompt(
    dispatcher: Dispatcher,
    ticket: dict,
    snapshot: str,
    monkeypatch,
) -> str:
    original_run = subprocess.run
    prompts: list[str] = []

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "git":
            return original_run(cmd, **kwargs)
        assert cmd == CLAUDE_P_DEFAULT_ARGS
        prompts.append(kwargs["input"])
        return subprocess.CompletedProcess(cmd, 0, stdout="PASS: scoped diff visible", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    passed, message = dispatcher._run_agent_review(ticket, snapshot)

    assert passed is True
    assert message == "PASS: scoped diff visible"
    assert len(prompts) == 1
    return prompts[0]


def test_agent_review_diff_includes_untracked_new_ticket_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _init_repo(tmp_path)
    new_file = tmp_path / "tests" / "test_new_feature.py"
    new_file.parent.mkdir()
    new_file.write_text(
        'def test_new_review_gate():\n    assert "untracked" == "untracked"\n',
        encoding="utf-8",
    )
    (tmp_path / "outside_secret.txt").write_text("SECRET_OUTSIDE_SCOPE\n", encoding="utf-8")

    prompt = _run_review_and_capture_prompt(
        _dispatcher(tmp_path),
        {
            "id": "T-REVIEW-UNTRACKED",
            "files": ["NEW: tests/test_new_feature.py"],
            "dod": ["Reviewer must see new test file contents."],
        },
        snapshot,
        monkeypatch,
    )

    assert "diff --git a/tests/test_new_feature.py b/tests/test_new_feature.py" in prompt
    assert "new file mode" in prompt
    assert "+def test_new_review_gate():" in prompt
    assert '+    assert "untracked" == "untracked"' in prompt
    assert "SECRET_OUTSIDE_SCOPE" not in prompt


def test_agent_review_diff_preserves_tracked_file_diff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _init_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("after\n", encoding="utf-8")

    prompt = _run_review_and_capture_prompt(
        _dispatcher(tmp_path),
        {
            "id": "T-REVIEW-TRACKED",
            "files": ["tracked.txt"],
            "dod": ["Reviewer must see tracked file diff."],
        },
        snapshot,
        monkeypatch,
    )

    assert "diff --git a/tracked.txt b/tracked.txt" in prompt
    assert "-before" in prompt
    assert "+after" in prompt

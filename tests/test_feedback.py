import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.feedback import FeedbackError, append_feedback, count_feedback

REPO = Path(__file__).resolve().parent.parent
BIN_OS3 = REPO / "bin" / "deos"


def test_append_creates_inbox_and_entry(tmp_path):
    host = tmp_path / "dev-os"
    inbox = append_feedback(host, "gate timeout too short", origin="meation")
    assert inbox == host / "devos" / "os-feedback" / "INBOX.md"
    body = inbox.read_text(encoding="utf-8")
    assert "gate timeout too short" in body
    assert "[meation]" in body
    assert count_feedback(host) == 1


def test_append_accumulates(tmp_path):
    host = tmp_path / "dev-os"
    append_feedback(host, "first")
    append_feedback(host, "second")
    assert count_feedback(host) == 2


def test_empty_feedback_rejected(tmp_path):
    host = tmp_path / "dev-os"
    with pytest.raises(FeedbackError):
        append_feedback(host, "   ")


def test_count_no_inbox_is_zero(tmp_path):
    assert count_feedback(tmp_path / "dev-os") == 0


def test_feedback_cli_e2e_writes_host_inbox(tmp_path):
    # feedback recorded to HOST inbox regardless of cwd
    host = tmp_path / "dev-os"
    (host / "devos").mkdir(parents=True)
    (host / "deos.yaml").write_text(
        (REPO / "deos.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    env = {**os.environ, "PYTHONPATH": str(REPO), "OS3_HOST_ROOT": str(host)}
    r = subprocess.run(
        [sys.executable, str(BIN_OS3), "feedback", "pr-check timeout insufficient"],
        cwd=str(workdir), env=env, capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    inbox = host / "devos" / "os-feedback" / "INBOX.md"
    assert inbox.is_file()
    assert "pr-check timeout insufficient" in inbox.read_text(encoding="utf-8")

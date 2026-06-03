"""Regression for T-OS3-INCIDENT-DISPATCHER-RESET (2026-05-16):

The reviewer sub-agent has Bash in its tools allowlist for read-only verification
(`git diff`, `git show`, `git log`). But during the 2026-05-16 incident the reviewer
ran `git stash --keep-index --include-untracked -u` to compare against HEAD, which
recorded a `reset: moving to HEAD` reflog entry and contributed to the wipeout of
PILOT-02/WAVE-1/WAVE-2 dispatcher.py work.

These tests assert that `.claude/agents/reviewer.md` keeps the forbidden-command
list and the explanatory citation, so the agent definition cannot silently drift
back to permissive guidance.
"""
from pathlib import Path

REVIEWER_AGENT = (
    Path(__file__).resolve().parent.parent / ".claude" / "agents" / "reviewer.md"
)

FORBIDDEN_TOKENS = [
    "git stash",
    "git reset --hard",
    "git checkout HEAD --",
    "git clean -fd",
]


def test_reviewer_agent_file_exists() -> None:
    assert REVIEWER_AGENT.exists(), f"missing {REVIEWER_AGENT}"


def test_reviewer_md_contains_forbidden_bash_section() -> None:
    text = REVIEWER_AGENT.read_text(encoding="utf-8")
    assert "## 금지 명령 (FORBIDDEN BASH)" in text, (
        "reviewer.md must declare a FORBIDDEN BASH section so reviewer subagent "
        "knows git stash / reset --hard / clean -fd are banned even though Bash "
        "is in the tools allowlist."
    )


def test_reviewer_md_lists_each_forbidden_command() -> None:
    text = REVIEWER_AGENT.read_text(encoding="utf-8")
    for token in FORBIDDEN_TOKENS:
        assert token in text, (
            f"reviewer.md FORBIDDEN BASH section is missing literal token "
            f"`{token}`; this is the 2026-05-16 incident regression marker."
        )


def test_reviewer_md_cites_incident_ticket() -> None:
    text = REVIEWER_AGENT.read_text(encoding="utf-8")
    assert "T-OS3-INCIDENT-DISPATCHER-RESET" in text or "2026-05-16 incident" in text, (
        "reviewer.md FORBIDDEN BASH section must cite T-OS3-INCIDENT-DISPATCHER-RESET "
        "or '2026-05-16 incident' so future readers find the forensic context."
    )

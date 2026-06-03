from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SANCTIONED_BASELINE_SCRIPT = "scripts/baseline-test.sh"
SANCTIONED_BASELINE_REFERENCE_FILES = [
    PROJECT_ROOT / ".claude" / "agents" / "reviewer.md",
    PROJECT_ROOT / ".claude" / "CLAUDE.md",
]

FORBIDDING_WORDS = [
    "금지",
    "forbidden",
    "do not",
    "never",
    "MUST NOT",
    "금지된다",
]


def _guidance_files() -> list[Path]:
    files = [
        PROJECT_ROOT / ".claude" / "CLAUDE.md",
        PROJECT_ROOT / "devos" / "AI.md",
        PROJECT_ROOT / "devos" / "AI-core.md",
    ]
    files.extend((PROJECT_ROOT / ".claude" / "agents").glob("*.md"))
    files.extend((PROJECT_ROOT / "devos" / "prompts" / "claude").glob("*.md"))
    return sorted(set(files))


def _is_forbidding_context(window: str) -> bool:
    folded = window.casefold()
    return any(word.casefold() in folded for word in FORBIDDING_WORDS)


def _forbidding_code_block_spans(text: str) -> list[range]:
    spans: list[range] = []
    in_code_block = False
    code_block_start = 0
    after_forbidding_heading = False
    current_section_is_forbidding = False
    offset = 0

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("#"):
            current_section_is_forbidding = _is_forbidding_context(stripped)

        if stripped.startswith("```"):
            if in_code_block:
                if after_forbidding_heading:
                    spans.append(range(code_block_start, offset + len(line)))
                in_code_block = False
                after_forbidding_heading = False
            else:
                in_code_block = True
                code_block_start = offset
                after_forbidding_heading = current_section_is_forbidding

        offset += len(line)

    return spans


def test_dispatch_guidance_files_exist() -> None:
    files = _guidance_files()
    assert PROJECT_ROOT / ".claude" / "CLAUDE.md" in files
    assert PROJECT_ROOT / "devos" / "AI.md" in files
    assert PROJECT_ROOT / "devos" / "AI-core.md" in files
    assert any(path.match("*.md") for path in (PROJECT_ROOT / ".claude" / "agents").iterdir())
    assert any(path.match("*.md") for path in (PROJECT_ROOT / "devos" / "prompts" / "claude").iterdir())


def test_sanctioned_baseline_script_reference_stays_in_core_guidance() -> None:
    failures: list[str] = []

    for path in SANCTIONED_BASELINE_REFERENCE_FILES:
        text = path.read_text(encoding="utf-8")
        if SANCTIONED_BASELINE_SCRIPT not in text:
            relative = path.relative_to(PROJECT_ROOT)
            failures.append(
                f"{relative} must contain literal {SANCTIONED_BASELINE_SCRIPT!r} "
                "so agents keep the stash-free baseline-test path"
            )

    assert not failures, "\n".join(failures)


def test_no_dispatch_guidance_recommends_git_stash_for_baseline_comparison() -> None:
    failures: list[str] = []

    for path in _guidance_files():
        text = path.read_text(encoding="utf-8")
        code_block_spans = _forbidding_code_block_spans(text)

        for match in re.finditer(r"git stash", text):
            start = match.start()
            window = text[max(0, start - 200) : min(len(text), match.end() + 200)]
            if _is_forbidding_context(window):
                continue
            if any(start in span for span in code_block_spans):
                continue

            relative = path.relative_to(PROJECT_ROOT)
            line = text.count("\n", 0, start) + 1
            failures.append(
                f"{relative}:{line}: bare `git stash` is not in forbidding context"
            )

    assert not failures, "\n".join(failures)

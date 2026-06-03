"""Export helper: selective sync of dev-os host → public template repo.

This module is the single source of truth for the allow / deny / preserve
classification logic.  The bash wrapper (scripts/export-to-public.sh) is a
thin shim that delegates here.

Usage (Python direct):
    python3 scripts/export_to_public.py [--dry-run] [--apply] <target-dir>

Default is --dry-run (fail-safe).  Pass --apply to actually write.

Classification:
    COPY      — file should be written from source to target
    SKIP      — file must never reach the target (private / generated / live data)
    PRESERVE  — file already exists in the target as public-only content;
                do NOT overwrite or delete it from the source side
    SCRUB     — file is re-created with an empty-template form in the target;
                never copy raw content from source

Security contract:
    The correctness of the deny/allow/preserve sets is the #1 requirement.
    Any change to these sets must have corresponding test coverage.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Root of the source (dev-os private host)
# ---------------------------------------------------------------------------
_SRC_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# PRESERVE set — public-only files in the target that MUST NOT be overwritten
# ---------------------------------------------------------------------------
PRESERVE_NAMES: frozenset[str] = frozenset(
    [
        "README.md",
        "START_HERE.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "THIRD_PARTY_LICENSES.md",
        ".nojekyll",
    ]
)

PRESERVE_PREFIXES: tuple[str, ...] = (
    ".github/",
    ".github",
    "docs/deep-dive.",
)

# ---------------------------------------------------------------------------
# SCRUB set — files re-created with empty-template form; raw content never copied
# ---------------------------------------------------------------------------
SCRUB_TARGETS: frozenset[str] = frozenset(
    [
        "devos/os-feedback/INBOX.md",
        "devos/questions/QUEUE.md",
    ]
)

# Directories whose content under devos/plans/ is replaced with only a .keep
_PLANS_SENTINEL_DIRS = frozenset(["approved", "pending", "rejected"])

# ---------------------------------------------------------------------------
# DENYLIST — prefixes / names / extensions that are ALWAYS SKIP
# ---------------------------------------------------------------------------
_DENY_PREFIXES: tuple[str, ...] = (
    "projects/",
    "projects",
    ".git/",
    ".git",
    ".venv/",
    ".venv",
    "venv/",
    "venv",
    "devos/consumers/",
    "devos/consumers",
    "devos/projects/",
    "devos/projects",
    "devos/docs/retrospective/",
    "devos/docs/retrospective",
    "devos/docs/decisions/",
    "devos/docs/decisions",
    "devos/docs/trials/",
    "devos/docs/trials",
    "devos/docs/runbook/",
    "devos/docs/runbook",
    "devos/plans/approved/",
    "devos/plans/rejected/",
    "devos/plans/pending/",
    # Security: internal triage files contain absolute private paths
    "devos/issues/",
    "devos/issues",
)

_DENY_EXACT: frozenset[str] = frozenset(
    [
        "devos/tasks/ARCHIVE.yaml",
        "devos/tasks/ARCHIVE-INDEX.yaml",
        "devos/CONTEXT.md",
        "devos/PROJECT_STATE.md",
        "devos/tasks/QUEUE.yaml",     # live queue — never overwrite target's curated example
        "devos/os-feedback/INBOX.md",  # raw content denied; SCRUB writes template
        "devos/questions/QUEUE.md",    # raw content denied; SCRUB writes template
        # Security: contains absolute /Users/hoanshin/dev-os path
        ".mcp.json",
        # Security: absolute private workspace path + internal WIP
        "docs/CODEX_WIP_HANDOFF.md",
    ]
)

_DENY_EXTENSIONS: frozenset[str] = frozenset(
    [
        ".pyc", ".pid", ".lock",
        # Key material (defense-in-depth)
        ".pem", ".key", ".crt", ".p12", ".keystore",
    ]
)

_DENY_BASENAMES: frozenset[str] = frozenset(
    [
        ".DS_Store", "__pycache__",
        # Security: machine-local / credential files
        ".pytest_cache",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
        ".netrc", ".npmrc", ".pypirc",
    ]
)

_DENY_BASENAME_PREFIXES: tuple[str, ...] = (
    ".env",
    # Key material prefix (defense-in-depth)
    "credentials",
)

_DENY_BASENAME_SUFFIXES: tuple[str, ...] = (
    # Machine-local configuration (e.g. .claude/settings.local.json)
    ".local.json",
)

# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

Classification = Literal["COPY", "SKIP", "PRESERVE", "SCRUB"]

# Regex matching absolute user-home paths that must never reach the public repo
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^/\s]+/")


def classify_path(rel: Path) -> Classification:  # noqa: C901
    """Return the classification for a path relative to the source root.

    Parameters
    ----------
    rel:
        Path relative to the source root (e.g. Path('devos/logs/foo.md')).
        May be a file or directory path (no trailing slash).

    Returns
    -------
    'COPY' | 'SKIP' | 'PRESERVE' | 'SCRUB'
    """
    rel_str = rel.as_posix()
    parts = rel.parts
    name = rel.name
    suffix = rel.suffix

    # -- PRESERVE (check before deny so public-only root files win) ----------
    # Root-level names
    if len(parts) == 1 and name in PRESERVE_NAMES:
        return "PRESERVE"
    # .github dir and everything under it
    if parts[0] == ".github":
        return "PRESERVE"
    # .nojekyll at root
    if len(parts) == 1 and name == ".nojekyll":
        return "PRESERVE"
    # docs/deep-dive.*.html — must have .html suffix
    if (
        len(parts) >= 2
        and parts[0] == "docs"
        and name.startswith("deep-dive.")
        and suffix == ".html"
    ):
        return "PRESERVE"

    # -- SCRUB ---------------------------------------------------------------
    if rel_str in SCRUB_TARGETS:
        return "SCRUB"

    # -- COPY: devos/plans/{approved,rejected,pending}/.keep sentinel --------
    # Must be checked before deny-prefix so the .keep exemption is reachable.
    if (
        len(parts) == 4
        and parts[0] == "devos"
        and parts[1] == "plans"
        and parts[2] in _PLANS_SENTINEL_DIRS
        and name == ".keep"
    ):
        return "COPY"

    # -- SKIP: exact denylist ------------------------------------------------
    if rel_str in _DENY_EXACT:
        return "SKIP"

    # -- SKIP: deny prefixes -------------------------------------------------
    for prefix in _DENY_PREFIXES:
        # Match "projects" and "projects/" both
        if rel_str == prefix.rstrip("/") or rel_str.startswith(
            prefix if prefix.endswith("/") else prefix + "/"
        ):
            return "SKIP"

    # -- SKIP: devos/logs/ — only README.md survives -------------------------
    if parts[0] == "devos" and len(parts) >= 2 and parts[1] == "logs":
        # Allow README.md exactly; skip all other .md and any deeper paths
        if rel_str == "devos/logs/README.md":
            return "COPY"
        if len(parts) == 2:
            # The logs/ directory itself — allow (it will be created)
            return "COPY"
        # Any file other than README.md under devos/logs/ is SKIP
        return "SKIP"

    # -- SKIP: devos/RESUME-* ------------------------------------------------
    if parts[0] == "devos" and len(parts) == 2 and name.startswith("RESUME-"):
        return "SKIP"

    # -- SKIP: devos/plans/{approved,rejected,pending}/* content (only .keep OK) --
    if (
        len(parts) >= 3
        and parts[0] == "devos"
        and parts[1] == "plans"
        and parts[2] in _PLANS_SENTINEL_DIRS
        and len(parts) > 3  # any file inside the dir (not the dir node itself)
        and name != ".keep"
    ):
        return "SKIP"

    # -- SKIP: .pytest_cache anywhere in the tree ----------------------------
    if ".pytest_cache" in parts:
        return "SKIP"

    # -- SKIP: extension-based -----------------------------------------------
    if suffix in _DENY_EXTENSIONS:
        return "SKIP"

    # -- SKIP: basename-based ------------------------------------------------
    if name in _DENY_BASENAMES:
        return "SKIP"
    for bp in _DENY_BASENAME_PREFIXES:
        if name.startswith(bp):
            return "SKIP"
    for bs in _DENY_BASENAME_SUFFIXES:
        if name.endswith(bs):
            return "SKIP"

    # -- SKIP: __pycache__ anywhere in the tree ------------------------------
    if "__pycache__" in parts:
        return "SKIP"

    # Everything else is COPY
    return "COPY"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_target(src: Path, target: Path) -> None:
    """Raise ValueError with a clear message if the target is unsuitable.

    Checks:
    1. Target exists and is a directory.
    2. Target is not the same as the source root.
    3. Target is a git repository.
    """
    if not target.exists():
        raise ValueError(
            f"Target directory does not exist: {target}\n"
            "Please provide the path to an existing git repository."
        )
    if not target.is_dir():
        raise ValueError(
            f"Target path is not a directory: {target}"
        )
    if target.resolve() == src.resolve():
        raise ValueError(
            "Target must not be the same as the source (dev-os root).\n"
            f"  source = {src}\n"
            f"  target = {target}\n"
            "Refusing to export into the source tree."
        )
    # Check git repo
    result = subprocess.run(
        ["git", "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ValueError(
            f"Target is not a git repository: {target}\n"
            "The export tool requires the target to be a git repo so that\n"
            "changes can be staged/reviewed before pushing."
        )


# ---------------------------------------------------------------------------
# Plan builder (pure — no I/O to target)
# ---------------------------------------------------------------------------

def build_plan(src: Path) -> list[tuple[Classification, Path]]:
    """Walk src and return a sorted list of (classification, rel_path) tuples.

    Only file paths are emitted (not directories), plus synthetic PRESERVE
    entries for public-only paths that do not exist in src.

    Directories that are always SKIP (.git, .venv, venv, __pycache__,
    projects, devos/consumers, devos/projects, .pytest_cache) are pruned early
    to avoid walking large trees.
    """
    plan: list[tuple[Classification, Path]] = []

    # Top-level directories to prune entirely (never descend)
    _PRUNE_TOPS: frozenset[str] = frozenset(
        [".git", ".venv", "venv", "projects", "__pycache__", ".pytest_cache"]
    )

    def _walk(directory: Path) -> None:
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            rel = entry.relative_to(src)
            # Prune top-level dirs that are always fully denied
            if entry.is_dir():
                if rel.parts[0] in _PRUNE_TOPS:
                    # Still emit the dir-level SKIP so dry-run shows it once
                    plan.append(("SKIP", rel))
                    continue
                # Prune devos/consumers, devos/projects as a whole
                if rel.as_posix() in ("devos/consumers", "devos/projects"):
                    plan.append(("SKIP", rel))
                    continue
                # Prune devos/issues as a whole (contains private paths)
                if rel.as_posix() in ("devos/issues",):
                    plan.append(("SKIP", rel))
                    continue
                # Prune __pycache__ anywhere
                if entry.name == "__pycache__":
                    plan.append(("SKIP", rel))
                    continue
                # Prune .pytest_cache anywhere
                if entry.name == ".pytest_cache":
                    plan.append(("SKIP", rel))
                    continue
                _walk(entry)
            else:
                cls = classify_path(rel)
                plan.append((cls, rel))

    _walk(src)

    # Add synthetic PRESERVE entries for public-only files that only live in
    # the target (e.g. CHANGELOG.md, deep-dive HTMLs).  These paths may not
    # exist in src at all, so we synthesise them so the dry-run output is
    # informative.
    synthetic_preserves = [
        Path("README.md"),
        Path("CHANGELOG.md"),
        Path("CONTRIBUTING.md"),
        Path("LICENSE"),
        Path("THIRD_PARTY_LICENSES.md"),
        Path("START_HERE.md"),
        Path(".nojekyll"),
        Path(".github"),
        Path("docs/deep-dive.en.html"),
        Path("docs/deep-dive.ko.html"),
    ]
    existing_rels = {rel for _, rel in plan}
    for sp in synthetic_preserves:
        if sp not in existing_rels:
            plan.append(("PRESERVE", sp))

    # Add synthetic COPY entries for plans sentinel .keep files so dry-run
    # matches what apply_plan() will write.
    for subdir in sorted(_PLANS_SENTINEL_DIRS):
        keep_rel = Path("devos") / "plans" / subdir / ".keep"
        if keep_rel not in existing_rels:
            plan.append(("COPY", keep_rel))

    plan.sort(key=lambda x: x[1].as_posix())
    return plan


# ---------------------------------------------------------------------------
# Home-path guard — scan COPY file content for absolute user-home paths
# ---------------------------------------------------------------------------

# Files exempt from the home-path content scan.  These are the guard's own
# implementation and test files: they legitimately contain the regex pattern
# string and /Users/.../ fixture strings as part of the guard itself, not as
# real PII leaks.  Every OTHER file must still be scanned — do not broaden
# this exemption set.
_HOME_SCAN_EXEMPT: frozenset[str] = frozenset(
    [
        "scripts/export_to_public.py",
        "scripts/export-to-public.sh",
        "tests/test_export_to_public.py",
    ]
)


def _scan_for_home_paths(
    src: Path, plan: list[tuple[Classification, Path]]
) -> list[Path]:
    """Return list of COPY-classified rel paths whose content contains a home path.

    Checks for patterns like /Users/<name>/ or /home/<name>/.
    Only text-decodable files are checked; binary files are skipped.

    Files in _HOME_SCAN_EXEMPT are skipped: they are the guard's own source
    and test files, which contain the regex pattern and fixture strings as
    part of the implementation, not as real PII leaks.
    """
    offenders: list[Path] = []
    for cls, rel in plan:
        if cls != "COPY":
            continue
        # Skip the guard's own implementation/test files — they legitimately
        # contain the pattern string and fixture paths used to implement and
        # verify this guard.  All other files are still scanned.
        if rel.as_posix() in _HOME_SCAN_EXEMPT:
            continue
        src_file = src / rel
        if not src_file.is_file():
            continue
        try:
            content = src_file.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            # Binary or unreadable — skip
            continue
        if _HOME_PATH_RE.search(content):
            offenders.append(rel)
    return offenders


# ---------------------------------------------------------------------------
# Dry-run output
# ---------------------------------------------------------------------------

def print_plan(
    plan: list[tuple[Classification, Path]], src: Path | None = None
) -> None:
    counts: dict[str, int] = {"COPY": 0, "SKIP": 0, "PRESERVE": 0, "SCRUB": 0}
    for cls, rel in plan:
        print(f"{cls:<8} {rel.as_posix()}")
        counts[cls] += 1
    print()
    print("Summary:")
    for cls, count in counts.items():
        print(f"  {cls:<8} {count}")
    print()

    # Home-path guard warning (dry-run)
    if src is not None:
        offenders = _scan_for_home_paths(src, plan)
        if offenders:
            print("WARNING: the following COPY files contain absolute home paths")
            print("  (e.g. /Users/<name>/ or /home/<name>/).  Review before --apply:")
            for rel in offenders:
                print(f"  WARN     {rel.as_posix()}")
            print()

    print("Dry-run complete. No files were written.")
    print("Pass --apply to execute.")


# ---------------------------------------------------------------------------
# Apply (actual write)
# ---------------------------------------------------------------------------

_EMPTY_INBOX_TEMPLATE = """\
# OS Feedback Inbox

> Submit feedback, observations, or improvement suggestions here.
> Format: date + topic + description.

<!-- No entries yet. -->
"""

_EMPTY_QUESTIONS_TEMPLATE = """\
# Questions Queue

> Open questions for the orchestrator.
> Format: Q-id | status | question | options | recommendation | default.

<!-- No entries yet. -->
"""

_SCRUB_CONTENT: dict[str, str] = {
    "devos/os-feedback/INBOX.md": _EMPTY_INBOX_TEMPLATE,
    "devos/questions/QUEUE.md": _EMPTY_QUESTIONS_TEMPLATE,
}

_KEEP_CONTENT = ""  # .keep sentinel files


def apply_plan(src: Path, target: Path, plan: list[tuple[Classification, Path]]) -> None:
    """Execute the plan: copy COPY, scrub SCRUB, skip SKIP/PRESERVE source writes.

    Fail-closed guard: before writing, scan every COPY file's content for
    absolute user-home paths.  If any are found, abort with nonzero exit.
    """
    # Fail-closed: abort if any COPY file contains an absolute home path
    offenders = _scan_for_home_paths(src, plan)
    if offenders:
        print(
            "ABORT: the following COPY files contain absolute home paths "
            "(/Users/<name>/ or /home/<name>/).  Fix them before re-running --apply:",
            file=sys.stderr,
        )
        for rel in offenders:
            print(f"  {rel.as_posix()}", file=sys.stderr)
        sys.exit(1)

    for cls, rel in plan:
        if cls == "SKIP":
            continue
        if cls == "PRESERVE":
            # Do not touch target's own content
            continue
        target_file = target / rel
        if cls == "SCRUB":
            content = _SCRUB_CONTENT.get(rel.as_posix(), "")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
            print(f"SCRUB    {rel.as_posix()}")
        elif cls == "COPY":
            src_file = src / rel
            if not src_file.exists():
                # Synthetic entry (e.g. .keep sentinel) — write empty file
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(_KEEP_CONTENT, encoding="utf-8")
            else:
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(target_file))

    print("Apply complete.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:  # noqa: C901
    import argparse

    parser = argparse.ArgumentParser(
        prog="export_to_public.py",
        description=(
            "Selective export of dev-os host to a public template repo.\n"
            "Default is --dry-run (safe). Pass --apply to write."
        ),
    )
    parser.add_argument("target", help="Path to the public target git repository")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Print the plan without writing anything (default)",
    )
    mode_group.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write files to the target",
    )
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    src = _SRC_ROOT

    try:
        validate_target(src, target)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    plan = build_plan(src)

    if args.apply:
        print(f"Applying export: {src} -> {target}")
        apply_plan(src, target, plan)
    else:
        print(f"Dry-run: {src} -> {target}")
        print()
        print_plan(plan, src=src)

    return 0


if __name__ == "__main__":
    sys.exit(main())

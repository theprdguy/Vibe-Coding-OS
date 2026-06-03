"""Tests for scripts/export_to_public.py — deny/allow/preserve set correctness.

Design:
- Pure-function tests (no shell out) for the allow/deny/preserve classification.
- Integration smoke test: dry-run against a tmp git repo checks the output plan.
- Refusal-guard tests: non-git target, target==source root.
- Apply tests: --apply writes COPY, SCRUBs templates, does not overwrite PRESERVE,
  is idempotent, and does not git-commit.
- Security tests: deny-set coverage for all security fixes; fail-closed home-path guard.

All path judgements go through export_to_public.classify_path() which is the
single source of truth for what gets COPY / SKIP / PRESERVE.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Add repo root to path so we can import scripts/export_to_public.py as a module.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import export_to_public as exp  # noqa: E402  (imported after sys.path tweak)


# ---------------------------------------------------------------------------
# Helper: classify a relative path string
# ---------------------------------------------------------------------------

def _classify(rel: str) -> str:
    """Return 'COPY', 'SKIP', or 'PRESERVE' for a relative path string."""
    return exp.classify_path(Path(rel))


# ---------------------------------------------------------------------------
# DENYLIST — these must NEVER be copied
# ---------------------------------------------------------------------------

class TestDenylist:
    def test_projects_dir_is_denied(self):
        assert _classify("projects/meation/server/main.py") == "SKIP"

    def test_projects_root_itself_is_denied(self):
        assert _classify("projects") == "SKIP"

    def test_devos_log_md_is_denied(self):
        # .md files under devos/logs/ must be SKIP
        assert _classify("devos/logs/2026-05-30-builder-T-BOLLARD.md") == "SKIP"

    def test_devos_logs_readme_is_allowed(self):
        # devos/logs/README.md is the sole exception
        assert _classify("devos/logs/README.md") == "COPY"

    def test_archive_yaml_is_denied(self):
        assert _classify("devos/tasks/ARCHIVE.yaml") == "SKIP"

    def test_archive_index_yaml_is_denied(self):
        assert _classify("devos/tasks/ARCHIVE-INDEX.yaml") == "SKIP"

    def test_resume_files_are_denied(self):
        assert _classify("devos/RESUME-2026-05-28-ssot-core.md") == "SKIP"
        assert _classify("devos/RESUME-anything.md") == "SKIP"

    def test_consumers_is_denied(self):
        assert _classify("devos/consumers/basket.md") == "SKIP"
        assert _classify("devos/consumers") == "SKIP"

    def test_devos_projects_is_denied(self):
        # devos/projects/ holds host registry files — not public
        assert _classify("devos/projects/basket.md") == "SKIP"
        assert _classify("devos/projects/bollard.md") == "SKIP"
        assert _classify("devos/projects") == "SKIP"

    def test_context_md_is_denied(self):
        assert _classify("devos/CONTEXT.md") == "SKIP"

    def test_project_state_md_is_denied(self):
        assert _classify("devos/PROJECT_STATE.md") == "SKIP"

    def test_retrospective_is_denied(self):
        assert _classify("devos/docs/retrospective/2026-04-30-meta.md") == "SKIP"
        assert _classify("devos/docs/retrospective") == "SKIP"

    def test_decisions_is_denied(self):
        assert _classify("devos/docs/decisions/2026-05-05-tbd-5.md") == "SKIP"
        assert _classify("devos/docs/decisions") == "SKIP"

    def test_trials_is_denied(self):
        assert _classify("devos/docs/trials/2026-05-14-mcp.md") == "SKIP"
        assert _classify("devos/docs/trials") == "SKIP"

    def test_runbook_is_denied(self):
        assert _classify("devos/docs/runbook/account-b-sunset.md") == "SKIP"
        assert _classify("devos/docs/runbook") == "SKIP"

    def test_git_dir_is_denied(self):
        assert _classify(".git/config") == "SKIP"
        assert _classify(".git") == "SKIP"

    def test_venv_is_denied(self):
        assert _classify(".venv/lib/python3.12/site-packages/x.py") == "SKIP"
        assert _classify("venv/bin/python") == "SKIP"

    def test_pycache_is_denied(self):
        assert _classify("server/__pycache__/foo.cpython-312.pyc") == "SKIP"
        assert _classify("__pycache__") == "SKIP"

    def test_pyc_is_denied(self):
        assert _classify("server/dispatcher.cpython-312.pyc") == "SKIP"

    def test_pid_is_denied(self):
        assert _classify("server.pid") == "SKIP"

    def test_lock_is_denied(self):
        assert _classify("package.lock") == "SKIP"

    def test_dotenv_is_denied(self):
        assert _classify(".env") == "SKIP"
        assert _classify(".env.local") == "SKIP"

    def test_ds_store_is_denied(self):
        assert _classify(".DS_Store") == "SKIP"

    def test_devos_plans_approved_content_is_denied(self):
        # Only .keep files survive; actual plan docs are denied
        assert _classify("devos/plans/approved/2026-05-05-osn.md") == "SKIP"

    def test_devos_plans_rejected_content_is_denied(self):
        assert _classify("devos/plans/rejected/some-plan.md") == "SKIP"

    def test_devos_plans_pending_content_is_denied(self):
        assert _classify("devos/plans/pending/draft.md") == "SKIP"

    def test_devos_tasks_queue_yaml_is_skipped(self):
        # Live QUEUE.yaml must not overwrite target's curated example
        assert _classify("devos/tasks/QUEUE.yaml") == "SKIP"

    def test_devos_os_feedback_inbox_is_scrubbed(self):
        # Real content must not leak; target gets an empty template (SCRUB, not raw COPY)
        assert _classify("devos/os-feedback/INBOX.md") == "SCRUB"

    def test_devos_questions_queue_is_scrubbed(self):
        # Real questions must not leak; target gets an empty template (SCRUB, not raw COPY)
        assert _classify("devos/questions/QUEUE.md") == "SCRUB"

    # -----------------------------------------------------------------------
    # Security deny-set tests (fixes 1-6)
    # -----------------------------------------------------------------------

    def test_mcp_json_is_denied(self):
        """Fix 1: .mcp.json contains absolute /Users/hoanshin/dev-os path."""
        assert _classify(".mcp.json") == "SKIP"

    def test_codex_wip_handoff_is_denied(self):
        """Fix 2: docs/CODEX_WIP_HANDOFF.md contains absolute private workspace path."""
        assert _classify("docs/CODEX_WIP_HANDOFF.md") == "SKIP"

    def test_devos_issues_dir_is_denied(self):
        """Fix 3: devos/issues/ contains private paths — deny as prefix."""
        assert _classify("devos/issues/x.md") == "SKIP"
        assert _classify("devos/issues") == "SKIP"
        assert _classify("devos/issues/sub/deep.md") == "SKIP"

    def test_pytest_cache_basename_is_denied(self):
        """Fix 4: .pytest_cache basename must be SKIP."""
        assert _classify(".pytest_cache") == "SKIP"

    def test_pytest_cache_contents_are_denied(self):
        """Fix 4: files inside .pytest_cache anywhere in the tree must be SKIP."""
        assert _classify(".pytest_cache/v/cache/lastfailed") == "SKIP"
        assert _classify("some/nested/.pytest_cache/x") == "SKIP"

    def test_local_json_is_denied(self):
        """Fix 5: any basename ending .local.json must be SKIP (machine-local by convention)."""
        assert _classify(".claude/settings.local.json") == "SKIP"
        assert _classify("foo.local.json") == "SKIP"
        assert _classify("config.local.json") == "SKIP"

    def test_pem_key_crt_are_denied(self):
        """Fix 6: key-material extensions must be SKIP."""
        assert _classify("server.pem") == "SKIP"
        assert _classify("private.key") == "SKIP"
        assert _classify("cert.crt") == "SKIP"
        assert _classify("bundle.p12") == "SKIP"
        assert _classify("app.keystore") == "SKIP"

    def test_ssh_key_basenames_are_denied(self):
        """Fix 6: well-known SSH/credential basenames must be SKIP."""
        assert _classify("id_rsa") == "SKIP"
        assert _classify("id_dsa") == "SKIP"
        assert _classify("id_ecdsa") == "SKIP"
        assert _classify("id_ed25519") == "SKIP"
        assert _classify(".netrc") == "SKIP"
        assert _classify(".npmrc") == "SKIP"
        assert _classify(".pypirc") == "SKIP"

    def test_credentials_prefix_is_denied(self):
        """Fix 6: any basename starting with 'credentials' must be SKIP."""
        assert _classify("credentials.json") == "SKIP"
        assert _classify("credentials-prod.yaml") == "SKIP"


# ---------------------------------------------------------------------------
# ALLOWLIST — these MUST be copied
# ---------------------------------------------------------------------------

class TestAllowlist:
    def test_server_package_is_allowed(self):
        assert _classify("server/__init__.py") == "COPY"
        assert _classify("server/dispatcher.py") == "COPY"

    def test_bin_deos_is_allowed(self):
        assert _classify("bin/deos") == "COPY"

    def test_scripts_dir_is_allowed(self):
        assert _classify("scripts/setup.sh") == "COPY"
        assert _classify("scripts/check-ticket-scope.sh") == "COPY"

    def test_packages_is_allowed(self):
        assert _classify("packages/shared/index.ts") == "COPY"

    def test_tests_dir_is_allowed(self):
        assert _classify("tests/test_dispatcher.py") == "COPY"

    def test_conftest_is_allowed(self):
        assert _classify("conftest.py") == "COPY"

    def test_pytest_ini_is_allowed(self):
        assert _classify("pytest.ini") == "COPY"

    def test_requirements_txt_is_allowed(self):
        assert _classify("requirements.txt") == "COPY"

    def test_dot_claude_agents_is_allowed(self):
        assert _classify(".claude/agents/builder.md") == "COPY"

    def test_dot_claude_hooks_is_allowed(self):
        assert _classify(".claude/hooks/pre-commit.sh") == "COPY"

    def test_dot_claude_settings_is_allowed(self):
        assert _classify(".claude/settings.json") == "COPY"

    def test_agents_md_is_allowed(self):
        assert _classify("AGENTS.md") == "COPY"

    def test_deos_yaml_is_allowed(self):
        assert _classify("deos.yaml") == "COPY"

    def test_plist_is_allowed(self):
        assert _classify("com.deos.server.plist") == "COPY"

    def test_devos_prompts_is_allowed(self):
        assert _classify("devos/prompts/claude/dispatch-orchestration.md") == "COPY"
        assert _classify("devos/prompts/common/scope-reduction-prohibition.md") == "COPY"

    def test_devos_agents_is_allowed(self):
        assert _classify("devos/agents/registry.yaml") == "COPY"

    def test_devos_templates_is_allowed(self):
        assert _classify("devos/templates/HANDOFF-template.md") == "COPY"

    def test_devos_gates_is_allowed(self):
        assert _classify("devos/gates/user-outcome-review.md") == "COPY"

    def test_devos_ai_md_is_allowed(self):
        assert _classify("devos/AI.md") == "COPY"

    def test_devos_ai_core_md_is_allowed(self):
        assert _classify("devos/AI-core.md") == "COPY"

    def test_devos_ethos_md_is_allowed(self):
        assert _classify("devos/ETHOS.md") == "COPY"

    def test_devos_version_txt_is_allowed(self):
        assert _classify("devos/VERSION.txt") == "COPY"

    def test_devos_dispatch_header_is_allowed(self):
        assert _classify("devos/dispatch-header.yaml") == "COPY"

    def test_devos_docs_non_denylist_is_allowed(self):
        # devos/docs/** is allowed except the specific denylist dirs
        assert _classify("devos/docs/BUILDER_GUIDE.md") == "COPY"
        assert _classify("devos/docs/AI.md") == "COPY"
        assert _classify("devos/docs/ARCHITECTURE.md") == "COPY"


# ---------------------------------------------------------------------------
# PRESERVE — must exist in target and not be overwritten or deleted
# ---------------------------------------------------------------------------

class TestPreserveList:
    def test_readme_is_preserved(self):
        assert _classify("README.md") == "PRESERVE"

    def test_start_here_is_preserved(self):
        assert _classify("START_HERE.md") == "PRESERVE"

    def test_changelog_is_preserved(self):
        assert _classify("CHANGELOG.md") == "PRESERVE"

    def test_contributing_is_preserved(self):
        assert _classify("CONTRIBUTING.md") == "PRESERVE"

    def test_license_is_preserved(self):
        assert _classify("LICENSE") == "PRESERVE"

    def test_third_party_licenses_is_preserved(self):
        assert _classify("THIRD_PARTY_LICENSES.md") == "PRESERVE"

    def test_deep_dive_html_is_preserved(self):
        assert _classify("docs/deep-dive.en.html") == "PRESERVE"
        assert _classify("docs/deep-dive.ko.html") == "PRESERVE"

    def test_deep_dive_non_html_is_not_preserved(self):
        """Fix 12: docs/deep-dive.* without .html suffix must NOT be PRESERVE."""
        # A .md file with deep-dive prefix should be COPY, not PRESERVE
        result = _classify("docs/deep-dive.en.md")
        assert result != "PRESERVE", (
            f"docs/deep-dive.en.md should not be PRESERVE (got {result}); "
            "only .html suffix is anchor for deep-dive preserve"
        )

    def test_github_dir_is_preserved(self):
        assert _classify(".github/workflows/ci.yml") == "PRESERVE"
        assert _classify(".github") == "PRESERVE"

    def test_nojekyll_is_preserved(self):
        assert _classify(".nojekyll") == "PRESERVE"


# ---------------------------------------------------------------------------
# Scrub targets — content written by export tool, not copied
# ---------------------------------------------------------------------------

class TestScrubTargets:
    def test_scrub_targets_are_recognised(self):
        scrubs = exp.SCRUB_TARGETS
        assert "devos/os-feedback/INBOX.md" in scrubs
        assert "devos/questions/QUEUE.md" in scrubs


# ---------------------------------------------------------------------------
# Refusal guards — validate_target() raises ValueError in these cases
# ---------------------------------------------------------------------------

class TestRefusalGuards:
    def test_refuses_when_target_is_source_root(self, tmp_path):
        """Target must not equal the source (dev-os) root."""
        src = Path(_REPO_ROOT)
        with pytest.raises((ValueError, SystemExit)):
            exp.validate_target(src, src)

    def test_refuses_when_target_is_not_git_repo(self, tmp_path):
        """Target directory must be a git repository."""
        # tmp_path is a plain directory, not a git repo
        with pytest.raises((ValueError, SystemExit)):
            exp.validate_target(_REPO_ROOT, tmp_path)

    def test_refuses_when_target_does_not_exist(self, tmp_path):
        """Target must exist."""
        missing = tmp_path / "no-such-dir"
        # Fix 13: only expect ValueError or SystemExit (not FileNotFoundError)
        with pytest.raises((ValueError, SystemExit)):
            exp.validate_target(_REPO_ROOT, missing)


# ---------------------------------------------------------------------------
# Integration: dry-run against a tmp git repo
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_public_repo(tmp_path):
    """Create a minimal git repo that mimics the public target structure."""
    repo = tmp_path / "vibe-coding-os"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    # Add public-only files that must be preserved
    (repo / "README.md").write_text("# Public README\n")
    (repo / "CHANGELOG.md").write_text("# Changelog\n")
    (repo / "LICENSE").write_text("MIT\n")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "deep-dive.en.html").write_text("<html/>\n")
    github = repo / ".github"
    github.mkdir()
    (github / "workflows").mkdir()
    (github / "workflows" / "ci.yml").write_text("name: CI\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "."],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init",
         "--author", "Test <t@t.com>"],
        check=True, capture_output=True,
    )
    return repo


class TestDryRunIntegration:
    def test_dry_run_produces_no_projects_copy(self, fake_public_repo, tmp_path):
        """Dry-run plan must not include any projects/ path in the COPY set."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        # Neither root projects/ nor devos/projects/ must appear in COPY lines
        copy_lines = [l for l in output.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            # Strip the "COPY     " prefix and get the path
            path_part = line.split(None, 1)[-1].strip()
            assert not path_part.startswith("projects/"), (
                f"projects/ leaked into COPY: {line}"
            )
            assert not path_part.startswith("devos/projects/"), (
                f"devos/projects/ leaked into COPY: {line}"
            )

    def test_dry_run_no_archive_yaml_in_copy(self, fake_public_repo):
        """ARCHIVE.yaml must never appear in the COPY set."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        copy_lines = [l for l in output.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            assert "ARCHIVE.yaml" not in line, f"ARCHIVE.yaml leaked into COPY: {line}"

    def test_dry_run_no_log_md_in_copy(self, fake_public_repo):
        """devos/logs/*.md (except README) must not appear in COPY set."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        copy_lines = [l for l in output.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            # Only README.md is allowed under devos/logs/
            if "devos/logs/" in line and "devos/logs/README.md" not in line:
                assert False, f"devos/logs/*.md leaked into COPY: {line}"

    def test_dry_run_shows_preserve_for_readme(self, fake_public_repo):
        """README.md and CHANGELOG.md must appear as PRESERVE in dry-run output."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        preserve_lines = [l for l in output.splitlines() if l.startswith("PRESERVE")]
        targets = {l.split()[-1] for l in preserve_lines}
        assert any("README.md" in t for t in targets), (
            f"README.md not in PRESERVE lines. preserve_lines={preserve_lines}"
        )
        assert any("CHANGELOG.md" in t for t in targets), (
            f"CHANGELOG.md not in PRESERVE lines."
        )

    def test_dry_run_deep_dive_in_preserve(self, fake_public_repo):
        """docs/deep-dive.*.html must appear as PRESERVE."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        output = result.stdout + result.stderr
        preserve_lines = [l for l in output.splitlines() if l.startswith("PRESERVE")]
        targets = " ".join(preserve_lines)
        assert "deep-dive" in targets, (
            f"deep-dive HTML not in PRESERVE. preserve_lines={preserve_lines}"
        )

    def test_dry_run_writes_nothing(self, fake_public_repo):
        """Dry-run must not create or modify any files in the target."""
        before_files = {
            str(p.relative_to(fake_public_repo))
            for p in fake_public_repo.rglob("*")
            if not str(p.relative_to(fake_public_repo)).startswith(".git")
        }
        subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        after_files = {
            str(p.relative_to(fake_public_repo))
            for p in fake_public_repo.rglob("*")
            if not str(p.relative_to(fake_public_repo)).startswith(".git")
        }
        assert before_files == after_files, (
            f"Dry-run modified the target. Added: {after_files - before_files}"
        )

    def test_refusal_nonzero_for_non_git_target(self, tmp_path):
        """Script exits nonzero and prints a clear message for non-git target."""
        not_a_repo = tmp_path / "plain_dir"
        not_a_repo.mkdir()
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(not_a_repo)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0, "Expected nonzero exit for non-git target"
        output = result.stdout + result.stderr
        assert "git" in output.lower() or "not a" in output.lower(), (
            f"Expected a clear error message. Got: {output!r}"
        )

    def test_dry_run_excludes_mcp_json(self, fake_public_repo):
        """Fix 1: .mcp.json must not appear in COPY lines."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        copy_lines = [l for l in result.stdout.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            assert ".mcp.json" not in line, f".mcp.json leaked into COPY: {line}"

    def test_dry_run_excludes_codex_wip_handoff(self, fake_public_repo):
        """Fix 2: docs/CODEX_WIP_HANDOFF.md must not appear in COPY lines."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        copy_lines = [l for l in result.stdout.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            assert "CODEX_WIP_HANDOFF" not in line, (
                f"CODEX_WIP_HANDOFF.md leaked into COPY: {line}"
            )

    def test_dry_run_excludes_devos_issues(self, fake_public_repo):
        """Fix 3: devos/issues/ must not appear in COPY lines."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        copy_lines = [l for l in result.stdout.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            assert "devos/issues" not in line, (
                f"devos/issues leaked into COPY: {line}"
            )

    def test_dry_run_excludes_settings_local_json(self, fake_public_repo):
        """Fix 5: .claude/settings.local.json must not appear in COPY lines."""
        result = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "export_to_public.py"),
             "--dry-run",
             str(fake_public_repo)],
            capture_output=True, text=True,
        )
        copy_lines = [l for l in result.stdout.splitlines() if l.startswith("COPY")]
        for line in copy_lines:
            assert "settings.local.json" not in line, (
                f"settings.local.json leaked into COPY: {line}"
            )


# ---------------------------------------------------------------------------
# Apply tests (Fix 8) — --apply writes COPY, SCRUBs, respects PRESERVE, idempotent
#
# These tests use a controlled fake source tree (no real dev-os paths) so that
# the home-path guard does not fire.  The guard itself is tested separately in
# TestHomePathGuard.
# ---------------------------------------------------------------------------

def _make_fake_src(tmp_path: Path) -> Path:
    """Build a minimal fake source tree that has no absolute home paths.

    Contains:
    - AGENTS.md (COPY)
    - devos/os-feedback/INBOX.md (SCRUB)
    - devos/questions/QUEUE.md (SCRUB)
    - README.md (PRESERVE — will NOT be COPY'd)
    """
    src = tmp_path / "fake-src"
    src.mkdir()
    (src / "AGENTS.md").write_text("# Agents\n")
    (src / "deos.yaml").write_text("version: 1\n")
    (src / "requirements.txt").write_text("pytest\n")
    inbox_dir = src / "devos" / "os-feedback"
    inbox_dir.mkdir(parents=True)
    (inbox_dir / "INBOX.md").write_text("REAL PRIVATE CONTENT — should not copy\n")
    q_dir = src / "devos" / "questions"
    q_dir.mkdir(parents=True)
    (q_dir / "QUEUE.md").write_text("REAL PRIVATE QUESTIONS — should not copy\n")
    plans_dir = src / "devos" / "plans"
    for sub in ["approved", "pending", "rejected"]:
        (plans_dir / sub).mkdir(parents=True)
    return src


def _make_git_target(tmp_path: Path, name: str = "target") -> Path:
    """Create a minimal git repo with public PRESERVE files."""
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "README.md").write_text("# Public README — must not be overwritten\n")
    (repo / "CHANGELOG.md").write_text("# Public Changelog\n")
    devos_tasks = repo / "devos" / "tasks"
    devos_tasks.mkdir(parents=True)
    (devos_tasks / "QUEUE.yaml").write_text("# Curated example\n")
    subprocess.run(
        ["git", "-C", str(repo), "add", "."],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "init",
         "--author", "Test <t@t.com>"],
        check=True, capture_output=True,
    )
    return repo


class TestApplyIntegration:
    """Tests for the --apply mode using a controlled fake source tree."""

    def test_apply_writes_copy_files(self, tmp_path):
        """Fix 8a: --apply actually writes COPY-classified files to the target."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)
        plan = exp.build_plan(src)
        exp.apply_plan(src, target, plan)
        # AGENTS.md is a COPY file in fake-src
        assert (target / "AGENTS.md").exists(), "AGENTS.md was not written by apply_plan"

    def test_apply_scrubs_inbox_to_template(self, tmp_path):
        """Fix 8b: apply_plan writes the empty template for devos/os-feedback/INBOX.md."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)
        plan = exp.build_plan(src)
        exp.apply_plan(src, target, plan)

        inbox = target / "devos" / "os-feedback" / "INBOX.md"
        assert inbox.exists(), "apply_plan did not create INBOX.md"
        content = inbox.read_text()
        assert "No entries yet" in content, (
            f"INBOX.md was not scrubbed to template. Got: {content[:200]}"
        )
        # Real source content must NOT be present
        assert "REAL PRIVATE CONTENT" not in content, (
            "Real INBOX.md content leaked into target"
        )

    def test_apply_scrubs_questions_queue_to_template(self, tmp_path):
        """Fix 8b: apply_plan writes the empty template for devos/questions/QUEUE.md."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)
        plan = exp.build_plan(src)
        exp.apply_plan(src, target, plan)

        queue_md = target / "devos" / "questions" / "QUEUE.md"
        assert queue_md.exists(), "apply_plan did not create questions/QUEUE.md"
        content = queue_md.read_text()
        assert "No entries yet" in content, (
            f"questions/QUEUE.md was not scrubbed to template. Got: {content[:200]}"
        )
        assert "REAL PRIVATE QUESTIONS" not in content, (
            "Real QUEUE.md content leaked into target"
        )

    def test_apply_does_not_overwrite_preserve_files(self, tmp_path):
        """Fix 8c: PRESERVE files pre-existing in target must not be overwritten."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)

        readme_before = (target / "README.md").read_text()
        changelog_before = (target / "CHANGELOG.md").read_text()
        queue_before = (target / "devos" / "tasks" / "QUEUE.yaml").read_text()

        plan = exp.build_plan(src)
        exp.apply_plan(src, target, plan)

        assert (target / "README.md").read_text() == readme_before, (
            "README.md was overwritten by apply_plan"
        )
        assert (target / "CHANGELOG.md").read_text() == changelog_before, (
            "CHANGELOG.md was overwritten by apply_plan"
        )
        assert (target / "devos" / "tasks" / "QUEUE.yaml").read_text() == queue_before, (
            "Curated QUEUE.yaml was overwritten by apply_plan"
        )

    def test_apply_is_idempotent(self, tmp_path):
        """Fix 8d: two apply_plan calls produce byte-identical target tree."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)
        plan = exp.build_plan(src)

        exp.apply_plan(src, target, plan)

        def snapshot(root: Path) -> dict[str, bytes]:
            result: dict[str, bytes] = {}
            for p in sorted(root.rglob("*")):
                rel = str(p.relative_to(root))
                if rel.startswith(".git"):
                    continue
                if p.is_file():
                    result[rel] = p.read_bytes()
            return result

        snap1 = snapshot(target)
        exp.apply_plan(src, target, plan)
        snap2 = snapshot(target)

        assert snap1 == snap2, (
            f"apply_plan is not idempotent. Differences: "
            f"{set(snap1.keys()) ^ set(snap2.keys())}"
        )

    def test_apply_does_not_git_commit(self, tmp_path):
        """Fix 8e: apply_plan must not run git add/commit/push."""
        src = _make_fake_src(tmp_path)
        target = _make_git_target(tmp_path)

        before = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        head_before = before.stdout.strip()

        plan = exp.build_plan(src)
        exp.apply_plan(src, target, plan)

        after = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        head_after = after.stdout.strip()

        assert head_before == head_after, (
            f"apply_plan changed git HEAD (committed). Before={head_before}, After={head_after}"
        )


# ---------------------------------------------------------------------------
# Fail-closed home-path guard (Fix 7, Fix 10)
# ---------------------------------------------------------------------------

class TestHomePathGuard:
    """Tests for the fail-closed absolute-home-path content scanner."""

    def test_apply_aborts_nonzero_when_copy_file_has_home_path(self, tmp_path):
        """Fix 10: a COPY file containing /Users/someone/ causes --apply to abort nonzero."""
        # Create a minimal git repo target
        repo = tmp_path / "guard-target"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init",
             "--author", "Test <t@t.com>"],
            check=True, capture_output=True,
        )

        # Create a temporary source tree with a COPY file that has a home path
        src = tmp_path / "fake-src"
        src.mkdir()
        subprocess.run(["git", "init", str(src)], check=True, capture_output=True)

        # Write a file that would be COPY but contains an absolute home path
        bad_file = src / "bad_config.py"
        bad_file.write_text("BASE = '/Users/someone/dev-os'\n")

        # Monkeypatch _SRC_ROOT to the fake source and call apply_plan directly
        plan = [("COPY", Path("bad_config.py"))]
        offenders = exp._scan_for_home_paths(src, plan)
        assert len(offenders) == 1, (
            f"Expected 1 offender, got {offenders}"
        )
        assert offenders[0] == Path("bad_config.py")

    def test_home_path_scanner_finds_users_pattern(self, tmp_path):
        """_scan_for_home_paths detects /Users/<name>/ patterns."""
        (tmp_path / "f.py").write_text("x = '/Users/alice/projects/foo'\n")
        plan = [("COPY", Path("f.py"))]
        offenders = exp._scan_for_home_paths(tmp_path, plan)
        assert Path("f.py") in offenders

    def test_home_path_scanner_finds_home_pattern(self, tmp_path):
        """_scan_for_home_paths detects /home/<name>/ patterns."""
        (tmp_path / "g.sh").write_text("export PATH=/home/bob/bin:$PATH\n")
        plan = [("COPY", Path("g.sh"))]
        offenders = exp._scan_for_home_paths(tmp_path, plan)
        assert Path("g.sh") in offenders

    def test_home_path_scanner_ignores_non_copy(self, tmp_path):
        """_scan_for_home_paths only scans COPY entries (not SKIP/PRESERVE/SCRUB)."""
        (tmp_path / "h.md").write_text("path: /Users/carol/stuff\n")
        plan = [
            ("SKIP", Path("h.md")),
            ("PRESERVE", Path("h.md")),
            ("SCRUB", Path("h.md")),
        ]
        offenders = exp._scan_for_home_paths(tmp_path, plan)
        assert offenders == [], (
            f"Scanner should ignore non-COPY entries, got: {offenders}"
        )

    def test_home_path_scanner_ignores_clean_files(self, tmp_path):
        """_scan_for_home_paths returns empty list for files without home paths."""
        (tmp_path / "clean.py").write_text("x = 1\nprint(x)\n")
        plan = [("COPY", Path("clean.py"))]
        offenders = exp._scan_for_home_paths(tmp_path, plan)
        assert offenders == []

    def test_apply_aborts_via_subprocess_on_home_path(self, tmp_path):
        """Fix 7: apply_plan sys.exit(1) surfaces as nonzero exit in subprocess call."""
        # Build a fake source tree that would trigger the guard
        src_root = tmp_path / "poisoned-src"
        src_root.mkdir()

        # Create the scripts/ dir so the module resolves _SRC_ROOT to src_root
        # We test via the module API (not subprocess) to avoid needing real dev-os
        repo = tmp_path / "target-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init",
             "--author", "Test <t@t.com>"],
            check=True, capture_output=True,
        )

        # Write a poisoned COPY file
        (src_root / "poisoned.txt").write_text("path=/Users/someone/private\n")
        plan = [("COPY", Path("poisoned.txt"))]

        # apply_plan should call sys.exit(1)
        with pytest.raises(SystemExit) as exc_info:
            exp.apply_plan(src_root, repo, plan)
        assert exc_info.value.code != 0, (
            "apply_plan should exit nonzero when home path found in COPY file"
        )

    # -----------------------------------------------------------------------
    # Exemption tests: guard's own source files are not self-flagged
    # -----------------------------------------------------------------------

    def test_exempt_files_not_reported_even_with_home_path(self, tmp_path):
        """Exempt tool files containing /Users/x/ must NOT be flagged by the scanner.

        This verifies that scripts/export_to_public.py and
        tests/test_export_to_public.py are excluded from the home-path scan,
        so the guard does not self-flag and abort --apply.
        """
        # Build a fake source dir that mirrors the exempted relpaths
        src = tmp_path / "fake-src"
        scripts_dir = src / "scripts"
        tests_dir = src / "tests"
        scripts_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        # Write fake versions of the exempt files that contain home-path patterns
        (scripts_dir / "export_to_public.py").write_text(
            "# guard pattern: r'/(?:Users|home)/[^/\\s]+/'\n"
            "# example: /Users/someone/dev-os\n"
        )
        (scripts_dir / "export-to-public.sh").write_text(
            "#!/bin/bash\n# target: /Users/someone/Desktop/repo\n"
        )
        (tests_dir / "test_export_to_public.py").write_text(
            "# fixture: bad_file.write_text(\"BASE = '/Users/someone/dev-os'\")\n"
        )

        plan = [
            ("COPY", Path("scripts/export_to_public.py")),
            ("COPY", Path("scripts/export-to-public.sh")),
            ("COPY", Path("tests/test_export_to_public.py")),
        ]
        offenders = exp._scan_for_home_paths(src, plan)
        assert offenders == [], (
            f"Exempt tool files must NOT be flagged by the home-path scanner. "
            f"Got offenders: {offenders}"
        )

    def test_non_exempt_file_with_home_path_is_still_reported(self, tmp_path):
        """A non-exempt COPY file containing /Users/x/ IS reported and aborts --apply.

        This verifies the guard is still fail-closed for all non-exempt files.
        """
        src = tmp_path / "fake-src"
        src.mkdir()

        # Write a non-exempt file that contains a home path
        (src / "config.py").write_text("ROOT = '/Users/alice/projects'\n")

        plan = [("COPY", Path("config.py"))]
        offenders = exp._scan_for_home_paths(src, plan)
        assert Path("config.py") in offenders, (
            f"Non-exempt file with /Users/.../ must be flagged. "
            f"Got offenders: {offenders}"
        )

        # Also verify apply_plan aborts
        repo = tmp_path / "target-repo"
        repo.mkdir()
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init",
             "--author", "Test <t@t.com>"],
            check=True, capture_output=True,
        )
        with pytest.raises(SystemExit) as exc_info:
            exp.apply_plan(src, repo, plan)
        assert exc_info.value.code != 0, (
            "apply_plan must abort nonzero when a non-exempt file has a home path"
        )


# ---------------------------------------------------------------------------
# .keep dry-run vs apply consistency (Fix 11)
# ---------------------------------------------------------------------------

class TestKeepSentinelConsistency:
    """Verify .keep sentinel entries appear in the plan (dry-run == apply)."""

    def test_build_plan_includes_keep_sentinels(self):
        """Fix 11: build_plan() must include .keep entries so dry-run == apply."""
        plan = exp.build_plan(_REPO_ROOT)
        keep_entries = [
            rel.as_posix() for cls, rel in plan
            if rel.name == ".keep"
        ]
        # All three sentinel dirs must have a .keep entry
        for subdir in ["approved", "pending", "rejected"]:
            expected = f"devos/plans/{subdir}/.keep"
            assert expected in keep_entries, (
                f"build_plan() missing sentinel: {expected}. "
                f"Found keep entries: {keep_entries}"
            )

    def test_keep_entries_are_copy_classified(self):
        """Fix 11: .keep sentinels in build_plan() must have COPY classification."""
        plan = exp.build_plan(_REPO_ROOT)
        for cls, rel in plan:
            if rel.name == ".keep" and "devos/plans/" in rel.as_posix():
                assert cls == "COPY", (
                    f"Expected COPY for {rel.as_posix()}, got {cls}"
                )

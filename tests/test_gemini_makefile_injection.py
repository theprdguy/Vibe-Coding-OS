"""T-OSN-W7-GEMINI-02 R6 — Makefile shell injection regression tests.

R6 (Phase 0 closure): gemini-pending / gemini-next / gemini-ingest / gemini-status
targets REMOVED from Makefile (osn-wide systemic RCE surface).

Root cause (R5 → R6 escalation):
  R5 added zero-arg Plan B targets (no T=/PROMPT=/IMAGES= in recipe bodies).
  However, `export GEMINI_T = $(T)` on Makefile line 10 is evaluated at parse
  phase for ALL targets, including zero-arg ones.
  PoC: `make gemini-next "T=T-X$(shell touch /tmp/R6_RCE_PROOF)Y"`
  → /tmp/R6_RCE_PROOF created even though gemini-next has no T= in its recipe.
  The export directive processes $(T) at parse phase regardless.

Why R1-R5 all failed
--------------------
R1 (CLI argv):    $(T) textual substitution → shell eval of backtick/$().
R2 (env-var):     T="$(T)" → bash evaluates backtick/$() inside "".
R3 (single-quote): '$(T)' → attacker's ' closes the quote; bare commands run.
R4 (Make export):  export GEMINI_T = $(T) → Make builtin $(shell ...) evaluated
                   at parse phase — export does NOT protect against Make functions.
R5 (queue-only):   export GEMINI_T = $(T) on line 10 still evaluated at parse
                   phase for all targets, including zero-arg ones.

R6 (current — structural fix):
  Plan B Make targets (gemini-pending / gemini-next / gemini-ingest / gemini-status)
  REMOVED from Makefile. Python CLI used directly:
    python3 -m server.gemini_handoff pending/next/ingest-stdin
    python3 -m server.gemini_dispatcher status
  Next milestone: bin/osn gemini * (T-OSN-W7-OSN-CLI-01).

This file:
  - 12 attack variants × 2 R5-removed targets = 24 "target not found" negative tests
    (handoff-gemini, ingest-gemini — removed in R5, confirmed removed in R6)
  - 12 attack variants × 1 surviving target (dispatch-gemini) = 12 PoC tests
    (dispatch-gemini still uses GEMINI_T export — Plan A, unaffected by R6)
  - 5 explicit R3 security-agent PoC reproductions
  - 6 original R3 regression tests
  - 4 newline injection tests
  - 150 fuzz tests (50 seeds × 3 vars, dangerous chars weighted)
  - 6 R6 queue-only surface tests (R5 targets now also removed — nonzero exit expected)
  Total: ~207 tests. All assert sentinel NOT created.
"""

from __future__ import annotations

import os
import random
import string
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Project root
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make(target: str, var_overrides: dict, tmp_path: Path, stdin: str = "") -> subprocess.CompletedProcess:
    """Run a make target with Make variable overrides (T=..., PROMPT=..., IMAGES=...).

    We pass args as Make command-line variables (not as env vars), exactly as
    an attacker would type them at the shell prompt.

    OS2_PROJECT_ROOT is overridden so logs/flags go to tmp_path (isolation).
    """
    env = {**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)}
    cmd = ["make", target] + [f"{k}={v}" for k, v in var_overrides.items()]
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=15,
    )


# ---------------------------------------------------------------------------
# R4 PoC parametrize — 12+ attack variants × 3 targets = 36+ tests
#
# Each (var, attack) tuple is one injection vector.
# {sentinel} is replaced with the actual tmp sentinel path before use.
# ---------------------------------------------------------------------------

_ATTACK_PARAMS = [
    # ── backtick injection ──────────────────────────────────────────────────
    ("T",      "T-OK`touch {sentinel}`X"),
    ("PROMPT", "x`touch {sentinel}`y"),
    ("IMAGES", "`touch {sentinel}`"),
    # ── $() command substitution ────────────────────────────────────────────
    ("T",      "T-OK$(touch {sentinel})X"),
    ("PROMPT", "x$(touch {sentinel})y"),
    ("IMAGES", "$(touch {sentinel})"),
    # ── single-quote escape (R3 BLOCKER — security agent 실측 5/5 confirmed) ─
    ("T",      "T-OK';touch {sentinel};'X"),
    ("PROMPT", "x';touch {sentinel};'y"),
    ("IMAGES", "x';touch {sentinel};'y"),
    # ── double-quote escape ─────────────────────────────────────────────────
    ("T",      'T-OK";touch {sentinel};"X'),
    ("PROMPT", 'x";touch {sentinel};"y'),
    ("IMAGES", 'x";touch {sentinel};"y'),
]

# R5: handoff-gemini and ingest-gemini REMOVED. dispatch-gemini still active (Plan A).
_TARGETS_REMOVED = ["handoff-gemini", "ingest-gemini"]  # R5: these no longer exist
_TARGETS_ACTIVE = ["dispatch-gemini"]                   # Plan A: still uses GEMINI_T

# Build parametrize params for removed targets (negative regression tests)
_REMOVED_TARGET_PARAMS = [
    pytest.param(target, var, attack, id=f"{target}-{var}-{i}")
    for i, (var, attack) in enumerate(_ATTACK_PARAMS)
    for target in _TARGETS_REMOVED
]

# Build parametrize params for active targets
_ACTIVE_TARGET_PARAMS = [
    pytest.param(target, var, attack, id=f"{target}-{var}-{i}")
    for i, (var, attack) in enumerate(_ATTACK_PARAMS)
    for target in _TARGETS_ACTIVE
]


@pytest.mark.parametrize("target,var,attack_template", _REMOVED_TARGET_PARAMS)
def test_removed_target_make_fails_fast_no_rce(tmp_path: Path, target: str, var: str, attack_template: str):
    """R5 regression guard: removed targets must not exist in Makefile.

    When handoff-gemini or ingest-gemini is called, Make must exit nonzero
    ("No rule to make target") — no shell evaluation occurs.
    Sentinel must NOT be created.

    Total: 12 attack variants × 2 removed targets = 24 tests.
    If these targets are re-added to the Makefile, these tests must be
    re-evaluated for injection safety.
    """
    sentinel = tmp_path / f"sentinel_{var}_{target}"
    attack = attack_template.format(sentinel=sentinel)

    overrides: dict = {}
    if var == "T":
        overrides["T"] = attack
    else:
        overrides["T"] = "T-OSN-SAFE-01"
        overrides[var] = attack

    if target == "ingest-gemini":
        result = _make(target, overrides, tmp_path, stdin="")
    else:
        result = _make(target, overrides, tmp_path)

    # Target removed → Make exits nonzero ("No rule to make target")
    # This is expected behaviour — the target no longer exists.
    # The key assertion: sentinel NOT created regardless of make exit code.
    assert not sentinel.exists(), (
        f"RCE DETECTED via removed target {target}: sentinel {sentinel} was created.\n"
        f"If this target was re-added to Makefile, it must pass injection safety audit.\n"
        f"Attack: {var}={attack!r}"
    )


@pytest.mark.parametrize("target,var,attack_template", _ACTIVE_TARGET_PARAMS)
def test_make_target_no_rce(tmp_path: Path, target: str, var: str, attack_template: str):
    """R5 PoC: all 12 attack variants × 1 active target (dispatch-gemini) must NOT create sentinel.

    dispatch-gemini uses export GEMINI_T = $(T) (Plan A). R5 does not change Plan A.
    We verify the existing Make export protection still holds for dispatch-gemini.

    Total: 12 × 1 = 12 parametrized tests.
    """
    sentinel = tmp_path / f"sentinel_{var}_{target}"
    attack = attack_template.format(sentinel=sentinel)

    overrides: dict = {}
    if var == "T":
        overrides["T"] = attack
    else:
        overrides["T"] = "T-OSN-SAFE-01"
        overrides[var] = attack

    _make(target, overrides, tmp_path)

    assert not sentinel.exists(), (
        f"RCE DETECTED: {target} with {var}={attack!r} created sentinel {sentinel}.\n"
        f"Make export pattern is NOT protecting against this injection vector."
    )


# ---------------------------------------------------------------------------
# Additional single-quote escape PoC (explicit — matches security agent PoCs)
# R5 update: handoff-gemini and ingest-gemini are REMOVED targets.
# Tests updated to verify: target not found → exit nonzero → NO sentinel.
# dispatch-gemini is the only surviving target — still tested.
# ---------------------------------------------------------------------------


def test_handoff_T_single_quote_escape_removed_target(tmp_path: Path):
    """R5 regression: handoff-gemini is removed. single-quote in T must NOT execute.
    Security agent PoC 1/5 — converted to 'target not found' negative test.
    """
    sentinel = tmp_path / "RCE_BREAK_CONFIRM"
    evil = f"T-OK';touch {sentinel};'X"
    result = _make("handoff-gemini", {"T": evil}, tmp_path)
    # Target removed → make exits nonzero. Sentinel must NOT be created.
    assert not sentinel.exists(), f"RCE: single-quote in T via removed handoff-gemini created {sentinel}"


def test_handoff_PROMPT_single_quote_escape_removed_target(tmp_path: Path):
    """R5 regression: handoff-gemini removed. single-quote in PROMPT. Security agent PoC 2/5."""
    sentinel = tmp_path / "RCE_PROMPT"
    evil = f"x';touch {sentinel};'y"
    _make("handoff-gemini", {"T": "T-OK", "PROMPT": evil}, tmp_path)
    assert not sentinel.exists(), f"RCE: single-quote in PROMPT via removed handoff-gemini created {sentinel}"


def test_handoff_IMAGES_single_quote_escape_removed_target(tmp_path: Path):
    """R5 regression: handoff-gemini removed. single-quote in IMAGES. Security agent PoC 3/5."""
    sentinel = tmp_path / "RCE_IMAGES"
    evil = f"x';touch {sentinel};'y"
    _make("handoff-gemini", {"T": "T-OK", "IMAGES": evil}, tmp_path)
    assert not sentinel.exists(), f"RCE: single-quote in IMAGES via removed handoff-gemini created {sentinel}"


def test_ingest_T_single_quote_escape_removed_target(tmp_path: Path):
    """R5 regression: ingest-gemini removed. single-quote in T. Security agent PoC 4/5."""
    sentinel = tmp_path / "RCE_INGEST"
    evil = f"T-OK';touch {sentinel};'X"
    subprocess.run(
        ["make", "ingest-gemini", f"T={evil}"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → make exits nonzero. Sentinel must NOT be created.
    assert not sentinel.exists(), f"RCE: single-quote in T via removed ingest-gemini created {sentinel}"


def test_dispatch_T_single_quote_escape_does_not_execute(tmp_path: Path):
    """R5 regression: dispatch-gemini (Plan A, ACTIVE) single-quote in T. Security agent PoC 5/5."""
    sentinel = tmp_path / "RCE_DISPATCH"
    evil = f"T-OK';touch {sentinel};'X"
    subprocess.run(
        ["make", "dispatch-gemini", f"T={evil}"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    assert not sentinel.exists(), f"RCE: single-quote in T (dispatch-gemini) created {sentinel}"


# ---------------------------------------------------------------------------
# R3 backtick / $() PoC regression (keep original 6 tests — updated for R5)
# handoff-gemini and ingest-gemini are REMOVED targets in R5.
# These tests now verify: removed target → make fails fast → sentinel NOT created.
# dispatch-gemini (Plan A) still active — sentinel must still not be created.
# ---------------------------------------------------------------------------


def test_handoff_T_backtick_removed_target(tmp_path: Path):
    """R5 update of R3 PoC 1: backtick in T for removed handoff-gemini target."""
    sentinel = tmp_path / "RCE_HANDOFF"
    _make("handoff-gemini", {"T": f"T-X`touch {sentinel}`"}, tmp_path)
    # Target removed → make fails fast, no shell evaluation
    assert not sentinel.exists()


def test_handoff_PROMPT_backtick_removed_target(tmp_path: Path):
    """R5 update of R3 PoC 2: backtick in PROMPT for removed handoff-gemini."""
    sentinel = tmp_path / "RCE_PROMPT_BACKTICK"
    _make("handoff-gemini", {"T": "T-OSN-SAFE-01", "PROMPT": f"hello`touch {sentinel}`"}, tmp_path)
    assert not sentinel.exists()


def test_handoff_IMAGES_backtick_removed_target(tmp_path: Path):
    """R5 update of R3 PoC 3: backtick in IMAGES for removed handoff-gemini."""
    sentinel = tmp_path / "RCE_IMAGES_BACKTICK"
    _make("handoff-gemini", {"T": "T-OSN-SAFE-02", "IMAGES": f"`touch {sentinel}`"}, tmp_path)
    assert not sentinel.exists()


def test_ingest_T_backtick_removed_target(tmp_path: Path):
    """R5 update of R3 PoC 4: backtick in T for removed ingest-gemini."""
    sentinel = tmp_path / "RCE_INGEST_BACKTICK"
    subprocess.run(
        ["make", "ingest-gemini", f"T=T-X`touch {sentinel}`"],
        input="",
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → make fails fast, no shell evaluation
    assert not sentinel.exists()


def test_dispatch_T_backtick_does_not_execute(tmp_path: Path):
    """Original R3 PoC 5: backtick in T for dispatch-gemini (still active Plan A target)."""
    sentinel = tmp_path / "RCE_DISPATCH_BACKTICK"
    subprocess.run(
        ["make", "dispatch-gemini", f"T=T-X`touch {sentinel}`"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    assert not sentinel.exists()


def test_handoff_T_dollar_subshell_removed_target(tmp_path: Path):
    """R5 update of R3 PoC 6: $() in T for removed handoff-gemini."""
    sentinel = tmp_path / "RCE_DOLLAR"
    _make("handoff-gemini", {"T": f"T-X$(touch {sentinel})"}, tmp_path)
    # Target removed → make fails fast
    assert not sentinel.exists()


# ---------------------------------------------------------------------------
# Newline injection tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("var,target", [
    ("T", "handoff-gemini"),    # R5: removed target — make fails fast
    ("PROMPT", "handoff-gemini"),  # R5: removed target — make fails fast
    ("T", "ingest-gemini"),     # R5: removed target — make fails fast
    ("T", "dispatch-gemini"),   # R5: active Plan A target
])
def test_newline_injection_does_not_execute(tmp_path: Path, var: str, target: str):
    """Newline injection must not create sentinel via command injection.

    R5 note: handoff-gemini and ingest-gemini are removed targets.
    They exit nonzero from make itself — no shell evaluation, sentinel not created.
    dispatch-gemini is still active but protected by export GEMINI_T.
    """
    sentinel = tmp_path / f"newline_{var}_{target}"
    attack = f"T-OK\ntouch {sentinel}\necho done" if var == "T" else f"x\ntouch {sentinel}\ny"
    overrides: dict = {}
    if var == "T":
        overrides["T"] = attack
    else:
        overrides["T"] = "T-OSN-SAFE-01"
        overrides[var] = attack

    if target == "ingest-gemini":
        _make(target, overrides, tmp_path, stdin="")
    else:
        _make(target, overrides, tmp_path)

    assert not sentinel.exists(), f"Newline injection via {var} ({target}) created {sentinel}"


# ---------------------------------------------------------------------------
# Property-based fuzz tests — random payloads with dangerous characters
# 50 seeds × 3 vars = 150 fuzz iterations
# ---------------------------------------------------------------------------

# Characters that historically triggered injections across R1–R3
_DANGEROUS_CHARS = "'\"`${};|&\n\r\\"
_FUZZ_CHARS = string.ascii_letters + string.digits + _DANGEROUS_CHARS


def _random_payload(rnd: random.Random, max_len: int = 64) -> str:
    """Generate a random string weighted toward dangerous characters."""
    n = rnd.randint(1, max_len)
    return "".join(rnd.choices(_FUZZ_CHARS, k=n))


@pytest.mark.parametrize("var", ["T", "PROMPT", "IMAGES"])
@pytest.mark.parametrize("seed", range(50))
def test_make_handoff_fuzz_no_rce(tmp_path: Path, var: str, seed: int):
    """Fuzz: 50 random seeds × 3 vars = 150 iterations.

    Each iteration generates a random payload containing dangerous characters
    and embeds a sentinel-creating snippet.  If the sentinel is created, RCE
    occurred via the injected command.

    R5 update: handoff-gemini is a removed target. Make exits nonzero immediately.
    No shell evaluation occurs — sentinel not created in any case.
    This fuzz suite is preserved as a regression guard: if handoff-gemini is
    re-added to the Makefile, it must pass this fuzz suite with zero RCE.
    """
    rnd = random.Random(seed)
    payload = _random_payload(rnd)
    sentinel = tmp_path / f"fuzz_{var}_{seed}"
    # Embed sentinel-creating snippet so the test fails if any injection works
    full = f"{payload};touch {sentinel};echo done"

    overrides: dict = {}
    if var == "T":
        overrides["T"] = full
    else:
        overrides["T"] = "T-OSN-SAFE-01"
        overrides[var] = full

    _make("handoff-gemini", overrides, tmp_path)

    assert not sentinel.exists(), (
        f"Fuzz RCE: seed={seed} var={var} payload={full!r} created {sentinel}.\n"
        f"handoff-gemini target was re-added without injection safety review."
    )


# ---------------------------------------------------------------------------
# R6 regression tests — gemini-pending / gemini-next / gemini-ingest removed
# R5 added these as zero-arg targets; R6 removes them (export GEMINI_T line 10
# is still evaluated at parse phase for all targets, including zero-arg ones).
# Targets must exit nonzero (No rule to make target). Sentinels must NOT exist.
# ---------------------------------------------------------------------------


def test_gemini_pending_target_removed(tmp_path: Path):
    """R6 regression: gemini-pending target removed from Makefile — must exit nonzero.

    R5 added this target (queue-only, zero args). R6 removes it because
    export GEMINI_T = $(T) on Makefile line 10 is still evaluated at parse
    phase and affects ALL targets including zero-arg ones.
    Python CLI `python3 -m server.gemini_handoff pending` is the safe alternative.
    """
    result = subprocess.run(
        ["make", "gemini-pending"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → Make exits nonzero ("No rule to make target")
    assert result.returncode != 0, (
        f"R6: gemini-pending target must not exist (removed). Got exit 0.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_gemini_next_target_removed(tmp_path: Path):
    """R6 regression: gemini-next target removed from Makefile — must exit nonzero.

    R5 added this target (queue-only, zero args). R6 removes it because
    export GEMINI_T = $(T) on Makefile line 10 is still evaluated at parse
    phase and affects ALL targets including zero-arg ones.
    Python CLI `python3 -m server.gemini_handoff next` is the safe alternative.
    """
    result = subprocess.run(
        ["make", "gemini-next"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → Make exits nonzero ("No rule to make target")
    assert result.returncode != 0, (
        f"R6: gemini-next target must not exist (removed). Got exit 0.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_gemini_ingest_target_removed_stdin_attack_no_sentinel(tmp_path: Path):
    """R6 regression: gemini-ingest target removed — must exit nonzero AND no sentinel.

    R5 PoC (preserved): stdin attack payload must NOT create sentinels.
    R6: gemini-ingest target is removed, so Make exits nonzero immediately
    before any recipe runs — stdin is never read by Make. Sentinel not created.
    Python CLI `python3 -m server.gemini_handoff ingest-stdin` is the safe alternative.
    """
    sentinel = tmp_path / "R6_INGEST_REMOVED_STDIN_PROOF"
    attack_stdin = f"$(touch {sentinel})\n`touch {sentinel}`\nNormal text."

    result = subprocess.run(
        ["make", "gemini-ingest"],
        input=attack_stdin,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → Make exits nonzero. Sentinel must NOT be created.
    assert result.returncode != 0, (
        f"R6: gemini-ingest target must not exist (removed). Got exit 0.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not sentinel.exists(), (
        f"R6 regression: gemini-ingest (removed target) still created sentinel {sentinel}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_gemini_ingest_target_removed_make_builtin_no_sentinel(tmp_path: Path):
    """R6 regression: gemini-ingest target removed — Make builtin in stdin no sentinel.

    R5 PoC (preserved): Make builtin $(shell ...) in stdin must not execute.
    R6: target removed, Make exits nonzero immediately — stdin never evaluated.
    """
    sentinel = tmp_path / "R6_INGEST_MAKE_BUILTIN_STDIN_PROOF"
    attack_stdin = f"$(shell touch {sentinel})\nNormal review text."

    result = subprocess.run(
        ["make", "gemini-ingest"],
        input=attack_stdin,
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "OS2_PROJECT_ROOT": str(tmp_path)},
        timeout=15,
    )
    # Target removed → Make exits nonzero. Sentinel must NOT be created.
    assert result.returncode != 0, (
        f"R6: gemini-ingest target must not exist (removed). Got exit 0.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert not sentinel.exists(), (
        f"R6 regression: Make builtin $(shell ...) via removed gemini-ingest created {sentinel}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# OSN-CLI-02: Makefile absence invariant — Make invocation itself must fail
# ---------------------------------------------------------------------------


def test_makefile_absence_blocks_make_invocation(tmp_path: Path):
    """Makefile 부재 시 'make any-target ...' 호출 자체 fail.

    → sentinel 미생성 (RCE 표면 부재 invariant).

    T-OSN-W7-OSN-CLI-02: Makefile 이 삭제됨. 어떤 target 을 어떤 injection payload 로
    호출해도 make 자체가 즉시 nonzero exit ('no Makefile found' 또는 'No rule to make
    target') — shell recipe 자체가 실행되지 않으므로 sentinel 이 생성될 수 없다.

    This test is the structural invariant guard: if a Makefile is re-added to
    the project, this test will PASS (make finds the file) which would cause the
    existing injection PoC tests to become relevant again and must be re-audited.

    Inverted logic: this test asserts make exits NON-ZERO (no Makefile → error).
    If make exits 0, the Makefile was re-added and this test fails as a warning.
    """
    sentinel = tmp_path / "should_not_exist"
    result = subprocess.run(
        ["make", "any-target", f"T=T-X`touch {sentinel}`Y"],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        timeout=10,
    )
    assert result.returncode != 0, (
        "make 호출 자체 fail 해야 함 (Makefile 부재). "
        "returncode=0 → Makefile 이 다시 추가됐을 가능성 — injection PoC 재감사 필요."
    )
    assert not sentinel.exists(), (
        f"RCE: sentinel {sentinel} was created despite Makefile absence. "
        "Make evaluation occurred — check if a Makefile was re-introduced."
    )

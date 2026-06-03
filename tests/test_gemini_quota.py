"""T-OSN-W7-GEMINI-04 — GeminiQuota test suite.

Coverage (13 original + R2 additions):
1.  Cap not reached — check_and_increment succeeds and returns new count
2.  Cap reached — 51st call raises QuotaExceededError
3.  Cap reached — fallback (handoff) triggered in dispatcher.run()
4.  Counter persists across GeminiQuota instances (file-backed)
5.  set_cap_reached forces counter to cap
6.  log_outcome writes JSONL line with correct fields
7.  log_outcome writes correct outcome values (success / quota_exceeded / fallback)
8.  questions/QUEUE.md auto-registered on cap exceeded (idempotent)
9.  Race condition: concurrent check_and_increment never double-counts past cap
10. load_daily_cap reads gemini.yaml and returns configured value
11. load_daily_cap falls back to DEFAULT when yaml missing
12. Dispatcher run() logs quota_exceeded outcome when QuotaExceededError raised
13. Infinite-loop guard: fallback model quota exhaustion goes to Plan B, not back to 3.1

R2 additions:
14. Cross-process race — multiprocessing 5+ processes → Q-* exactly 1 entry (BLOCKER 1)
15. quota_overflow_action=silent — no Q-* registration (WARNING 4)
16. quota_overflow_action=raise — RuntimeError raised (WARNING 4)
17. fallback_on_quota_exceeded=false — fallback model skipped, direct Plan B (WARNING 4)
18. Dispatcher daily_cap=50 explicit overrides config cap=100 (WARNING 5)
19. Dispatcher daily_cap=None reads config cap (WARNING 5)
"""

from __future__ import annotations

import json
import multiprocessing
import os
import threading
import time
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from server.gemini_quota import (
    DEFAULT_DAILY_CAP,
    GeminiQuota,
    QuotaExceededError,
    load_daily_cap,
    load_gemini_config,
)
from server.gemini_dispatcher import (
    GeminiDispatcher,
    GeminiResult,
    GEMINI_DEFAULT_MODEL,
    GEMINI_FALLBACK_MODEL,
    _detect_quota_exhaustion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Minimal project root with required subdirectories.

    WARNING 2 fix: sets OS2_PROJECT_ROOT env var to tmp_path so that any
    load_daily_cap(project_root=None) call inside tests resolves to the
    isolated tmp dir — not the real repo root.
    """
    (tmp_path / ".cache").mkdir()
    (tmp_path / "devos" / "logs" / "gemini").mkdir(parents=True)
    (tmp_path / "devos" / "questions").mkdir(parents=True)
    (tmp_path / "devos" / "state").mkdir(parents=True)
    (tmp_path / "server" / "state").mkdir(parents=True)
    # Write a minimal questions/QUEUE.md so append works
    (tmp_path / "devos" / "questions" / "QUEUE.md").write_text(
        "# Question Queue\n", encoding="utf-8"
    )
    # WARNING 2 fix: pin OS2_PROJECT_ROOT so load_daily_cap(project_root=None)
    # uses tmp_path, not the real repo root.
    monkeypatch.setenv("OS2_PROJECT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture()
def quota(project_root: Path) -> GeminiQuota:
    return GeminiQuota(project_root, daily_cap=3)


# ---------------------------------------------------------------------------
# Test 1: Cap not reached — check_and_increment succeeds
# ---------------------------------------------------------------------------


def test_check_and_increment_succeeds_below_cap(quota: GeminiQuota):
    """First call returns count=1 when cap=3."""
    count = quota.check_and_increment("T-OSN-TEST-01")
    assert count == 1, f"Expected count=1, got {count}"


def test_check_and_increment_increments_sequentially(quota: GeminiQuota):
    """Three sequential calls return 1, 2, 3 (each below cap)."""
    counts = [quota.check_and_increment("T-OSN-TEST-01") for _ in range(3)]
    assert counts == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test 2: Cap reached — QuotaExceededError raised on 51st call (DOD: cap=50)
# ---------------------------------------------------------------------------


def test_cap_reached_raises_quota_exceeded():
    """With cap=2, the 3rd call raises QuotaExceededError."""
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "server" / "state").mkdir(parents=True)
        (root / "devos" / "logs" / "gemini").mkdir(parents=True)
        (root / "devos" / "questions").mkdir(parents=True)
        (root / "devos" / "questions" / "QUEUE.md").write_text("# Q\n", encoding="utf-8")
        q = GeminiQuota(root, daily_cap=2)
        q.check_and_increment("T-OSN-TEST-01")
        q.check_and_increment("T-OSN-TEST-01")
        with pytest.raises(QuotaExceededError, match="daily cap reached"):
            q.check_and_increment("T-OSN-TEST-01")


def test_cap_50_51st_call_exceeds(project_root: Path):
    """DOD: dispatch 51st call when cap=50 raises QuotaExceededError."""
    q = GeminiQuota(project_root, daily_cap=50)
    # increment 50 times (1..50)
    for i in range(50):
        q.check_and_increment(f"T-OSN-TEST-{i:02d}")
    # 51st call must fail
    with pytest.raises(QuotaExceededError, match="50/50"):
        q.check_and_increment("T-OSN-TEST-51")


# ---------------------------------------------------------------------------
# Test 3: Cap reached → fallback (handoff) triggered in dispatcher.run()
# ---------------------------------------------------------------------------


def test_dispatcher_triggers_handoff_on_quota_exceeded(project_root: Path):
    """When quota is exceeded, dispatcher.run() returns success=False and calls handoff."""
    # Pre-fill counter to cap
    q = GeminiQuota(project_root, daily_cap=50)
    for i in range(50):
        q.check_and_increment(f"T-FILL-{i:02d}")

    # Create a minimal image so path validation passes
    img = project_root / ".cache" / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    dispatcher = GeminiDispatcher(project_root=project_root, daily_cap=50)
    # Use the same quota object (same state dir)
    dispatcher._quota = q

    handoff_calls: List[str] = []

    def fake_handoff(ticket_id, *, prompt, image_paths):
        handoff_calls.append(ticket_id)

    dispatcher.handoff_fallback = fake_handoff  # type: ignore[method-assign]

    result = dispatcher.run(
        ticket_id="T-OSN-TEST-51",
        prompt="Review this screen",
        image_paths=[str(img)],
        gui_review_required=False,
    )

    assert result.success is False
    assert "T-OSN-TEST-51" in handoff_calls, "handoff_fallback must be called when quota exceeded"


# ---------------------------------------------------------------------------
# Test 4: Counter persists across GeminiQuota instances
# ---------------------------------------------------------------------------


def test_counter_persists_across_instances(project_root: Path):
    """Counter file is read by a new GeminiQuota instance — state is durable."""
    q1 = GeminiQuota(project_root, daily_cap=10)
    q1.check_and_increment("T-OSN-TEST-01")
    q1.check_and_increment("T-OSN-TEST-02")

    q2 = GeminiQuota(project_root, daily_cap=10)
    count = q2.check_and_increment("T-OSN-TEST-03")
    assert count == 3, f"Expected count=3 (persisted across instances), got {count}"


# ---------------------------------------------------------------------------
# Test 5: set_cap_reached forces counter to cap
# ---------------------------------------------------------------------------


def test_set_cap_reached_blocks_future_calls(project_root: Path):
    """After set_cap_reached(), the next check_and_increment raises immediately."""
    q = GeminiQuota(project_root, daily_cap=10)
    q.check_and_increment("T-OSN-TEST-01")
    q.set_cap_reached()
    with pytest.raises(QuotaExceededError):
        q.check_and_increment("T-OSN-TEST-02")


# ---------------------------------------------------------------------------
# Test 6: log_outcome writes JSONL line with correct fields
# ---------------------------------------------------------------------------


def test_log_outcome_writes_jsonl_line(project_root: Path):
    """log_outcome appends a JSONL entry with all required fields."""
    q = GeminiQuota(project_root, daily_cap=10)
    q.log_outcome("T-OSN-TEST-01", "gemini-3.1-pro-preview", 100, 200, "success")

    from datetime import datetime, timezone
    ym = datetime.now(tz=timezone.utc).strftime("%Y%m")
    log_path = project_root / "devos" / "logs" / "gemini" / f"quota_{ym}.jsonl"
    assert log_path.exists(), "quota JSONL file must exist after log_outcome"

    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])

    assert entry["ticket_id"] == "T-OSN-TEST-01"
    assert entry["model"] == "gemini-3.1-pro-preview"
    assert entry["input_tokens"] == 100
    assert entry["output_tokens"] == 200
    assert entry["outcome"] == "success"
    assert "ts" in entry  # timestamp UTC present


# ---------------------------------------------------------------------------
# Test 7: log_outcome outcome values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["success", "fallback", "quota_exceeded", "error"])
def test_log_outcome_records_outcome_value(project_root: Path, outcome: str):
    """Each outcome value is recorded accurately in the JSONL entry."""
    q = GeminiQuota(project_root, daily_cap=10)
    q.log_outcome("T-OSN-TEST-01", "gemini-3.1-pro-preview", 0, 0, outcome)

    from datetime import datetime, timezone
    ym = datetime.now(tz=timezone.utc).strftime("%Y%m")
    log_path = project_root / "devos" / "logs" / "gemini" / f"quota_{ym}.jsonl"
    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    last = json.loads(lines[-1])
    assert last["outcome"] == outcome


# ---------------------------------------------------------------------------
# Test 8: questions/QUEUE.md auto-registered on cap exceeded (idempotent)
# ---------------------------------------------------------------------------


def test_quota_exceeded_registers_question(project_root: Path):
    """QuotaExceededError auto-registers Q-* in devos/questions/QUEUE.md."""
    q = GeminiQuota(project_root, daily_cap=1)
    q.check_and_increment("T-OSN-TEST-01")  # reaches cap
    with pytest.raises(QuotaExceededError):
        q.check_and_increment("T-OSN-TEST-02")

    queue_md = project_root / "devos" / "questions" / "QUEUE.md"
    content = queue_md.read_text(encoding="utf-8")
    assert "quota-exceeded" in content, "questions/QUEUE.md must contain quota-exceeded entry"
    assert "daily cap" in content.lower(), "Entry must mention daily cap"


def test_quota_question_registration_is_idempotent(project_root: Path):
    """Calling _register_quota_question twice on same day produces only one entry."""
    q = GeminiQuota(project_root, daily_cap=1)
    q._register_quota_question()
    q._register_quota_question()

    queue_md = project_root / "devos" / "questions" / "QUEUE.md"
    content = queue_md.read_text(encoding="utf-8")
    # Count occurrences of the tag — must be exactly 1
    from datetime import datetime, timezone
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    tag = f"quota-exceeded-{today}"
    count = content.count(tag)
    assert count == 1, f"Expected 1 quota entry for {today}, found {count}"


# ---------------------------------------------------------------------------
# Test 9: Race condition — concurrent check_and_increment never exceeds cap
# ---------------------------------------------------------------------------


def test_concurrent_increment_does_not_exceed_cap(project_root: Path):
    """10 threads each trying 5 increments with cap=8 — final count must be <= 8."""
    cap = 8
    q = GeminiQuota(project_root, daily_cap=cap)
    success_counts: List[int] = []
    errors: List[Exception] = []
    lock = threading.Lock()

    def worker():
        for _ in range(5):
            try:
                c = q.check_and_increment("T-OSN-RACE-01")
                with lock:
                    success_counts.append(c)
            except QuotaExceededError:
                pass
            except Exception as exc:
                with lock:
                    errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Unexpected errors in race test: {errors}"
    # The maximum successful count must equal exactly cap (not exceed it)
    assert max(success_counts) <= cap, (
        f"Counter exceeded cap={cap}: max successful count was {max(success_counts)}"
    )
    # Exactly 'cap' successful increments must have occurred
    assert len(success_counts) == cap, (
        f"Expected exactly {cap} successful increments, got {len(success_counts)}"
    )


# ---------------------------------------------------------------------------
# Test 10: load_daily_cap reads gemini.yaml
# ---------------------------------------------------------------------------


def test_load_daily_cap_reads_yaml(project_root: Path):
    """load_daily_cap returns the value from server/config/gemini.yaml."""
    config_dir = project_root / "server" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "gemini.yaml").write_text(
        "daily_call_cap: 99\nquota_overflow_action: questions_queue\n",
        encoding="utf-8",
    )
    cap = load_daily_cap(project_root)
    assert cap == 99, f"Expected 99 from gemini.yaml, got {cap}"


# ---------------------------------------------------------------------------
# Test 11: load_daily_cap falls back to DEFAULT when yaml missing
# ---------------------------------------------------------------------------


def test_load_daily_cap_fallback_when_yaml_missing(project_root: Path):
    """load_daily_cap returns DEFAULT_DAILY_CAP when config file is absent."""
    cap = load_daily_cap(project_root)
    # No gemini.yaml in tmp project_root → fallback
    assert cap == DEFAULT_DAILY_CAP, f"Expected DEFAULT_DAILY_CAP={DEFAULT_DAILY_CAP}, got {cap}"


# ---------------------------------------------------------------------------
# Test 12: Dispatcher run() logs quota_exceeded outcome when cap hit
# ---------------------------------------------------------------------------


def test_dispatcher_logs_quota_exceeded_outcome(project_root: Path):
    """outcome='quota_exceeded' is written to JSONL when cap is reached."""
    img = project_root / ".cache" / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    # Pre-fill counter so next call exceeds cap
    q = GeminiQuota(project_root, daily_cap=1)
    q.check_and_increment("T-OSN-FILL-01")

    dispatcher = GeminiDispatcher(project_root=project_root, daily_cap=1)
    dispatcher._quota = q

    def fake_handoff(tid, *, prompt, image_paths):
        pass

    dispatcher.handoff_fallback = fake_handoff  # type: ignore[method-assign]

    dispatcher.run(
        ticket_id="T-OSN-TEST-QUOTA",
        prompt="check this",
        image_paths=[str(img)],
    )

    from datetime import datetime, timezone
    ym = datetime.now(tz=timezone.utc).strftime("%Y%m")
    log_path = project_root / "devos" / "logs" / "gemini" / f"quota_{ym}.jsonl"
    assert log_path.exists(), "quota JSONL must exist"
    lines = [l for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    outcomes = [json.loads(l)["outcome"] for l in lines]
    assert "quota_exceeded" in outcomes, f"Expected 'quota_exceeded' in outcomes, got {outcomes}"


# ---------------------------------------------------------------------------
# Test 13: Infinite-loop guard — fallback model quota exhaustion → Plan B
# ---------------------------------------------------------------------------


def test_no_infinite_loop_on_fallback_quota_exhaustion(project_root: Path):
    """When fallback model (2.5-pro) also gets RESOURCE_EXHAUSTED, go to Plan B once."""
    img = project_root / ".cache" / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    dispatcher = GeminiDispatcher(project_root=project_root)

    invoke_calls: List[str] = []
    handoff_calls: List[str] = []

    def fake_invoke(cmd, *, env):
        model_arg = ""
        for i, arg in enumerate(cmd):
            if arg == "-m" and i + 1 < len(cmd):
                model_arg = cmd[i + 1]
        invoke_calls.append(model_arg)
        # Both primary and fallback report RESOURCE_EXHAUSTED
        return '{"response": ""}', "RESOURCE_EXHAUSTED: daily limit exceeded", 1

    def fake_handoff(ticket_id, *, prompt, image_paths):
        handoff_calls.append(ticket_id)

    dispatcher._invoke = fake_invoke  # type: ignore[method-assign]
    dispatcher.handoff_fallback = fake_handoff  # type: ignore[method-assign]

    # Patch smoke cache so dispatcher doesn't try real gemini smoke check
    with patch.object(dispatcher, "_ensure_smoke_cache"):
        result = dispatcher.run(
            ticket_id="T-OSN-TEST-LOOP",
            prompt="check this",
            image_paths=[str(img)],
            gui_review_required=False,
        )

    # Must have stopped — not an infinite loop (invoke called at most twice)
    assert len(invoke_calls) <= 2, (
        f"Expected at most 2 invocations (primary + one fallback), got {len(invoke_calls)}: {invoke_calls}"
    )
    # Plan B handoff must have been triggered
    assert handoff_calls, "handoff must be called when both primary and fallback are quota-exhausted"
    assert result.success is False


# ---------------------------------------------------------------------------
# Test: _detect_quota_exhaustion patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stderr,expected", [
    ("Error: daily limit exceeded", True),
    ("RESOURCE_EXHAUSTED: quota exceeded for project", True),
    ("quota exceeded for API", True),
    ("rateLimitExceeded", True),
    ("Normal response from model", False),
    ("", False),
    ("exit code 1: model error", False),
])
def test_detect_quota_exhaustion_stderr_patterns(stderr: str, expected: bool):
    """_detect_quota_exhaustion correctly identifies quota messages in stderr."""
    assert _detect_quota_exhaustion("", stderr) is expected


def test_detect_quota_exhaustion_plain_stdout():
    """Plain-text stdout (non-JSON) with quota keywords triggers detection."""
    assert _detect_quota_exhaustion("RESOURCE_EXHAUSTED: daily limit", "") is True


def test_detect_quota_exhaustion_json_stdout_not_intercepted():
    """JSON stdout with 'quota' in body is NOT intercepted (handled by JSON parsing path)."""
    json_stdout = '{"error": {"type": "Error", "message": "Quota exceeded"}}'
    # quota keyword is inside valid JSON — should NOT trigger (false positive guard)
    assert _detect_quota_exhaustion(json_stdout, "") is False


def test_detect_quota_exhaustion_false_for_clean_text():
    """Normal text does not trigger quota detection."""
    assert _detect_quota_exhaustion("Normal response from model", "") is False
    assert _detect_quota_exhaustion("", "") is False


# ---------------------------------------------------------------------------
# R2 Test 14: Cross-process race — multiprocessing → Q-* exactly 1 entry
# (BLOCKER 1 fix verification)
# ---------------------------------------------------------------------------


def _worker_register_quota_q(project_root_str: str, cap: int, results_path: str) -> None:
    """Subprocess worker: create GeminiQuota and call _register_quota_question().

    Records whether it succeeded in appending (tag present after call) to a
    shared results file (each process writes one JSON line).
    """
    from pathlib import Path
    import json
    from server.gemini_quota import GeminiQuota

    root = Path(project_root_str)
    q = GeminiQuota(root, daily_cap=cap)
    q._register_quota_question()
    # Write result line (process pid) — used only for debugging
    result_file = Path(results_path)
    with open(str(result_file), "a") as f:
        f.write(json.dumps({"pid": os.getpid()}) + "\n")


def test_concurrent_increment_cross_process(tmp_path: Path):
    """Cross-process race: 5+ processes call _register_quota_question() concurrently.

    R2 BLOCKER 1 fix: sentinel file (O_CREAT|O_EXCL) ensures exactly 1 Q-*
    entry is written to QUEUE.md regardless of concurrent cross-process calls.

    WARNING 3 fix: this is a multiprocessing.Process test (not thread-only).
    """
    # Set up a project root that all subprocesses can access
    root = tmp_path
    (root / ".cache").mkdir(exist_ok=True)
    (root / "devos" / "logs" / "gemini").mkdir(parents=True, exist_ok=True)
    (root / "devos" / "questions").mkdir(parents=True, exist_ok=True)
    (root / "devos" / "state").mkdir(parents=True, exist_ok=True)
    (root / "server" / "state").mkdir(parents=True, exist_ok=True)
    queue_md = root / "devos" / "questions" / "QUEUE.md"
    queue_md.write_text("# Question Queue\n", encoding="utf-8")

    results_file = tmp_path / "proc_results.jsonl"
    results_file.write_text("")

    n_procs = 5
    procs = [
        multiprocessing.Process(
            target=_worker_register_quota_q,
            args=(str(root), 10, str(results_file)),
        )
        for _ in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    # Count quota-exceeded-{today} tag occurrences in QUEUE.md
    from datetime import datetime, timezone
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    tag = f"quota-exceeded-{today}"
    content = queue_md.read_text(encoding="utf-8")
    count = content.count(tag)

    assert count == 1, (
        f"Expected exactly 1 Q-* quota entry in QUEUE.md after {n_procs} concurrent "
        f"processes, found {count}. Full QUEUE.md:\n{content}"
    )


# ---------------------------------------------------------------------------
# R2 Test 15: quota_overflow_action=silent — no Q-* registration (WARNING 4)
# ---------------------------------------------------------------------------


def test_overflow_action_silent_skips_registration(project_root: Path):
    """quota_overflow_action='silent' — _register_quota_question does nothing."""
    q = GeminiQuota(project_root, daily_cap=1, overflow_action="silent")
    # Fill to cap
    q.check_and_increment("T-OSN-TEST-SILENT")
    # Next call would normally register Q-* but overflow_action=silent suppresses it
    with pytest.raises(QuotaExceededError):
        q.check_and_increment("T-OSN-TEST-SILENT-2")

    queue_md = project_root / "devos" / "questions" / "QUEUE.md"
    content = queue_md.read_text(encoding="utf-8")
    assert "quota-exceeded" not in content, (
        "quota_overflow_action=silent must not register any Q-* entry in QUEUE.md"
    )


# ---------------------------------------------------------------------------
# R2 Test 16: quota_overflow_action=raise — RuntimeError raised (WARNING 4)
# ---------------------------------------------------------------------------


def test_overflow_action_raise_raises_runtime_error(project_root: Path):
    """quota_overflow_action='raise' — _register_quota_question raises RuntimeError."""
    q = GeminiQuota(project_root, daily_cap=10, overflow_action="raise")
    with pytest.raises(RuntimeError, match="quota_overflow_action=raise"):
        q._register_quota_question()


# ---------------------------------------------------------------------------
# R2 Test 17: fallback_on_quota_exceeded=false — direct Plan B (WARNING 4)
# ---------------------------------------------------------------------------


def test_fallback_on_quota_exceeded_false_skips_fallback_model(project_root: Path):
    """fallback_on_quota_exceeded=false: quota exhaustion goes directly to Plan B.

    Verifies dispatcher does NOT call _try_fallback_model when config says false.
    """
    # Write a gemini.yaml with fallback_on_quota_exceeded=false
    config_dir = project_root / "server" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "gemini.yaml").write_text(
        "daily_call_cap: 50\nquota_overflow_action: questions_queue\nfallback_on_quota_exceeded: false\n",
        encoding="utf-8",
    )

    img = project_root / ".cache" / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    dispatcher = GeminiDispatcher(project_root=project_root)
    assert dispatcher._fallback_on_quota_exceeded is False, (
        "Dispatcher must read fallback_on_quota_exceeded=false from config"
    )

    invoke_calls: List[str] = []
    handoff_calls: List[str] = []

    def fake_invoke(cmd, *, env):
        model_arg = ""
        for i, arg in enumerate(cmd):
            if arg == "-m" and i + 1 < len(cmd):
                model_arg = cmd[i + 1]
        invoke_calls.append(model_arg)
        # Primary model reports quota exhaustion
        return "", "RESOURCE_EXHAUSTED: daily limit exceeded", 1

    def fake_handoff(ticket_id, *, prompt, image_paths):
        handoff_calls.append(ticket_id)

    dispatcher._invoke = fake_invoke  # type: ignore[method-assign]
    dispatcher.handoff_fallback = fake_handoff  # type: ignore[method-assign]

    with patch.object(dispatcher, "_ensure_smoke_cache"):
        result = dispatcher.run(
            ticket_id="T-OSN-TEST-NOFALLBACK",
            prompt="check this",
            image_paths=[str(img)],
            gui_review_required=False,
        )

    # Only 1 invoke call — fallback model must NOT have been tried
    assert len(invoke_calls) == 1, (
        f"Expected exactly 1 invoke call (no fallback), got {len(invoke_calls)}: {invoke_calls}"
    )
    # Plan B handoff must still be triggered
    assert handoff_calls, "Plan B handoff must be triggered even with fallback_on_quota_exceeded=false"
    assert result.success is False


# ---------------------------------------------------------------------------
# R2 Test 18: explicit daily_cap=50 overrides config cap=100 (WARNING 5)
# ---------------------------------------------------------------------------


def test_dispatcher_explicit_daily_cap_overrides_config(project_root: Path):
    """explicit daily_cap=50 is not overridden by config daily_call_cap=100 (WARNING 5 fix)."""
    config_dir = project_root / "server" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "gemini.yaml").write_text(
        "daily_call_cap: 100\nquota_overflow_action: questions_queue\nfallback_on_quota_exceeded: true\n",
        encoding="utf-8",
    )
    dispatcher = GeminiDispatcher(project_root=project_root, daily_cap=50)
    assert dispatcher.daily_cap == 50, (
        f"Explicit daily_cap=50 must win over config cap=100; got {dispatcher.daily_cap}"
    )


# ---------------------------------------------------------------------------
# R2 Test 19: daily_cap=None reads config cap (WARNING 5)
# ---------------------------------------------------------------------------


def test_dispatcher_none_daily_cap_reads_config(project_root: Path):
    """daily_cap=None causes dispatcher to read daily_call_cap from gemini.yaml (WARNING 5 fix)."""
    config_dir = project_root / "server" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "gemini.yaml").write_text(
        "daily_call_cap: 77\nquota_overflow_action: questions_queue\nfallback_on_quota_exceeded: true\n",
        encoding="utf-8",
    )
    dispatcher = GeminiDispatcher(project_root=project_root, daily_cap=None)
    assert dispatcher.daily_cap == 77, (
        f"daily_cap=None must read config value 77; got {dispatcher.daily_cap}"
    )

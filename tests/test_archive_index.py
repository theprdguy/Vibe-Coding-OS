"""Tests for ARCHIVE-INDEX.yaml and bin/osn lookup --archive (T-OSN-W7-OPT-06)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml
import pytest

from server.ssot import (
    archive_done_tickets,
    archive_path_for_queue,
    build_archive_index,
    find_archived_ticket,
    index_path_for_archive,
)


# ── Helpers ────────────────────────────────────────────────────────────────


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_archive(path: Path, ticket_ids: list[str]) -> None:
    tickets = [{"id": tid, "owner": "CODEX", "status": "done", "goal": f"{tid} goal"} for tid in ticket_ids]
    _write_yaml(path, {"version": "3.0", "tickets": tickets})


def _write_queue(path: Path, ticket_ids: list[str], status: str = "todo") -> None:
    tickets = [{"id": tid, "owner": "CODEX", "status": status, "goal": f"{tid} goal"} for tid in ticket_ids]
    _write_yaml(path, {"version": "3.0", "tickets": tickets})


# ── index_path_for_archive ─────────────────────────────────────────────────


def test_index_path_for_archive_is_sibling(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    idx = index_path_for_archive(archive)
    assert idx == tmp_path / "ARCHIVE-INDEX.yaml"


# ── build_archive_index ────────────────────────────────────────────────────


def test_build_archive_index_creates_index_file(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-A", "T-B", "T-C"])
    idx_path = tmp_path / "ARCHIVE-INDEX.yaml"

    build_archive_index(archive)

    assert idx_path.exists()


def test_build_archive_index_maps_all_ticket_ids(tmp_path: Path) -> None:
    from server.ssot import ARCHIVE_INDEX_MTIME_KEY

    ids = [f"T-TICKET-{i:03d}" for i in range(10)]
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ids)

    build_archive_index(archive)

    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    assert isinstance(idx, dict)
    # Filter out reserved metadata keys (__ prefix) before comparing ticket ids.
    ticket_keys = {k for k in idx.keys() if not k.startswith("__")}
    assert ticket_keys == set(ids)
    # The mtime key must also be present.
    assert ARCHIVE_INDEX_MTIME_KEY in idx


def test_build_archive_index_values_are_integers(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-X", "T-Y"])

    build_archive_index(archive)

    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    for tid, lineno in idx.items():
        assert isinstance(lineno, int), f"{tid}: expected int, got {type(lineno)}"
        assert lineno >= 1


def test_build_archive_index_is_idempotent(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-A", "T-B"])

    build_archive_index(archive)
    first = (tmp_path / "ARCHIVE-INDEX.yaml").read_text()

    build_archive_index(archive)
    second = (tmp_path / "ARCHIVE-INDEX.yaml").read_text()

    assert first == second


def test_build_archive_index_overwrites_stale_index(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-OLD"])
    build_archive_index(archive)

    # Now update archive with new ticket
    _write_archive(archive, ["T-OLD", "T-NEW"])
    build_archive_index(archive)

    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    assert "T-NEW" in idx
    assert "T-OLD" in idx


def test_build_archive_index_real_archive_has_100_plus_entries() -> None:
    """Integration: real ARCHIVE.yaml must have >= 100 entries in INDEX."""
    repo_root = Path(__file__).resolve().parent.parent
    archive = repo_root / "devos" / "tasks" / "ARCHIVE.yaml"
    if not archive.exists():
        pytest.skip("ARCHIVE.yaml not present in this checkout")

    build_archive_index(archive)

    idx_path = index_path_for_archive(archive)
    idx = yaml.safe_load(idx_path.read_text())
    assert isinstance(idx, dict)
    assert len(idx) >= 100, f"Expected >= 100 entries, got {len(idx)}"


def test_build_archive_index_all_ids_present_or_raises(tmp_path: Path) -> None:
    """All ticket IDs in ARCHIVE.yaml must appear in INDEX after rebuild."""
    ids = ["T-ALPHA", "T-BETA", "T-GAMMA"]
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ids)

    build_archive_index(archive)

    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    missing = [tid for tid in ids if tid not in idx]
    assert missing == [], f"Missing from INDEX: {missing}"


# ── find_archived_ticket ───────────────────────────────────────────────────


def test_find_archived_ticket_returns_ticket_dict(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-TARGET", "T-OTHER"])
    build_archive_index(archive)

    ticket = find_archived_ticket(archive, "T-TARGET")

    assert ticket is not None
    assert ticket["id"] == "T-TARGET"


def test_find_archived_ticket_returns_none_when_missing(tmp_path: Path) -> None:
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-EXISTS"])
    build_archive_index(archive)

    result = find_archived_ticket(archive, "T-DOES-NOT-EXIST")

    assert result is None


def test_find_archived_ticket_works_without_index_file(tmp_path: Path) -> None:
    """Fallback: if INDEX missing, still returns ticket (builds index on demand)."""
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-NO-INDEX"])
    # Deliberately do NOT call build_archive_index

    ticket = find_archived_ticket(archive, "T-NO-INDEX")

    assert ticket is not None
    assert ticket["id"] == "T-NO-INDEX"


def test_find_archived_ticket_returns_correct_among_many(tmp_path: Path) -> None:
    ids = [f"T-BULK-{i:04d}" for i in range(50)]
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ids)
    build_archive_index(archive)

    for target in ["T-BULK-0000", "T-BULK-0025", "T-BULK-0049"]:
        result = find_archived_ticket(archive, target)
        assert result is not None
        assert result["id"] == target


# ── archive_done_tickets rebuilds INDEX ───────────────────────────────────


def test_archive_done_tickets_rebuilds_index(tmp_path: Path) -> None:
    queue = tmp_path / "QUEUE.yaml"
    archive = archive_path_for_queue(queue)
    _write_queue(queue, ["T-EXISTING"], status="done")
    _write_archive(archive, ["T-PRE"])
    build_archive_index(archive)

    idx_before = yaml.safe_load(index_path_for_archive(archive).read_text())
    assert "T-EXISTING" not in idx_before

    archive_done_tickets(queue)

    idx_path = index_path_for_archive(archive)
    assert idx_path.exists()
    idx_after = yaml.safe_load(idx_path.read_text())
    assert "T-EXISTING" in idx_after, "Newly archived ticket must appear in INDEX"
    assert "T-PRE" in idx_after


def test_archive_done_tickets_index_count_increases(tmp_path: Path) -> None:
    queue = tmp_path / "QUEUE.yaml"
    archive = archive_path_for_queue(queue)
    _write_archive(archive, [])
    _write_queue(queue, ["T-NEW-01", "T-NEW-02"], status="done")
    build_archive_index(archive)

    archive_done_tickets(queue)

    idx = yaml.safe_load(index_path_for_archive(archive).read_text())
    # Index contains ticket entries plus the reserved __mtime_ns__ metadata key.
    ticket_count = sum(1 for k in idx if not k.startswith("__"))
    assert ticket_count == 2


# ── find_ticket regression (dispatcher compat) ─────────────────────────────


def test_find_ticket_still_finds_archived_via_read_queue_with_archive(tmp_path: Path) -> None:
    """Regression: find_ticket() caller signature must remain intact."""
    from server.ssot import find_ticket

    queue = tmp_path / "QUEUE.yaml"
    archive = archive_path_for_queue(queue)
    _write_queue(queue, ["T-ACTIVE"])
    _write_archive(archive, ["T-ARCHIVED"])
    build_archive_index(archive)

    ticket, source = find_ticket(queue, "T-ARCHIVED")

    assert ticket is not None
    assert ticket["id"] == "T-ARCHIVED"
    assert source == "archive"


def test_find_ticket_signature_unchanged_for_queue_ticket(tmp_path: Path) -> None:
    """find_ticket(queue_path, ticket_id) -> (dict | None, str | None) must work."""
    from server.ssot import find_ticket

    queue = tmp_path / "QUEUE.yaml"
    _write_queue(queue, ["T-QUEUE-TICKET"])

    ticket, source = find_ticket(queue, "T-QUEUE-TICKET")

    assert ticket is not None
    assert source == "queue"


# ── CLI: bin/osn lookup --archive ─────────────────────────────────────────


def _run_osn(
    args: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    repo_root = Path(__file__).resolve().parent.parent
    env_cwd = cwd or repo_root
    bin_deos = repo_root / "bin" / "deos"
    run_env = {**__import__("os").environ, "PYTHONPATH": str(repo_root)}
    if env:
        run_env.update(env)
    result = subprocess.run(
        [sys.executable, str(bin_deos), *args],
        cwd=str(env_cwd),
        env=run_env,
        capture_output=True,
        text=True,
    )
    return result


def _make_lookup_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    """Build a self-contained host+project fixture for CLI lookup tests.

    Returns (host_dir, project_dir, ticket_id).
    The project QUEUE.yaml contains exactly one ticket with the returned id.
    """
    repo_root = Path(__file__).resolve().parent.parent
    ticket_id = "T-TEST-LOOKUP-01"

    host = tmp_path / "host"
    (host / "projects").mkdir(parents=True)
    # Minimal host deos.yaml — copy real file so all keys resolve correctly.
    (host / "deos.yaml").write_text(
        (repo_root / "deos.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    proj = host / "projects" / "test-proj"
    (proj / "devos" / "tasks").mkdir(parents=True)
    (proj / ".deos.yaml").write_text("name: test-proj\n", encoding="utf-8")
    (proj / "devos" / "tasks" / "QUEUE.yaml").write_text(
        f"version: '3.0'\ntickets:\n"
        f"  - id: {ticket_id}\n"
        f"    owner: CODEX\n"
        f"    status: todo\n"
        f"    goal: self-contained lookup fixture\n",
        encoding="utf-8",
    )
    (proj / "devos" / "tasks" / "ARCHIVE.yaml").write_text(
        "version: '3.0'\ntickets: []\n", encoding="utf-8"
    )
    return host, proj, ticket_id


def test_cli_lookup_archive_flag_not_found_exits_1() -> None:
    """bin/osn lookup --archive T-DOES-NOT-EXIST: exit 1 + stderr contains not_found."""
    result = _run_osn(["lookup", "--archive", "T-DOES-NOT-EXIST"])
    assert result.returncode == 1
    assert "not_found" in result.stderr or "not found" in result.stderr


def test_cli_lookup_queue_ticket_returns_yaml(tmp_path: Path) -> None:
    """bin/deos lookup <id> should return YAML with id field (ticket is in QUEUE).

    Uses a self-contained tmp fixture so the test passes regardless of the
    host repo's QUEUE contents (public template compatibility).
    """
    host, proj, ticket_id = _make_lookup_fixture(tmp_path)
    result = _run_osn(
        ["lookup", ticket_id],
        cwd=proj,
        env={"OS3_HOST_ROOT": str(host), "PWD": str(proj)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = yaml.safe_load(result.stdout)
    assert data is not None
    assert data.get("id") == ticket_id


def test_cli_lookup_archive_parseable_yaml(tmp_path: Path) -> None:
    """bin/osn lookup --archive returns parseable YAML ticket."""
    # Use real repo archive for an archived ticket
    repo_root = Path(__file__).resolve().parent.parent
    archive = repo_root / "devos" / "tasks" / "ARCHIVE.yaml"
    if not archive.exists():
        pytest.skip("ARCHIVE.yaml not present")

    # Pick first archived ticket ID
    data = yaml.safe_load(archive.read_text())
    first_id = data["tickets"][0]["id"]

    result = _run_osn(["lookup", "--archive", first_id])
    assert result.returncode == 0, f"stderr: {result.stderr}"
    parsed = yaml.safe_load(result.stdout)
    assert parsed is not None
    assert parsed.get("id") == first_id


def test_cli_lookup_archive_first_3_lines_contain_id(tmp_path: Path) -> None:
    """head -3 of lookup --archive output should include 'id:' line."""
    repo_root = Path(__file__).resolve().parent.parent
    archive = repo_root / "devos" / "tasks" / "ARCHIVE.yaml"
    if not archive.exists():
        pytest.skip("ARCHIVE.yaml not present")

    data = yaml.safe_load(archive.read_text())
    first_id = data["tickets"][0]["id"]

    result = _run_osn(["lookup", "--archive", first_id])
    assert result.returncode == 0
    first_3 = "\n".join(result.stdout.splitlines()[:3])
    assert "id:" in first_3


def test_cli_lookup_no_archive_flag_still_works_for_queue_ticket(tmp_path: Path) -> None:
    """Lookup without --archive must resolve a QUEUE ticket (regression guard).

    Uses a self-contained tmp fixture so the test passes regardless of the
    host repo's QUEUE contents (public template compatibility).
    """
    host, proj, ticket_id = _make_lookup_fixture(tmp_path)
    result = _run_osn(
        ["lookup", ticket_id],
        cwd=proj,
        env={"OS3_HOST_ROOT": str(host), "PWD": str(proj)},
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    data = yaml.safe_load(result.stdout)
    assert data["id"] == ticket_id


# ── F1: quoted id fix (OPT-07) ────────────────────────────────────────────


def test_build_archive_index_handles_quoted_id_single_quotes(tmp_path: Path) -> None:
    """F1: ARCHIVE.yaml with quoted ids like `- id: 'T-WITH-QUOTE'` must not raise."""
    archive = tmp_path / "ARCHIVE.yaml"
    # Write YAML with single-quoted id (valid YAML, but line-scanner must strip quotes)
    archive.write_text(
        "version: '3.0'\ntickets:\n  - id: 'T-WITH-QUOTE'\n    owner: CODEX\n    status: done\n    goal: quoted\n",
        encoding="utf-8",
    )
    # Should not raise ValueError — quoted id must match YAML-parsed id
    build_archive_index(archive)
    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    assert "T-WITH-QUOTE" in idx


def test_build_archive_index_handles_quoted_id_double_quotes(tmp_path: Path) -> None:
    """F1: ARCHIVE.yaml with double-quoted ids like `- id: "T-DBL"` must not raise."""
    archive = tmp_path / "ARCHIVE.yaml"
    archive.write_text(
        'version: "3.0"\ntickets:\n  - id: "T-DBL-QUOTE"\n    owner: CODEX\n    status: done\n    goal: dbl\n',
        encoding="utf-8",
    )
    build_archive_index(archive)
    idx = yaml.safe_load((tmp_path / "ARCHIVE-INDEX.yaml").read_text())
    assert "T-DBL-QUOTE" in idx


# ── F2: ValueError on malformed ARCHIVE (OPT-07) ──────────────────────────


def test_build_archive_index_raises_value_error_on_malformed_archive(tmp_path: Path) -> None:
    """F2: ARCHIVE where YAML-parsed ids mismatch line-scan raises ValueError (integrity guard)."""
    archive = tmp_path / "ARCHIVE.yaml"
    # Craft a file where a ticket's id in YAML is present but line-scanner
    # cannot locate it (e.g. id field is deeply indented or non-standard).
    # We simulate this by writing a ticket whose id is entirely missing from
    # any `- id:` line (raw YAML where id appears only as a nested key).
    archive.write_text(
        "version: '3.0'\n"
        "tickets:\n"
        "  - owner: CODEX\n"
        "    status: done\n"
        "    goal: orphan\n"
        "    id: T-ORPHAN-ID\n",  # id is NOT the first key — line-scanner misses `- id:` pattern
        encoding="utf-8",
    )
    # YAML parses id=T-ORPHAN-ID but line-scanner finds no `- id:` line → ValueError
    with pytest.raises(ValueError, match="INDEX integrity error"):
        build_archive_index(archive)


# ── F3: atomic write + lock in find_archived_ticket fallback (OPT-07) ──────


def test_find_archived_ticket_fallback_produces_atomic_index(tmp_path: Path) -> None:
    """F3: fallback index build must result in a valid index file (atomic write guard)."""
    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-ATOMIC-01", "T-ATOMIC-02"])
    idx_path = index_path_for_archive(archive)
    # No pre-existing index
    assert not idx_path.exists()

    ticket = find_archived_ticket(archive, "T-ATOMIC-01")
    assert ticket is not None
    assert ticket["id"] == "T-ATOMIC-01"

    # Index file must exist and be valid YAML after fallback
    assert idx_path.exists()
    idx = yaml.safe_load(idx_path.read_text(encoding="utf-8"))
    assert isinstance(idx, dict)
    assert "T-ATOMIC-01" in idx
    assert "T-ATOMIC-02" in idx


def test_build_archive_index_write_is_atomic(tmp_path: Path, monkeypatch) -> None:
    """F3: build_archive_index must use atomic write (os.replace) not direct open('w')."""
    import os
    replacements: list[tuple[str, str]] = []
    original_replace = os.replace

    def capturing_replace(src: str, dst: str) -> None:
        replacements.append((src, dst))
        original_replace(src, dst)

    monkeypatch.setattr(os, "replace", capturing_replace)

    archive = tmp_path / "ARCHIVE.yaml"
    _write_archive(archive, ["T-ATOM-A", "T-ATOM-B"])
    build_archive_index(archive)

    assert len(replacements) >= 1, "os.replace not called — write is not atomic"
    # The destination must be the index file path
    idx_path = str(index_path_for_archive(archive))
    assert any(dst == idx_path for _, dst in replacements), (
        f"os.replace destination was not INDEX path. calls: {replacements}"
    )

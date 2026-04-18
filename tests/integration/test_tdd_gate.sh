#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    printf 'ASSERTION FAILED: expected output to contain: %s\n' "$needle" >&2
    printf '--- output ---\n%s\n-------------\n' "$haystack" >&2
    exit 1
  fi
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" == *"$needle"* ]]; then
    printf 'ASSERTION FAILED: expected output to not contain: %s\n' "$needle" >&2
    printf '--- output ---\n%s\n-------------\n' "$haystack" >&2
    exit 1
  fi
}

assert_exit_code() {
  local actual="$1"
  local expected="$2"
  if [ "$actual" -ne "$expected" ]; then
    printf 'ASSERTION FAILED: expected exit code %s, got %s\n' "$expected" "$actual" >&2
    exit 1
  fi
}

write_stub_gitleaks() {
  local repo_dir="$1"
  mkdir -p "$repo_dir/bin"
  cat > "$repo_dir/bin/gitleaks" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'gitleaks: clean\n'
exit 0
EOF
  chmod +x "$repo_dir/bin/gitleaks"
}

create_repo() {
  local name="$1"
  local ticket_id="$2"
  local tdd_mode="$3"
  local repo_dir="$TMP_DIR/$name"

  mkdir -p "$repo_dir/scripts" "$repo_dir/apps/api/src" "$repo_dir/tests" "$repo_dir/devos/logs" "$repo_dir/devos/tasks"
  cp "$ROOT_DIR/Makefile" "$repo_dir/Makefile"
  cp "$ROOT_DIR/scripts/check-contract-sync.sh" "$repo_dir/scripts/check-contract-sync.sh"
  cp "$ROOT_DIR/scripts/check-ticket-scope.sh" "$repo_dir/scripts/check-ticket-scope.sh"
  cp "$ROOT_DIR/scripts/check-session-log.sh" "$repo_dir/scripts/check-session-log.sh"
  cp "$ROOT_DIR/scripts/check-tdd-first-commit.sh" "$repo_dir/scripts/check-tdd-first-commit.sh" 2>/dev/null || true

  cat > "$repo_dir/apps/api/src/foo.py" <<'EOF'
print("baseline")
EOF

  cat > "$repo_dir/devos/tasks/QUEUE.yaml" <<EOF
version: '3.0'
tickets:
- id: ${ticket_id}
  owner: CODEX
  status: doing
  tdd: ${tdd_mode}
  files:
  - scripts/check-tdd-first-commit.sh
  - Makefile
  - tests/integration/test_tdd_gate.sh
EOF

  cat > "$repo_dir/devos/logs/2026-04-19-codex.md" <<'EOF'
# Session Log: CODEX — 2026-04-19
EOF

  (
    cd "$repo_dir"
    git init -q
    git config user.name "Test User"
    git config user.email "test@example.com"
    git add .
    git commit -qm "baseline"
  )

  write_stub_gitleaks "$repo_dir"
  printf '%s\n' "$repo_dir"
}

commit_for_ticket() {
  local repo_dir="$1"
  local ticket_id="$2"
  local path="$3"
  local content="$4"

  mkdir -p "$(dirname "$repo_dir/$path")"
  printf '%s\n' "$content" > "$repo_dir/$path"
  (
    cd "$repo_dir"
    git add "$path"
    git commit -qm "${ticket_id} add $(basename "$path")"
  )
}

run_tdd_check() {
  local repo_dir="$1"
  local output_file="$repo_dir/tdd.out"
  local exit_code=0

  (
    cd "$repo_dir"
    AGENT_NAME=codex bash scripts/check-tdd-first-commit.sh
  ) >"$output_file" 2>&1 || exit_code=$?

  TDD_OUTPUT="$(cat "$output_file")"
  TDD_EXIT_CODE="$exit_code"
}

run_pr_check() {
  local repo_dir="$1"
  local output_file="$repo_dir/pr-check.out"
  local exit_code=0

  (
    cd "$repo_dir"
    PATH="$repo_dir/bin:$PATH" AGENT_NAME=codex make pr-check
  ) >"$output_file" 2>&1 || exit_code=$?

  PR_CHECK_OUTPUT="$(cat "$output_file")"
  PR_CHECK_EXIT_CODE="$exit_code"
}

test_required_ticket_fails_without_test_files() {
  local repo_dir
  repo_dir="$(create_repo required-fail T-X required)"
  commit_for_ticket "$repo_dir" "T-X" "apps/api/src/foo.py" "print('impl only')"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 1
  assert_contains "$TDD_OUTPUT" "T-X first commit lacks test files"
}

test_required_ticket_passes_with_tests_directory_file() {
  local repo_dir
  repo_dir="$(create_repo required-tests-dir T-Y required)"
  commit_for_ticket "$repo_dir" "T-Y" "tests/test_foo.py" "def test_foo():\n    assert True"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 0
  assert_contains "$TDD_OUTPUT" "PASS tdd-first-commit"
  assert_contains "$TDD_OUTPUT" "T-Y"
}

test_required_ticket_passes_with_suffix_test_file() {
  local repo_dir
  repo_dir="$(create_repo required-suffix T-Z required)"
  commit_for_ticket "$repo_dir" "T-Z" "apps/api/src/foo_test.py" "def test_foo():\n    assert True"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 0
  assert_contains "$TDD_OUTPUT" "PASS tdd-first-commit"
  assert_contains "$TDD_OUTPUT" "T-Z"
}

test_skip_ticket_passes_without_tests() {
  local repo_dir
  repo_dir="$(create_repo skip-pass T-SKIP skip)"
  commit_for_ticket "$repo_dir" "T-SKIP" "apps/api/src/foo.py" "print('skip')"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 0
  assert_contains "$TDD_OUTPUT" "TDD skip"
}

test_self_evident_ticket_records_waiver() {
  local repo_dir
  repo_dir="$(create_repo self-evident T-WAIVE self-evident)"
  commit_for_ticket "$repo_dir" "T-WAIVE" "apps/api/src/foo.py" "print('waive')"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 0
  assert_contains "$TDD_OUTPUT" "self-evident"
  assert_contains "$(cat "$repo_dir/devos/logs/2026-04-19-codex.md")" "self-evident TDD waiver for T-WAIVE"
}

test_missing_ticket_commit_is_skipped() {
  local repo_dir
  repo_dir="$(create_repo missing-ticket T-NO-COMMIT required)"
  commit_for_ticket "$repo_dir" "OTHER-1" "apps/api/src/foo.py" "print('other ticket')"

  run_tdd_check "$repo_dir"

  assert_exit_code "$TDD_EXIT_CODE" 0
  assert_contains "$TDD_OUTPUT" "not found in commit history"
  assert_not_contains "$TDD_OUTPUT" "lacks test files"
}

test_pr_check_runs_tdd_gate_as_fifth_gate() {
  local repo_dir
  repo_dir="$(create_repo pr-check T-PR required)"
  commit_for_ticket "$repo_dir" "T-PR" "tests/test_foo.py" "def test_foo():\n    assert True"

  run_pr_check "$repo_dir"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "[5/5] tdd-first-commit"
  assert_contains "$PR_CHECK_OUTPUT" "All baseline gates passed"
}

test_required_ticket_fails_without_test_files
test_required_ticket_passes_with_tests_directory_file
test_required_ticket_passes_with_suffix_test_file
test_skip_ticket_passes_without_tests
test_self_evident_ticket_records_waiver
test_missing_ticket_commit_is_skipped
test_pr_check_runs_tdd_gate_as_fifth_gate

printf 'PASS: tdd first commit gate integration\n'

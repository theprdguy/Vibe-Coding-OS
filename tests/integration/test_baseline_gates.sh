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

assert_exit_code() {
  local actual="$1"
  local expected="$2"
  if [ "$actual" -ne "$expected" ]; then
    printf 'ASSERTION FAILED: expected exit code %s, got %s\n' "$expected" "$actual" >&2
    if [ -n "${PR_CHECK_OUTPUT:-}" ]; then
      printf '%s\n' '--- output ---' >&2
      printf '%s\n' "$PR_CHECK_OUTPUT" >&2
      printf '%s\n' '-------------' >&2
    fi
    exit 1
  fi
}

write_stub_gitleaks() {
  local repo_dir="$1"
  local mode="$2"
  mkdir -p "$repo_dir/bin"
  cat > "$repo_dir/bin/gitleaks" <<EOF
#!/usr/bin/env bash
set -euo pipefail
mode="${mode}"
if [ "\${mode}" = "detect-secret" ]; then
  if git grep -n "SECRET_TEST_VALUE" -- . >/dev/null 2>&1; then
    printf 'gitleaks: secret detected\n' >&2
    exit 1
  fi
fi
printf 'gitleaks: clean\n'
exit 0
EOF
  chmod +x "$repo_dir/bin/gitleaks"
}

create_repo() {
  local name="$1"
  local repo_dir="$TMP_DIR/$name"

  mkdir -p "$repo_dir/scripts" "$repo_dir/apps/api" "$repo_dir/apps/web" "$repo_dir/devos/docs" "$repo_dir/devos/logs" "$repo_dir/devos/tasks"
  mkdir -p "$repo_dir/.venv/bin"
  cp "$ROOT_DIR/scripts/check-contract-sync.sh" "$repo_dir/scripts/check-contract-sync.sh" 2>/dev/null || true
  cp "$ROOT_DIR/scripts/check-ticket-scope.sh" "$repo_dir/scripts/check-ticket-scope.sh" 2>/dev/null || true
  cp "$ROOT_DIR/scripts/check-session-log.sh" "$repo_dir/scripts/check-session-log.sh" 2>/dev/null || true
  cp "$ROOT_DIR/scripts/check-tdd-first-commit.sh" "$repo_dir/scripts/check-tdd-first-commit.sh" 2>/dev/null || true
  cp "$ROOT_DIR/scripts/setup.sh" "$repo_dir/scripts/setup.sh"
  ln -sf "$(command -v python3)" "$repo_dir/.venv/bin/python3"
  # Minimal deos.yaml so bin/deos pr-check stays in the temp repo dir (no auto-chdir to ROOT_DIR).
  printf 'project: test\n' > "$repo_dir/deos.yaml"

  cat > "$repo_dir/devos/docs/API_CONTRACT.md" <<'EOF'
# API Contract
EOF
  cat > "$repo_dir/devos/docs/UI_CONTRACT.md" <<'EOF'
# UI Contract
EOF
  cat > "$repo_dir/apps/api/app.txt" <<'EOF'
baseline api
EOF
  cat > "$repo_dir/apps/web/app.txt" <<'EOF'
baseline web
EOF
  cat > "$repo_dir/devos/tasks/QUEUE.yaml" <<'EOF'
version: '3.0'
tickets:
- id: T-INFRA-02
  owner: CODEX
  status: doing
  files:
  - Makefile
  - scripts/check-contract-sync.sh
  - scripts/check-ticket-scope.sh
  - scripts/check-session-log.sh
  - scripts/setup.sh
  - tests/integration/test_baseline_gates.sh
EOF
  # Use today's date so check-session-log.sh (which uses `date '+%Y-%m-%d'`) finds the log.
  local today
  today="$(date '+%Y-%m-%d')"
  cat > "$repo_dir/devos/logs/${today}-codex.md" <<'EOF'
# session log
EOF

  (
    cd "$repo_dir"
    git init -q
    git config user.name "Test User"
    git config user.email "test@example.com"
    git add .
    git commit -qm "baseline"
  )

  printf '%s\n' "$repo_dir"
}

run_pr_check() {
  local repo_dir="$1"
  local agent_name="${2-}"
  local output_file="$repo_dir/pr-check.out"
  local exit_code=0

  (
    cd "$repo_dir"
    if [ -n "$agent_name" ]; then
      PATH="$repo_dir/bin:$PATH" AGENT_NAME="$agent_name" \
        PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/bin/deos" pr-check
    else
      PATH="$repo_dir/bin:$PATH" \
        PYTHONPATH="$ROOT_DIR" python3 "$ROOT_DIR/bin/deos" pr-check
    fi
  ) >"$output_file" 2>&1 || exit_code=$?

  PR_CHECK_OUTPUT="$(cat "$output_file")"
  PR_CHECK_EXIT_CODE="$exit_code"
}

test_all_gates_pass() {
  local repo_dir
  repo_dir="$(create_repo pass)"
  write_stub_gitleaks "$repo_dir" "pass"

  run_pr_check "$repo_dir" "codex"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "scan-secrets"
  assert_contains "$PR_CHECK_OUTPUT" "contract-sync"
  assert_contains "$PR_CHECK_OUTPUT" "ticket-scope"
  assert_contains "$PR_CHECK_OUTPUT" "session-log"
  assert_contains "$PR_CHECK_OUTPUT" "All baseline gates passed"
}

test_secret_scan_fails() {
  local repo_dir
  repo_dir="$(create_repo secret)"
  write_stub_gitleaks "$repo_dir" "detect-secret"
  printf 'SECRET_TEST_VALUE\n' > "$repo_dir/scripts/leak.txt"

  (
    cd "$repo_dir"
    git add scripts/leak.txt
    git commit -qm "add secret fixture"
  )

  run_pr_check "$repo_dir" "codex"

  if [ "$PR_CHECK_EXIT_CODE" -eq 0 ]; then
    printf 'ASSERTION FAILED: secret scan should fail\n' >&2
    exit 1
  fi
  assert_contains "$PR_CHECK_OUTPUT" "secret detected"
}

test_contract_warning_when_docs_change_without_apps() {
  local repo_dir
  repo_dir="$(create_repo contract)"
  write_stub_gitleaks "$repo_dir" "pass"
  printf '\nupdated\n' >> "$repo_dir/devos/docs/API_CONTRACT.md"

  run_pr_check "$repo_dir" "codex"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "계약 변경 감지, 코드 변경 없음"
}

test_scope_guard_warns_for_out_of_scope_files() {
  local repo_dir
  repo_dir="$(create_repo scope)"
  write_stub_gitleaks "$repo_dir" "pass"
  printf '\nout of scope\n' >> "$repo_dir/apps/api/app.txt"

  run_pr_check "$repo_dir" "codex"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "scope guard warning"
  assert_contains "$PR_CHECK_OUTPUT" "apps/api/app.txt"
}

test_session_log_missing_warns() {
  local repo_dir
  repo_dir="$(create_repo session-log)"
  write_stub_gitleaks "$repo_dir" "pass"
  rm -f "$repo_dir/devos/logs/"*-codex.md

  run_pr_check "$repo_dir" "codex"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "session log missing"
  assert_contains "$PR_CHECK_OUTPUT" "Set AGENT_NAME env or mark ticket as doing"
  assert_contains "$PR_CHECK_OUTPUT" "AGENT_NAME=CODEX bin/deos pr-check"
}

test_session_log_prefers_agent_name_env() {
  local repo_dir
  repo_dir="$(create_repo env-agent)"
  write_stub_gitleaks "$repo_dir" "pass"
  local today
  today="$(date '+%Y-%m-%d')"
  cat > "$repo_dir/devos/logs/${today}-claude1.md" <<'EOF'
# claude1 session log
EOF

  run_pr_check "$repo_dir" "CLAUDE1"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "✅ PASS session-log"
  if [[ "$PR_CHECK_OUTPUT" == *"(fallback)"* ]]; then
    printf 'ASSERTION FAILED: env-based session-log check should not use fallback\n' >&2
    exit 1
  fi
}

test_session_log_falls_back_to_git_email() {
  local repo_dir
  repo_dir="$(create_repo fallback-git-email)"
  write_stub_gitleaks "$repo_dir" "pass"
  python3 - <<'PY' "$repo_dir/devos/tasks/QUEUE.yaml"
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text("""version: '3.0'\ntickets:\n- id: T-INFRA-02\n  owner: CODEX\n  status: todo\n  files:\n  - Makefile\n  - scripts/check-contract-sync.sh\n  - scripts/check-ticket-scope.sh\n  - scripts/check-session-log.sh\n  - scripts/setup.sh\n  - tests/integration/test_baseline_gates.sh\n""")
PY
  (
    cd "$repo_dir"
    git config user.email "claude2@example.com"
  )
  local today
  today="$(date '+%Y-%m-%d')"
  rm -f "$repo_dir/devos/logs/"*-codex.md
  cat > "$repo_dir/devos/logs/${today}-claude2.md" <<'EOF'
# claude2 session log
EOF

  run_pr_check "$repo_dir"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "✅ PASS session-log (fallback)"
}

test_session_log_falls_back_to_claude_config() {
  local repo_dir
  repo_dir="$(create_repo fallback-claude-config)"
  write_stub_gitleaks "$repo_dir" "pass"
  python3 - <<'PY' "$repo_dir/devos/tasks/QUEUE.yaml"
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text("""version: '3.0'\ntickets:\n- id: T-INFRA-02\n  owner: CODEX\n  status: todo\n  files:\n  - Makefile\n  - scripts/check-contract-sync.sh\n  - scripts/check-ticket-scope.sh\n  - scripts/check-session-log.sh\n  - scripts/setup.sh\n  - tests/integration/test_baseline_gates.sh\n""")
PY
  (
    cd "$repo_dir"
    git config --unset user.email
  )
  mkdir -p "$repo_dir/.claude"
  cat > "$repo_dir/.claude/.claude.json" <<'EOF'
{}
EOF
  local today
  today="$(date '+%Y-%m-%d')"
  rm -f "$repo_dir/devos/logs/"*-codex.md
  cat > "$repo_dir/devos/logs/${today}-claude1.md" <<'EOF'
# claude1 session log
EOF

  run_pr_check "$repo_dir"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "✅ PASS session-log (fallback)"
}

test_session_log_defaults_to_codex_fallback() {
  local repo_dir
  repo_dir="$(create_repo fallback-codex)"
  write_stub_gitleaks "$repo_dir" "pass"
  python3 - <<'PY' "$repo_dir/devos/tasks/QUEUE.yaml"
from pathlib import Path
import sys

path = Path(sys.argv[1])
path.write_text("""version: '3.0'\ntickets:\n- id: T-INFRA-02\n  owner: CODEX\n  status: todo\n  files:\n  - Makefile\n  - scripts/check-contract-sync.sh\n  - scripts/check-ticket-scope.sh\n  - scripts/check-session-log.sh\n  - scripts/setup.sh\n  - tests/integration/test_baseline_gates.sh\n""")
PY
  (
    cd "$repo_dir"
    git config --unset user.email
  )
  rm -rf "$repo_dir/.claude" "$repo_dir/.claude-b"

  run_pr_check "$repo_dir"

  assert_exit_code "$PR_CHECK_EXIT_CODE" 0
  assert_contains "$PR_CHECK_OUTPUT" "✅ PASS session-log (fallback)"
}

test_setup_warns_when_gitleaks_missing() {
  local repo_dir
  repo_dir="$(create_repo setup)"
  PATH="/usr/bin:/bin:/usr/sbin:/sbin" bash "$repo_dir/scripts/setup.sh" >"$repo_dir/setup.out" 2>&1 || true
  local output
  output="$(cat "$repo_dir/setup.out")"
  assert_contains "$output" "gitleaks not found"
  assert_contains "$output" "brew install gitleaks"
}

test_all_gates_pass
test_secret_scan_fails
test_contract_warning_when_docs_change_without_apps
test_scope_guard_warns_for_out_of_scope_files
test_session_log_missing_warns
test_session_log_prefers_agent_name_env
test_session_log_falls_back_to_git_email
test_session_log_falls_back_to_claude_config
test_session_log_defaults_to_codex_fallback
test_setup_warns_when_gitleaks_missing

printf 'PASS: baseline gates integration\n'

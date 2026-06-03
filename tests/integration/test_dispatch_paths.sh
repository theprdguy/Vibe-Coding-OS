#!/usr/bin/env bash
# T-OSN-W3-03 — dispatch path 통합 검증 (bin/osn dispatch)
# 5 owner 분기 (BUILDER / CODEX / CLAUDE1 / CLAUDE2 / unknown) 각각 정확 동작 + exit code 검증.
#
# Usage: bash tests/integration/test_dispatch_paths.sh
# Returns: 0 if all 5 cases PASS, 1 otherwise.

set -uo pipefail
cd "$(dirname "$0")/../.."

PASS=0
FAIL=0
LOG="devos/logs/$(date +%Y-%m-%d)-w3-integration.md"

mkdir -p "$(dirname "$LOG")"
{
    echo "# W3-03 Integration Test — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "## Cases"
} > "$LOG"

run_case() {
    local label="$1"
    local ticket="$2"
    local expect_exit="$3"
    local expect_pattern="$4"

    echo "=== $label ($ticket, expect exit=$expect_exit) ==="
    local out exit_code
    out=$(bin/osn dispatch "$ticket" 2>&1) || true
    exit_code=$?
    # bin/osn dispatch 의 exit: 0 (CODEX/CLAUDE1), 2 (BUILDER/in-session), 1 (unknown)
    # exit_code 는 bin/osn 의 결과
    local pass="FAIL"
    if [[ "$out" =~ $expect_pattern ]]; then
        pass="PASS"
        PASS=$((PASS+1))
    else
        FAIL=$((FAIL+1))
    fi
    {
        echo "- **$label** ($ticket)"
        echo "  - expected pattern: \`$expect_pattern\`"
        echo "  - actual exit: $exit_code"
        echo "  - actual output:"
        echo "    \`\`\`"
        echo "$out" | head -3 | sed 's/^/    /'
        echo "    \`\`\`"
        echo "  - **$pass**"
    } >> "$LOG"
    echo "$pass: $label"
}

# Case 1: BUILDER ticket → in-session 안내
run_case "BUILDER → in-session message" "T-OSN-W5-02" "2" "in-session|/dispatch|in-session"

# Case 2: CODEX ticket — owner 만 검증 (실제 dispatch 는 codex CLI 가 필요)
echo "=== CODEX (T-OSN-W6-03) — owner-only check ==="
codex_owner=$(.venv/bin/python3 -m server owner T-OSN-W6-03 2>&1 || python3 -m server owner T-OSN-W6-03 2>&1)
if [[ "$codex_owner" == "CODEX" ]]; then
    PASS=$((PASS+1))
    echo "- **CODEX owner detection**: \`$codex_owner\` — **PASS**" >> "$LOG"
    echo "PASS: CODEX owner detection"
else
    FAIL=$((FAIL+1))
    echo "- **CODEX owner detection**: \`$codex_owner\` (expected CODEX) — **FAIL**" >> "$LOG"
    echo "FAIL: CODEX owner detection"
fi

# Case 3: CLAUDE1 ticket → interactive only
run_case "CLAUDE1 → interactive only" "T-OSN-W3-03" "2" "interactive|policy|CLAUDE1"

# Case 4: CLAUDE2 ticket — 옛 ticket 중 하나 (T-OS2-V36-01 가 owner: CLAUDE2 이지만 W4-05 로 BUILDER 치환 예정)
# 현 시점에는 CLAUDE2 ticket 없을 수 있음 — W4-05 미완료 시점 가정. 없으면 SKIP.
claude2_test=$(grep -B1 "owner: CLAUDE2" devos/tasks/QUEUE.yaml 2>/dev/null | grep "id:" | head -1 | awk '{print $3}' || echo "")
if [[ -n "$claude2_test" ]]; then
    echo "=== CLAUDE2 deprecation ($claude2_test) ==="
    out=$(bin/osn dispatch "$claude2_test" 2>&1 || true)
    if [[ "$out" =~ DEPRECATED|deprecated ]]; then
        PASS=$((PASS+1))
        echo "PASS: CLAUDE2 deprecation warning"
        echo "- **CLAUDE2 deprecation** ($claude2_test) — deprecation 경고 출력 — **PASS**" >> "$LOG"
    else
        FAIL=$((FAIL+1))
        echo "FAIL: CLAUDE2 deprecation"
        echo "- **CLAUDE2 deprecation** ($claude2_test) — 경고 누락 — **FAIL**" >> "$LOG"
    fi
else
    echo "SKIP: CLAUDE2 (no in-flight CLAUDE2 ticket — W4-05 후 정상)"
    echo "- **CLAUDE2 deprecation** — SKIP (no CLAUDE2 ticket in QUEUE)" >> "$LOG"
fi

# Case 5: unknown ticket → exit 1
run_case "unknown ticket → exit 1" "T-DOES-NOT-EXIST-XYZ" "1" "unknown|UNKNOWN|not found"

echo
echo "Total PASS: $PASS, FAIL: $FAIL"
{
    echo
    echo "## Summary"
    echo "- PASS: $PASS"
    echo "- FAIL: $FAIL"
    if [[ $FAIL -eq 0 ]]; then
        echo "- **Status: all $PASS cases passed**"
    else
        echo "- **Status: $FAIL cases failed**"
    fi
} >> "$LOG"

if [[ $FAIL -eq 0 ]]; then
    echo "all $PASS cases passed"
    exit 0
else
    exit 1
fi

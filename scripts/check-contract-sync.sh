#!/usr/bin/env bash

set -euo pipefail

changed_files() {
  local tracked untracked
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    tracked="$(git diff --name-only HEAD --)"
  else
    tracked="$(git diff --name-only --cached --)"
  fi
  untracked="$(git ls-files --others --exclude-standard)"
  printf '%s\n%s\n' "$tracked" "$untracked" | awk 'NF && !seen[$0]++'
}

printf '[2/4] contract-sync\n'

changes="$(changed_files)"
docs_changed=0
apps_changed=0

if printf '%s\n' "$changes" | grep -Eq '^devos/docs/(API_CONTRACT|UI_CONTRACT)\.md$'; then
  docs_changed=1
fi

if printf '%s\n' "$changes" | grep -Eq '^apps/'; then
  apps_changed=1
fi

if [ "$docs_changed" -eq 1 ] && [ "$apps_changed" -eq 0 ]; then
  echo "⚠️ WARN contract-sync: 계약 변경 감지, 코드 변경 없음"
elif [ "$docs_changed" -eq 0 ] && [ "$apps_changed" -eq 1 ]; then
  echo "⚠️ WARN contract-sync: 앱 코드 변경 감지, 계약 문서 변경 없음"
else
  echo "✅ PASS contract-sync"
fi

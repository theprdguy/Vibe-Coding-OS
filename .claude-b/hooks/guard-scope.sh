#!/bin/bash
# Guard: Prevent Claude 2 (Builder) from writing outside its allowed scope.
# Used as a Claude Code PreToolUse hook for Write/Edit tools.
#
# Exit 0 = allow, Exit 2 = block with message

INPUT=$(cat)

FILE_PATH=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('file_path',''))" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Normalize absolute paths to relative (strip project root prefix)
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
FILE_PATH=$(echo "$FILE_PATH" | sed "s|^${PROJECT_ROOT}/||")

# Strip leading ./ if present
FILE_PATH=$(echo "$FILE_PATH" | sed 's|^\./||')

# Allowed paths for Claude 2
ALLOWED_PATTERNS=(
  "^apps/api/src/"
  "^apps/web/"
  "^devos/docs/API_CONTRACT\.md$"
  "^devos/docs/UI_CONTRACT\.md$"
  "^devos/logs/"
)

for pattern in "${ALLOWED_PATTERNS[@]}"; do
  if echo "$FILE_PATH" | grep -qE "$pattern"; then
    exit 0
  fi
done

# Block everything else
echo ""
echo "BUILDER SCOPE GUARD: Write blocked — file outside allowed scope."
echo "   File: $FILE_PATH"
echo ""
echo "   Claude 2 (Builder) may only write to:"
echo "     - apps/api/src/**"
echo "     - apps/web/**"
echo "     - devos/docs/API_CONTRACT.md"
echo "     - devos/docs/UI_CONTRACT.md"
echo "     - devos/logs/**"
echo ""
echo "   If this file is needed, ask Claude 1 to update the ticket scope."
echo ""
exit 2

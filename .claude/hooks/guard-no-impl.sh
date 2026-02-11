#!/bin/bash
# Guard: Prevent Claude (Dispatcher) from writing implementation code.
# Used as a Claude Code PreToolUse hook for Write/Edit tools.
#
# This script reads the tool input from stdin (JSON) and checks if the
# target file is in an implementation directory.
#
# Exit 0 = allow, Exit 2 = block with message

# Read the tool input from stdin
INPUT=$(cat)

# Extract file path from the JSON input
FILE_PATH=$(echo "$INPUT" | grep -oE '"file_path"\s*:\s*"[^"]*"' | head -1 | sed 's/.*"file_path"\s*:\s*"//;s/"$//')

# If no file_path found, allow (might be a non-file tool)
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Implementation directories that Claude should NOT write to
IMPL_PATTERNS=(
  "src/"
  "app/"
  "apps/"
  "components/"
  "pages/"
  "lib/"
  "api/"
  "styles/"
  "public/"
  "assets/"
  "frontend/"
  "backend/"
  "packages/"
  "tests/"
  "__tests__/"
)

# Check if the file is in an implementation directory
for pattern in "${IMPL_PATTERNS[@]}"; do
  if echo "$FILE_PATH" | grep -qE "(^|/)${pattern}"; then
    echo ""
    echo "⚠️  DISPATCHER GUARD: You are trying to write to an implementation file."
    echo "   File: $FILE_PATH"
    echo ""
    echo "   As Dispatcher, you should NOT write implementation code."
    echo "   Instead: Create a ticket in devos/tasks/QUEUE.yaml"
    echo "   Then tell the user to run: make copy-codex or make copy-gemini"
    echo ""
    echo "   Override: If this is a config/setup file, the user can approve."
    echo ""
    exit 2
  fi
done

# Allow devos/, .claude/, config files, etc.
exit 0

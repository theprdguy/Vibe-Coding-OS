#!/usr/bin/env bash
# export-to-public.sh — thin wrapper around scripts/export_to_public.py
#
# Usage:
#   bash scripts/export-to-public.sh [--dry-run] [--apply] <target-dir>
#
# Default is --dry-run (fail-safe). Pass --apply to actually write files.
#
# The Python module (scripts/export_to_public.py) owns all logic.
# This script is a convenience entry point only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MODULE="${SCRIPT_DIR}/export_to_public.py"

if [[ ! -f "${PYTHON_MODULE}" ]]; then
    echo "ERROR: Python module not found: ${PYTHON_MODULE}" >&2
    exit 1
fi

exec python3 "${PYTHON_MODULE}" "$@"

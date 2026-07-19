#!/usr/bin/env bash
# Schema audit pre-commit wrapper — called from tools/pre-commit
# Must be runnable from repo root.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR" python3 tools/check-schema-audit.py

#!/usr/bin/env bash
# SessionStart hook: reset the batch counter so /clear correctly starts a new session.
# The post-commit hook uses wall-clock intervals to guess session boundaries,
# but /clear is the real boundary. This script runs on every new session start.
set -euo pipefail

COUNTER_FILE="$(git rev-parse --git-dir 2>/dev/null)/batch-counter-synapse"

if [ -f "$COUNTER_FILE" ]; then
  rm -f "$COUNTER_FILE"
fi

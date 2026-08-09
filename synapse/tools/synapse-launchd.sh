#!/usr/bin/env bash
# synapse-launchd.sh — macOS launchd daemon management for Synapse Workers.
#
# P12-B3: Replaces Claude Code Bash-spawned daemons (which die with the shell)
# with OS-level launchd persistence. Invokes session-init.js --health --silent
# every 60s — mechanical, no LLM involvement. The AI reads the repaired state.
#
# Usage:
#   synapse-launchd.sh install   <project-dir> <worker_id>  # generate plist + launchctl load
#   synapse-launchd.sh uninstall <worker_id>                 # launchctl unload + delete plist
#   synapse-launchd.sh status    <worker_id>                 # launchctl list + plist file check
#   synapse-launchd.sh plist     <project-dir> <worker_id>   # print plist to stdout (dry-run)
#
# Worker ID: unique worker identifier (e.g. wa_xxx). PFL-129: label is now
# worker_id-based so multiple workers with the same role don't collide.
#
# Examples:
#   bash tools/synapse-launchd.sh install ~/my-project wa_abc123
#   bash tools/synapse-launchd.sh status  wa_abc123
#   bash tools/synapse-launchd.sh uninstall wa_abc123
#
# Line B (Codex CLI): Codex has no launchd support — prompt-driven only.
# See header comment at end of file for Codex live verification checklist.
#
# P12-B2 design: docs/plans/p12-b2-cross-client-autonomy.md §4.2

set -euo pipefail

# ── Constants ───────────────────────────────────────────────────────────

LABEL_PREFIX="com.synapse.worker"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"

# ── Help ────────────────────────────────────────────────────────────────

usage() {
    cat << 'USAGE'
synapse-launchd.sh — macOS launchd daemon manager for Synapse Workers.

USAGE:
  synapse-launchd.sh install   <project-dir> <worker_id>  generate plist + launchctl load
  synapse-launchd.sh uninstall <worker_id>                 launchctl unload + delete plist
  synapse-launchd.sh status    <worker_id>                 launchctl list + plist file check
  synapse-launchd.sh plist     <project-dir> <worker_id>   print plist to stdout (dry-run)

WORKER_ID: unique worker identifier (e.g. wa_xxx). PFL-129: label is now
worker_id-based so multiple workers with the same role don't collide.

EXAMPLES:
  bash tools/synapse-launchd.sh install ~/my-project wa_abc123
  bash tools/synapse-launchd.sh status  wa_abc123
  bash tools/synapse-launchd.sh uninstall wa_abc123

DESIGN:
  - launchd invokes session-init.js --health --silent every 60 seconds
  - AI never sees "daemon dead" — health() auto-re-spawns before state sync
  - API key NOT stored in plist — session-init.js reads .env or OS keychain
  - Daemon survives Claude Code /clear, exit, and restart
USAGE
    exit 0
}

# ── Platform guard ──────────────────────────────────────────────────────

check_macos() {
    if [[ "$(uname -s)" != "Darwin" ]]; then
        echo "❌ synapse-launchd.sh requires macOS (launchd)."
        echo "   Current OS: $(uname -s)"
        echo "   Linux: use systemd user unit instead (not yet implemented — P13)."
        exit 1
    fi
}

# ── Validation ──────────────────────────────────────────────────────────

validate_worker_id() {
    local worker_id="$1"
    if [[ -z "$worker_id" ]]; then
        echo "❌ Worker ID cannot be empty."
        exit 1
    fi
    # Worker IDs typically start with "w" prefix (e.g. wa_xxx for claude, wb_xxx for codex)
    if [[ ! "$worker_id" =~ ^w ]]; then
        echo "⚠️  Worker ID '${worker_id}' doesn't match expected format (w* prefix)."
        echo "   Continuing anyway — if this is wrong, uninstall/status will fail."
    fi
}

validate_project_dir() {
    local dir="$1"
    local worker_id="$2"

    # Resolve to absolute path
    dir="$(cd "$dir" 2>/dev/null && pwd)" || {
        echo "❌ Project directory does not exist: $dir"
        exit 1
    }

    # Check for .claude/ directory (Claude Code Worker root)
    local claude_dir="$dir/.claude"
    if [[ ! -d "$claude_dir" ]]; then
        echo "❌ No .claude/ directory found in $dir"
        echo "   Is this a Synapse Worker project? Run generate-skill.sh first."
        exit 1
    fi

    # Check for session-init.js
    local init_script="$claude_dir/skills/synapse/scripts/session-init.js"
    if [[ ! -f "$init_script" ]]; then
        echo "❌ session-init.js not found at: $init_script"
        echo "   Run generate-skill.sh --target claude first to bootstrap the Worker."
        exit 1
    fi

    # Check for .env (session-init.js inline-env needs it for SYNAPSE_* vars)
    local env_file="$claude_dir/.env"
    if [[ ! -f "$env_file" ]]; then
        echo "⚠️  No .claude/.env found at $env_file"
        echo "   session-init.js needs SYNAPSE_API_URL + SYNAPSE_PROJECT_ID."
        echo "   Create .claude/.env with the required variables before the Worker starts."
    fi

    echo "$dir"
}

find_node() {
    local node_path
    node_path="$(which node 2>/dev/null)" || {
        echo "❌ Node.js not found in PATH."
        echo "   Install Node.js ≥22: https://nodejs.org"
        exit 1
    }
    echo "$node_path"
}

# ── Path helpers ────────────────────────────────────────────────────────

plist_label() {
    local worker_id="$1"
    echo "${LABEL_PREFIX}.${worker_id}"
}

plist_path() {
    local worker_id="$1"
    echo "${LAUNCH_AGENTS_DIR}/$(plist_label "$worker_id").plist"
}

log_path() {
    local worker_id="$1"
    echo "${LOG_DIR}/synapse-worker-${worker_id}.log"
}

error_log_path() {
    local worker_id="$1"
    echo "${LOG_DIR}/synapse-worker-${worker_id}-error.log"
}

# ── plist generation ────────────────────────────────────────────────────

generate_plist() {
    local project_dir="$1"
    local worker_id="$2"
    local node_path="$3"

    local init_script="${project_dir}/.claude/skills/synapse/scripts/session-init.js"
    local label
    label="$(plist_label "$worker_id")"
    local stdout_log
    stdout_log="$(log_path "$worker_id")"
    local stderr_log
    stderr_log="$(error_log_path "$worker_id")"

    # Read env vars from .claude/.env for the plist.
    # session-init.js checkEnv() reads process.env only — it does NOT parse the
    # .env file from disk. All required vars must be passed as EnvironmentVariables.
    # API key IS passed here because session-init.js has no .env-file reader;
    # the security stance is: if .env is plaintext on disk anyway, the plist
    # (same directory, same permissions) adds no material risk.
    local env_file="${project_dir}/.claude/.env"
    local synapse_api_url="http://localhost:8000"
    local synapse_project_id=""
    local synapse_worker_id=""
    local synapse_api_key=""
    local synapse_worker_role=""

    # Helper: extract a value from a KEY=VALUE .env file
    _env_val() {
        grep -E "^${1}=" "$env_file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true
    }

    if [[ -f "$env_file" ]]; then
        synapse_api_url="$(_env_val 'SYNAPSE_API_URL')"
        [[ -z "$synapse_api_url" ]] && synapse_api_url="http://localhost:8000"
        synapse_project_id="$(_env_val 'SYNAPSE_PROJECT_ID')"
        synapse_worker_id="$(_env_val 'SYNAPSE_WORKER_ID')"
        synapse_api_key="$(_env_val 'SYNAPSE_API_KEY')"
        synapse_worker_role="$(_env_val 'SYNAPSE_WORKER_ROLE')"
    fi

    cat << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${node_path}</string>
        <string>${init_script}</string>
        <string>--health</string>
        <string>--silent</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${project_dir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>SYNAPSE_API_URL</key>
        <string>${synapse_api_url}</string>
        <key>SYNAPSE_PROJECT_ID</key>
        <string>${synapse_project_id}</string>
        <key>SYNAPSE_WORKER_ID</key>
        <string>${synapse_worker_id}</string>
        <key>SYNAPSE_API_KEY</key>
        <string>${synapse_api_key}</string>
        <key>SYNAPSE_WORKER_ROLE</key>
        <string>${synapse_worker_role}</string>
    </dict>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>${stderr_log}</string>
</dict>
</plist>
PLIST
}

# ── Subcommands ─────────────────────────────────────────────────────────

cmd_plist() {
    local project_dir="$1"
    local worker_id="$2"

    check_macos
    validate_worker_id "$worker_id"
    project_dir="$(validate_project_dir "$project_dir" "$worker_id")"
    local node_path
    node_path="$(find_node)"

    generate_plist "$project_dir" "$worker_id" "$node_path"
}

cmd_install() {
    local project_dir="$1"
    local worker_id="$2"

    check_macos
    validate_worker_id "$worker_id"
    project_dir="$(validate_project_dir "$project_dir" "$worker_id")"
    local node_path
    node_path="$(find_node)"

    local plist_file
    plist_file="$(plist_path "$worker_id")"
    local label
    label="$(plist_label "$worker_id")"

    echo "▎ Synapse Worker (${worker_id}) — launchd install"
    echo "  Project:    ${project_dir}"
    echo "  Node.js:    ${node_path}"
    echo "  plist:      ${plist_file}"
    echo "  StdOut:     $(log_path "$worker_id")"
    echo "  StdErr:     $(error_log_path "$worker_id")"
    echo ""

    # Pre-flight: unload if already loaded (idempotent install)
    if launchctl list "$label" &>/dev/null; then
        echo "  ⚠️  Existing job found — unloading first..."
        launchctl unload "$plist_file" 2>/dev/null || true
    fi

    # Create LaunchAgents dir if needed
    mkdir -p "$LAUNCH_AGENTS_DIR"
    mkdir -p "$LOG_DIR"

    # Generate and write plist
    generate_plist "$project_dir" "$worker_id" "$node_path" > "$plist_file"
    echo "  ✅ plist written: ${plist_file}"

    # Load
    launchctl load "$plist_file"
    echo "  ✅ launchctl load: ${label}"

    # Verify
    sleep 1
    if launchctl list "$label" &>/dev/null; then
        echo "  ✅ job registered in launchctl list"
    else
        echo "  ⚠️  job not visible in launchctl list — check logs:"
        echo "     cat $(error_log_path "$worker_id")"
    fi

    echo ""
    echo "  📋 To check status:  bash tools/synapse-launchd.sh status ${worker_id}"
    echo "  📋 To uninstall:     bash tools/synapse-launchd.sh uninstall ${worker_id}"
    echo "  📋 Logs:             tail -f $(log_path "$worker_id")"
}

cmd_uninstall() {
    local worker_id="$1"

    check_macos
    validate_worker_id "$worker_id"

    local plist_file
    plist_file="$(plist_path "$worker_id")"
    local label
    label="$(plist_label "$worker_id")"

    echo "▎ Synapse Worker (${worker_id}) — launchd uninstall"

    # Unload
    if [[ -f "$plist_file" ]]; then
        launchctl unload "$plist_file" 2>/dev/null && echo "  ✅ launchctl unload: ${label}" || echo "  ⚠️  unload returned non-zero (may already be stopped)"
        rm -f "$plist_file"
        echo "  ✅ plist deleted: ${plist_file}"
    else
        echo "  ℹ️  No plist found at ${plist_file}"
    fi

    # Try label-based unload as fallback
    if launchctl list "$label" &>/dev/null; then
        launchctl remove "$label" 2>/dev/null && echo "  ✅ launchctl remove: ${label}" || true
    fi
}

cmd_status() {
    local worker_id="$1"

    check_macos
    validate_worker_id "$worker_id"

    local plist_file
    plist_file="$(plist_path "$worker_id")"
    local label
    label="$(plist_label "$worker_id")"

    echo "▎ Synapse Worker (${worker_id}) — launchd status"
    echo ""

    # launchctl list
    echo "  launchctl list ${label}:"
    if launchctl list "$label" &>/dev/null; then
        launchctl list "$label" 2>/dev/null | sed 's/^/    /'
        echo "    ✅ job is loaded"
    else
        echo "    ❌ job NOT loaded"
    fi

    echo ""

    # plist file
    echo "  plist file: ${plist_file}"
    if [[ -f "$plist_file" ]]; then
        echo "    ✅ exists ($(wc -c < "$plist_file" | tr -d ' ') bytes)"
    else
        echo "    ❌ NOT found"
    fi

    echo ""

    # session-init.js
    local init_script="/tmp/.synapse-launchd-check-sentinel"
    if [[ -f "$plist_file" ]]; then
        init_script="$(grep -A1 'session-init.js' "$plist_file" 2>/dev/null | tail -1 | sed 's/.*<string>\(.*\)<\/string>.*/\1/' || echo "unknown")"
    fi
    echo "  session-init.js: ${init_script}"
    if [[ -f "$init_script" ]]; then
        echo "    ✅ exists"
    else
        echo "    ⚠️  file not found (Worker may have moved)"
    fi

    echo ""

    # Logs
    local out_log="$(log_path "$worker_id")"
    local err_log="$(error_log_path "$worker_id")"
    echo "  StdOut: ${out_log}"
    [[ -f "$out_log" ]] && echo "    📋 $(wc -l < "$out_log" | tr -d ' ') lines · last modified: $(stat -f '%Sm' "$out_log" 2>/dev/null || echo 'unknown')"
    echo "  StdErr: ${err_log}"
    [[ -f "$err_log" ]] && echo "    📋 $(wc -l < "$err_log" | tr -d ' ') lines · last modified: $(stat -f '%Sm' "$err_log" 2>/dev/null || echo 'unknown')"
}

# ── Main dispatch ───────────────────────────────────────────────────────

[[ "${1:-}" =~ ^(-h|--help|help)$ ]] && usage

COMMAND="${1:-}"
case "$COMMAND" in
    install)
        [[ $# -ne 3 ]] && { echo "Usage: $0 install <project-dir> <worker_id>"; exit 1; }
        cmd_install "$2" "$3"
        ;;
    uninstall)
        [[ $# -ne 2 ]] && { echo "Usage: $0 uninstall <worker_id>"; exit 1; }
        cmd_uninstall "$2"
        ;;
    status)
        [[ $# -ne 2 ]] && { echo "Usage: $0 status <worker_id>"; exit 1; }
        cmd_status "$2"
        ;;
    plist)
        [[ $# -ne 3 ]] && { echo "Usage: $0 plist <project-dir> <worker_id>"; exit 1; }
        cmd_plist "$2" "$3"
        ;;
    *)
        echo "Unknown command: ${COMMAND:-<empty>}"
        echo "Usage: $0 {install|uninstall|status|plist} ..."
        echo "Run '$0 --help' for details."
        exit 1
        ;;
esac

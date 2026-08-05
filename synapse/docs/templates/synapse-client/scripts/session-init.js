#!/usr/bin/env node
/**
 * session-init.js — Mechanical startup for Synapse Worker sessions.
 *
 * Replaces SKILL.md Steps 1, 2, 2.5, 3, 3.5 with a single deterministic script.
 * Design principle (B98): scripts do mechanical actions, prompts do judgment.
 *
 * What this script does (mechanical):
 *   1. Check required env vars → structured report
 *   2. Resolve API key (env → OS keychain fallback)
 *   2.5 Start heartbeat daemon (detached · B91 PFL-083)
 *   2.6 Start WS daemon (detached · B96 PFL-093) — real-time event push
 *   3. GET /protocol → fetch project context + role
 *   4. POST /handshake → activate worker
 *   5. Run state sync queries (auth requests, in_progress tasks, ready/verification tasks)
 *   6. Write structured state to _task-current.md
 *   7. Output role banner text to stdout
 *
 * What this script does NOT do (judgment — left to the AI):
 *   - Decide which task to claim
 *   - Evaluate verification conditions
 *   - Handle error recovery strategy
 *   - Decide when to escalate
 *
 * Exit code: ALWAYS 0 (non-blocking for SessionStart hooks).
 * All errors are captured in the output file — the AI reads and decides.
 *
 * Usage:
 *   node scripts/session-init.js                     # full init (inline-env ON by default)
 *   node scripts/session-init.js --quick             # quick refresh (skips daemon/protocol/handshake)
 *   node scripts/session-init.js --health            # daemon self-heal + quick refresh (B137)
 *   node scripts/session-init.js --upgrade            # template upgrade
 *   node scripts/session-init.js --json              # output full state JSON to stdout (Codex sandbox)
 *   node scripts/session-init.js --no-inline-env     # disable .env auto-load
 *   node scripts/session-init.js --silent            # suppress console output (for daemon use)
 *
 * Environment:
 *   SYNAPSE_API_URL      — Synapse instance base URL
 *   SYNAPSE_WORKER_ID    — Worker's agent ID
 *   SYNAPSE_PROJECT_ID   — Default project ID
 *   SYNAPSE_API_KEY      — Bearer token (falls back to OS keychain)
 *   SYNAPSE_WORKER_ROLE  — "builder" | "orchestrator" | "steward"
 *
 * @version 1.6.0 — B137: Worker harness — lib/prompts.js + lib/daemon-manager.js + --health mode
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');
const { SynapseClient } = require('./api-client');
const { getKey } = require('./keychain');
const { CRONCREATE_PROMPT } = require('./lib/prompts');
const { createDaemonManager } = require('./lib/daemon-manager');

// ── Constants ──────────────────────────────────────────────────────
const WORKER_ROOT = path.resolve(__dirname, '..', '..', '..');
// WORKER_ROOT is already at .claude/ level (3 dirs up from scripts/).
// path.join(WORKER_ROOT, '.claude', ...) would create .claude/.claude/ nesting.
// Settings go directly under WORKER_ROOT (i.e., .claude/settings.local.json).
const SETTINGS_LOCAL = path.join(WORKER_ROOT, 'settings.local.json');
const OUTPUT_FILE = path.join(__dirname, '..', '_task-current.md');
const PROTOCOL_CACHE = path.join(__dirname, '..', '_protocol-cache.json');
const COLLABORATION_NORMS_FILE = path.join(__dirname, '..', '_collaboration-norms.md');
// B112 PFL-112: _boot-prompt.md at Worker root — human types @_boot-prompt.md to cold-start
const BOOT_PROMPT_FILE = path.resolve(__dirname, '..', '..', '..', '..', '_boot-prompt.md');
const SCRIPT_NAME = 'session-init';
// P12-B8 (HK-3): hook sentinel — written on every SessionStart hook fire.
// If this file is missing or > 5 min old, the SessionStart hook isn't firing.
// Worker SKILL.md should check this file on wakeup as a hook health diagnostic.
const HOOK_SENTINEL = path.join(__dirname, '..', '..', '_last-session-init.txt');

// ── CLI Flags ──────────────────────────────────────────────────────
// B122 PFL-110: --quick mode skips daemon spawn, protocol fetch, handshake.
// Only re-queries API state and updates _task-current.md. Designed for:
//   - Worker mid-session wakeup refresh (snapshot staleness check)
//   - God's-eye post-task-creation refresh
const QUICK_MODE = process.argv.includes('--quick');

// P11-B124 (PFL-084): --upgrade mode — fetch latest templates from server,
// regenerate all Skill files, update version file, clear upgrade-needed flag.
// This is the "action" layer of the 3-layer template upgrade architecture.
const UPGRADE_MODE = process.argv.includes('--upgrade');

// P11-B135 (PFL-127 discovery 2): --inline-env mode — read .env file directly
// and override process.env SYNAPSE_* values. Fixes env pollution where global
// shell has old/incorrect API key that takes precedence over .env file.
// Claude Code Bash tool creates independent shells per call, so `source .env`
// in one call doesn't carry to the next. This flag makes daemon spawn + API
// calls independent of shell environment.
//
// Default: ON (always attempt .env load). Pass --no-inline-env to disable.
const INLINE_ENV_MODE = !process.argv.includes('--no-inline-env');

// B137: --health mode — daemon self-heal + heartbeat + state refresh.
// Replaces --quick for CronCreate wakeups. Checks daemon liveness,
// auto-re-spawns dead daemons, then does quick state refresh.
// AI reads the REPAIRED state — it never sees "daemon dead."
const HEALTH_MODE = process.argv.includes('--health');

// P12-B5: --json outputs full state as JSON to stdout instead of (or in addition to)
// writing _task-current.md. Designed for Codex workers whose .agents/ directory
// is read-only — the AI reads stdout instead of the file.
const JSON_MODE = process.argv.includes('--json');

// B122 PFL-110 direction 2: --silent suppresses all console output.
// Used when ws-daemon spawns session-init.js — daemon has no terminal.
// console.log/console.error are replaced with no-ops rather than conditional
// checks at every call site, keeping the rest of the code unchanged.
const SILENT_MODE = process.argv.includes('--silent');
if (SILENT_MODE) {
  console.log = () => {};
  console.error = () => {};
}

// ── PID files for daemon lifecycle (PFL-116/117/118 · B115) ──────────
// Each Worker writes its own daemon PIDs to .claude/.daemon-*.pid.
// On startup, stale PIDs from prior sessions are killed before spawn.
// This replaces the global pgrep approach which caused cross-worker
// interference and orphan accumulation.
// NOTE: WORKER_ROOT is already at .claude/ level (3 dirs up from scripts/),
// so PID files go directly under WORKER_ROOT, not .claude/.claude/.
const HEARTBEAT_PID_FILE = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
const WS_DAEMON_PID_FILE = path.join(WORKER_ROOT, '.daemon-ws.pid');

// P11-B132: daemon liveness signal — written/updated on every session-init run.
// heartbeat.js and ws-daemon.js check this file's timestamp instead of parent PID.
// Fixes R5 death loop where process.ppid pointed to hook shell (not Claude).
const SESSION_ALIVE_FILE = path.join(WORKER_ROOT, '.session-alive');

// B137: Daemon manager — extracted to lib/daemon-manager.js
const dm = createDaemonManager(WORKER_ROOT, __dirname);

// ── Helpers ─────────────────────────────────────────────────────────

/** Current ISO timestamp for output files. */
function now() {
  return new Date().toISOString();
}

/**
 * P11-B132: Check template version from heartbeat response.
 * Compares server version against local synapse-version.json.
 * Writes .claude/template-upgrade-needed flag on mismatch.
 *
 * This replaces the daemon-side check in heartbeat.js's checkTemplateVersion()
 * for the cron heartbeat path. The daemon still does its own check every 55s.
 *
 * @param {string} serverVersion — template_version from heartbeat response
 * @param {object} state — mutated: state.templateUpgradeNeeded set if mismatch
 */
function checkTemplateVersionInHeartbeat(serverVersion, state) {
  const UPGRADE_FLAG = path.join(WORKER_ROOT, 'template-upgrade-needed');
  const VERSION_FILE_SI = path.join(WORKER_ROOT, 'synapse-version.json');

  var localVersion = null;
  try {
    if (fs.existsSync(VERSION_FILE_SI)) {
      var raw = fs.readFileSync(VERSION_FILE_SI, 'utf-8');
      var parsed = JSON.parse(raw);
      localVersion = parsed.version || null;
    }
  } catch (_) { /* non-critical */ }

  if (!localVersion) {
    try {
      fs.writeFileSync(UPGRADE_FLAG, JSON.stringify({
        current: null, latest: serverVersion,
        detected_at: new Date().toISOString(), reason: 'no_local_version',
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }
    return;
  }

  if (localVersion !== serverVersion) {
    try {
      fs.writeFileSync(UPGRADE_FLAG, JSON.stringify({
        current: localVersion, latest: serverVersion,
        detected_at: new Date().toISOString(),
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }
    state.templateUpgradeNeeded = { current: localVersion, latest: serverVersion, detected_at: new Date().toISOString() };
  } else {
    // Clear stale flag if versions match
    try {
      if (fs.existsSync(UPGRADE_FLAG)) fs.unlinkSync(UPGRADE_FLAG);
    } catch (_) { /* best-effort */ }
  }
}

/**
 * P11-B129 (PFL-124 硬加固): Generate deterministic ownership label for a task.
 *
 * This is a DATA TRANSFORMATION — not a prompt hint. The script compares
 * task.owner_id against the Worker's own ID and produces an unambiguous label.
 * The AI doesn't need to "remember" its identity — the data already tells it.
 *
 * Returns one of:
 *   "🫵 YOU"                        — this task belongs to the current Worker
 *   "owner: <name> (NOT YOU)"       — belongs to another Worker
 *   "owner: <name>"                 — belongs to a Human/Member
 *   "unassigned"                    — no owner
 *   ""                              — owner data not available
 *
 * @param {object} task — task object from API (has owner_id, owner_type, owner_name)
 * @param {string} myWorkerId — the current Worker's ID (SYNAPSE_WORKER_ID)
 * @returns {string}
 */
function ownerLabel(task, myWorkerId) {
  if (!task.owner_id) return 'unassigned';
  if (!myWorkerId) return `owner: ${task.owner_name || task.owner_id}`;

  if (task.owner_id === myWorkerId) {
    // Layer 4 (API) already appends (YOU) to owner_name when it matches.
    // Use it if available; otherwise generate our own.
    return '🫵 YOU';
  }

  // Belongs to someone else — make it unambiguous
  const name = task.owner_name || task.owner_id;
  if (task.owner_type === 'worker') {
    return `owner: ${name} (NOT YOU)`;
  }
  return `owner: ${name}`;
}

// ── Daemon lifecycle (delegated to lib/daemon-manager.js · B137) ──

function readPidFile(pidFile) { return dm.readPidFile(pidFile); }
function writePidFile(pidFile, pid) { dm.writePidFile(pidFile, pid); }
function isProcessAlive(pid) { return dm.isProcessAlive(pid); }
function killOldDaemon(pidFile) { return dm.killOldDaemon(pidFile); }
function cleanupOrphanDaemons() { return dm.cleanupOrphanDaemons(); }
function checkHeartbeatDaemon() { return dm.checkHeartbeatDaemon(); }
function startHeartbeatDaemon() { return dm.startHeartbeatDaemon(); }
function checkWsDaemon() { return dm.checkWsDaemon(); }
function startWsDaemon() { return dm.startWsDaemon(); }

/**
 * Read recent WS events from _ws-events.jsonl.
 * Returns last N lines as parsed objects.
 *
 * @param {number} [n=5] — Number of recent events to return
 * @returns {Array<Object>}
 */
function readRecentWsEvents(n = 5) {
  const eventsFile = path.join(__dirname, '..', '_ws-events.jsonl');
  try {
    const raw = fs.readFileSync(eventsFile, 'utf-8');
    const lines = raw.trim().split('\n').filter(Boolean);
    const recent = lines.slice(-n);
    return recent.map(line => { try { return JSON.parse(line); } catch (_) { return null; } }).filter(Boolean);
  } catch (_) {
    return [];
  }
}

/**
 * PFL-110 (B122): Calculate the age of the existing _task-current.md snapshot.
 * Returns a human-readable age string, or null if no existing snapshot or unparseable.
 *
 * Used in two contexts:
 *   1. Normal mode: "replacing snapshot that was X min old" context
 *   2. Quick mode: "refreshing snapshot that was X min old" — the primary use case
 *
 * @returns {string|null} — e.g. "5 min" or "2.3 hr" or null
 */
function getExistingSnapshotAge() {
  try {
    if (!fs.existsSync(OUTPUT_FILE)) return null;
    const content = fs.readFileSync(OUTPUT_FILE, 'utf-8');
    const match = content.match(/^# Session State — (.+)$/m);
    if (!match) return null;
    const oldTs = new Date(match[1]);
    if (isNaN(oldTs.getTime())) return null;
    const ageMs = Date.now() - oldTs.getTime();
    if (ageMs < 0) return null; // clock skew — treat as fresh
    const ageMin = Math.round(ageMs / 60000);
    if (ageMin < 1) return '<1 min';
    if (ageMin < 60) return `${ageMin} min`;
    const ageHr = (ageMs / 3600000).toFixed(1);
    return `${ageHr} hr`;
  } catch (_e) {
    return null;
  }
}

/**
 * Read role from _protocol-cache.json (quick mode fallback).
 * Returns the role string, or null if cache doesn't exist or is invalid.
 *
 * @returns {string|null}
 */
function readRoleFromCache() {
  try {
    if (!fs.existsSync(PROTOCOL_CACHE)) return null;
    const raw = fs.readFileSync(PROTOCOL_CACHE, 'utf-8');
    const cache = JSON.parse(raw);
    // role_instructions is keyed by role ("builder"/"orchestrator"/"steward")
    if (cache.role_instructions) {
      const roles = Object.keys(cache.role_instructions);
      if (roles.length === 1) return roles[0];
      // Multiple roles — can't disambiguate without protocol fetch
    }
    return null;
  } catch (_e) {
    return null;
  }
}

/**
 * Ensure the Worker's .claude/settings.local.json grants necessary permissions.
 *
 * B110 root cause: the project root settings.local.json had a restrictive allowlist
 * that blocked Worker windows from reading their own skill files (synapse-builder/**,
 * synapse-orchestrator/**), calling curl, or using CronCreate/ScheduleWakeup.
 *
 * This function auto-generates a per-Worker settings.local.json during bootstrap
 * so new Workers don't hit the same permission wall. The per-Worker file merges
 * additively with parent settings — it only adds, never removes.
 *
 * Idempotent: if settings.local.json already exists, it is NOT overwritten.
 * This preserves any manual customizations the user may have made.
 */
function ensureWorkerSettings() {
  try {
    if (fs.existsSync(SETTINGS_LOCAL)) {
      return { created: false, path: SETTINGS_LOCAL, reason: 'already exists' };
    }

    const permissions = {
      permissions: {
        allow: [
          // Read access to this Worker's own directory plus synapse/ shared resources
          `Read(${path.join(WORKER_ROOT, '**')})`,
          `Read(${path.join(path.resolve(WORKER_ROOT, '..'), 'synapse', '**')})`,
          // Read access to user memory
          `Read(${path.join(require('os').homedir(), '.claude', '**')})`,

          // API calls to the Synapse server
          'Bash(curl -s *)',

          // Session scripts (heartbeat.js, ws-daemon.js, session-init.js)
          'Bash(set -a; . ./.claude/.env; set +a; node .claude/skills/synapse/scripts/*)',
          'Bash(node .claude/skills/synapse/scripts/*)',

          // Basic shell utilities for operational tasks
          'Bash(echo *)',
          'Bash(cat *)',
          'Bash(ls *)',
          'Bash(grep *)',
          'Bash(find *)',
          'Bash(which *)',
          'Bash(git *)',
          'Bash(env)',
          'Bash(source .claude/.env *)',
          'Bash(python3 -c *)',
          'Bash(python3 -m json.tool)',
          'Bash(security find-generic-password *)',

          // Self-scheduling — without these Workers die after first turn (B82 dogfood)
          'CronCreate',
          'ScheduleWakeup',

          // Synapse skill
          'Skill(synapse)',
        ],
      },
    };

    fs.mkdirSync(path.dirname(SETTINGS_LOCAL), { recursive: true });
    fs.writeFileSync(SETTINGS_LOCAL, JSON.stringify(permissions, null, 2) + '\n', 'utf-8');
    return { created: true, path: SETTINGS_LOCAL };
  } catch (e) {
    return { created: false, path: SETTINGS_LOCAL, error: e.message };
  }
}

/**
 * P11-B135 (PFL-127 discovery 2): Load and parse .env file.
 *
 * Claude Code Bash tool creates independent shells per call. `source .env` in one
 * call doesn't carry to the next. Global shell may have old/incorrect SYNAPSE_API_KEY
 * that conflicts with the .env file. This function reads the .env file directly and
 * returns parsed key=value pairs for SYNAPSE_* vars — making daemon spawn and API
 * calls independent of shell environment pollution.
 *
 * Format: KEY=VALUE, # comments, blank lines ignored.
 * Handles values with spaces, inline comments, and quoted values.
 *
 * @param {string} envPath — path to .env file
 * @returns {{ vars: object, errors: string[], loaded: boolean }}
 */
function loadEnvFile(envPath) {
  const result = { vars: {}, errors: [], loaded: false };
  try {
    if (!fs.existsSync(envPath)) {
      return result;
    }
    const raw = fs.readFileSync(envPath, 'utf-8');
    const lines = raw.split('\n');
    let lineNo = 0;
    for (const line of lines) {
      lineNo++;
      const trimmed = line.trim();
      // Skip blank lines and comments
      if (!trimmed || trimmed.startsWith('#')) continue;
      // Parse KEY=VALUE
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.substring(0, eqIdx).trim();
      let value = trimmed.substring(eqIdx + 1).trim();
      // Remove inline comments (only if outside quotes)
      // Simple heuristic: if # appears after a space, it's likely a comment
      const hashIdx = value.indexOf(' #');
      if (hashIdx !== -1) {
        value = value.substring(0, hashIdx).trim();
      }
      // Strip surrounding quotes (single or double)
      if ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.substring(1, value.length - 1);
      }
      if (key) {
        result.vars[key] = value;
      }
    }
    result.loaded = true;
  } catch (e) {
    result.errors.push(`Failed to read .env file: ${e.message}`);
  }
  return result;
}

/**
 * Check all required env vars. Returns { ok: bool, missing: string[], present: {} }
 */
function checkEnv() {
  const required = ['SYNAPSE_API_URL', 'SYNAPSE_WORKER_ID', 'SYNAPSE_PROJECT_ID'];
  const missing = [];
  const present = {};

  for (const v of required) {
    if (process.env[v]) {
      present[v] = process.env[v];
    } else {
      missing.push(v);
    }
  }

  // API key: env first, then keychain fallback
  let apiKey = process.env.SYNAPSE_API_KEY || '';
  let keySource = 'env';
  if (!apiKey && present.SYNAPSE_WORKER_ID) {
    apiKey = getKey(present.SYNAPSE_WORKER_ID) || '';
    if (apiKey) keySource = 'keychain';
  }
  if (apiKey) {
    present.SYNAPSE_API_KEY = apiKey;
    present._keySource = keySource;

    // B104-1 (B106): Key liveness — validate format before making API calls.
    // Catches copy-paste errors and truncated keys early, before the first
    // failed protocol fetch produces an opaque diagnostic.
    if (!apiKey.startsWith('sk-syn-') || apiKey.length < 32) {
      present._keyInvalid = true;
      present._keyFormatError =
        `API key does not match expected format (prefix sk-syn-, min 32 chars, got ${apiKey.length} chars). ` +
        'Check your SYNAPSE_API_KEY env var or keychain entry.';
    }
  } else {
    missing.push('SYNAPSE_API_KEY');
  }

  // Worker role
  const role = process.env.SYNAPSE_WORKER_ROLE || '';
  if (role) present.SYNAPSE_WORKER_ROLE = role;

  return { ok: missing.length === 0, missing, present };
}

/**
 * PFL-115 (B117): Check if existing _task-current.md is from today and healthy.
 * Returns true if the existing snapshot should be preserved (not overwritten).
 *
 * A healthy snapshot means: envOk + protocolOk + handshakeOk, and the
 * snapshot was generated today (same date in the header).
 *
 * @returns {boolean}
 */
function isExistingSnapshotHealthy() {
  try {
    if (!fs.existsSync(OUTPUT_FILE)) return false;
    const content = fs.readFileSync(OUTPUT_FILE, 'utf-8');
    // Check if generated today
    const today = new Date().toISOString().slice(0, 10);
    if (!content.includes(today)) return false;
    // Check for healthy indicators
    const hasEnvOk = content.includes('API URL') && !content.includes('Environment incomplete');
    const hasProtocolOk = content.includes('Protocol') && !content.includes('Protocol fetch failed');
    return hasEnvOk && hasProtocolOk;
  } catch (_e) {
    return false;
  }
}

/**
 * Write _task-current.md with structured state.
 */
function writeState(state) {
  const snapshotTs = now();
  const modeTag = state.quickRefresh ? 'quick refresh' : 'full init';
  const ageTag = state.oldSnapshotAge ? ` | replaced ${state.oldSnapshotAge} old snapshot` : '';
  const versionTag = 'B122 PFL-110';

  const lines = [
    `# Session State — ${snapshotTs}`,
    '',
    '> ⚠️ Auto-generated by session-init.js. Do not edit manually.',
    '> The AI reads this file to understand current state before making judgments.',
    `> **Snapshot timestamp**: ${snapshotTs} | **Mode**: ${modeTag}${ageTag} | **v**: ${versionTag}`,
    '',
  ];

  // ── P11-B129 (PFL-124): WHO YOU ARE — FIRST cognitive anchor ──
  // MUST come before CronCreate. PFL-124 root cause: Worker saw owner_id
  // matching its own ID but didn't recognize itself. The FIRST thing the AI
  // encounters must be its own identity — before any action instruction.
  // "Know who you are" precedes "know what to do."
  if (state.envOk && state.env.SYNAPSE_WORKER_ID) {
    const workerId = state.env.SYNAPSE_WORKER_ID;
    const role = state.role || state.env.SYNAPSE_WORKER_ROLE || 'unknown';
    lines.push('## 🫵 WHO YOU ARE（P11-B129 · PFL-124 硬锚点）');
    lines.push('');
    lines.push(`**Your Worker ID**: \`${workerId}\``);
    lines.push(`**Your Role**: ${role}`);
    lines.push('');
    lines.push('> 🚨 **MEMORIZE THIS.** The ID above is YOU. Not "another Worker." Not "the system." YOU.');
    lines.push('> ');
    lines.push('> **Self-check before ANY action below**: When you see `owner_id` or `worker_id` ');
    lines.push(`> equal to \`${workerId}\` — that task is YOURS. That request is for YOU. `);
    lines.push('> There is no other entity with this ID. This ID = your identity on this platform.');
    lines.push('> ');
    lines.push('> **PFL-124**: Builder saw `owner_id = ag_019fc710cca87488` and said "another Worker ');
    lines.push('> claimed this task, I am locked out." That WAS the Builder\'s own ID. ');
    lines.push('> **If you make this mistake, you are repeating a known bug.** Don\'t.');
    lines.push('');
  }

  // ── PFL-081 CronCreate FIRST ACTION Banner (B85 · 机械生成 · 无条件) ──
  // This is ALWAYS written — before ANY conditional banner. B84 deep-check found
  // that the static template CronCreate banner was overwritten by session-init.js
  // on every SessionStart, so the AI never saw it. Fix: the script now generates
  // this banner mechanically, ensuring the AI always sees the CronCreate instruction.
  // CronCreate is a Claude Code tool — Node.js subprocess can't call it directly,
  // but it CAN write the call instruction as text that the AI reads and executes.
  lines.push('## 🚨 FIRST ACTION — CronCreate NOW（PFL-081 机械生成 · B85）');
  lines.push('');
  lines.push('**Before you analyze anything, before you read any state below — call the CronCreate tool:**');
  lines.push('');
  lines.push('```');
  lines.push('CronCreate({');
  lines.push('  cron: "*/1 * * * *",');
  // B137: CRONCREATE_PROMPT from lib/prompts.js — single source of truth
  // --health replaces --quick: daemon self-heal + heartbeat + refresh
  lines.push('  prompt: "' + CRONCREATE_PROMPT + '",');
  lines.push('  recurring: true');
  lines.push('})');
  lines.push('```');
  lines.push('');
  lines.push('> ⚠️ **This is NOT optional.** B82 狗粮 3 次复现：Agent 在"分析→写总结→建议下一步"后直接停止——episodic 模型不包含"设闹钟让自己回头"。没有 CronCreate，你退出后就是永久的。没有外部触发，你永远不会再醒来。');
  lines.push('> ');
  lines.push('> **唯一例外**：人类用户显式说"停止"或"退出循环"。');
  lines.push('> ');
  lines.push('> **🔄 CronCreate vs ScheduleWakeup 分工（B90 补文档）**：');
  lines.push('> - **CronCreate**（本 banner）= 安全网（belt）— 每 60 秒兜底，只在 REPL 空闲时触发，不会在你工作时打扰');
  lines.push('> - **ScheduleWakeup**（角色模板"空闲出口"）= 主通道（suspenders）— 精确控制下次唤醒时间，你必须在退出前调用');
  lines.push('> - **两个都要设**：启动时 CronCreate（安全网），退出时 ScheduleWakeup（主通道）。缺一不可。');
  lines.push('> ');
  lines.push('> **然后**再读下面的状态。本 banner 由 session-init.js 机械生成——脚本不会骗你。');
  lines.push('');

  // ── PFL-110 Snapshot Freshness (B122 · 快照新鲜度检查) ──
  // The snapshot is a point-in-time cache from SessionStart. When the Worker
  // wakes up mid-session (CronCreate/ScheduleWakeup), the snapshot may be
  // hours old. God's-eye may have created/assigned tasks in the meantime.
  // PFL-110 lesson (B110 dogfood): Builder woke up, snapshot said "no ready
  // tasks," Builder went back to sleep — but God's-eye had already created
  // and assigned a task. The snapshot was stale. The Worker had no idea.
  lines.push('## ⏰ Snapshot Freshness Check（PFL-110 · B122）');
  lines.push('');
  lines.push(`> ⚠️ **This snapshot was generated at ${snapshotTs}**. It is a point-in-time cache, NOT live state.`);
  lines.push('> ');
  lines.push('> **Every time you wake up (CronCreate / ScheduleWakeup), before trusting this snapshot:**');
  lines.push('> 1. Check the **Snapshot timestamp** above — compute how old it is');
  lines.push('> 2. **Snapshot < 5 min old** → use for orientation, but still call API for real-time decisions（循环铁律 #2）');
  lines.push('> 3. **Snapshot > 5 min old** → **DO NOT TRUST IT BLINDLY** — refresh first:');
  lines.push('>    - `node .claude/skills/synapse/scripts/session-init.js --quick` (2-3s, sends heartbeat + skips protocol/handshake)');
  lines.push('>    - OR call API directly: `curl -s $SYNAPSE_API_URL/v1/projects/$SYNAPSE_PROJECT_ID/tasks?status=ready`');
  lines.push('> 4. **Snapshot > 30 min old** → **MUST refresh** — the world has almost certainly changed');
  lines.push('> ');
  lines.push('> 🚨 **Critical**: If this snapshot says "no ready tasks" AND is > 5 min old — ');
  lines.push('> **DO NOT call ScheduleWakeup and sleep.** The snapshot is stale. Refresh first, then decide.');
  lines.push('> ');
  lines.push('> **PFL-110 lesson** (B110 狗粮): God\'s-eye created + assigned a task while Builder slept.');
  lines.push('> Builder woke up, read stale snapshot ("no ready tasks"), went back to sleep.');
  lines.push('> The task sat unclaimed for hours. Stale snapshot = blind spot.');
  lines.push('');

  // ── P11-B124 Template Upgrade Detection (PFL-084) ──
  // heartbeat daemon detects version mismatch → writes flag file →
  // session-init.js surfaces it here so the Worker AI sees the banner.
  if (state.templateUpgradeNeeded) {
    const localV = state.templateUpgradeNeeded.current
      ? state.templateUpgradeNeeded.current.slice(0, 16) + '...'
      : 'none';
    const serverV = state.templateUpgradeNeeded.latest
      ? state.templateUpgradeNeeded.latest.slice(0, 16) + '...'
      : 'unknown';
    lines.push('## ⚠️ TEMPLATE UPGRADE AVAILABLE (P11-B124 · PFL-084)');
    lines.push('');
    lines.push('> 🚨 **Your Skill templates are outdated.** Running with stale templates');
    lines.push('> may cause protocol mismatches, missing rules, or incorrect role instructions.');
    lines.push('> ');
    lines.push('> - **Local version**: `' + localV + '`');
    lines.push('> - **Server version**: `' + serverV + '`');
    if (state.templateUpgradeNeeded.detected_at) {
      lines.push('> - **Detected at**: ' + state.templateUpgradeNeeded.detected_at);
    }
    lines.push('> ');
    lines.push('> **Action required — run before continuing:**');
    lines.push('> ```');
    lines.push('> node .claude/skills/synapse/scripts/session-init.js --upgrade');
    lines.push('> ```');
    lines.push('> ');
    lines.push('> ⚠️ Upgrade first, then continue working. The upgrade takes ~2-5 seconds');
    lines.push('> and updates all Skill files to match the server\'s latest templates.');
    lines.push('> Restart your Claude Code session after upgrading to load the new instructions.');
    lines.push('');
  }

  // ── PFL-115 Stale Snapshot Warning (B117 · 快照可能过期) ──
  // When the current session-init run has errors/warnings, the snapshot data
  // may be stale or incomplete. The AI should actively retry API calls rather
  // than treating the snapshot as authoritative.
  if ((state.errors && state.errors.length > 0) || (state.warnings && state.warnings.length > 0)) {
    lines.push('## ⚠️ 快照可能过期 — 主动重试 API（PFL-115 · B117）');
    lines.push('');
    lines.push('> ⚠️ **快照不可信警告**：当前会话初始化时部分步骤失败，快照中的数据可能已过期。');
    lines.push('> ');
    lines.push('> **不要因为快照显示"API 不可达"或"队列空"就直接退出。** 快照是启动时的瞬时状态——');
    lines.push('> 网络波动、服务重启、DNS 解析延迟都可能导致快照生成失败。');
    lines.push('> ');
    lines.push('> **在做出"无法继续"的判断之前，必须先主动重试 API：**');
    lines.push('> 1. `curl -s $SYNAPSE_API_URL/health` — 确认 API 可达性');
    lines.push('> 2. 如果 API 可达 → 重新运行 `node scripts/session-init.js` 刷新快照');
    lines.push('> 3. 如果 API 仍不可达 → ScheduleWakeup 120s 后重试，不要永久退出');
    lines.push('> ');
    lines.push('> **PFL-115 教训**：O 收到需求但快照说"API 不可达"，O 放弃——需求→Task 链路断裂。');
    lines.push('> 快照是参考，不是判决书。API 的真实状态可能和快照不同。');
    lines.push('');
  }

  // ── PFL-079/082 Active Task Banner (B84 · 机械告警) ──
  // MUST appear before Connection section — the AI reads this file top-to-bottom.
  // If activeTaskCount > 0, Worker must NOT judge itself as idle, regardless of
  // what the queue looks like. B82 lesson: both Workers stopped after doing their
  // own action — neither stayed alive to wait for the other.
  if (state.activeTaskCount > 0) {
    lines.push(`## 🚨 你有 ${state.activeTaskCount} 个活跃任务，禁止判断为空闲`);
    lines.push('');
    lines.push('> ⚠️ **PFL-079/082 机械告警（B84 · session-init.js 硬约束）**：');
    lines.push('> 脚本检测到活跃任务（in_progress / in_verification / submitted / ready）。');
    lines.push('> 即使当前队列看起来"空"，这些任务仍在进行中——退出循环 = 死锁。');
    lines.push('> ');
    lines.push('> **B82 教训**：两个 Worker 各自完成自己的动作就停止——');
    lines.push('> B 空队列→退出→O assign 后 B 不在（PFL-079）· O assign 完→退出→B submit 后 O 不在（PFL-082）。');
    lines.push('> 没有一方在"等待对方"时保持循环活跃。**脚本不会骗你——如果你判断为空闲，你就是错的。**');
    lines.push('');
  }

  // ── B90 API Unreachable Banner (B90 · 防止真空闲假信号) ──
  // When ALL API queries return -1, activeTaskCount = 0 could mean "API down"
  // rather than "truly idle". The AI must not exit when it can't verify the queue.
  if (state.apiUnreachable) {
    lines.push('## ⚠️ API 不可达 — 无法判断是否空闲');
    lines.push('');
    lines.push('> 🚨 **B90 机械检测**：所有状态查询（in_progress / ready / verification）均返回错误。');
    lines.push('> `activeTaskCount = 0` 不代表真空闲 — API 不可达时脚本无法获取真实状态。');
    lines.push('> ');
    lines.push('> **禁止判断为空闲退出。** 改为：');
    lines.push('> 1. 检查网络/API 连接（`curl $SYNAPSE_API_URL/health`）');
    lines.push('> 2. 如果 API 恢复 → 重新运行 `node scripts/session-init.js` 刷新状态');
    lines.push('> 3. 如果 API 持续不可达 → ScheduleWakeup 120s 后重试，评论区 @Human 报告');
    lines.push('');
  }

  // ── PFL-077 Stale Verification Banner (B84 · 机械停滞检测) ──
  if (state.staleVerificationCount > 0) {
    lines.push(`## 🚨 死锁风险: ${state.staleVerificationCount} tasks stuck in verification for >15min`);
    lines.push('');
    for (const t of state.staleVerificationTasks) {
      const ageMin = t.updated_at
        ? Math.round((Date.now() - new Date(t.updated_at).getTime()) / 60000)
        : '?';
      lines.push(`- 🔴 **${t.title || t.id}** (\`${t.id}\`) — last updated ${ageMin} min ago`);
    }
    lines.push('');
    lines.push('> ⚠️ **PFL-077 机械停滞检测（B84 · session-init.js 硬约束）**：');
    lines.push('> 这些 Task 卡在 `in_verification` 超过 15 分钟。Human 可能不在线，');
    lines.push('> 或者验收结果未通过 API 写入。**不要无限等待**——采取超时策略：');
    lines.push('> 1. `POST /tasks/{id}/messages @Human "请验收"` — 通知 Human');
    lines.push('> 2. 继续等待 5 分钟 → 仍无响应 → 强制 reject 或标记 stale → 继续处理下一个 Task');
    lines.push('> 3. O 的职责是推进工作流，不是等 Human 永远不来的回复。');
    lines.push('');
  }

  // ── Connection status ──
  lines.push('## 🔌 Connection');
  lines.push('');
  if (state.envOk) {
    lines.push(`- **API URL**: \`${state.env.SYNAPSE_API_URL}\``);
    lines.push(`- **Worker**: \`${state.env.SYNAPSE_WORKER_ID}\``);
    lines.push(`- **Project**: \`${state.env.SYNAPSE_PROJECT_ID}\``);
    lines.push(`- **Role**: \`${state.role || state.env.SYNAPSE_WORKER_ROLE || 'unknown'}\``);
    lines.push(`- **API Key**: from ${state.env._keySource || 'env'}`);
    // P11-B132: dual-channel heartbeat — daemon (Layer 1) + cron (Layer 2)
    if (state._heartbeatRuntimeStatus) {
      lines.push(`- **Cron heartbeat**: ${state._heartbeatRuntimeStatus} (sent on wakeup)`);
    }
    if (state.heartbeatDaemon) {
      if (state.heartbeatDaemon.running) {
        lines.push(`- **Heartbeat daemon**: ✅ running (pid: ${state.heartbeatDaemon.pids.join(', ')})`);
      } else if (state.heartbeatDaemon.startError) {
        lines.push(`- **Heartbeat daemon**: 🔴 FAILED TO START — ${state.heartbeatDaemon.startError}. Cron heartbeat will keep worker alive.`);
      } else {
        lines.push('- **Heartbeat daemon**: ⚠️ NOT RUNNING — cron heartbeat will keep worker alive');
      }
    }
    // WS daemon status (P11-B132: .session-alive keeps it alive)
    if (state.wsDaemon) {
      if (state.wsDaemon.running) {
        lines.push(`- **WS Daemon**: ✅ running (pid: ${state.wsDaemon.pids.join(', ')})`);
        if (state.recentWsEvents && state.recentWsEvents.length > 0) {
          lines.push('- **Recent WS events**:');
          for (const evt of state.recentWsEvents) {
            const type = evt.type || evt.event_type || 'unknown';
            const ts = evt.ts || evt.timestamp || '?';
            lines.push(`  - \`${type}\` @ ${ts}`);
          }
        }
      } else if (state.wsDaemon.skippedNodeVersion) {
        lines.push(`- **WS Daemon**: ⚠️ SKIPPED — ${state.wsDaemon.nodeVersionError}. Real-time push unavailable, falling back to HTTP polling.`);
      } else if (state.wsDaemon.startError) {
        lines.push(`- **WS Daemon**: 🔴 FAILED TO START — ${state.wsDaemon.startError}. Real-time push unavailable.`);
      } else if (state.wsDaemon.error) {
        lines.push(`- **WS Daemon**: ⚠️ unable to check (${state.wsDaemon.error})`);
      } else {
        lines.push('- **WS Daemon**: ⚠️ NOT RUNNING — real-time push unavailable');
      }
    }
  } else {
    lines.push('❌ **Environment incomplete** — missing:');
    for (const m of state.envMissing) {
      lines.push(`  - \`${m}\``);
    }
  }

  // ── Protocol ──
  lines.push('');
  lines.push('## 📋 Protocol');
  lines.push('');
  if (state.protocolOk) {
    lines.push(`- **Project**: ${state.protocolData?.project_name || 'unknown'}`);
    lines.push(`- **Role source**: \`${state.protocolData?.role_source || 'unknown'}\``);
    lines.push(`- **Protocol cached**: \`_protocol-cache.json\` (essential) + \`_collaboration-norms.md\` (on-demand, B105)`);
  } else if (state.protocolError) {
    lines.push(`❌ Protocol fetch failed: ${state.protocolError}`);
  } else {
    lines.push('⏳ Protocol not fetched (env incomplete)');
  }

  // ── Handshake ──
  lines.push('');
  lines.push('## 🤝 Handshake');
  lines.push('');
  if (state.handshakeOk) {
    lines.push(`- **Status**: \`${state.handshakeData?.runtime_status || 'active'}\``);
  } else if (state.handshakeError) {
    lines.push(`❌ Handshake failed: ${state.handshakeError}`);
  } else {
    lines.push('⏳ Not attempted');
  }

  // ── P11-B129: Worker identity for ownership labeling ──
  // Compute once, used by ownerLabel() in every task list below.
  // This is deterministic — the script compares owner_id against this value.
  const myId = state.env.SYNAPSE_WORKER_ID || '';

  // ── Authorization Requests ──
  lines.push('');
  lines.push('## 🔐 Authorization Requests');
  lines.push('');
  if (state.authRequestsTotal === 0) {
    lines.push('✅ No pending authorization requests.');
  } else if (state.authRequestsTotal > 0) {
    lines.push(`**${state.authRequestsTotal} pending**:`);
    for (const ar of (state.authRequests || [])) {
      const typeIcon = ar.request_type === 'interactive_prompt' ? '💬' : '🔑';
      lines.push(`- ${typeIcon} \`${ar.id}\` — ${ar.request_type} — status: \`${ar.status}\``);
    }
  } else {
    lines.push('⏳ Not checked (API unavailable)');
  }

  // ── Unread Messages (PFL-080 · 评论区盲区防御) ──
  lines.push('');
  lines.push('## 💬 Unread Messages (PFL-080)');
  lines.push('');
  if (state.unreadMessagesTotal === 0) {
    lines.push('✅ No unread messages requiring attention.');
  } else if (state.unreadMessagesTotal > 0) {
    lines.push(`🚨 **${state.unreadMessagesTotal} unread message(s) across ${state.unreadMessages.length} task(s):**`);
    lines.push('');
    for (const m of (state.unreadMessages || [])) {
      lines.push(`- **${m.taskTitle}** (\`${m.taskId}\`): ${m.count} unread — types: ${m.types.join(', ')}`);
    }
    lines.push('');
    lines.push('> ⚠️ **PFL-080**: 评论区是 Worker 间唯一的异步通道。未回复的 blocking/clarification/handoff 消息意味着对方在等你。先读消息再做事——不读评论区 = 盲区。');
  } else {
    lines.push('⏳ Not checked');
  }

  // ── Active Tasks ──
  // P11-B129: ownership label added to every task — deterministic data transform
  lines.push('');
  lines.push('## 📝 Active Tasks (in_progress)');
  lines.push('');
  if (state.inProgressTotal === 0) {
    lines.push('✅ No in-progress tasks.');
  } else if (state.inProgressTotal > 0) {
    for (const t of (state.inProgressTasks || [])) {
      const own = ownerLabel(t, myId);
      lines.push(`- **${t.title || t.id}** (\`${t.id}\`) — status: \`${t.status}\` · ${own}`);
    }
  } else {
    lines.push('⏳ Not checked');
  }

  // ── Role-specific ──
  if (state.role === 'builder') {
    lines.push('');
    lines.push('## 🎯 Ready Tasks (Builder)');
    lines.push('');
    if (state.readyTotal === 0) {
      lines.push('No ready tasks available. Queue is empty.');
    } else if (state.readyTotal > 0) {
      for (const t of (state.readyTasks || [])) {
        const deps = t.depends_on?.length ? ` (depends: ${t.depends_on.join(', ')})` : '';
        const own = ownerLabel(t, myId);
        lines.push(`- **${t.title || t.id}** (\`${t.id}\`)${deps} · ${own}`);
      }
    } else {
      lines.push('⏳ Not checked');
    }
  } else if (state.role === 'orchestrator') {
    // Verification queue
    lines.push('');
    lines.push('## 🔍 Tasks in Verification (Orchestrator)');
    lines.push('');
    if (state.verificationTotal === 0) {
      lines.push('No tasks awaiting verification.');
    } else if (state.verificationTotal > 0) {
      for (const t of (state.verificationTasks || [])) {
        const own = ownerLabel(t, myId);
        lines.push(`- 🔴 **${t.title || t.id}** (\`${t.id}\`) — submitted, awaiting review · ${own}`);
      }
    } else {
      lines.push('⏳ Not checked');
    }

    // Ready tasks (for assignment)
    lines.push('');
    lines.push('## 🎯 Ready Tasks (for Assignment)');
    lines.push('');
    if (state.readyTotal === 0) {
      lines.push('No ready tasks to assign.');
    } else if (state.readyTotal > 0) {
      for (const t of (state.readyTasks || [])) {
        const deps = t.depends_on?.length ? ` (depends: ${t.depends_on.join(', ')})` : '';
        const own = ownerLabel(t, myId);
        lines.push(`- 🟡 **${t.title || t.id}** (\`${t.id}\`)${deps} · ${own} — needs assignment`);
      }
    } else {
      lines.push('⏳ Not checked');
    }

    // All active tasks summary (supervisor overview)
    if (state.allActiveTotal >= 0) {
      lines.push('');
      lines.push('## 📊 Active Tasks Overview');
      lines.push('');
      lines.push(`**${state.allActiveTotal} active tasks** (excl. completed/cancelled):`);
      const byStatus = {};
      for (const t of (state.allActiveTasks || [])) {
        byStatus[t.status] = (byStatus[t.status] || 0) + 1;
      }
      for (const [status, count] of Object.entries(byStatus).sort()) {
        const icon = { submitted: '🔴', in_verification: '🔴', ready: '🟡', in_progress: '🔵', paused: '⚪' }[status] || '⚪';
        lines.push(`- ${icon} ${status}: ${count}`);
      }
    }
  }

  // ── Warnings ──
  if (state.warnings && state.warnings.length > 0) {
    lines.push('');
    lines.push('## ⚠️ Warnings');
    lines.push('');
    for (const w of state.warnings) {
      lines.push(`- ${w}`);
    }
  }

  // ── Errors ──
  if (state.errors && state.errors.length > 0) {
    lines.push('');
    lines.push('## ⚠️ Errors');
    lines.push('');
    for (const e of state.errors) {
      lines.push(`- ${e}`);
    }
  }

  // ── P11-B129 Identity Verification Footer ──
  // Final self-check: the AI confirms ownership understanding before acting.
  // This is a HARD GATE — the labels above are deterministic, not hints.
  if (state.envOk && state.env.SYNAPSE_WORKER_ID) {
    lines.push('');
    lines.push('## 🫵 Identity Verification（P11-B129 · 硬校验）');
    lines.push('');
    lines.push(`> ✅ My Worker ID: **\`${state.env.SYNAPSE_WORKER_ID}\`**`);
    lines.push('> ');
    lines.push('> **Ownership rules (deterministic — not up for interpretation):**');
    lines.push('> - Task labeled `🫵 YOU` above → **MY task**. Claim it. Work on it. Own it.');
    lines.push('> - Task labeled `owner: <name> (NOT YOU)` → **NOT my task**. Do not touch.');
    lines.push('> - Task labeled `unassigned` → Available. I may claim it if it matches my role.');
    lines.push('> ');
    lines.push('> **PFL-124 self-check**: Before I claim any task, I verify: does `owner_id` ');
    lines.push('> match my Worker ID? If yes → it\'s already mine, no need to claim. If no → ');
    lines.push('> it belongs to someone else. This is mechanical — no judgment required.');
  }

  // ── Footer ──
  lines.push('');
  lines.push('---');
  lines.push(`*Generated ${snapshotTs} by session-init.js (B122 PFL-110 · B129 PFL-124${state.quickRefresh ? ' --quick' : ''})*`);

  // P12-B5: Graceful degradation for read-only sandboxes (Codex .agents/).
  // Try file write first — on failure (EROFS/EPERM/EACCES), output JSON to stdout.
  try {
    fs.writeFileSync(OUTPUT_FILE, lines.join('\n') + '\n', 'utf-8');
  } catch (e) {
    if (e.code === 'EROFS' || e.code === 'EPERM' || e.code === 'EACCES') {
      console.error(`⚠️ ${SCRIPT_NAME}: read-only filesystem — _task-current.md cannot be written (${e.code}). Outputting state JSON to stdout as fallback.`);
    } else {
      console.error(`⚠️ ${SCRIPT_NAME}: _task-current.md write failed — ${e.message}. Outputting state JSON to stdout.`);
    }
    // Fallback: output state JSON to stdout so AI can read it
    if (!SILENT_MODE) {
      outputStateJson(state);
    }
  }
}

/**
 * P12-B5: Output full state as JSON to stdout.
 *
 * Used when file writes fail (Codex read-only sandbox) or when --json flag
 * is explicitly requested. The Worker AI reads stdout instead of _task-current.md.
 *
 * All API data is already in memory — this is a zero-cost serialization.
 */
function outputStateJson(state) {
  // Build a safe-to-serialize copy — strip internal/transient fields
  const safe = {
    generated_at: now(),
    worker_id: state.env?.SYNAPSE_WORKER_ID || null,
    role: state.role || null,
    env_ok: state.envOk,
    protocol_ok: state.protocolOk,
    handshake_ok: state.handshakeOk,
    api_url: state.env?.SYNAPSE_API_URL || null,
    project_id: state.env?.SYNAPSE_PROJECT_ID || null,
    connection: {
      heartbeat_daemon: state.heartbeatDaemon,
      ws_daemon: state.wsDaemon ? { running: state.wsDaemon.running } : null,
    },
    tasks: {
      active_count: state.activeTaskCount,
      in_progress: (state.inProgressTasks || []).map(summarizeTask),
      ready: (state.readyTasks || []).map(summarizeTask),
      verification: (state.verificationTasks || []).map(summarizeTask),
    },
    auth_requests: {
      total: state.authRequestsTotal,
      pending: (state.authRequests || []).map(function(ar) {
        return { id: ar.id, type: ar.request_type, status: ar.status };
      }),
    },
    stale: {
      verification_count: state.staleVerificationCount,
      verification_ids: (state.staleVerificationTasks || []).map(function(t) { return t.id; }),
    },
    warnings: state.warnings || [],
    errors: state.errors || [],
    api_unreachable: state.apiUnreachable || false,
    template_upgrade_needed: state.templateUpgradeNeeded || null,
  };
  console.log('┌──────────────────────────────────────────────┐');
  console.log('│  Synapse Worker State (JSON · P12-B5)          │');
  console.log('└──────────────────────────────────────────────┘');
  console.log(JSON.stringify(safe, null, 2));
}

/** P12-B5: Minimal task summary for JSON output. */
function summarizeTask(t) {
  return {
    id: t.id,
    title: t.title || t.id,
    status: t.status,
    owner_id: t.owner_id || null,
    owner_name: t.owner_name || null,
    depends_on: t.depends_on || [],
  };
}

/**
 * Write _boot-prompt.md at Worker root for cold-start bootstrap (B112 PFL-112 · B129 PFL-124).
 *
 * B112 v1 lesson: 64-line markdown with sections/headers/bullets → AI treats it as
 * a document to analyze and summarize, then stops. It does NOT call CronCreate.
 * The episodic model's default is "read → understand → summarize → suggest → stop".
 *
 * B112 v2: Radically minimal. 3-4 lines, no markdown structure, no explanations.
 * The AI has nothing to analyze — only one action to take. Imperative, non-negotiable.
 *
 * B129 (PFL-124): Worker ID injected into role identity line. PFL-124 root cause:
 * Builder saw owner_id matching its own Worker ID but didn't recognize itself.
 * The boot prompt is the FIRST identity anchor — "You are Worker X, your ID is Y."
 *
 * Idempotent: overwrites on every SessionStart with fresh state.
 */
function writeBootPrompt(state) {
  const role = state.role || 'worker';
  const workerId = state.env?.SYNAPSE_WORKER_ID || 'unknown';

  // P11-B129 (PFL-124): Identity comes FIRST — before any action instruction.
  // PFL-124 root cause: Builder didn't recognize its own Worker ID on a task.
  // The boot prompt's FIRST line establishes identity. Then action follows.
  // Format: "I am X (ID: Y). Now: CronCreate → work loop."
  const identityLine = {
    builder: `You are the Builder Worker. Your Worker ID is ${workerId}. Claim ready tasks, execute, collect evidence, submit.`,
    orchestrator: `You are the Orchestrator Worker. Your Worker ID is ${workerId}. Assign tasks, verify results, close tasks.`,
    steward: `You are the Steward Worker. Your Worker ID is ${workerId}. Review code, audit security, report findings.`,
  }[role] || `You are a Synapse ${role} Worker. Your Worker ID is ${workerId}.`;

  // P11-B136 (PFL-126 闭环): daemon check in CronCreate wakeup.
  // --quick refreshes state + sends heartbeat (B132 cron-native Layer 2).
  // Wakeup reads _task-current.md Connection section → if daemon dead or
  // template fallback → run FULL session-init.js to re-spawn daemons.
  // This closes PFL-126: boot prompt → CronCreate → daemon check chain
  // now survives SessionStart hook failure (PFL-127 · B135).
  // B137: CRONCREATE_PROMPT from lib/prompts.js — single source of truth
  const cronPrompt = CRONCREATE_PROMPT;

  const lines = [
    // P11-B129: IDENTITY FIRST — the AI reads this line before any action.
    // "I am X" must be the FIRST cognitive anchor.
    identityLine,
    '',
    `CronCreate({cron: "*/1 * * * *", prompt: "${cronPrompt}", recurring: true})`,
    '',
    // P11-B136 (PFL-126): Reference B135 daemon self-heal path
    `Then: read SKILL.md §「第二步：读取初始状态 + Daemon 自愈」（P11-B135 · PFL-127 硬约束）→ read _task-current.md → enter work loop.`,
    '',
    'Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.',
  ];

  try {
    fs.writeFileSync(BOOT_PROMPT_FILE, lines.join('\n') + '\n', 'utf-8');
  } catch (e) {
    console.error(`⚠️ ${SCRIPT_NAME}: unable to write _boot-prompt.md — ${e.message}`);
  }
}

/**
 * Generate role banner text for the AI to display.
 */
function roleBanner(state) {
  const roleColors = { builder: '🔵', orchestrator: '🟠', steward: '⚪' };
  const emoji = roleColors[state.role] || '⚪';
  const roleName = state.role || 'unknown';
  const projectName = state.protocolData?.project_name || 'unknown';

  const roleBanners = {
    builder: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Builder`,
      `   项目: ${projectName}`,
      `   职责: 接 Task · 执行 · 收集 evidence · 提交验证`,
      `   边界: 不创建 Task · 不分配 Task · 不验收`,
    ],
    orchestrator: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Orchestrator`,
      `   项目: ${projectName}`,
      `   职责: 拆解 Task · 分配 Builder · 验收结果`,
      `   边界: 不写代码 · 不认领 Task · 不提交 evidence`,
    ],
    steward: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Steward`,
      `   项目: ${projectName}`,
      `   职责: 审查代码 · 安全检查 · 反馈意见`,
      `   边界: 不写代码 · 不创建 Task · 不验收`,
    ],
  };

  const lines = roleBanners[state.role] || roleBanners.builder;

  if (state.protocolData?.role_source === 'default_fallback') {
    lines.push('');
    lines.push('⚠️ 你的角色未在 Worker 元数据中配置，已默认分配为 Builder。');
    lines.push('如果这不是你的预期角色，请联系 Admin 更新 Worker 配置。');
  }

  return lines.join('\n');
}

// ── Main ────────────────────────────────────────────────────────────

// P11-B124 (PFL-084): Template upgrade — fetch latest rendered templates
// from server and regenerate all Skill files.  One-shot operation;
// exits after completion.
async function runUpgrade() {
  const UPGRADE_FLAG = path.join(WORKER_ROOT, 'template-upgrade-needed');
  const VERSION_FILE_SI = path.join(WORKER_ROOT, 'synapse-version.json');
  const SKILL_DIR = path.join(__dirname, '..'); // .claude/skills/synapse/

  console.log('┌──────────────────────────────────────────────┐');
  console.log('│  Synapse Template Upgrade (P11-B124 · PFL-084) │');
  console.log('└──────────────────────────────────────────────┘');
  console.log('');

  // Step 1: Check env vars
  const envCheck = checkEnv();
  if (!envCheck.ok) {
    console.error('❌ upgrade: env incomplete — missing: ' + envCheck.missing.join(', '));
    console.error('   Ensure SYNAPSE_API_URL, SYNAPSE_WORKER_ID, SYNAPSE_API_KEY, SYNAPSE_PROJECT_ID are set.');
    process.exit(1);
  }

  const config = SynapseClient.resolveConfig(envCheck.present);
  const workerId = config.workerId;
  const projectId = envCheck.present.SYNAPSE_PROJECT_ID;
  const role = envCheck.present.SYNAPSE_WORKER_ROLE || readRoleFromCache() || 'builder';
  const client = new SynapseClient(config);

  // Step 2: Get server version
  console.log('▎ Checking server template version...');
  const versionRes = await client.get('/v1/templates/versions');
  if (versionRes.error) {
    console.error('❌ upgrade: failed to fetch template versions — ' + (versionRes.message || 'unknown error'));
    process.exit(1);
  }
  const serverVersion = versionRes.data.version;
  const serverVersionShort = serverVersion ? serverVersion.slice(0, 16) + '...' : 'unknown';
  console.log('  Server version: ' + serverVersionShort);

  // Read local version for comparison display
  var localVersionShort = 'none';
  try {
    if (fs.existsSync(VERSION_FILE_SI)) {
      var localParsed = JSON.parse(fs.readFileSync(VERSION_FILE_SI, 'utf-8'));
      if (localParsed.version) {
        localVersionShort = localParsed.version.slice(0, 16) + '...';
      }
    }
  } catch (_) { /* best-effort */ }

  if (localVersionShort === serverVersionShort) {
    console.log('  ✅ Templates already up to date.');
    // Clean up stale flag if it exists
    try { if (fs.existsSync(UPGRADE_FLAG)) fs.unlinkSync(UPGRADE_FLAG); } catch (_) {}
    process.exit(0);
  }

  console.log('  Local: ' + localVersionShort + ' → Server: ' + serverVersionShort);

  // Step 3: Fetch rendered protocol
  console.log('▎ Fetching rendered templates from server...');
  var protocolUrl = '/v1/workers/' + workerId + '/protocol?project_id=' + projectId;
  if (role) protocolUrl += '&role=' + role;
  const protocolRes = await client.get(protocolUrl);
  if (protocolRes.error) {
    console.error('❌ upgrade: failed to fetch protocol — ' + (protocolRes.message || 'unknown error'));
    process.exit(1);
  }

  var data = protocolRes.data;

  // Step 4: Write Skill files
  console.log('▎ Writing Skill files to ' + SKILL_DIR + '...');

  var filesToWrite = [
    { name: '_protocol.md', content: data.collaboration_norms },
    { name: '_project.md', content: data.project_context },
    { name: 'role-' + role + '.md', content: data.role_instructions },
    { name: '_env.md', content: data.env_template },
  ];

  for (var i = 0; i < filesToWrite.length; i++) {
    var f = filesToWrite[i];
    if (!f.content || f.content === 'null') {
      console.log('  ⚠️  ' + f.name + ' — empty/null, skipping');
      continue;
    }
    try {
      fs.writeFileSync(path.join(SKILL_DIR, f.name), f.content, 'utf-8');
      console.log('  ✅ ' + f.name);
    } catch (e) {
      console.error('  ❌ ' + f.name + ' — ' + e.message);
    }
  }

  // Step 5: Write version file
  try {
    fs.writeFileSync(VERSION_FILE_SI, JSON.stringify({
      version: serverVersion,
      files: versionRes.data.files || {},
      updated_at: versionRes.data.updated_at || new Date().toISOString(),
    }, null, 2) + '\n', 'utf-8');
    console.log('  ✅ synapse-version.json updated');
  } catch (e) {
    console.error('  ❌ synapse-version.json — ' + e.message);
  }

  // Step 6: Remove upgrade-needed flag
  try {
    if (fs.existsSync(UPGRADE_FLAG)) {
      fs.unlinkSync(UPGRADE_FLAG);
      console.log('  ✅ template-upgrade-needed flag cleared');
    }
  } catch (_) { /* best-effort */ }

  // Step 7: Summary
  console.log('');
  console.log('✅ Template upgrade complete.');
  console.log('');
  console.log('⚠️  Skill files have been updated. Restart your Claude Code session');
  console.log('    to load the latest instructions.');
}

async function main() {
  // P12-B8 (HK-3): Write hook sentinel FIRST — before any potential failure.
  // If hook fires at all, this file exists. Timestamp enables staleness check.
  // AI/Worker can check this to diagnose "hook never fires" vs "hook fires but fails."
  try { fs.writeFileSync(HOOK_SENTINEL, `${new Date().toISOString()}\n`, 'utf-8'); } catch (e) { /* non-blocking */ }

  // P11-B124 (PFL-084): --upgrade is a one-shot operation, exit early
  if (UPGRADE_MODE) {
    await runUpgrade();
    return;
  }

  // PFL-110 (B122): Calculate age of existing snapshot before replacing it
  const oldSnapshotAge = getExistingSnapshotAge();

  const state = {
    envOk: false,
    env: {},
    envMissing: [],
    role: null,
    protocolOk: false,
    protocolData: null,
    protocolError: null,
    handshakeOk: false,
    handshakeData: null,
    handshakeError: null,
    authRequestsTotal: -1,
    authRequests: [],
    inProgressTotal: -1,
    inProgressTasks: [],
    readyTotal: -1,
    readyTasks: [],
    verificationTotal: -1,
    verificationTasks: [],
    allActiveTotal: -1,
    allActiveTasks: [],
    errors: [],
    warnings: [],
    heartbeatDaemon: null,
    // B96 PFL-093: WS daemon for real-time event push
    wsDaemon: null,
    recentWsEvents: [],
    // B84: PFL-077/079/082 mechanical guards
    activeTaskCount: 0,
    staleVerificationCount: 0,
    staleVerificationTasks: [],
    unreadMessagesTotal: 0,
    unreadMessages: [],
    // B90: apiUnreachable flag — prevent "0 active tasks" false signal when API is down
    apiUnreachable: false,
    // B122 PFL-110: quick refresh mode + old snapshot staleness context
    quickRefresh: QUICK_MODE || HEALTH_MODE,
    oldSnapshotAge: oldSnapshotAge,
    // P11-B124 (PFL-084): template upgrade flag — set below before writeState
    templateUpgradeNeeded: null,
  };

  // ── Step 0 (P11-B135 · PFL-127): Load .env inline — override polluted shell env ──
  // Claude Code Bash creates independent shells. `source .env` in one call
  // doesn't carry to the next. Global shell may have old SYNAPSE_API_KEY.
  // This reads .env directly and overrides process.env BEFORE checkEnv() runs,
  // so both the script's API calls and daemon spawn use the correct values.
  if (INLINE_ENV_MODE) {
    const envPath = path.join(WORKER_ROOT, '.env');
    const envResult = loadEnvFile(envPath);
    if (envResult.loaded) {
      let overridden = 0;
      for (const [key, value] of Object.entries(envResult.vars)) {
        if (key.startsWith('SYNAPSE_') || key === 'DATABASE_URL') {
          const oldVal = process.env[key];
          process.env[key] = value;
          if (oldVal !== value) {
            overridden++;
            if (oldVal && key === 'SYNAPSE_API_KEY') {
              // Log tail of key for debugging without exposing full secret
              const oldTail = oldVal.slice(-8);
              const newTail = value.slice(-8);
              console.log(`🔧 ${SCRIPT_NAME}: SYNAPSE_API_KEY overridden from .env (old tail: ...${oldTail} → new tail: ...${newTail})`);
            }
          }
        }
      }
      if (overridden > 0) {
        console.log(`📝 ${SCRIPT_NAME}: inline-env — ${overridden} var(s) overridden from ${envPath}`);
      }
    } else if (envResult.errors.length > 0) {
      // .env read errors are non-fatal — fall back to process.env
      console.log(`⚠️ ${SCRIPT_NAME}: inline-env — ${envResult.errors.join('; ')}`);
    }
    // If .env doesn't exist, that's fine — process.env is the fallback
  }

  // ── Step 1: Check environment ──────────────────────────────────
  const envCheck = checkEnv();
  state.envOk = envCheck.ok;
  state.env = envCheck.present;
  state.envMissing = envCheck.missing;
  state.role = envCheck.present.SYNAPSE_WORKER_ROLE || null;

  if (!envCheck.ok) {
    console.log(`❌ ${SCRIPT_NAME}: env incomplete — missing: ${envCheck.missing.join(', ')}`);
    writeState(state);
    if (!QUICK_MODE && !HEALTH_MODE) writeBootPrompt(state);
    process.exit(0);
  }

  if (!QUICK_MODE && !HEALTH_MODE) {
  // ── Step 1.5: Ensure Worker settings.local.json (B110 · Layer 2) ─
  const wsResult = ensureWorkerSettings();
  if (wsResult.created) {
    console.log(`📝 ${SCRIPT_NAME}: created ${wsResult.path} (per-Worker permissions auto-generated)`);
  }
  } // END !QUICK_MODE && !HEALTH_MODE: settings

  // ── Step 2: Create client ──────────────────────────────────────
  const config = SynapseClient.resolveConfig(envCheck.present);
  const workerId = config.workerId;
  const projectId = envCheck.present.SYNAPSE_PROJECT_ID;
  const client = new SynapseClient(config);

  // ── P11-B132: Write .session-alive BEFORE daemon spawn ──
  // Daemons check this file's timestamp to decide if the session is alive.
  // Updated on EVERY session-init run (full + --quick) so CronCreate wakeup
  // keeps the timestamp fresh, preventing daemon self-destruct.
  try {
    fs.writeFileSync(SESSION_ALIVE_FILE, JSON.stringify({
      updated_at: now(),
      pid: String(process.pid),
      mode: HEALTH_MODE ? 'health' : (QUICK_MODE ? 'quick' : 'full'),
    }), 'utf-8');
  } catch (_) { /* best-effort */ }

  if (!QUICK_MODE && !HEALTH_MODE) {
  // ── Step 2.4: Cleanup pre-B115 orphan daemons (PFL-116 · B121) ──
  // Must run BEFORE spawning new daemons — kills zombies that have no PID file.
  const orphanResult = cleanupOrphanDaemons();
  if (orphanResult.cleaned > 0) {
    console.log(`🧹 ${SCRIPT_NAME}: cleaned ${orphanResult.cleaned} pre-B115 orphan daemon(s)`);
  }

  // ── Step 2.5: Start heartbeat daemon (PFL-083 · B91 · B115 PID files) ──
  // B115 (PFL-116/118): Always spawn new daemon → kill old (PID file) → write new PID.
  // startHeartbeatDaemon() internally spawns first (so old daemon is fallback on failure),
  // then calls killOldDaemon(), then writes the new PID file.
  // No more "already running" skip — every SessionStart gets a fresh daemon.
  const hbResult = startHeartbeatDaemon();
  if (hbResult.started) {
    state.heartbeatDaemon = { running: true, pids: [String(hbResult.pid)], startedByUs: true };
  } else {
    // Spawn failed — fall back to checking if a prior daemon still runs
    state.heartbeatDaemon = checkHeartbeatDaemon();
    if (!state.heartbeatDaemon.running) {
      state.heartbeatDaemon.startedByUs = false;
      state.heartbeatDaemon.startError = hbResult.error;
    }
  }

  // ── Step 2.6: Start ws-daemon (PFL-093 · B96 · B115 PID files) ──────
  // B115 (PFL-116/117/118): Always spawn new daemon → kill old (PID file) → write new PID.
  // startWsDaemon() internally spawns first (so old daemon is fallback on failure),
  // then calls killOldDaemon(), then writes the new PID file.
  // Per-worker PID files eliminate cross-worker pgrep interference.
  const wsDaemonResult = startWsDaemon();
  if (wsDaemonResult.started) {
    state.wsDaemon = { running: true, pids: [String(wsDaemonResult.pid)], startedByUs: true };
  } else {
    // Spawn failed — fall back to checking if a prior daemon still runs
    state.wsDaemon = checkWsDaemon();
    if (!state.wsDaemon.running) {
      state.wsDaemon.startedByUs = false;
      if (wsDaemonResult.skippedNodeVersion) {
        state.wsDaemon.skippedNodeVersion = true;
        state.wsDaemon.nodeVersionError = wsDaemonResult.error;
      } else if (wsDaemonResult.error) {
        state.wsDaemon.startError = wsDaemonResult.error;
      }
    }
  }
  // Read recent WS events (even if daemon was already running)
  state.recentWsEvents = readRecentWsEvents(5);
  } // END !QUICK_MODE && !HEALTH_MODE: daemon management

  // B137: --health mode — run daemon self-heal BEFORE state sync
  // AI reads the REPAIRED state — daemons are already re-spawned if they died
  if (HEALTH_MODE) {
    const healthReport = dm.health();
    state._healthReport = healthReport;

    // Update daemon state for _task-current.md Connection section
    state.heartbeatDaemon = { running: true, pids: healthReport.heartbeat.pid ? [healthReport.heartbeat.pid] : [], healthMode: true };
    state.wsDaemon = { running: true, pids: healthReport.wsDaemon.pid ? [healthReport.wsDaemon.pid] : [], healthMode: true };

    if (healthReport.heartbeat.reSpawned) {
      console.log(`🫀 ${SCRIPT_NAME}: heartbeat daemon RE-SPAWNED (was dead, now pid ${healthReport.heartbeat.pid})`);
    }
    if (healthReport.wsDaemon.reSpawned) {
      console.log(`🔌 ${SCRIPT_NAME}: ws-daemon RE-SPAWNED (was dead, now pid ${healthReport.wsDaemon.pid})`);
    }
    if (!healthReport.heartbeat.reSpawned && !healthReport.wsDaemon.reSpawned) {
      // Silent when healthy — don't spam CronCreate wakeups
    }
    console.log(`✅ ${SCRIPT_NAME}: health check complete (hb: ${healthReport.heartbeat.reSpawned ? 're-spawned' : 'healthy'}, ws: ${healthReport.wsDaemon.reSpawned ? 're-spawned' : 'healthy'})`);
  }

  if (!QUICK_MODE && !HEALTH_MODE) {
  // ── Step 3: Fetch protocol ─────────────────────────────────────
  const protocolRole = state.role || 'builder';
  const protocolRes = await client.get(
    `/v1/workers/${workerId}/protocol?project_id=${projectId}&role=${protocolRole}&require_role=true`
  );

  if (protocolRes.error) {
    // P11-B97: 422 WORKER_ROLE_NOT_CONFIGURED is a config error — bail immediately, no retry
    if (protocolRes.status === 422) {
      state.protocolError = protocolRes.message || 'Worker role not configured';
      state.errors.push(`Protocol fetch: ${state.protocolError}`);
      console.log(`❌ ${SCRIPT_NAME}: worker role not configured on server`);
      console.log('   请在 Synapse 中为 Worker 配置角色（POST /v1/projects/{pid}/workers/{wid}/roles）');
      writeState(state);
      writeBootPrompt(state);
      process.exit(1);
    }
    state.protocolError = protocolRes.message || 'Unknown protocol error';
    state.errors.push(`Protocol fetch: ${state.protocolError}`);
    // Retry once after 2s (B100-A6: was 5s, too long vs 10s client timeout → worst case 25s)
    await new Promise(r => setTimeout(r, 2000));
    const retryRes = await client.get(
      `/v1/workers/${workerId}/protocol?project_id=${projectId}&role=${protocolRole}&require_role=true`
    );
    if (retryRes.error) {
      state.protocolError = `Retry also failed: ${retryRes.message}`;
      console.log(`❌ ${SCRIPT_NAME}: protocol fetch failed after retry`);
      writeState(state);
      writeBootPrompt(state);
      process.exit(0);
    }
    // Retry succeeded
    state.protocolOk = true;
    state.protocolData = retryRes.data;
  } else {
    state.protocolOk = true;
    state.protocolData = protocolRes.data;
  }

  // P11-B97: Belt-and-suspenders — if server still returned default_fallback
  // (e.g. old server without require_role support), client-side hard-fail
  if (state.protocolOk && state.protocolData?.role_source === 'default_fallback') {
    console.log(`❌ ${SCRIPT_NAME}: worker role not configured (role_source=default_fallback)`);
    console.log('   请在 Synapse 中为 Worker 配置角色（POST /v1/projects/{pid}/workers/{wid}/roles）');
    console.log('   或在 Worker metadata JSON 中添加 "role" 字段');
    writeState(state);
    writeBootPrompt(state);
    process.exit(1);
  }

  // Update role from protocol response if not set in env
  // P11-B83 PFL-078: protocol response 可能不返回 role → 保留 env 值作为 fallback
  if (!state.role && state.protocolData?.role) {
    state.role = state.protocolData.role;
  }
  // PFL-078: 默认值从 'builder' 改为 'unknown' — 静默覆盖比显式 unknown 更危险
  if (!state.role) {
    state.role = 'unknown';
    state.warnings.push('Role unknown — SYNAPSE_WORKER_ROLE not set in env and protocol did not return role. Defaulting to "unknown". Worker may not function correctly.');
  }

  // B105: Split protocol cache — essential fields (auto-load) vs collaboration_norms (on-demand)
  // Context overload root cause (B104): full 80KB JSON loaded at startup → Deepseek analysis paralysis.
  // Essential: role_instructions (15.5KB) + project_context (0.8KB) + env_template (1.9KB) ≈ 18KB
  // On-demand: collaboration_norms (29KB) — AI reads _collaboration-norms.md only when needed
  try {
    const essential = {
      role_instructions: state.protocolData?.role_instructions,
      project_context: state.protocolData?.project_context,
      env_template: state.protocolData?.env_template,
      unfilled_variables: state.protocolData?.unfilled_variables,
      role_source: state.protocolData?.role_source,
    };
    fs.writeFileSync(PROTOCOL_CACHE, JSON.stringify(essential, null, 2), 'utf-8');

    // Write collaboration_norms as standalone on-demand file
    if (state.protocolData?.collaboration_norms) {
      fs.writeFileSync(COLLABORATION_NORMS_FILE, state.protocolData.collaboration_norms, 'utf-8');
    }
  } catch (_) { /* non-critical */ }

  // ── Step 4: Handshake ──────────────────────────────────────────
  const handshakeRes = await client.post(`/v1/workers/${workerId}/handshake`, {
    agent_version: '1.0.0',
    capabilities: [
      { name: 'code-generation', description: 'Generate and modify code files' },
      { name: 'code-review', description: 'Review code for correctness and quality' },
    ],
    supported_events: ['task.assigned', 'task.updated', 'verification.completed'],
    preferred_channel: 'websocket',
  });

  if (handshakeRes.error) {
    state.handshakeError = handshakeRes.message || 'Unknown handshake error';
    state.errors.push(`Handshake: ${state.handshakeError}`);
  } else {
    state.handshakeOk = true;
    state.handshakeData = handshakeRes.data;
  }

  } else {
    // ── QUICK MODE: Skip protocol fetch + handshake ─────────────────
    // PFL-110 (B122): Quick refresh re-uses cached protocol data and skips
    // handshake (already done at session start). Role resolution:
    //   1. Try _protocol-cache.json (role_instructions keys)
    //   2. Fall back to env var SYNAPSE_WORKER_ROLE
    //   3. Fall back to 'unknown'
    const cachedRole = readRoleFromCache();
    if (cachedRole) {
      if (!state.role) state.role = cachedRole;
    } else if (!state.role) {
      state.role = 'unknown';
    }
    if (!state.role || state.role === 'unknown') {
      state.warnings.push('Quick refresh: role unknown — protocol cache unavailable and SYNAPSE_WORKER_ROLE not set. State sync may be incomplete.');
    }
    // Mark protocol as "cached" rather than "ok" to indicate stale data
    state.protocolOk = true;
    state.protocolData = { role_source: 'quick_refresh_cached' };
    console.log(`⚡ ${SCRIPT_NAME}: quick refresh — skipping protocol fetch + handshake (role: ${state.role}, old snapshot: ${oldSnapshotAge || 'N/A'})`);
  } // END QUICK_MODE: role from cache

  // ── P11-B132 (cron-native Layer 2): Heartbeat on every wakeup ──
  // This is defense-in-depth: daemon heartbeat (Layer 1, 55s interval)
  // plus cron heartbeat (Layer 2, each CronCreate wakeup).
  // Either channel alone keeps the Worker from going offline.
  // Runs in both full and --quick mode so CronCreate wakeup triggers it.
  try {
    const hbRes = await client.post('/v1/workers/' + workerId + '/heartbeat', { current_load: 0 });
    if (!hbRes.error && hbRes.data) {
      state._heartbeatRuntimeStatus = hbRes.data.runtime_status || 'unknown';
      // PFL-084 template auto-upgrade: check template_version in heartbeat response
      if (hbRes.data.template_version) {
        checkTemplateVersionInHeartbeat(hbRes.data.template_version, state);
      }
    } else {
      state.warnings.push('cron heartbeat failed: ' + (hbRes.message || 'unknown'));
    }
  } catch (hbErr) {
    state.warnings.push('cron heartbeat exception: ' + (hbErr.message || String(hbErr)));
  }

  // ── Step 5: State sync ─────────────────────────────────────────

  // 5a. Authorization requests
  const authRes = await client.get('/v1/workers/me/authorization-requests?status=pending');
  if (!authRes.error && authRes.data) {
    const authList = Array.isArray(authRes.data) ? authRes.data : (authRes.data.items || []);
    state.authRequestsTotal = authList.length;
    state.authRequests = authList;
  } else if (authRes.error) {
    state.authRequestsTotal = -1;
    if (authRes.status !== 404) {
      state.errors.push(`Auth requests: ${authRes.message}`);
    } else {
      state.authRequestsTotal = 0;
    }
  }

  // 5b. In-progress tasks
  const ipRes = await client.get(`/v1/projects/${projectId}/tasks?status=in_progress`);
  if (!ipRes.error && ipRes.data) {
    const ipList = Array.isArray(ipRes.data) ? ipRes.data : (ipRes.data.items || []);
    state.inProgressTotal = ipList.length;
    state.inProgressTasks = ipList;
  } else if (ipRes.error) {
    state.inProgressTotal = -1;
    if (ipRes.status !== 404) {
      state.errors.push(`In-progress tasks: ${ipRes.message}`);
    } else {
      state.inProgressTotal = 0;
    }
  }

  // 5c. Role-specific queries
  if (state.role === 'builder') {
    const readyRes = await client.get(`/v1/projects/${projectId}/tasks?status=ready`);
    if (!readyRes.error && readyRes.data) {
      const readyList = Array.isArray(readyRes.data) ? readyRes.data : (readyRes.data.items || []);
      state.readyTotal = readyList.length;
      state.readyTasks = readyList;
    } else if (readyRes.error) {
      state.readyTotal = -1;
      if (readyRes.status !== 404) {
        state.errors.push(`Ready tasks: ${readyRes.message}`);
      } else {
        state.readyTotal = 0;
      }
    }
  } else if (state.role === 'orchestrator') {
    // Verification queue (highest priority — tasks awaiting review)
    const verRes = await client.get(`/v1/projects/${projectId}/tasks?status=in_verification`);
    if (!verRes.error && verRes.data) {
      const verList = Array.isArray(verRes.data) ? verRes.data : (verRes.data.items || []);
      state.verificationTotal = verList.length;
      state.verificationTasks = verList;
    } else if (verRes.error) {
      state.verificationTotal = -1;
      if (verRes.status !== 404) {
        state.errors.push(`Verification tasks: ${verRes.message}`);
      } else {
        state.verificationTotal = 0;
      }
    }

    // Ready tasks (for assignment — Orchestrator needs to assign these to Builders)
    const readyRes = await client.get(`/v1/projects/${projectId}/tasks?status=ready`);
    if (!readyRes.error && readyRes.data) {
      const readyList = Array.isArray(readyRes.data) ? readyRes.data : (readyRes.data.items || []);
      state.readyTotal = readyList.length;
      state.readyTasks = readyList;
    } else if (readyRes.error) {
      state.readyTotal = -1;
      if (readyRes.status !== 404) {
        state.errors.push(`Ready tasks (Orch): ${readyRes.message}`);
      } else {
        state.readyTotal = 0;
      }
    }

    // All active tasks (for supervisor loop — full picture)
    const allRes = await client.get(`/v1/projects/${projectId}/tasks`);
    if (!allRes.error && allRes.data) {
      const allList = Array.isArray(allRes.data) ? allRes.data : (allRes.data.items || []);
      const active = allList.filter(t => t.status !== 'completed' && t.status !== 'cancelled');
      state.allActiveTasks = active;
      state.allActiveTotal = active.length;
    } else if (allRes.error) {
      state.allActiveTotal = -1;
    }
  }

  // 5d. Unread messages (PFL-080 hardening — O must see B's messages, not just task status)
  state.unreadMessagesTotal = 0;
  state.unreadMessages = [];
  const allTasks = [
    ...(state.inProgressTasks || []),
    ...(state.verificationTasks || []),
    ...(state.readyTasks || []),
  ];
  // Deduplicate by task id
  const seen = new Set();
  const uniqueTasks = allTasks.filter(t => { const k = t.id; if (seen.has(k)) return false; seen.add(k); return true; });
  const MSG_CHECK_CAP = 10;
  if (uniqueTasks.length > MSG_CHECK_CAP) {
    state.warnings.push(`Unread message check capped at ${MSG_CHECK_CAP} of ${uniqueTasks.length} active tasks — messages on tasks beyond the cap were not checked.`);
  }
  for (const t of uniqueTasks.slice(0, MSG_CHECK_CAP)) { // Cap to avoid excessive API calls
    try {
      const msgRes = await client.get(`/v1/projects/${projectId}/tasks/${t.id}/messages?is_resolved=false`);
      if (!msgRes.error && msgRes.data) {
        const msgList = Array.isArray(msgRes.data) ? msgRes.data : (msgRes.data.items || []);
        const unread = msgList.filter(m => !m.is_resolved && (m.message_type === 'blocking' || m.message_type === 'clarification' || m.message_type === 'handoff'));
        if (unread.length > 0) {
          state.unreadMessages.push({ taskId: t.id, taskTitle: t.title || t.id, count: unread.length, types: [...new Set(unread.map(m => m.message_type))] });
          state.unreadMessagesTotal += unread.length;
        }
      }
    } catch (_) { /* best-effort — don't block startup on message query failure */ }
  }

  // ── Step 5e: Active task count + stale detection (PFL-077/079/082) ─
  // PFL-079/082: Compute total active tasks for "do NOT judge as idle" banner.
  // Active = any task that is NOT completed/cancelled. If count > 0, Worker
  // must not exit — tasks exist that need attention, even if current queue looks empty.
  let activeTaskCount = 0;
  if (state.inProgressTotal > 0) activeTaskCount += state.inProgressTotal;
  if (state.verificationTotal > 0) activeTaskCount += state.verificationTotal;
  // For Builder: ready tasks are the work queue — they count as active
  if (state.role === 'builder' && state.readyTotal > 0) {
    activeTaskCount += state.readyTotal;
  }
  // For Orchestrator: use allActiveTotal if available (more comprehensive)
  if (state.role === 'orchestrator' && state.allActiveTotal > 0) {
    activeTaskCount = state.allActiveTotal;
  }
  state.activeTaskCount = activeTaskCount;

  // B90: Detect API unreachable — when ALL queried totals are -1, "0 active tasks"
  // is a false signal. activeTaskCount = 0 can mean either "truly idle" or "API down,
  // can't determine". The apiUnreachable flag disambiguates for the writeState banner.
  const queriedTotals = [state.inProgressTotal];
  if (state.role === 'builder') { queriedTotals.push(state.readyTotal); }
  else if (state.role === 'orchestrator') { queriedTotals.push(state.readyTotal, state.verificationTotal); }
  state.apiUnreachable = queriedTotals.length > 0 && queriedTotals.every(t => t < 0);

  // B96 PFL-093: Detect dead WS daemon — reconnect exhausted
  try {
    const statusFile = path.join(__dirname, '..', '_ws-status.json');
    if (fs.existsSync(statusFile)) {
      const statusRaw = fs.readFileSync(statusFile, 'utf-8');
      const status = JSON.parse(statusRaw);
      if (status.status === 'dead') {
        state.wsDaemonDead = true;
        state.wsDaemonDeadSince = status.since || 'unknown';
        state.warnings.push(
          `WS Daemon has crashed after 3 reconnect attempts (since ${state.wsDaemonDeadSince}). ` +
          'Real-time push is unavailable — falling back to HTTP polling. ' +
          'Report to Orchestrator: POST /tasks/{id}/messages with @Orchestrator mentioning WS daemon failure.'
        );
      }
    }
  } catch (_) { /* best-effort */ }

  // PFL-077: Detect stale in_verification tasks (>15 min without update).
  // These indicate Human is not responding — O should not wait forever.
  state.staleVerificationCount = 0;
  state.staleVerificationTasks = [];
  if (state.verificationTasks && state.verificationTasks.length > 0) {
    const nowTs = Date.now();
    const STALE_THRESHOLD_MS = 15 * 60 * 1000; // 15 minutes
    for (const t of state.verificationTasks) {
      const updatedAt = t.updated_at ? new Date(t.updated_at).getTime() : 0;
      if (updatedAt > 0 && (nowTs - updatedAt) > STALE_THRESHOLD_MS) {
        state.staleVerificationTasks.push(t);
      }
    }
    state.staleVerificationCount = state.staleVerificationTasks.length;
  }

  // ── P11-B124 (PFL-084): Check for template upgrade flag ──
  // heartbeat daemon writes .claude/template-upgrade-needed on version mismatch.
  // Surface this in _task-current.md so the Worker AI sees the upgrade banner.
  try {
    const upgradeFlagFile = path.join(WORKER_ROOT, 'template-upgrade-needed');
    if (fs.existsSync(upgradeFlagFile)) {
      const raw = fs.readFileSync(upgradeFlagFile, 'utf-8');
      state.templateUpgradeNeeded = JSON.parse(raw);
    }
  } catch (_) { /* best-effort */ }

  // ── Step 6: Write output (PFL-115 guard: don't overwrite healthy snapshot) ──
  // PFL-115 (B117): 不覆盖已有成功快照。如果当前快照有错误且已有今日健康快照，保留旧快照。
  // B122 PFL-110: Quick refresh ALWAYS overwrites — the point is to refresh stale data.
  const hasErrors = state.errors && state.errors.length > 0;
  const existingHealthy = isExistingSnapshotHealthy();
  if (hasErrors && existingHealthy && !QUICK_MODE && !HEALTH_MODE) {
    console.log(`⚠️ ${SCRIPT_NAME}: PFL-115 — 保留今日健康快照，当前快照有 ${state.errors.length} 个错误，不覆盖。`);
    console.log('   旧快照可能已过期——AI 应主动重试 API 确认状态。');
  } else {
    writeState(state);
  }

  // P12-B5: --json mode — output full state JSON to stdout for Codex workers
  // whose .agents/ sandbox prevents _task-current.md file reads.
  if (JSON_MODE && !SILENT_MODE) {
    outputStateJson(state);
  }

  // B112 PFL-112: Generate _boot-prompt.md for one-click cold-start
  // B122 PFL-110: Skip in quick/health mode — boot prompt is only for cold starts
  if (!QUICK_MODE && !HEALTH_MODE) writeBootPrompt(state);

  // ── Step 7: Output banner to stdout ───────────────────────────
  if (state.protocolOk) {
    const banner = roleBanner(state);
    console.log(banner);
    const modeLabel = HEALTH_MODE ? ' (health — daemon self-heal + refresh)' : (QUICK_MODE ? ` (quick refresh, old snapshot was ${oldSnapshotAge || 'unknown'} old)` : '');
    console.log(`\n📋 状态已写入: _task-current.md${modeLabel}`);
  } else {
    console.log(`⚠️ ${SCRIPT_NAME}: partial success — state written to _task-current.md`);
    console.log(`   协议未获取，角色横幅无法渲染。检查 API 连接。`);
  }

  process.exit(0);
}

// ── Entry point ─────────────────────────────────────────────────────
main().catch((err) => {
  console.error(`❌ ${SCRIPT_NAME}: unexpected error — ${err.message}`);
  // Write minimal error state
  const errorState = {
    envOk: false,
    env: {},
    envMissing: [],
    errors: [`Script failure: ${err.message}`],
    warnings: [],
    role: null,
    protocolOk: false,
    handshakeOk: false,
    authRequestsTotal: -1,
    inProgressTotal: -1,
    readyTotal: -1,
    verificationTotal: -1,
    allActiveTotal: -1,
    unreadMessagesTotal: -1,
    unreadMessages: [],
    heartbeatDaemon: null,
    activeTaskCount: 0,
    staleVerificationCount: 0,
    staleVerificationTasks: [],
    apiUnreachable: true,  // B90: assume unreachable on script failure — safer default
  };
  try {
    writeState(errorState);
  } catch (_) { /* last resort */ }
  process.exit(0);
});

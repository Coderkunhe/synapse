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
 *   node scripts/session-init.js
 *
 * Environment:
 *   SYNAPSE_API_URL      — Synapse instance base URL
 *   SYNAPSE_WORKER_ID    — Worker's agent ID
 *   SYNAPSE_PROJECT_ID   — Default project ID
 *   SYNAPSE_API_KEY      — Bearer token (falls back to OS keychain)
 *   SYNAPSE_WORKER_ROLE  — "builder" | "orchestrator" | "steward"
 *
 * @version 1.2.0 — B110: auto-generate per-Worker settings.local.json (Layer 2 治本)
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');
const { SynapseClient } = require('./api-client');
const { getKey } = require('./keychain');

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

// ── PID files for daemon lifecycle (PFL-116/117/118 · B115) ──────────
// Each Worker writes its own daemon PIDs to .claude/.daemon-*.pid.
// On startup, stale PIDs from prior sessions are killed before spawn.
// This replaces the global pgrep approach which caused cross-worker
// interference and orphan accumulation.
// NOTE: WORKER_ROOT is already at .claude/ level (3 dirs up from scripts/),
// so PID files go directly under WORKER_ROOT, not .claude/.claude/.
const HEARTBEAT_PID_FILE = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
const WS_DAEMON_PID_FILE = path.join(WORKER_ROOT, '.daemon-ws.pid');

// ── Helpers ─────────────────────────────────────────────────────────

/** Current ISO timestamp for output files. */
function now() {
  return new Date().toISOString();
}

/**
 * Read a daemon PID from its PID file.
 * Returns the PID as a number, or null if the file doesn't exist or is invalid.
 *
 * @param {string} pidFile - Path to the PID file
 * @returns {number|null}
 */
function readPidFile(pidFile) {
  try {
    if (!fs.existsSync(pidFile)) return null;
    const raw = fs.readFileSync(pidFile, 'utf-8').trim();
    const pid = parseInt(raw, 10);
    if (isNaN(pid) || pid <= 0) return null;
    return pid;
  } catch (_e) {
    return null;
  }
}

/**
 * Write a daemon PID to its PID file.
 *
 * @param {string} pidFile - Path to the PID file
 * @param {number} pid - The daemon PID
 */
function writePidFile(pidFile, pid) {
  try {
    fs.writeFileSync(pidFile, String(pid), 'utf-8');
  } catch (_e) {
    // Best-effort — daemon still runs even if PID file write fails
  }
}

/**
 * Check if a process with the given PID is alive.
 *
 * @param {number} pid
 * @returns {boolean}
 */
function isProcessAlive(pid) {
  try {
    // signal 0 = existence check, no signal sent
    process.kill(pid, 0);
    return true;
  } catch (_e) {
    return false;
  }
}

/**
 * Kill an old daemon identified by its PID file.
 * Reads the PID, checks if the process is alive, sends SIGTERM if so,
 * waits briefly for graceful shutdown, then cleans up the PID file.
 *
 * @param {string} pidFile - Path to the PID file
 * @returns {{ killed: boolean, oldPid: number|null }}
 */
function killOldDaemon(pidFile) {
  const oldPid = readPidFile(pidFile);
  if (oldPid === null) return { killed: false, oldPid: null };

  if (!isProcessAlive(oldPid)) {
    // Process already dead — just clean up the stale PID file
    try { fs.unlinkSync(pidFile); } catch (_e) { /* ok */ }
    return { killed: false, oldPid };
  }

  try {
    process.kill(oldPid, 'SIGTERM');
    // Give the old daemon up to 1s to shut down gracefully
    const start = Date.now();
    while (Date.now() - start < 1000) {
      if (!isProcessAlive(oldPid)) break;
      // Busy-wait in 50ms increments
      const until = Date.now() + 50;
      while (Date.now() < until) { /* spin */ }
    }
    // Force kill if still alive
    if (isProcessAlive(oldPid)) {
      try { process.kill(oldPid, 'SIGKILL'); } catch (_e) { /* ok */ }
    }
    return { killed: true, oldPid };
  } catch (_e) {
    return { killed: false, oldPid };
  } finally {
    try { fs.unlinkSync(pidFile); } catch (_e) { /* ok */ }
  }
}

/**
 * PFL-116 (B121): Find and kill pre-B115 orphan daemon processes.
 *
 * B115 introduced per-worker PID files (readPidFile/writePidFile/killOldDaemon).
 * New daemons are tracked by PID file and killed on next startup. But pre-B115
 * daemons (spawned with detached:true + unref()) have NO PID file, so
 * killOldDaemon() can't find them. Each Worker restart accumulates orphans.
 *
 * This function bridges the gap: it scans running processes for daemon scripts
 * matching THIS worker's scripts directory, and kills any that aren't tracked
 * by a PID file. Post-B115 daemons are left alone (they're tracked).
 *
 * Called BEFORE spawning new daemons — cleanup first, then spawn fresh.
 *
 * @returns {{ cleaned: number }} — number of orphan processes terminated
 */
function cleanupOrphanDaemons() {
  const knownPids = new Set();
  for (const pidFile of [HEARTBEAT_PID_FILE, WS_DAEMON_PID_FILE]) {
    const pid = readPidFile(pidFile);
    if (pid !== null && isProcessAlive(pid)) knownPids.add(pid);
  }

  let cleaned = 0;
  try {
    const hbScript = path.join(__dirname, 'heartbeat.js');
    const wsScript = path.join(__dirname, 'ws-daemon.js');

    // Use ps to list all processes, filter in JS to avoid shell escaping issues
    const output = execSync('ps -eo pid,command', { encoding: 'utf-8' });
    const lines = output.trim().split('\n');

    for (const line of lines) {
      const parts = line.trim().split(/\s+/);
      const pid = parseInt(parts[0], 10);
      if (isNaN(pid)) continue;
      const cmd = parts.slice(1).join(' ');

      // Match this Worker's daemon scripts only (scoped by __dirname)
      if (!cmd.includes(hbScript) && !cmd.includes(wsScript)) continue;
      // Skip our own process
      if (pid === process.pid) continue;
      // Skip daemons tracked by PID files (post-B115, managed by killOldDaemon)
      if (knownPids.has(pid)) continue;

      // Pre-B115 orphan: running but no PID file tracks it
      try {
        process.kill(pid, 'SIGTERM');
        // Brief grace period for graceful shutdown
        const start = Date.now();
        while (Date.now() - start < 500) {
          if (!isProcessAlive(pid)) break;
        }
        if (isProcessAlive(pid)) {
          try { process.kill(pid, 'SIGKILL'); } catch (_e) { /* already gone */ }
        }
        cleaned++;
      } catch (_e) {
        // Process may have exited between ps and kill — not an error
      }
    }
  } catch (_e) {
    // ps may fail in constrained environments — non-blocking
  }

  return { cleaned };
}

/**
 * Check if a heartbeat daemon process is running.
 * Uses the per-worker PID file (PFL-117 · B115) — no global pgrep,
 * so Builder and Orchestrator daemons are independently tracked.
 *
 * @returns {{ running: boolean, pids: string[] }}
 */
function checkHeartbeatDaemon() {
  const pid = readPidFile(HEARTBEAT_PID_FILE);
  if (pid === null) return { running: false, pids: [] };
  if (isProcessAlive(pid)) return { running: true, pids: [String(pid)] };
  // Stale PID file — clean up
  try { fs.unlinkSync(HEARTBEAT_PID_FILE); } catch (_e) { /* ok */ }
  return { running: false, pids: [] };
}

/**
 * Start the heartbeat daemon as a detached background process (PFL-083 · B91).
 *
 * PFL-116/117/118 (B115): Before spawning, kills any old heartbeat daemon
 * tracked by the per-worker PID file. After spawning, writes the new PID.
 *
 * Uses child_process.spawn with detached:true + unref() — the daemon survives
 * the parent hook subprocess exit.
 *
 * Returns the daemon PID on success, null on failure.
 */
function startHeartbeatDaemon() {
  try {
    const scriptPath = path.join(__dirname, 'heartbeat.js');
    if (!fs.existsSync(scriptPath)) {
      return { started: false, error: 'heartbeat.js not found at ' + scriptPath };
    }
    const child = spawn(process.execPath, [scriptPath], {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },  // inherit SYNAPSE_* vars
    });
    child.unref();  // detach from parent — daemon survives hook exit
    if (child.pid) {
      // PFL-116: kill old daemon AFTER new one is confirmed spawned.
      // If spawn fails, the old daemon is left untouched as fallback.
      killOldDaemon(HEARTBEAT_PID_FILE);
      writePidFile(HEARTBEAT_PID_FILE, child.pid);
    }
    return { started: true, pid: child.pid };
  } catch (e) {
    return { started: false, error: e.message };
  }
}

/**
 * Check if the ws-daemon process is running.
 * Uses the per-worker PID file (PFL-117 · B115) — no global pgrep.
 *
 * @returns {{ running: boolean, pids: string[] }}
 */
function checkWsDaemon() {
  const pid = readPidFile(WS_DAEMON_PID_FILE);
  if (pid === null) return { running: false, pids: [] };
  if (isProcessAlive(pid)) return { running: true, pids: [String(pid)] };
  // Stale PID file — clean up
  try { fs.unlinkSync(WS_DAEMON_PID_FILE); } catch (_e) { /* ok */ }
  return { running: false, pids: [] };
}

/**
 * Start the ws-daemon as a detached background process (PFL-093 · B96).
 *
 * PFL-116/117/118 (B115): Before spawning, kills any old ws-daemon
 * tracked by the per-worker PID file. After spawning, writes the new PID.
 *
 * The ws-daemon maintains a persistent WebSocket connection to the Synapse
 * server for real-time event push. On disconnect, it auto-reconnects with
 * 1s→5s→25s backoff. Events are written to _ws-events.jsonl.
 *
 * Requires Node.js ≥22 (native WebSocket global). On older Node.js,
 * ws-daemon is skipped gracefully — the Worker falls back to HTTP polling
 * (which was the de-facto behavior before B96 anyway).
 *
 * @returns {{ started: boolean, pid?: number, error?: string, skippedNodeVersion?: boolean }}
 */
function startWsDaemon() {
  try {
    // Version guard: native WebSocket requires Node.js ≥22
    const nodeVersion = process.versions?.node;
    if (nodeVersion) {
      const major = parseInt(String(nodeVersion).split('.')[0], 10);
      if (major < 22) {
        return { started: false, skippedNodeVersion: true, error: `Node.js ${nodeVersion} < 22 — WebSocket not available` };
      }
    }

    const scriptPath = path.join(__dirname, 'ws-daemon.js');
    if (!fs.existsSync(scriptPath)) {
      return { started: false, error: 'ws-daemon.js not found at ' + scriptPath };
    }
    const child = spawn(process.execPath, [scriptPath], {
      detached: true,
      stdio: 'ignore',
      env: { ...process.env },  // inherit SYNAPSE_* vars
    });
    child.unref();  // detach from parent — daemon survives hook exit
    if (child.pid) {
      // PFL-116: kill old daemon AFTER new one is confirmed spawned
      killOldDaemon(WS_DAEMON_PID_FILE);
      writePidFile(WS_DAEMON_PID_FILE, child.pid);
    }
    return { started: true, pid: child.pid };
  } catch (e) {
    return { started: false, error: e.message };
  }
}

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
  const lines = [
    `# Session State — ${now()}`,
    '',
    '> ⚠️ Auto-generated by session-init.js. Do not edit manually.',
    '> The AI reads this file to understand current state before making judgments.',
    '',
  ];

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
  lines.push('  prompt: "Wake up and check for work. Read _task-current.md. If there are active tasks, continue working. If idle, set another CronCreate and wait.",');
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
    // Heartbeat daemon status (A5: SessionStart hook 三阶段无状态协调 · B91: auto-start)
    if (state.heartbeatDaemon) {
      if (state.heartbeatDaemon.running) {
        const tag = state.heartbeatDaemon.startedByUs ? '🆕 auto-started by session-init' : 'already running';
        lines.push(`- **Heartbeat daemon**: ✅ running (pid: ${state.heartbeatDaemon.pids.join(', ')}, ${tag})`);
      } else if (state.heartbeatDaemon.startError) {
        lines.push(`- **Heartbeat daemon**: 🔴 FAILED TO START — ${state.heartbeatDaemon.startError}. AI should send manual heartbeat.`);
      } else if (state.heartbeatDaemon.error) {
        lines.push(`- **Heartbeat daemon**: ⚠️ unable to check (${state.heartbeatDaemon.error})`);
      } else {
        lines.push('- **Heartbeat daemon**: ⚠️ NOT RUNNING — AI should check before proceeding');
      }
    }
    // WS daemon status (B96 PFL-093)
    if (state.wsDaemon) {
      if (state.wsDaemon.running) {
        const tag = state.wsDaemon.startedByUs ? '🆕 auto-started by session-init' : 'already running';
        lines.push(`- **WS Daemon**: ✅ running (pid: ${state.wsDaemon.pids.join(', ')}, ${tag})`);
        // Recent events
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
  lines.push('');
  lines.push('## 📝 Active Tasks (in_progress)');
  lines.push('');
  if (state.inProgressTotal === 0) {
    lines.push('✅ No in-progress tasks.');
  } else if (state.inProgressTotal > 0) {
    for (const t of (state.inProgressTasks || [])) {
      lines.push(`- **${t.title || t.id}** (\`${t.id}\`) — status: \`${t.status}\``);
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
        lines.push(`- **${t.title || t.id}** (\`${t.id}\`)${deps}`);
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
        lines.push(`- 🔴 **${t.title || t.id}** (\`${t.id}\`) — submitted, awaiting review`);
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
        lines.push(`- 🟡 **${t.title || t.id}** (\`${t.id}\`)${deps} — needs assignment`);
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

  // ── Footer ──
  lines.push('');
  lines.push('---');
  lines.push(`*Generated ${now()} by session-init.js (B98 脚本硬约束)*`);

  fs.writeFileSync(OUTPUT_FILE, lines.join('\n') + '\n', 'utf-8');
}

/**
 * Write _boot-prompt.md at Worker root for cold-start bootstrap (B112 PFL-112).
 *
 * B112 v1 lesson: 64-line markdown with sections/headers/bullets → AI treats it as
 * a document to analyze and summarize, then stops. It does NOT call CronCreate.
 * The episodic model's default is "read → understand → summarize → suggest → stop".
 *
 * B112 v2: Radically minimal. 3-4 lines, no markdown structure, no explanations.
 * The AI has nothing to analyze — only one action to take. Imperative, non-negotiable.
 *
 * Idempotent: overwrites on every SessionStart with fresh state.
 */
function writeBootPrompt(state) {
  const role = state.role || 'worker';

  const roleLine = {
    builder: 'You are the Builder Worker. Claim ready tasks, execute, collect evidence, submit.',
    orchestrator: 'You are the Orchestrator Worker. Assign tasks, verify results, close tasks.',
    steward: 'You are the Steward Worker. Review code, audit security, report findings.',
  }[role] || `You are a Synapse ${role} Worker.`;

  const lines = [
    `CronCreate({cron: "*/1 * * * *", prompt: "Wake up and check for work. Read _task-current.md. Continue working if active tasks exist, ScheduleWakeup if idle.", recurring: true})`,
    '',
    `Then: read .claude/skills/synapse/_task-current.md → read .claude/skills/synapse/SKILL.md → enter work loop. ${roleLine}`,
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

async function main() {
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
  };

  // ── Step 1: Check environment ──────────────────────────────────
  const envCheck = checkEnv();
  state.envOk = envCheck.ok;
  state.env = envCheck.present;
  state.envMissing = envCheck.missing;
  state.role = envCheck.present.SYNAPSE_WORKER_ROLE || null;

  if (!envCheck.ok) {
    console.log(`❌ ${SCRIPT_NAME}: env incomplete — missing: ${envCheck.missing.join(', ')}`);
    writeState(state);
    writeBootPrompt(state);
    process.exit(0);
  }

  // ── Step 1.5: Ensure Worker settings.local.json (B110 · Layer 2) ─
  const wsResult = ensureWorkerSettings();
  if (wsResult.created) {
    console.log(`📝 ${SCRIPT_NAME}: created ${wsResult.path} (per-Worker permissions auto-generated)`);
  }

  // ── Step 2: Create client ──────────────────────────────────────
  const config = SynapseClient.resolveConfig(envCheck.present);
  const workerId = config.workerId;
  const projectId = envCheck.present.SYNAPSE_PROJECT_ID;
  const client = new SynapseClient(config);

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

  // ── Step 6: Write output (PFL-115 guard: don't overwrite healthy snapshot) ──
  // PFL-115 (B117): 不覆盖已有成功快照。如果当前快照有错误且已有今日健康快照，保留旧快照。
  const hasErrors = state.errors && state.errors.length > 0;
  const existingHealthy = isExistingSnapshotHealthy();
  if (hasErrors && existingHealthy) {
    console.log(`⚠️ ${SCRIPT_NAME}: PFL-115 — 保留今日健康快照，当前快照有 ${state.errors.length} 个错误，不覆盖。`);
    console.log('   旧快照可能已过期——AI 应主动重试 API 确认状态。');
  } else {
    writeState(state);
  }

  // B112 PFL-112: Generate _boot-prompt.md for one-click cold-start
  writeBootPrompt(state);

  // ── Step 7: Output banner to stdout ───────────────────────────
  if (state.protocolOk) {
    console.log(roleBanner(state));
    console.log(`\n📋 状态已写入: _task-current.md`);
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

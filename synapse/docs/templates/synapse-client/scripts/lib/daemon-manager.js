/**
 * daemon-manager.js — Daemon lifecycle management for Synapse Worker.
 *
 * P11-B137: Extracted from session-init.js. Handles spawn, check, kill,
 * orphan cleanup, and health self-healing for heartbeat and WS daemons.
 *
 * P14-B6: Extended with heartbeat functional freshness check (PFL-173)
 * and unstaged git changes detection (PFL-174).
 *
 * All functions are deterministic and testable — they depend only on
 * filesystem (fs), process table (ps), and child_process.spawn.
 *
 * @version 1.1.0 — B6: +checkHeartbeatFreshness +checkUnstagedChanges
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');

/**
 * Create a daemon manager scoped to a Worker root directory.
 *
 * @param {string} workerRoot — path to the Worker's .claude/ directory
 * @param {string} scriptsDir — path to the scripts/ directory (for heartbeat.js, ws-daemon.js)
 * @returns {object} daemon management API
 */
function createDaemonManager(workerRoot, scriptsDir) {
  const HEARTBEAT_PID_FILE = path.join(workerRoot, '.daemon-heartbeat.pid');
  const WS_DAEMON_PID_FILE = path.join(workerRoot, '.daemon-ws.pid');
  const SESSION_ALIVE_FILE = path.join(workerRoot, '.session-alive');

  // ── PID file helpers ──────────────────────────────────────────────

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

  function writePidFile(pidFile, pid) {
    try {
      fs.writeFileSync(pidFile, String(pid), 'utf-8');
    } catch (_e) {
      // Best-effort — daemon still runs even if PID file write fails
    }
  }

  function isProcessAlive(pid) {
    try {
      process.kill(pid, 0); // signal 0 = existence check
      return true;
    } catch (_e) {
      return false;
    }
  }

  // ── Daemon lifecycle ──────────────────────────────────────────────

  function killOldDaemon(pidFile) {
    const oldPid = readPidFile(pidFile);
    if (oldPid === null) return { killed: false, oldPid: null };

    if (!isProcessAlive(oldPid)) {
      try { fs.unlinkSync(pidFile); } catch (_e) { /* ok */ }
      return { killed: false, oldPid };
    }

    try {
      process.kill(oldPid, 'SIGTERM');
      const start = Date.now();
      while (Date.now() - start < 1000) {
        if (!isProcessAlive(oldPid)) break;
        const until = Date.now() + 50;
        while (Date.now() < until) { /* spin */ }
      }
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

  function cleanupOrphanDaemons() {
    const knownPids = new Set();
    for (const pidFile of [HEARTBEAT_PID_FILE, WS_DAEMON_PID_FILE]) {
      const pid = readPidFile(pidFile);
      if (pid !== null && isProcessAlive(pid)) knownPids.add(pid);
    }

    let cleaned = 0;
    try {
      const hbScript = path.join(scriptsDir, 'heartbeat.js');
      const wsScript = path.join(scriptsDir, 'ws-daemon.js');

      const output = execSync('ps -eo pid,command', { encoding: 'utf-8' });
      const lines = output.trim().split('\n');

      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const pid = parseInt(parts[0], 10);
        if (isNaN(pid)) continue;
        const cmd = parts.slice(1).join(' ');

        if (!cmd.includes(hbScript) && !cmd.includes(wsScript)) continue;
        if (pid === process.pid) continue;
        if (knownPids.has(pid)) continue;

        try {
          process.kill(pid, 'SIGTERM');
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

  // ── Heartbeat daemon ──────────────────────────────────────────────

  function checkHeartbeatDaemon() {
    const pid = readPidFile(HEARTBEAT_PID_FILE);
    if (pid === null) return { running: false, pids: [] };
    if (isProcessAlive(pid)) return { running: true, pids: [String(pid)] };
    try { fs.unlinkSync(HEARTBEAT_PID_FILE); } catch (_e) { /* ok */ }
    return { running: false, pids: [] };
  }

  function startHeartbeatDaemon() {
    try {
      const scriptPath = path.join(scriptsDir, 'heartbeat.js');
      if (!fs.existsSync(scriptPath)) {
        return { started: false, error: 'heartbeat.js not found at ' + scriptPath };
      }
      const child = spawn(process.execPath, [scriptPath, '--session-pid', String(process.ppid)], {
        detached: true,
        stdio: 'ignore',
        env: { ...process.env },
      });
      child.unref();
      if (child.pid) {
        killOldDaemon(HEARTBEAT_PID_FILE);
        writePidFile(HEARTBEAT_PID_FILE, child.pid);
      }
      return { started: true, pid: child.pid };
    } catch (e) {
      return { started: false, error: e.message };
    }
  }

  // ── WS daemon ─────────────────────────────────────────────────────

  function checkWsDaemon() {
    const pid = readPidFile(WS_DAEMON_PID_FILE);
    if (pid === null) return { running: false, pids: [] };
    if (isProcessAlive(pid)) return { running: true, pids: [String(pid)] };
    try { fs.unlinkSync(WS_DAEMON_PID_FILE); } catch (_e) { /* ok */ }
    return { running: false, pids: [] };
  }

  function startWsDaemon() {
    try {
      const nodeVersion = process.versions?.node;
      if (nodeVersion) {
        const major = parseInt(String(nodeVersion).split('.')[0], 10);
        if (major < 22) {
          return { started: false, skippedNodeVersion: true, error: `Node.js ${nodeVersion} < 22 — WebSocket not available` };
        }
      }

      const scriptPath = path.join(scriptsDir, 'ws-daemon.js');
      if (!fs.existsSync(scriptPath)) {
        return { started: false, error: 'ws-daemon.js not found at ' + scriptPath };
      }
      const child = spawn(process.execPath, [scriptPath, '--session-pid', String(process.ppid)], {
        detached: true,
        stdio: 'ignore',
        env: { ...process.env },
      });
      child.unref();
      if (child.pid) {
        killOldDaemon(WS_DAEMON_PID_FILE);
        writePidFile(WS_DAEMON_PID_FILE, child.pid);
      }
      return { started: true, pid: child.pid };
    } catch (e) {
      return { started: false, error: e.message };
    }
  }

  // ── B6: Heartbeat freshness ──────────────────────────────────────

  /**
   * Check functional heartbeat freshness (P14-B6 · PFL-173).
   *
   * Goes beyond process liveness — verifies the daemon has actually
   * sent a successful heartbeat recently. A zombie daemon (PID alive
   * but stuck event loop) passes isProcessAlive but fails this check.
   *
   * Reads .daemon-heartbeat-last-success.txt written by heartbeat.js
   * on each successful POST.
   *
   * @param {string} wRoot — path to Worker's .claude/ directory
   * @returns {{ fresh: boolean, lastSuccess: string|null, ageSeconds: number|null }}
   */
  function checkHeartbeatFreshness(wRoot) {
    const HB_FRESHNESS_FILE = path.join(wRoot, '.daemon-heartbeat-last-success.txt');
    try {
      if (!fs.existsSync(HB_FRESHNESS_FILE)) return { fresh: false, lastSuccess: null, ageSeconds: null };
      const raw = fs.readFileSync(HB_FRESHNESS_FILE, 'utf-8').trim();
      if (!raw) return { fresh: false, lastSuccess: null, ageSeconds: null };
      const ts = new Date(raw);
      if (isNaN(ts.getTime())) return { fresh: false, lastSuccess: null, ageSeconds: null };
      const ageSeconds = Math.round((Date.now() - ts.getTime()) / 1000);
      // 2× heartbeat interval (110s) + 10s buffer = 120s
      return { fresh: ageSeconds < 120, lastSuccess: raw, ageSeconds };
    } catch (_e) {
      return { fresh: false, lastSuccess: null, ageSeconds: null };
    }
  }

  // ── B6: Unstaged changes detection ───────────────────────────────

  /**
   * Check for uncommitted changes in the Worker's git repo (P14-B6 · PFL-174).
   *
   * P14-B4 lesson: B1 wrote code but never committed → daemon died →
   * stale reaper reverted task → B2 claimed and lost B1's work.
   * This check surfaces unstaged changes so the AI can commit as checkpoint.
   *
   * @param {string} wRoot — path to Worker's .claude/ directory
   * @returns {{ hasUnstaged: boolean, fileCount: number, files: string[] }}
   */
  function checkUnstagedChanges(wRoot) {
    // wRoot = .claude/ → parent = project root (git repo)
    const repoRoot = path.dirname(wRoot);
    try {
      const { execSync: _execSync } = require('child_process');
      const output = _execSync('git status --porcelain', {
        cwd: repoRoot,
        encoding: 'utf-8',
        timeout: 5000,
      });
      if (!output || !output.trim()) return { hasUnstaged: false, fileCount: 0, files: [] };
      // git status --porcelain format: XY filename (2 status chars + space + path)
      // Don't trim the whole output — leading spaces in status lines are meaningful
      const fileList = output.split('\n')
        .filter(function(l) { return l.length >= 4; })
        .map(function(l) { return l.slice(3); })
        .filter(Boolean);
      return { hasUnstaged: true, fileCount: fileList.length, files: fileList };
    } catch (_e) {
      // Not a git repo, git not installed, or timeout — graceful degradation
      return { hasUnstaged: false, fileCount: 0, files: [], error: _e.message };
    }
  }

  // ── B137: Health self-heal ────────────────────────────────────────

  /**
   * Health check with auto-heal (B137 · extended B6).
   *
   * 1. Check heartbeat daemon → dead? → auto re-spawn
   * 2. Check WS daemon → dead? → auto re-spawn
   * 3. Check heartbeat functional freshness (PFL-173 · B6)
   * 4. Check unstaged git changes (PFL-174 · B6)
   * 5. Update .session-alive timestamp
   *
   * Returns a health report. The AI reads the REPAIRED state — it never
   * sees "daemon dead" because health() already fixed it.
   *
   * @returns {{
   *   heartbeat: {wasRunning: boolean, reSpawned: boolean, pid: string|null},
   *   wsDaemon: {wasRunning: boolean, reSpawned: boolean, pid: string|null},
   *   sessionAlive: string,
   *   _heartbeatFreshness: {fresh: boolean, lastSuccess: string|null, ageSeconds: number|null},
   *   _unstagedChanges: {hasUnstaged: boolean, fileCount: number, files: string[]}
   * }}
   */
  function health() {
    const report = {
      heartbeat: { wasRunning: false, reSpawned: false, pid: null },
      wsDaemon: { wasRunning: false, reSpawned: false, pid: null },
      sessionAlive: null,
    };

    // Heartbeat daemon
    const hbStatus = checkHeartbeatDaemon();
    report.heartbeat.wasRunning = hbStatus.running;
    if (hbStatus.running) {
      report.heartbeat.pid = hbStatus.pids[0] || null;
    } else {
      const result = startHeartbeatDaemon();
      if (result.started) {
        report.heartbeat.reSpawned = true;
        report.heartbeat.pid = String(result.pid);
      }
    }

    // WS daemon
    const wsStatus = checkWsDaemon();
    report.wsDaemon.wasRunning = wsStatus.running;
    if (wsStatus.running) {
      report.wsDaemon.pid = wsStatus.pids[0] || null;
    } else {
      const result = startWsDaemon();
      if (result.started) {
        report.wsDaemon.reSpawned = true;
        report.wsDaemon.pid = String(result.pid);
      }
    }

    // Update session-alive timestamp
    try {
      const ts = new Date().toISOString();
      fs.writeFileSync(SESSION_ALIVE_FILE, JSON.stringify({
        updated_at: ts,
        pid: String(process.pid),
        mode: 'health',
      }), 'utf-8');
      report.sessionAlive = ts;
    } catch (_) { /* best-effort */ }

    // B6: Heartbeat functional freshness (PFL-173)
    report._heartbeatFreshness = checkHeartbeatFreshness(workerRoot);

    // B6: Unstaged git changes (PFL-174)
    report._unstagedChanges = checkUnstagedChanges(workerRoot);

    return report;
  }

  // ── API ───────────────────────────────────────────────────────────

  return {
    // Low-level (exported for testing)
    readPidFile,
    writePidFile,
    isProcessAlive,

    // Lifecycle
    killOldDaemon,
    cleanupOrphanDaemons,

    // Heartbeat daemon
    checkHeartbeatDaemon,
    startHeartbeatDaemon,

    // WS daemon
    checkWsDaemon,
    startWsDaemon,

    // B137: self-heal
    health,

    // B6: functional freshness + unstaged changes
    checkHeartbeatFreshness,
    checkUnstagedChanges,

    // Paths (for session-init.js compatibility)
    HEARTBEAT_PID_FILE,
    WS_DAEMON_PID_FILE,
    SESSION_ALIVE_FILE,
  };
}

module.exports = { createDaemonManager };

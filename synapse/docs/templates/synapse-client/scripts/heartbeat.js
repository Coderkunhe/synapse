#!/usr/bin/env node
/**
 * synapse-heartbeat — Worker heartbeat daemon (Node.js edition, B98 daemon mode).
 *
 * Default mode (daemon): sends heartbeat immediately, then every 55s in a loop.
 * Keeps Worker status = "active" throughout the session.
 * Designed to run as a background process in SessionStart hook: `node heartbeat.js &`
 *
 * --once mode: sends one heartbeat and exits (backward compatible).
 *
 * P11-B132: daemon liveness uses .session-alive file (written by session-init.js)
 * instead of parent PID. session-init.js updates this file on every run
 * (full init + --quick on CronCreate wakeup). If the file is stale (>2 min),
 * the daemon self-terminates — the Claude session is gone.
 *
 * Zero external dependencies — uses Node.js >=18 built-ins only.
 *
 * Usage:
 *   node scripts/heartbeat.js          # daemon mode (loop every 55s)
 *   node scripts/heartbeat.js --once   # one-shot (original behavior)
 *
 * Environment variables:
 *   SYNAPSE_API_URL   — e.g. http://127.0.0.1:8001 (default)
 *   SYNAPSE_WORKER_ID — e.g. ag_019f7a7c7a6f7886
 *   SYNAPSE_API_KEY   — Bearer token (falls back to OS keychain if not set)
 *
 * Exit codes:
 *   0 — Always (non-blocking contract for SessionStart hooks)
 *
 * @version 1.2.0
 * @file heartbeat.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

const { SynapseClient } = require('./api-client');

const HEARTBEAT_INTERVAL_MS = 55_000;
const MAX_CONSECUTIVE_FAILURES = 3;

// P11-B124 (PFL-084): template upgrade detection paths
// __dirname = .claude/skills/synapse/scripts/, go up 3 = .claude/
const WORKER_ROOT = path.resolve(__dirname, '..', '..', '..');
const VERSION_FILE = path.join(WORKER_ROOT, 'synapse-version.json');
const UPGRADE_FLAG_FILE = path.join(WORKER_ROOT, 'template-upgrade-needed');

// P11-B132: daemon liveness signal — session-init.js writes/updates
// .session-alive on each run (full init + --quick on CronCreate wakeup).
// Daemon checks this file timestamp instead of parent PID.
// This fixes the R5 death loop: process.ppid in SessionStart hook context
// was the hook shell (not Claude), which exits immediately.
const SESSION_ALIVE_FILE = path.join(WORKER_ROOT, '.session-alive');
const SESSION_ALIVE_TIMEOUT_MS = 120_000; // 2 min — 2× CronCreate interval

/**
 * Check if the session that spawned us is still alive by reading
 * the .session-alive file timestamp written by session-init.js.
 *
 * session-init.js updates this file on every run:
 *   - Full mode: SessionStart hook (first spawn)
 *   - --quick mode: CronCreate wakeup (every 60s)
 *
 * If the file hasn't been touched in SESSION_ALIVE_TIMEOUT_MS,
 * the Claude session is gone → daemon self-terminates.
 */
function isSessionAlive() {
  try {
    const stat = fs.statSync(SESSION_ALIVE_FILE);
    const age = Date.now() - stat.mtimeMs;
    return age < SESSION_ALIVE_TIMEOUT_MS;
  } catch (e) {
    // File missing — session-init hasn't run yet or was cleaned up
    return false;
  }
}

// Keep --session-pid parsing for backward compatibility (ignored — replaced by .session-alive)
// session-init.js still passes it; daemon no longer uses it for liveness decisions.
let _sessionPid = 0;
{
  const idx = process.argv.indexOf('--session-pid');
  if (idx >= 0 && idx + 1 < process.argv.length) {
    const parsed = parseInt(process.argv[idx + 1], 10);
    if (parsed > 0) _sessionPid = parsed;
  }
}

/**
 * P11-B124 (PFL-084): Compare server template_version against local
 * synapse-version.json.  Writes .claude/template-upgrade-needed flag
 * on mismatch so session-init.js can surface a banner in _task-current.md.
 *
 * When versions match and a stale flag exists, the flag is cleared
 * (the Worker has upgraded).
 *
 * @param {string} serverVersion — template_version from heartbeat response
 */
function checkTemplateVersion(serverVersion) {
  if (!serverVersion) return; // pre-B94 server, no version field

  var localVersion = null;
  try {
    if (fs.existsSync(VERSION_FILE)) {
      var raw = fs.readFileSync(VERSION_FILE, 'utf-8');
      var parsed = JSON.parse(raw);
      localVersion = parsed.version || null;
    }
  } catch (_) {
    // File missing or corrupt — treat as stale (no local version = needs upgrade)
  }

  if (!localVersion) {
    // No local version file — first-time detection or deployment issue
    try {
      fs.writeFileSync(UPGRADE_FLAG_FILE, JSON.stringify({
        current: null,
        latest: serverVersion,
        detected_at: new Date().toISOString(),
        reason: 'no_local_version',
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }
    console.error('heartbeat: WARN template version missing locally (server: ' + serverVersion.slice(0, 16) + '...)');
    return;
  }

  if (localVersion !== serverVersion) {
    try {
      fs.writeFileSync(UPGRADE_FLAG_FILE, JSON.stringify({
        current: localVersion,
        latest: serverVersion,
        detected_at: new Date().toISOString(),
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }
    console.error('heartbeat: WARN template outdated (local: ' + localVersion.slice(0, 16) + '..., server: ' + serverVersion.slice(0, 16) + '...)');

    // P11-B126 (PFL-084): auto-upgrade — spawn upgrade immediately instead of
    // waiting for Worker AI to notice the flag and run --upgrade manually.
    // Fire-and-forget: detached + unref() — daemon does not wait for completion.
    try {
      const upgradeScript = path.join(__dirname, 'session-init.js');
      const child = spawn(process.execPath, [upgradeScript, '--upgrade', '--silent'], {
        detached: true,
        stdio: 'ignore',
        env: { ...process.env },
      });
      child.unref();
      console.error('heartbeat: auto-upgrade spawned — ' +
        'local: ' + localVersion.slice(0, 16) + '... → server: ' + serverVersion.slice(0, 16) + '...');
    } catch (_) {
      console.error('heartbeat: auto-upgrade spawn FAILED — flag file written, Worker AI must upgrade manually');
    }
  } else {
    // Versions match — clear stale flag if it exists (upgrade was done)
    try {
      if (fs.existsSync(UPGRADE_FLAG_FILE)) {
        fs.unlinkSync(UPGRADE_FLAG_FILE);
      }
    } catch (_) { /* best-effort */ }
  }
}

async function sendHeartbeat(client, workerId) {
  const res = await client.post('/v1/workers/' + workerId + '/heartbeat', { current_load: 0 });
  if (res.error) {
    if (res.status && res.status > 0) {
      console.error('heartbeat: WARN (HTTP ' + res.status + ')');
    } else {
      console.error('heartbeat: WARN (unreachable)');
    }
    return null;
  }
  // P11-B124 (PFL-084): detect template staleness on every successful heartbeat
  if (res.data && res.data.template_version) {
    checkTemplateVersion(res.data.template_version);
  }
  return res.data || { runtime_status: 'unknown' };
}

// --once mode (backward compatible)
async function once() {
  const config = SynapseClient.resolveConfig();
  if (!config.workerId) { console.log('heartbeat: SKIP (no SYNAPSE_WORKER_ID)'); process.exit(0); }
  if (!config.apiKey) { console.log('heartbeat: SKIP (no API key)'); process.exit(0); }
  const client = new SynapseClient(config);
  const status = await sendHeartbeat(client, config.workerId);
  if (status) console.log('heartbeat: ' + (status.runtime_status || 'ok'));
  process.exit(0);
}

// Daemon mode (default) — loops every 55s
async function daemon() {
  const config = SynapseClient.resolveConfig();
  if (!config.workerId) { process.exit(0); }
  if (!config.apiKey) { process.exit(0); }
  const client = new SynapseClient(config);
  let consecutiveFailures = 0;

  async function tick() {
    // P11-B132: check .session-alive file instead of parent PID.
    // session-init.js updates this file on every CronCreate wakeup (--quick).
    // If the file is stale (>2 min), the Claude session is gone → self-terminate.
    if (!isSessionAlive()) {
      console.error('heartbeat daemon: session alive file stale/missing — self-terminating (orphan)');
      process.exit(0);
    }
    const status = await sendHeartbeat(client, config.workerId);
    if (status) { consecutiveFailures = 0; return true; }
    consecutiveFailures++;
    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
      console.error('heartbeat daemon: ' + MAX_CONSECUTIVE_FAILURES + ' consecutive failures - exiting');
      process.exit(0);
    }
    return false;
  }

  const firstOk = await tick();
  console.log('heartbeat daemon: started (' + (firstOk ? 'ok' : 'warn') + ')');

  const interval = setInterval(function() { tick(); }, HEARTBEAT_INTERVAL_MS);

  function shutdown() {
    clearInterval(interval);
    console.error('heartbeat daemon: stopped');
    process.exit(0);
  }
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

const isOnce = process.argv.includes('--once') || process.argv.includes('-o');
if (isOnce) { once().catch(function() { process.exit(0); }); }
else { daemon().catch(function() { process.exit(0); }); }

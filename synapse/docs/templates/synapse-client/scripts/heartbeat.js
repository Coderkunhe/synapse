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

const { SynapseClient } = require('./api-client');
const { isSessionAlive, checkTemplateVersion, sendHeartbeat: _sendHeartbeat } = require('./lib/heartbeat-core');

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

// checkTemplateVersion and sendHeartbeat are now in lib/heartbeat-core.js.
// Thin wrappers that wire up local paths and logging.

function _onTemplateVersion(serverVersion) {
  const upgradeScript = path.join(__dirname, 'session-init.js');
  const result = checkTemplateVersion(serverVersion, {
    versionFile: VERSION_FILE,
    upgradeFlagFile: UPGRADE_FLAG_FILE,
    sessionInitScript: upgradeScript,
    execPath: process.execPath,
  });
  if (!result || result.action === 'ok') return;
  if (result.action === 'flag_written') {
    if (result.reason === 'no_local_version') {
      console.error('heartbeat: WARN template version missing locally (server: ' + serverVersion.slice(0, 16) + '...)');
    } else {
      console.error('heartbeat: WARN template outdated (local: ' + (result.localVersion || '?').slice(0, 16) + '..., server: ' + serverVersion.slice(0, 16) + '...)');
    }
  } else if (result.action === 'upgrade_spawned') {
    console.error('heartbeat: auto-upgrade spawned — ' +
      'local: ' + result.localVersion.slice(0, 16) + '... → server: ' + result.serverVersion.slice(0, 16) + '...');
  } else if (result.action === 'flag_cleared') {
    // versions match, stale flag removed — silent
  }
}

async function sendHeartbeat(client, workerId) {
  const res = await _sendHeartbeat(client, workerId, {
    onTemplateVersion: _onTemplateVersion,
  });
  if (res.error) {
    if (res.status && res.status > 0) {
      console.error('heartbeat: WARN (HTTP ' + res.status + ')');
    } else {
      console.error('heartbeat: WARN (unreachable)');
    }
  }
  return res.data || null;
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
    if (!isSessionAlive(SESSION_ALIVE_FILE, SESSION_ALIVE_TIMEOUT_MS)) {
      console.error('heartbeat daemon: session alive file stale/missing — self-terminating (orphan)');
      process.exit(0);
    }
    const status = await sendHeartbeat(client, config.workerId);
    if (status) { consecutiveFailures = 0; try { fs.writeFileSync(path.join(WORKER_ROOT, ".daemon-heartbeat-last-success.txt"), new Date().toISOString(), "utf-8"); } catch (_) { /* best-effort */ } return true; }
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

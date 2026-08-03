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
 * @version 1.1.0
 * @file heartbeat.js
 */

'use strict';

const { SynapseClient } = require('./api-client');

const HEARTBEAT_INTERVAL_MS = 55_000;
const MAX_CONSECUTIVE_FAILURES = 3;

// PFL-116 (B123): daemon self-check — detect orphaned daemon by checking
// whether the session that spawned us is still alive.
// session-init.js passes --session-pid <ppid> when spawning.
// If session PID is dead (Claude session exited), daemon self-terminates.
let _sessionPid = 0;
{
  const idx = process.argv.indexOf('--session-pid');
  if (idx >= 0 && idx + 1 < process.argv.length) {
    const parsed = parseInt(process.argv[idx + 1], 10);
    if (parsed > 0) _sessionPid = parsed;
  }
}

/** Check if a process with the given PID is alive (signal 0 = existence check). */
function isProcessAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    // ESRCH = process not found → dead
    // EPERM = no permission → assume alive (better false negative than false positive)
    return e.code === 'EPERM';
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
  return (res.data && res.data.runtime_status) || 'unknown';
}

// --once mode (backward compatible)
async function once() {
  const config = SynapseClient.resolveConfig();
  if (!config.workerId) { console.log('heartbeat: SKIP (no SYNAPSE_WORKER_ID)'); process.exit(0); }
  if (!config.apiKey) { console.log('heartbeat: SKIP (no API key)'); process.exit(0); }
  const client = new SynapseClient(config);
  const status = await sendHeartbeat(client, config.workerId);
  if (status) console.log('heartbeat: ' + status);
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
    // PFL-116 (B123): self-check — if spawning session is dead, daemon is orphaned
    if (_sessionPid && !isProcessAlive(_sessionPid)) {
      console.error('heartbeat daemon: session PID ' + _sessionPid + ' is gone — self-terminating (orphan)');
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

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
 * @file heartbeat.js
 */

'use strict';

const { SynapseClient } = require('./api-client');
const { getKey } = require('./keychain');

const HEARTBEAT_INTERVAL_MS = 55_000;
const MAX_CONSECUTIVE_FAILURES = 3;

function resolveApiKey(workerId) {
  let apiKey = process.env.SYNAPSE_API_KEY || '';
  if (!apiKey && workerId) {
    apiKey = getKey(workerId) || '';
  }
  return apiKey;
}

async function sendHeartbeat(client, workerId) {
  const res = await client.post('/v1/workers/' + workerId + '/heartbeat', { current_load: 0 });
  if (res.error) {
    if (res.status && res.status > 0) {
      process.stderr.write('heartbeat: WARN (HTTP ' + res.status + ')\n');
    } else {
      process.stderr.write('heartbeat: WARN (unreachable)\n');
    }
    return null;
  }
  return (res.data && res.data.runtime_status) || 'unknown';
}

// --once mode (backward compatible)
async function once() {
  const workerId = process.env.SYNAPSE_WORKER_ID || '';
  if (!workerId) { console.log('heartbeat: SKIP (no SYNAPSE_WORKER_ID)'); process.exit(0); }
  const apiKey = resolveApiKey(workerId);
  if (!apiKey) { console.log('heartbeat: SKIP (no API key)'); process.exit(0); }
  const apiUrl = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
  const client = new SynapseClient({ apiUrl, workerId, apiKey });
  const status = await sendHeartbeat(client, workerId);
  if (status) console.log('heartbeat: ' + status);
  process.exit(0);
}

// Daemon mode (default) — loops every 55s
async function daemon() {
  const workerId = process.env.SYNAPSE_WORKER_ID || '';
  if (!workerId) { process.exit(0); }
  const apiKey = resolveApiKey(workerId);
  if (!apiKey) { process.exit(0); }
  const apiUrl = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
  const client = new SynapseClient({ apiUrl, workerId, apiKey });
  let consecutiveFailures = 0;

  async function tick() {
    const status = await sendHeartbeat(client, workerId);
    if (status) { consecutiveFailures = 0; return true; }
    consecutiveFailures++;
    if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
      process.stderr.write('heartbeat daemon: ' + MAX_CONSECUTIVE_FAILURES + ' consecutive failures - exiting\n');
      process.exit(0);
    }
    return false;
  }

  const firstOk = await tick();
  console.log('heartbeat daemon: started (' + (firstOk ? 'ok' : 'warn') + ')');

  const interval = setInterval(function() { tick(); }, HEARTBEAT_INTERVAL_MS);

  function shutdown() {
    clearInterval(interval);
    process.stderr.write('heartbeat daemon: stopped\n');
    process.exit(0);
  }
  process.on('SIGTERM', shutdown);
  process.on('SIGINT', shutdown);
}

const isOnce = process.argv.includes('--once') || process.argv.includes('-o');
if (isOnce) { once().catch(function() { process.exit(0); }); }
else { daemon().catch(function() { process.exit(0); }); }

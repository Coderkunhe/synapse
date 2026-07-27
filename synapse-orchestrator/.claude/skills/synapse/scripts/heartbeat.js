#!/usr/bin/env node
/**
 * synapse-heartbeat — Worker heartbeat (Node.js edition).
 *
 * Replaces synapse-heartbeat.sh with a cross-platform Node.js implementation.
 * Zero external dependencies — uses Node.js ≥18 built-ins only.
 *
 * Usage:
 *   node scripts/heartbeat.js
 *
 * Environment variables (same as bash version):
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

/**
 * Main heartbeat flow — mirrors synapse-heartbeat.sh step for step.
 */
async function main() {
  // ── Step 1: Check SYNAPSE_WORKER_ID ──────────────────────────
  const workerId = process.env.SYNAPSE_WORKER_ID || '';
  if (!workerId) {
    console.log('🫀 heartbeat: SKIP (no SYNAPSE_WORKER_ID)');
    process.exit(0);
  }

  // ── Step 2: Resolve API key — env var → keychain ─────────────
  let apiKey = process.env.SYNAPSE_API_KEY || '';
  if (!apiKey) {
    apiKey = getKey(workerId) || '';
  }
  if (!apiKey) {
    console.log('🫀 heartbeat: SKIP (no API key — keychain may need setup)');
    process.exit(0);
  }

  // ── Step 3: Build API URL ────────────────────────────────────
  const apiUrl = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');

  // ── Step 4: Create client + POST heartbeat ───────────────────
  const client = new SynapseClient({ apiUrl, workerId, apiKey });

  const res = await client.post(`/v1/workers/${workerId}/heartbeat`, { current_load: 0 });

  // ── Step 5: Handle errors (non-blocking) ─────────────────────
  if (res.error) {
    if (res.status && res.status > 0) {
      // Server responded with an error
      console.log(`🫀 heartbeat: WARN (HTTP ${res.status} — ${apiUrl})`);
    } else {
      // Network error or timeout
      console.log(`🫀 heartbeat: WARN (API unreachable — ${apiUrl})`);
    }
    process.exit(0);
  }

  // ── Step 6: Parse response ───────────────────────────────────
  const runtimeStatus = (res.data && res.data.runtime_status) || 'unknown';

  if (runtimeStatus === 'idle' || runtimeStatus === 'busy' || runtimeStatus === 'error') {
    console.log(`🫀 heartbeat: ${runtimeStatus}`);
  } else {
    console.log(`🫀 heartbeat: done (raw: ${runtimeStatus})`);
  }

  process.exit(0);
}

// ── Entry point ──────────────────────────────────────────────────
main().catch((err) => {
  // Only catches script-level failures (syntax errors, missing requires)
  // Never blocks hook chains.
  console.error(`🫀 heartbeat: ERROR (script failure — ${err.message})`);
  process.exit(0);
});

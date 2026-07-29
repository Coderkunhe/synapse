#!/usr/bin/env node
/**
 * ws-daemon — Synapse WebSocket event daemon with auto-reconnect.
 *
 * Maintains a persistent WebSocket connection to the Synapse server.
 * On disconnect, auto-reconnects with exponential backoff:
 *   1s → 5s → 25s → report failure and exit.
 *
 * This daemon fulfills the _protocol.md §8 promise:
 *   "WebSocket 断开 → 1s 后重连 → 失败则 5s → 25s → 报告给 Orchestrator"
 *
 * Events received over WS are written to _ws-events.jsonl (max 50 lines,
 * rotating). session-init.js reads recent events and surfaces them to the AI.
 *
 * @requires Node.js ≥22 (native WebSocket global)
 *
 * Zero external dependencies — uses Node.js ≥22 built-in `WebSocket` API.
 *
 * Usage:
 *   node scripts/ws-daemon.js
 *
 * Environment variables:
 *   SYNAPSE_API_URL   — e.g. http://127.0.0.1:8001 (default)
 *   SYNAPSE_WORKER_ID — e.g. ag_019f7a7c7a6f7886
 *   SYNAPSE_API_KEY   — Bearer token (falls back to OS keychain if not set)
 *
 * Output files (relative to scripts/..):
 *   _ws-events.jsonl  — Append-only event log (max 50 lines, rotating)
 *   _ws-health.txt    — Last successful message timestamp (touch on each event)
 *   _ws-status.json   — Daemon status: {"status":"running"} | {"status":"dead","since":"..."}
 *
 * Exit codes:
 *   0 — Clean shutdown (SIGTERM / SIGINT)
 *   1 — All reconnect attempts exhausted
 *
 * @version 1.0.0
 * @file ws-daemon.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { getKey } = require('./keychain');

// ── Constants ──────────────────────────────────────────────────────
const EVENTS_FILE = path.join(__dirname, '..', '_ws-events.jsonl');
const HEALTH_FILE = path.join(__dirname, '..', '_ws-health.txt');
const STATUS_FILE = path.join(__dirname, '..', '_ws-status.json');
const MAX_EVENTS = 50;

// Reconnect backoff (seconds): 1s → 5s → 25s → give up
const BACKOFF_SCHEDULE = [1, 5, 25];

// ── Helpers ─────────────────────────────────────────────────────────

/** Current ISO timestamp. */
function now() {
  return new Date().toISOString();
}

/**
 * Convert an HTTP(S) base URL to a WebSocket URL.
 *   http://127.0.0.1:8001 → ws://127.0.0.1:8001
 *   https://api.example.com → wss://api.example.com
 *
 * @param {string} apiUrl
 * @returns {string}
 */
function toWsUrl(apiUrl) {
  return apiUrl.replace(/^http/, 'ws');
}

/**
 * Write daemon status file.
 * @param {"running"|"dead"} status
 */
function writeStatus(status) {
  const payload = status === 'dead'
    ? { status: 'dead', since: now() }
    : { status: 'running', since: now(), pid: process.pid };
  try {
    fs.writeFileSync(STATUS_FILE, JSON.stringify(payload) + '\n', 'utf-8');
  } catch (_) { /* best-effort */ }
}

/**
 * Append an event to the JSONL event log.
 * Keeps at most MAX_EVENTS lines — shifts oldest when exceeded.
 *
 * @param {Object} event — The parsed WS message payload
 */
function appendEvent(event) {
  try {
    const line = JSON.stringify({ ts: now(), ...event }) + '\n';

    // Read existing, append, trim
    let lines = [];
    try {
      const raw = fs.readFileSync(EVENTS_FILE, 'utf-8');
      lines = raw.trim().split('\n').filter(Boolean);
    } catch (_) { /* file doesn't exist yet — ok */ }

    lines.push(line.trimEnd());

    // Rotate: keep only last MAX_EVENTS
    if (lines.length > MAX_EVENTS) {
      lines = lines.slice(lines.length - MAX_EVENTS);
    }

    fs.writeFileSync(EVENTS_FILE, lines.join('\n') + '\n', 'utf-8');
  } catch (_) { /* best-effort — don't crash on disk full */ }
}

/** Touch health file with current timestamp. */
function touchHealth() {
  try {
    fs.writeFileSync(HEALTH_FILE, now() + '\n', 'utf-8');
  } catch (_) { /* best-effort */ }
}

/** Log to stderr (daemon has no stdout — it's detached). */
function log(msg) {
  process.stderr.write(`[ws-daemon ${now()}] ${msg}\n`);
}

// ── Resolve config ──────────────────────────────────────────────────

function resolveConfig() {
  const apiUrl = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
  const workerId = process.env.SYNAPSE_WORKER_ID || '';
  let apiKey = process.env.SYNAPSE_API_KEY || '';
  if (!apiKey && workerId) {
    apiKey = getKey(workerId) || '';
  }
  return { apiUrl, workerId, apiKey };
}

// ── Main daemon logic ───────────────────────────────────────────────

/**
 * Create a WebSocket connection and set up event handlers.
 * Returns the WebSocket instance (already connecting).
 *
 * @param {string} wsUrl — Full WebSocket URL with token
 * @returns {WebSocket}
 */
function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    log('connected');
    writeStatus('running');
    touchHealth();
  };

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      appendEvent(payload);
      touchHealth();
    } catch (_) {
      // Non-JSON message (e.g. plain text) — still record it
      appendEvent({ type: 'unknown', raw: String(event.data).slice(0, 500) });
      touchHealth();
    }
  };

  ws.onerror = () => {
    // onclose will fire after onerror — no separate handling needed.
    // The error event itself doesn't carry useful diagnostics in the
    // standard WebSocket API.
  };

  return ws;
}

/**
 * Reconnect loop with backoff.
 *
 * @param {() => string} getWsUrl — Factory that returns the current WS URL
 * @returns {Promise<void>} — Resolves when connected, rejects if all retries exhausted
 */
function reconnectLoop(getWsUrl) {
  return new Promise((resolve, reject) => {
    let attempt = 0;

    function tryConnect() {
      const delay = BACKOFF_SCHEDULE[attempt];
      log(`reconnect attempt ${attempt + 1}/${BACKOFF_SCHEDULE.length} — waiting ${delay}s`);

      setTimeout(() => {
        const ws = connect(getWsUrl());

        // Wait for first open or close
        const cleanup = () => {
          ws.onopen = null;
          ws.onclose = null;
          ws.onerror = null;
        };

        ws.onopen = () => {
          cleanup();
          log('reconnected successfully');
          resolve(ws);
        };

        ws.onclose = (event) => {
          cleanup();
          attempt++;
          if (attempt < BACKOFF_SCHEDULE.length) {
            tryConnect();
          } else {
            log(`all ${BACKOFF_SCHEDULE.length} reconnect attempts exhausted (last close: code=${event?.code || '?'})`);
            reject(new Error('Reconnect exhausted'));
          }
        };

        ws.onerror = () => {
          // onclose will fire next — don't double-count
        };
      }, delay * 1000);
    }

    tryConnect();
  });
}

// ── Entry point ─────────────────────────────────────────────────────

async function main() {
  // Version guard: native WebSocket requires Node.js ≥22
  if (typeof WebSocket === 'undefined') {
    log('FATAL: Node.js ≥22 required (WebSocket not available). ws-daemon cannot start.');
    writeStatus('dead');
    process.exit(1);
  }

  const config = resolveConfig();

  if (!config.apiKey) {
    log('FATAL: no API key available — set SYNAPSE_API_KEY or store in OS keychain.');
    writeStatus('dead');
    process.exit(1);
  }

  const wsBase = toWsUrl(config.apiUrl);
  const getWsUrl = () => `${wsBase}/v1/ws?token=${encodeURIComponent(config.apiKey)}`;

  log(`starting — worker=${config.workerId || '?'} url=${config.apiUrl}`);

  // ── Graceful shutdown ────────────────────────────────────────
  let shuttingDown = false;
  const shutdown = (signal) => {
    if (shuttingDown) return;
    shuttingDown = true;
    log(`received ${signal} — shutting down`);
    writeStatus('running');  // clean shutdown is not a crash
    process.exit(0);
  };
  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));

  // ── Initial connect ──────────────────────────────────────────
  let ws = connect(getWsUrl());

  // ── Event loop: reconnect on disconnect ─────────────────────
  while (!shuttingDown) {
    // Wait for the current connection to close (or never, if it stays open)
    const closePromise = new Promise((resolve) => {
      ws.onclose = (event) => {
        log(`disconnected — code=${event?.code || '?'} reason="${event?.reason || ''}"`);
        resolve();
      };
    });

    await closePromise;

    if (shuttingDown) break;

    // Attempt reconnect with backoff
    try {
      ws = await reconnectLoop(getWsUrl);
      // reconnectLoop resolved → we have a fresh connected ws
      // Re-attach the onclose handler in the next while iteration
    } catch (_) {
      // All retries exhausted
      log('FATAL: reconnect exhausted — reporting to status file');
      writeStatus('dead');
      process.exit(1);
    }
  }
}

main().catch((err) => {
  log(`unexpected error: ${err.message}`);
  writeStatus('dead');
  process.exit(1);
});

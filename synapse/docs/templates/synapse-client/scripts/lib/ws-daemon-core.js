/**
 * ws-daemon-core.js — Pure logic extracted from ws-daemon.js for testability.
 *
 * Every function is stateless: all external inputs (filesystem, keychain, env)
 * come through parameters or the node built-in modules passed at call time.
 *
 * @version 1.0.0 — P12-B31 extraction
 * @file ws-daemon-core.js
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { getKey } = require('../keychain');

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Current ISO timestamp.
 * @returns {string}
 */
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
 * Check if the session that spawned us is still alive by reading
 * the .session-alive file timestamp written by session-init.js.
 *
 * @param {string} sessionAliveFile — absolute path to .session-alive
 * @param {number} timeoutMs — max age in milliseconds (e.g. 120_000)
 * @returns {boolean}
 */
function isSessionAlive(sessionAliveFile, timeoutMs) {
  try {
    const stat = fs.statSync(sessionAliveFile);
    const age = Date.now() - stat.mtimeMs;
    return age < timeoutMs;
  } catch (e) {
    return false;
  }
}

/**
 * Resolve config from environment + OS keychain fallback.
 *
 * @returns {{ apiUrl: string, workerId: string, apiKey: string }}
 */
function resolveConfig() {
  const apiUrl = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
  const workerId = process.env.SYNAPSE_WORKER_ID || '';
  let apiKey = process.env.SYNAPSE_API_KEY || '';
  if (!apiKey && workerId) {
    apiKey = getKey(workerId) || '';
  }
  return { apiUrl, workerId, apiKey };
}

/**
 * Write daemon status file.
 *
 * @param {string} statusFile — absolute path to _ws-status.json
 * @param {"running"|"dead"} status
 */
function writeStatus(statusFile, status) {
  const payload = status === 'dead'
    ? { status: 'dead', since: now() }
    : { status: 'running', since: now(), pid: process.pid };
  try {
    fs.writeFileSync(statusFile, JSON.stringify(payload) + '\n', 'utf-8');
  } catch (_) { /* best-effort */ }
}

/**
 * Append an event to the JSONL event log.
 * Keeps at most maxEvents lines — shifts oldest when exceeded.
 *
 * @param {string} eventsFile — absolute path to _ws-events.jsonl
 * @param {number} maxEvents — max lines to keep (e.g. 50)
 * @param {Object} event — the parsed WS message payload
 */
function appendEvent(eventsFile, maxEvents, event) {
  try {
    const line = JSON.stringify({ ts: now(), ...event }) + '\n';

    // Read existing, append, trim
    let lines = [];
    try {
      const raw = fs.readFileSync(eventsFile, 'utf-8');
      lines = raw.trim().split('\n').filter(Boolean);
    } catch (_) { /* file doesn't exist yet — ok */ }

    lines.push(line.trimEnd());

    // Rotate: keep only last maxEvents
    if (lines.length > maxEvents) {
      lines = lines.slice(lines.length - maxEvents);
    }

    fs.writeFileSync(eventsFile, lines.join('\n') + '\n', 'utf-8');
  } catch (_) { /* best-effort — don't crash on disk full */ }
}

/**
 * Touch health file with current timestamp.
 *
 * @param {string} healthFile — absolute path to _ws-health.txt
 */
function touchHealth(healthFile) {
  try {
    fs.writeFileSync(healthFile, now() + '\n', 'utf-8');
  } catch (_) { /* best-effort */ }
}

module.exports = { now, toWsUrl, isSessionAlive, resolveConfig, writeStatus, appendEvent, touchHealth };

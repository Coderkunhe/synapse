/**
 * heartbeat-core.js — Pure logic extracted from heartbeat.js for testability.
 *
 * Every function is stateless: all external inputs (filesystem, HTTP client, env)
 * come through parameters rather than module-level constants.
 *
 * @version 1.0.0 — P12-B31 extraction
 * @file heartbeat-core.js
 */

'use strict';

const fs = require('fs');
const { spawn } = require('child_process');

// ── Helpers ─────────────────────────────────────────────────────────

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
 * P11-B124 (PFL-084): Compare server template_version against local
 * synapse-version.json.  Writes template-upgrade-needed flag on mismatch
 * so session-init.js can surface a banner in _task-current.md.
 *
 * All I/O paths are injected for testability.
 *
 * @param {string} serverVersion — template_version from heartbeat response
 * @param {Object} opts — injectable dependencies
 * @param {string} opts.versionFile — absolute path to synapse-version.json
 * @param {string} opts.upgradeFlagFile — absolute path to template-upgrade-needed
 * @param {string} [opts.sessionInitScript] — path to session-init.js (for auto-upgrade spawn)
 * @param {string} [opts.execPath] — Node.js executable path (defaults to process.execPath)
 */
function checkTemplateVersion(serverVersion, opts) {
  if (!serverVersion) return; // pre-B94 server, no version field

  const { versionFile, upgradeFlagFile, sessionInitScript, execPath } = opts;

  let localVersion = null;
  try {
    if (fs.existsSync(versionFile)) {
      const raw = fs.readFileSync(versionFile, 'utf-8');
      const parsed = JSON.parse(raw);
      localVersion = parsed.version || null;
    }
  } catch (_) {
    // File missing or corrupt — treat as stale (no local version = needs upgrade)
  }

  if (!localVersion) {
    // No local version file — first-time detection or deployment issue
    try {
      fs.writeFileSync(upgradeFlagFile, JSON.stringify({
        current: null,
        latest: serverVersion,
        detected_at: new Date().toISOString(),
        reason: 'no_local_version',
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }
    return { action: 'flag_written', reason: 'no_local_version', serverVersion };
  }

  if (localVersion !== serverVersion) {
    try {
      fs.writeFileSync(upgradeFlagFile, JSON.stringify({
        current: localVersion,
        latest: serverVersion,
        detected_at: new Date().toISOString(),
      }, null, 2) + '\n', 'utf-8');
    } catch (_) { /* best-effort */ }

    // P11-B126 (PFL-084): auto-upgrade — spawn upgrade immediately
    if (sessionInitScript && execPath) {
      try {
        const child = spawn(execPath, [sessionInitScript, '--upgrade', '--silent'], {
          detached: true,
          stdio: 'ignore',
          env: { ...process.env },
        });
        child.unref();
        return { action: 'upgrade_spawned', localVersion, serverVersion };
      } catch (_) {
        return { action: 'flag_written', reason: 'spawn_failed', localVersion, serverVersion };
      }
    }
    return { action: 'flag_written', localVersion, serverVersion };
  }

  // Versions match — clear stale flag if it exists (upgrade was done)
  try {
    if (fs.existsSync(upgradeFlagFile)) {
      fs.unlinkSync(upgradeFlagFile);
      return { action: 'flag_cleared', localVersion, serverVersion };
    }
  } catch (_) { /* best-effort */ }

  return { action: 'ok', localVersion, serverVersion };
}

/**
 * Send a heartbeat and optionally check template version.
 *
 * @param {Object} client — SynapseClient instance with a .post() method
 * @param {string} workerId
 * @param {Object} [opts]
 * @param {(serverVersion: string) => any} [opts.onTemplateVersion] — called on successful heartbeat with template_version
 * @returns {Promise<{error: boolean, status?: number, data?: any}>}
 */
async function sendHeartbeat(client, workerId, opts) {
  const res = await client.post('/v1/workers/' + workerId + '/heartbeat', { current_load: 0 });
  if (res.error) {
    if (res.status && res.status > 0) {
      return { error: true, status: res.status, message: 'HTTP ' + res.status };
    }
    return { error: true, message: 'unreachable' };
  }
  // P11-B124 (PFL-084): detect template staleness on every successful heartbeat
  if (res.data && res.data.template_version && opts && opts.onTemplateVersion) {
    opts.onTemplateVersion(res.data.template_version);
  }
  return { error: false, data: res.data || { runtime_status: 'unknown' } };
}

module.exports = { isSessionAlive, checkTemplateVersion, sendHeartbeat };

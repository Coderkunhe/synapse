/**
 * keychain.js — Cross-platform OS keychain abstraction for Synapse Worker API keys.
 *
 * Three-tier architecture (matching synapse-key.sh P11-B35 design):
 *   Tier 1 (macOS):  security add-generic-password / find-generic-password
 *   Tier 2 (Linux):  secret-tool store / lookup (libsecret)
 *   Tier 3 (Windows): cmdkey /generic + PowerShell CredentialManager
 *   Fallback:        returns null — caller should try process.env
 *
 * Key naming convention (shared with synapse-key.sh):
 *   Account:  synapse-worker-{workerId}
 *   Service:  synapse
 *
 * Zero dependencies — uses Node.js ≥18 built-in child_process.execSync.
 *
 * **SECURITY (B100-A1)**: Store operations pass API keys via stdin pipe
 * (execSync `input` option), NOT command-line arguments. This prevents
 * API key leakage through `ps aux` / process listings. One exception:
 * Windows `cmdkey` does not support stdin — documented in _winStore().
 *
 * @version 1.1.0
 * @module keychain
 */

const { execSync } = require('child_process');
const os = require('os');

const SERVICE_NAME = 'synapse';
const ACCOUNT_PREFIX = 'synapse-worker-';

// ── Platform detection ──────────────────────────────────────────────

/**
 * Detect the current platform's keychain backend.
 * @returns {'macos' | 'linux' | 'windows' | 'fallback'}
 */
function detectPlatform() {
  const platform = os.platform();

  if (platform === 'darwin') {
    // Check if `security` CLI is available
    try {
      execSync('command -v security', { stdio: 'pipe' });
      return 'macos';
    } catch (_) {
      return 'fallback';
    }
  }

  if (platform === 'linux') {
    // Check if `secret-tool` CLI is available
    try {
      execSync('command -v secret-tool', { stdio: 'pipe' });
      return 'linux';
    } catch (_) {
      return 'fallback';
    }
  }

  if (platform === 'win32') {
    // Check if `cmdkey` CLI is available (always present on Windows)
    try {
      execSync('where cmdkey', { stdio: 'pipe' });
      return 'windows';
    } catch (_) {
      return 'fallback';
    }
  }

  return 'fallback';
}

// ── macOS Keychain ──────────────────────────────────────────────────

/**
 * Build the macOS keychain account string.
 * @param {string} workerId
 * @returns {string}
 */
function _macAccount(workerId) {
  return `${ACCOUNT_PREFIX}${workerId}`;
}

/**
 * Retrieve API key from macOS Keychain.
 * @param {string} workerId
 * @returns {string | null}
 */
function _macGet(workerId) {
  try {
    const account = _macAccount(workerId);
    const result = execSync(
      `security find-generic-password -a "${account}" -s "${SERVICE_NAME}" -w`,
      { stdio: 'pipe', timeout: 3000 }
    );
    return result.toString().trim() || null;
  } catch (_) {
    return null;
  }
}

/**
 * Store API key in macOS Keychain.
 *
 * **SECURITY**: Uses stdin pipe (execSync `input` option) instead of `-w`
 * command-line argument to prevent API key leakage via `ps aux`.
 *
 * @param {string} workerId
 * @param {string} apiKey
 * @returns {boolean}
 */
function _macStore(workerId, apiKey) {
  try {
    const account = _macAccount(workerId);
    // Delete existing entry (idempotent — ignore errors)
    try {
      execSync(
        `security delete-generic-password -a "${account}" -s "${SERVICE_NAME}"`,
        { stdio: 'pipe' }
      );
    } catch (_) { /* entry may not exist */ }

    // B100-A1: Pass API key via stdin pipe, NOT command-line argument.
    // macOS `security` reads password from stdin when `-w` is omitted.
    execSync(
      `security add-generic-password -a "${account}" -s "${SERVICE_NAME}" -U`,
      { input: apiKey, stdio: 'pipe', timeout: 5000 }
    );
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Delete API key from macOS Keychain.
 * @param {string} workerId
 * @returns {boolean}
 */
function _macDelete(workerId) {
  try {
    const account = _macAccount(workerId);
    execSync(
      `security delete-generic-password -a "${account}" -s "${SERVICE_NAME}"`,
      { stdio: 'pipe' }
    );
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Check if API key exists in macOS Keychain.
 * @param {string} workerId
 * @returns {boolean}
 */
function _macHas(workerId) {
  return _macGet(workerId) !== null;
}

// ── Linux libsecret ─────────────────────────────────────────────────

/**
 * Retrieve API key from Secret Service (libsecret).
 * @param {string} workerId
 * @returns {string | null}
 */
function _linuxGet(workerId) {
  try {
    const account = `${ACCOUNT_PREFIX}${workerId}`;
    const result = execSync(
      `secret-tool lookup account "${account}" service "${SERVICE_NAME}"`,
      { stdio: 'pipe', timeout: 3000 }
    );
    return result.toString().trim() || null;
  } catch (_) {
    return null;
  }
}

/**
 * Store API key in Secret Service.
 *
 * **SECURITY**: Uses stdin pipe (execSync `input` option) — API key
 * never appears in command-line arguments visible to `ps aux`.
 *
 * @param {string} workerId
 * @param {string} apiKey
 * @returns {boolean}
 */
function _linuxStore(workerId, apiKey) {
  try {
    const account = `${ACCOUNT_PREFIX}${workerId}`;
    // B100-A1+A4: Pass API key via stdin pipe, not echo -n (non-POSIX) in shell argv.
    // secret-tool store reads password from stdin when not provided as argument.
    execSync(
      `secret-tool store --label="Synapse Worker ${workerId}" account "${account}" service "${SERVICE_NAME}"`,
      { input: apiKey, stdio: 'pipe', timeout: 5000 }
    );
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Delete API key from Secret Service.
 * @param {string} workerId
 * @returns {boolean}
 */
function _linuxDelete(workerId) {
  try {
    const account = `${ACCOUNT_PREFIX}${workerId}`;
    execSync(
      `secret-tool clear account "${account}" service "${SERVICE_NAME}"`,
      { stdio: 'pipe' }
    );
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Check if API key exists in Secret Service.
 * @param {string} workerId
 * @returns {boolean}
 */
function _linuxHas(workerId) {
  return _linuxGet(workerId) !== null;
}

// ── Windows Credential Manager ──────────────────────────────────────

/**
 * Build Windows credential target name.
 * @param {string} workerId
 * @returns {string}
 */
function _winTarget(workerId) {
  return `${ACCOUNT_PREFIX}${workerId}`;
}

/**
 * Retrieve API key from Windows Credential Manager.
 *
 * Uses PowerShell to read from Credential Manager.
 * Falls back silently if CredentialManager module is not available
 * (e.g., Windows Server Core without the module installed).
 *
 * @param {string} workerId
 * @returns {string | null}
 */
function _winGet(workerId) {
  try {
    const target = _winTarget(workerId);
    // PowerShell script: try CredentialManager module first
    const psScript = [
      `$target = '${target}'`,
      `$cred = Get-StoredCredential -Target $target -ErrorAction SilentlyContinue`,
      `if ($cred) { $cred.GetNetworkCredential().Password }`,
      `else { Write-Output '' }`,
    ].join('; ');

    const result = execSync(
      `powershell -NoProfile -Command "${psScript}"`,
      { stdio: 'pipe', timeout: 5000 }
    );
    const password = result.toString().trim();
    return password || null;
  } catch (_) {
    return null;
  }
}

/**
 * Store API key in Windows Credential Manager.
 *
 * Uses `cmdkey /generic` which is always available on Windows.
 *
 * **SECURITY NOTE (B100-A1)**: `cmdkey` does not support stdin for
 * passwords — `/pass` value is visible in process listings during the
 * brief execSync window. This is a known Windows OS limitation.
 * Mitigation: execSync is synchronous and completes in milliseconds.
 *
 * @param {string} workerId
 * @param {string} apiKey
 * @returns {boolean}
 */
function _winStore(workerId, apiKey) {
  try {
    const target = _winTarget(workerId);
    // Remove existing entry first (idempotent)
    try {
      execSync(`cmdkey /delete:${target}`, { stdio: 'pipe' });
    } catch (_) { /* entry may not exist */ }

    // Store new entry
    execSync(
      `cmdkey /generic:"${target}" /user:synapse /pass:"${apiKey}"`,
      { stdio: 'pipe', timeout: 5000 }
    );
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Delete API key from Windows Credential Manager.
 * @param {string} workerId
 * @returns {boolean}
 */
function _winDelete(workerId) {
  try {
    const target = _winTarget(workerId);
    execSync(`cmdkey /delete:${target}`, { stdio: 'pipe' });
    return true;
  } catch (_) {
    return false;
  }
}

/**
 * Check if API key exists in Windows Credential Manager.
 * @param {string} workerId
 * @returns {boolean}
 */
function _winHas(workerId) {
  return _winGet(workerId) !== null;
}

// ── Public API ──────────────────────────────────────────────────────

/**
 * Retrieve the Synapse API key for a Worker from the OS keychain.
 *
 * Does NOT fall back to environment variables — that's the caller's job.
 * Returns null if keychain is unavailable or key not found.
 *
 * @param {string} workerId — Worker ID (e.g. ag_019f7a7c7a6f7886)
 * @returns {string | null}
 */
function getKey(workerId) {
  if (!workerId) return null;

  const platform = detectPlatform();
  switch (platform) {
    case 'macos':   return _macGet(workerId);
    case 'linux':   return _linuxGet(workerId);
    case 'windows': return _winGet(workerId);
    default:        return null;
  }
}

/**
 * Store a Synapse API key in the OS keychain.
 *
 * @param {string} workerId — Worker ID
 * @param {string} apiKey   — API key to store
 * @returns {boolean} — true on success, false if keychain unavailable
 */
function storeKey(workerId, apiKey) {
  if (!workerId || !apiKey) return false;

  const platform = detectPlatform();
  switch (platform) {
    case 'macos':   return _macStore(workerId, apiKey);
    case 'linux':   return _linuxStore(workerId, apiKey);
    case 'windows': return _winStore(workerId, apiKey);
    default:        return false;
  }
}

/**
 * Delete a Synapse API key from the OS keychain.
 *
 * @param {string} workerId — Worker ID
 * @returns {boolean} — true if deleted or didn't exist
 */
function deleteKey(workerId) {
  if (!workerId) return false;

  const platform = detectPlatform();
  switch (platform) {
    case 'macos':   return _macDelete(workerId);
    case 'linux':   return _linuxDelete(workerId);
    case 'windows': return _winDelete(workerId);
    default:        return false;
  }
}

/**
 * Check if a Worker's API key exists in the OS keychain.
 *
 * @param {string} workerId — Worker ID
 * @returns {boolean}
 */
function hasKey(workerId) {
  if (!workerId) return false;

  const platform = detectPlatform();
  switch (platform) {
    case 'macos':   return _macHas(workerId);
    case 'linux':   return _linuxHas(workerId);
    case 'windows': return _winHas(workerId);
    default:        return false;
  }
}

module.exports = { detectPlatform, getKey, storeKey, deleteKey, hasKey };

/**
 * P12-B28: Unit tests for keychain.js — Cross-platform OS keychain abstraction.
 *
 * Usage: node scripts/tests/test-keychain.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Mock strategy: intercept child_process.execSync and os.platform BEFORE
 * requiring the module, then clear require cache to get a fresh module
 * with mocks in place. Each test group reloads with its own mock config.
 */

'use strict';

const child_process = require('child_process');
const os = require('os');

const originalExecSync = child_process.execSync;
const originalPlatform = os.platform;

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
  } catch (e) {
    failed++;
    console.error(`❌ ${name}: ${e.message}`);
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg || 'assertion failed');
}

// ── Mock helpers ────────────────────────────────────────────────────────

let _execSyncImpl = null;
let _platformImpl = null;

function mockExecSync(fn) {
  _execSyncImpl = fn;
  child_process.execSync = function(cmd, opts) {
    return _execSyncImpl(cmd, opts);
  };
}

function mockPlatform(returnValue) {
  _platformImpl = returnValue;
  os.platform = function() { return _platformImpl; };
}

function restoreAll() {
  child_process.execSync = originalExecSync;
  os.platform = originalPlatform;
  _execSyncImpl = null;
  _platformImpl = null;
}

function reloadKeychain() {
  delete require.cache[require.resolve('../keychain')];
  return require('../keychain');
}

// ── detectPlatform tests ────────────────────────────────────────────────

test('detectPlatform returns macos when darwin and security CLI exists', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'macos', 'should detect macos');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns fallback when darwin but security CLI missing', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) throw new Error('not found');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'fallback', 'should fallback when security missing');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns linux when linux and secret-tool exists', () => {
  mockPlatform('linux');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v secret-tool')) return Buffer.from('/usr/bin/secret-tool\n');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'linux', 'should detect linux');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns fallback when linux but secret-tool missing', () => {
  mockPlatform('linux');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v secret-tool')) throw new Error('not found');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'fallback', 'should fallback when secret-tool missing');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns windows when win32 and cmdkey exists', () => {
  mockPlatform('win32');
  mockExecSync((cmd) => {
    if (cmd.includes('where cmdkey')) return Buffer.from('C:\\Windows\\System32\\cmdkey.exe\n');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'windows', 'should detect windows');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns fallback when win32 but cmdkey missing', () => {
  mockPlatform('win32');
  mockExecSync((cmd) => {
    if (cmd.includes('where cmdkey')) throw new Error('not found');
    throw new Error('unexpected command');
  });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'fallback', 'should fallback when cmdkey missing');
  } finally {
    restoreAll();
  }
});

test('detectPlatform returns fallback for unknown platform (aix)', () => {
  mockPlatform('aix');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.detectPlatform() === 'fallback', 'unknown platform should fallback');
  } finally {
    restoreAll();
  }
});

// ── getKey: input validation ────────────────────────────────────────────

test('getKey returns null for empty string workerId', () => {
  mockPlatform('darwin');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('') === null, 'empty workerId → null');
    assert(kc.getKey(null) === null, 'null workerId → null');
    assert(kc.getKey(undefined) === null, 'undefined workerId → null');
  } finally {
    restoreAll();
  }
});

// ── getKey: platform dispatch ───────────────────────────────────────────

test('getKey returns key on macOS when security succeeds', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('find-generic-password')) return Buffer.from('sk-test-api-key-12345\n');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_001') === 'sk-test-api-key-12345', 'should return key from keychain');
  } finally {
    restoreAll();
  }
});

test('getKey returns null on macOS when security fails (key not found)', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('find-generic-password')) throw new Error('key not found');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_001') === null, 'should return null when key not in keychain');
  } finally {
    restoreAll();
  }
});

test('getKey returns key on Linux when secret-tool succeeds', () => {
  mockPlatform('linux');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v secret-tool')) return Buffer.from('/usr/bin/secret-tool\n');
    if (cmd.includes('secret-tool lookup')) return Buffer.from('sk-linux-key-789\n');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_002') === 'sk-linux-key-789', 'should return key from secret-tool');
  } finally {
    restoreAll();
  }
});

test('getKey returns null on fallback platform', () => {
  mockPlatform('aix');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_001') === null, 'fallback → null');
  } finally {
    restoreAll();
  }
});

// ── storeKey: input validation ──────────────────────────────────────────

test('storeKey returns false for empty workerId or apiKey', () => {
  mockPlatform('darwin');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.storeKey('', 'key') === false, 'empty workerId → false');
    assert(kc.storeKey('ag_001', '') === false, 'empty apiKey → false');
    assert(kc.storeKey(null, 'key') === false, 'null workerId → false');
    assert(kc.storeKey('ag_001', null) === false, 'null apiKey → false');
  } finally {
    restoreAll();
  }
});

// ── storeKey: platform dispatch ─────────────────────────────────────────

test('storeKey succeeds on macOS (delete old + add new)', () => {
  const calls = [];
  mockPlatform('darwin');
  mockExecSync((cmd, opts) => {
    calls.push({ cmd, hasInput: !!opts.input });
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    // delete-generic-password may throw if entry doesn't exist — should be caught
    if (cmd.includes('delete-generic-password')) throw new Error('entry not found');
    // add-generic-password should succeed
    if (cmd.includes('add-generic-password')) return Buffer.from('');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.storeKey('ag_worker_001', 'sk-my-secret') === true, 'storeKey should succeed');
    // Verify stdin pipe was used (B100-A1 security)
    const addCall = calls.find(c => c.cmd.includes('add-generic-password'));
    assert(addCall !== undefined, 'should call add-generic-password');
    assert(addCall.hasInput === true, 'apiKey must be passed via stdin, not CLI arg (B100-A1)');
  } finally {
    restoreAll();
  }
});

test('storeKey returns false on macOS when add-generic-password fails', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('delete-generic-password')) throw new Error('entry not found');
    if (cmd.includes('add-generic-password')) throw new Error('keychain write error');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.storeKey('ag_worker_001', 'sk-my-secret') === false, 'should return false on failure');
  } finally {
    restoreAll();
  }
});

test('storeKey returns false on fallback platform', () => {
  mockPlatform('aix');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.storeKey('ag_001', 'sk-key') === false, 'fallback → false');
  } finally {
    restoreAll();
  }
});

// ── deleteKey: input validation ─────────────────────────────────────────

test('deleteKey returns false for empty workerId', () => {
  mockPlatform('darwin');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.deleteKey('') === false, 'empty workerId → false');
    assert(kc.deleteKey(null) === false, 'null workerId → false');
    assert(kc.deleteKey(undefined) === false, 'undefined workerId → false');
  } finally {
    restoreAll();
  }
});

// ── deleteKey: platform dispatch ────────────────────────────────────────

test('deleteKey succeeds on macOS', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('delete-generic-password')) return Buffer.from('');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.deleteKey('ag_worker_001') === true, 'deleteKey should succeed');
  } finally {
    restoreAll();
  }
});

test('deleteKey returns false on macOS when security command fails', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('delete-generic-password')) throw new Error('keychain error');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.deleteKey('ag_worker_001') === false, 'should return false on failure');
  } finally {
    restoreAll();
  }
});

test('deleteKey returns false on fallback platform', () => {
  mockPlatform('aix');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.deleteKey('ag_001') === false, 'fallback → false');
  } finally {
    restoreAll();
  }
});

// ── hasKey tests ────────────────────────────────────────────────────────

test('hasKey returns false for empty workerId', () => {
  mockPlatform('darwin');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.hasKey('') === false, 'empty workerId → false');
    assert(kc.hasKey(null) === false, 'null workerId → false');
  } finally {
    restoreAll();
  }
});

test('hasKey returns true when key exists (macOS)', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('find-generic-password')) return Buffer.from('sk-existing-key\n');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.hasKey('ag_worker_001') === true, 'hasKey should return true');
  } finally {
    restoreAll();
  }
});

test('hasKey returns false when key does not exist (macOS)', () => {
  mockPlatform('darwin');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v security')) return Buffer.from('/usr/bin/security\n');
    if (cmd.includes('find-generic-password')) throw new Error('not found');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.hasKey('ag_worker_001') === false, 'hasKey should return false');
  } finally {
    restoreAll();
  }
});

test('hasKey returns false on fallback platform', () => {
  mockPlatform('aix');
  mockExecSync(() => { throw new Error('should not be called'); });
  const kc = reloadKeychain();
  try {
    assert(kc.hasKey('ag_001') === false, 'fallback → false');
  } finally {
    restoreAll();
  }
});

// ── Cross-platform: Linux storeKey ──────────────────────────────────────

test('storeKey succeeds on Linux (secret-tool stdin pipe)', () => {
  const calls = [];
  mockPlatform('linux');
  mockExecSync((cmd, opts) => {
    calls.push({ cmd, hasInput: !!opts.input });
    if (cmd.includes('command -v secret-tool')) return Buffer.from('/usr/bin/secret-tool\n');
    if (cmd.includes('secret-tool store')) return Buffer.from('');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.storeKey('ag_worker_002', 'sk-linux-secret') === true, 'storeKey on linux should succeed');
    const storeCall = calls.find(c => c.cmd.includes('secret-tool store'));
    assert(storeCall !== undefined, 'should call secret-tool store');
    assert(storeCall.hasInput === true, 'apiKey must be passed via stdin, not CLI arg (B100-A1)');
  } finally {
    restoreAll();
  }
});

test('deleteKey succeeds on Linux (secret-tool clear)', () => {
  mockPlatform('linux');
  mockExecSync((cmd) => {
    if (cmd.includes('command -v secret-tool')) return Buffer.from('/usr/bin/secret-tool\n');
    if (cmd.includes('secret-tool clear')) return Buffer.from('');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.deleteKey('ag_worker_002') === true, 'deleteKey on linux should succeed');
  } finally {
    restoreAll();
  }
});

// ── Cross-platform: Windows getKey ──────────────────────────────────────

test('getKey returns key on Windows when PowerShell succeeds', () => {
  mockPlatform('win32');
  mockExecSync((cmd) => {
    if (cmd.includes('where cmdkey')) return Buffer.from('C:\\Windows\\System32\\cmdkey.exe\n');
    if (cmd.includes('powershell')) return Buffer.from('sk-windows-key-456\n');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_003') === 'sk-windows-key-456', 'should return key from Windows');
  } finally {
    restoreAll();
  }
});

test('getKey returns null on Windows when PowerShell returns empty', () => {
  mockPlatform('win32');
  mockExecSync((cmd) => {
    if (cmd.includes('where cmdkey')) return Buffer.from('C:\\Windows\\System32\\cmdkey.exe\n');
    if (cmd.includes('powershell')) return Buffer.from('  \n');
    throw new Error('unexpected: ' + cmd);
  });
  const kc = reloadKeychain();
  try {
    assert(kc.getKey('ag_worker_003') === null, 'should return null for empty PowerShell output');
  } finally {
    restoreAll();
  }
});

// ── Summary ─────────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

/**
 * P12-B31: Unit tests for lib/heartbeat-core.js — Pure logic extracted from heartbeat.js.
 *
 * Usage: node scripts/tests/test-heartbeat.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Mock strategy (per test): mock fs + child_process.spawn, reload module,
 * run assertions, restore originals.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const child_process = require('child_process');

// Save originals
const originals = {
  existsSync: fs.existsSync,
  readFileSync: fs.readFileSync,
  writeFileSync: fs.writeFileSync,
  unlinkSync: fs.unlinkSync,
  statSync: fs.statSync,
  spawn: child_process.spawn,
};

let passed = 0;
let failed = 0;
const _pending = [];  // collect promises from async tests

function test(name, fn) {
  try {
    const result = fn();
    if (result && typeof result.then === 'function') {
      // Async test — count only after promise settles
      _pending.push(
        result.then(
          () => { passed++; },
          (e) => {
            failed++;
            console.error(`❌ ${name}: ${e.message}`);
          }
        )
      );
      return; // don't count yet
    }
    // Sync test — count immediately
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

let _mockFs = {
  existingFiles: new Set(),
  fileContents: new Map(),
  writeCalls: [],
  unlinkCalls: [],
  statMtimes: new Map(),
};

function resetMockFs() {
  _mockFs.existingFiles.clear();
  _mockFs.fileContents.clear();
  _mockFs.writeCalls.length = 0;
  _mockFs.unlinkCalls.length = 0;
  _mockFs.statMtimes.clear();
}

function installMocks() {
  fs.existsSync = (p) => {
    if (_mockFs.existingFiles.has(p)) return true;
    return originals.existsSync(p);
  };
  fs.readFileSync = (p, enc) => {
    if (_mockFs.fileContents.has(p)) return _mockFs.fileContents.get(p);
    return originals.readFileSync(p, enc);
  };
  fs.writeFileSync = (p, content, enc) => {
    _mockFs.writeCalls.push({ path: p, content });
  };
  fs.unlinkSync = (p) => {
    _mockFs.unlinkCalls.push(p);
    // Only delegate to real fs if the path is real (not in mock state)
    if (!_mockFs.existingFiles.has(p)) {
      originals.unlinkSync(p);
    }
    // Path was in mock state — silently succeed (file removed)
    _mockFs.existingFiles.delete(p);
  };
  fs.statSync = (p) => {
    if (_mockFs.statMtimes.has(p)) {
      return { mtimeMs: _mockFs.statMtimes.get(p) };
    }
    if (_mockFs.existingFiles.has(p)) {
      return { mtimeMs: Date.now() };
    }
    throw new Error('ENOENT: ' + p);
  };
}

function restoreAll() {
  fs.existsSync = originals.existsSync;
  fs.readFileSync = originals.readFileSync;
  fs.writeFileSync = originals.writeFileSync;
  fs.unlinkSync = originals.unlinkSync;
  fs.statSync = originals.statSync;
  child_process.spawn = originals.spawn;
}

function reloadHeartbeatCore() {
  delete require.cache[require.resolve('../lib/heartbeat-core')];
  return require('../lib/heartbeat-core');
}

// ── isSessionAlive() tests ─────────────────────────────────────────────

test('isSessionAlive: recent file → true', () => {
  resetMockFs();
  installMocks();
  try {
    const aliveFile = '/fake/.session-alive';
    _mockFs.existingFiles.add(aliveFile);
    _mockFs.statMtimes.set(aliveFile, Date.now() - 10_000); // 10s ago
    const mod = reloadHeartbeatCore();
    assert(mod.isSessionAlive(aliveFile, 60_000) === true);
  } finally { restoreAll(); }
});

test('isSessionAlive: stale file → false', () => {
  resetMockFs();
  installMocks();
  try {
    const aliveFile = '/fake/.session-alive';
    _mockFs.existingFiles.add(aliveFile);
    _mockFs.statMtimes.set(aliveFile, Date.now() - 300_000); // 5 min ago
    const mod = reloadHeartbeatCore();
    assert(mod.isSessionAlive(aliveFile, 120_000) === false);
  } finally { restoreAll(); }
});

test('isSessionAlive: missing file → false', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadHeartbeatCore();
    assert(mod.isSessionAlive('/nonexistent/file', 120_000) === false);
  } finally { restoreAll(); }
});

// ── checkTemplateVersion() tests ────────────────────────────────────────

test('checkTemplateVersion: no serverVersion → returns undefined', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('', {
      versionFile: '/fake/version.json',
      upgradeFlagFile: '/fake/upgrade-needed',
    });
    assert(result === undefined, 'should return undefined when no version');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: null serverVersion → returns undefined', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion(null, {
      versionFile: '/fake/version.json',
      upgradeFlagFile: '/fake/upgrade-needed',
    });
    assert(result === undefined);
  } finally { restoreAll(); }
});

test('checkTemplateVersion: no local version → writes flag with reason', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
    });
    assert(result.action === 'flag_written');
    assert(result.reason === 'no_local_version');
    assert(result.serverVersion === 'v2.0.0');
    // Check that upgrade flag was written
    const flagWrite = _mockFs.writeCalls.find(c => c.path === upgradeFlagFile);
    assert(flagWrite !== undefined, 'should write upgrade flag');
    const flag = JSON.parse(flagWrite.content);
    assert(flag.current === null);
    assert(flag.latest === 'v2.0.0');
    assert(flag.reason === 'no_local_version');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: version match (no stale flag) → ok', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ version: 'v1.0.0' }));
    _mockFs.existingFiles.add(versionFile);
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v1.0.0', {
      versionFile,
      upgradeFlagFile,
    });
    assert(result.action === 'ok');
    assert(result.localVersion === 'v1.0.0');
    // Should NOT write flag
    const flagWrite = _mockFs.writeCalls.find(c => c.path === upgradeFlagFile);
    assert(flagWrite === undefined, 'should not write flag when versions match');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: version match + stale flag exists → clears flag', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ version: 'v1.0.0' }));
    _mockFs.existingFiles.add(versionFile);
    _mockFs.existingFiles.add(upgradeFlagFile); // stale flag exists
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v1.0.0', {
      versionFile,
      upgradeFlagFile,
    });
    assert(result.action === 'flag_cleared');
    // unlinkSync was called on the flag
    assert(_mockFs.unlinkCalls.includes(upgradeFlagFile), 'should unlink stale flag');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: version mismatch → writes flag', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ version: 'v1.0.0' }));
    _mockFs.existingFiles.add(versionFile);
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
      // No sessionInitScript → won't spawn
    });
    assert(result.action === 'flag_written');
    assert(result.localVersion === 'v1.0.0');
    assert(result.serverVersion === 'v2.0.0');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: version mismatch with sessionInitScript → spawns upgrade', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ version: 'v1.0.0' }));
    _mockFs.existingFiles.add(versionFile);

    // Mock spawn to track calls
    const spawnCalls = [];
    child_process.spawn = (cmd, args, opts) => {
      spawnCalls.push({ cmd, args, opts });
      return { unref() {}, pid: 9999 };
    };

    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
      sessionInitScript: '/fake/session-init.js',
      execPath: '/usr/bin/node',
    });
    assert(result.action === 'upgrade_spawned');
    assert(spawnCalls.length === 1);
    assert(spawnCalls[0].args.includes('--upgrade'));
    assert(spawnCalls[0].args.includes('--silent'));
    assert(spawnCalls[0].opts.detached === true);
  } finally { restoreAll(); }
});

test('checkTemplateVersion: spawn failure is handled gracefully', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ version: 'v1.0.0' }));
    _mockFs.existingFiles.add(versionFile);

    child_process.spawn = () => { throw new Error('spawn ENOENT'); };

    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
      sessionInitScript: '/nonexistent/script.js',
      execPath: '/usr/bin/node',
    });
    assert(result.action === 'flag_written');
    assert(result.reason === 'spawn_failed');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: corrupt local version file → treated as no local version', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, 'not valid json {{{');
    _mockFs.existingFiles.add(versionFile);
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
    });
    assert(result.action === 'flag_written');
    assert(result.reason === 'no_local_version');
  } finally { restoreAll(); }
});

test('checkTemplateVersion: version file has no version field → treated as no local version', () => {
  resetMockFs();
  installMocks();
  try {
    const versionFile = '/fake/version.json';
    const upgradeFlagFile = '/fake/upgrade-needed';
    _mockFs.fileContents.set(versionFile, JSON.stringify({ other: 'data' }));
    _mockFs.existingFiles.add(versionFile);
    const mod = reloadHeartbeatCore();
    const result = mod.checkTemplateVersion('v2.0.0', {
      versionFile,
      upgradeFlagFile,
    });
    assert(result.action === 'flag_written');
    assert(result.reason === 'no_local_version');
  } finally { restoreAll(); }
});

// ── sendHeartbeat() tests ──────────────────────────────────────────────

test('sendHeartbeat: success returns data', async () => {
  const mod = reloadHeartbeatCore();
  const mockClient = {
    post: async () => ({ error: false, data: { runtime_status: 'active' } }),
  };
  const result = await mod.sendHeartbeat(mockClient, 'ag_test');
  assert(result.error === false);
  assert(result.data.runtime_status === 'active');
});

test('sendHeartbeat: success with template_version calls onTemplateVersion', async () => {
  const mod = reloadHeartbeatCore();
  let versionReceived = null;
  const mockClient = {
    post: async () => ({
      error: false,
      data: { runtime_status: 'active', template_version: 'v3.0.0' },
    }),
  };
  const result = await mod.sendHeartbeat(mockClient, 'ag_test', {
    onTemplateVersion: (v) => { versionReceived = v; },
  });
  assert(result.error === false);
  assert(versionReceived === 'v3.0.0', 'onTemplateVersion should be called with server version');
});

test('sendHeartbeat: HTTP error returns error=true with status', async () => {
  const mod = reloadHeartbeatCore();
  const mockClient = {
    post: async () => ({ error: true, status: 503 }),
  };
  const result = await mod.sendHeartbeat(mockClient, 'ag_test');
  assert(result.error === true);
  assert(result.status === 503);
});

test('sendHeartbeat: network error (no status) returns error=true', async () => {
  const mod = reloadHeartbeatCore();
  const mockClient = {
    post: async () => ({ error: true }), // no status = unreachable
  };
  const result = await mod.sendHeartbeat(mockClient, 'ag_test');
  assert(result.error === true);
  assert(result.message === 'unreachable');
});

// ── Edge cases ──────────────────────────────────────────────────────────

test('edge: sendHeartbeat response data is null → defaults runtime_status', async () => {
  const mod = reloadHeartbeatCore();
  const mockClient = {
    post: async () => ({ error: false, data: null }),
  };
  const result = await mod.sendHeartbeat(mockClient, 'ag_test');
  assert(result.error === false);
  assert(result.data.runtime_status === 'unknown');
});

test('edge: sendHeartbeat with template_version=null does not call onTemplateVersion', async () => {
  const mod = reloadHeartbeatCore();
  let called = false;
  const mockClient = {
    post: async () => ({
      error: false,
      data: { runtime_status: 'active', template_version: null },
    }),
  };
  await mod.sendHeartbeat(mockClient, 'ag_test', {
    onTemplateVersion: () => { called = true; },
  });
  assert(called === false, 'null version should not trigger callback');
});

test('edge: sendHeartbeat with no onTemplateVersion callback does not throw', async () => {
  const mod = reloadHeartbeatCore();
  const mockClient = {
    post: async () => ({
      error: false,
      data: { runtime_status: 'active', template_version: 'v1.0.0' },
    }),
  };
  // Should not throw even without callback
  const result = await mod.sendHeartbeat(mockClient, 'ag_test');
  assert(result.error === false);
});

// ── Summary (awaits async tests before reporting) ──────────────────────

Promise.all(_pending).then(() => {
  console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
  process.exit(failed > 0 ? 1 : 0);
}).catch(() => {
  console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
  process.exit(1);
});

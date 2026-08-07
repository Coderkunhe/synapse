/**
 * P12-B31: Unit tests for lib/ws-daemon-core.js — Pure logic extracted from ws-daemon.js.
 *
 * Usage: node scripts/tests/test-ws-daemon.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Mock strategy (per test): mock fs + process.env + keychain, reload module,
 * run assertions, restore originals. Each test group clears the require cache
 * so the module is loaded fresh with new mocks.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const child_process = require('child_process');

// Save originals for restoration
const originals = {
  existsSync: fs.existsSync,
  readFileSync: fs.readFileSync,
  writeFileSync: fs.writeFileSync,
  statSync: fs.statSync,
};

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

let _mockFs = {
  existingFiles: new Set(),
  fileContents: new Map(),
  writeCalls: [],
  unlinkCalls: [],
  statMtimes: new Map(), // path → mtimeMs
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
  fs.statSync = originals.statSync;
}

// Mock keychain.getKey — replace BEFORE require
const keychainPath = path.resolve(__dirname, '..', 'keychain.js');
const originalKeychain = require.cache[require.resolve(keychainPath)];

function reloadWsDaemonCore() {
  delete require.cache[require.resolve('../lib/ws-daemon-core')];
  return require('../lib/ws-daemon-core');
}

// ── toWsUrl() tests ────────────────────────────────────────────────────

test('toWsUrl: http → ws', () => {
  const mod = reloadWsDaemonCore();
  assert(mod.toWsUrl('http://127.0.0.1:8001') === 'ws://127.0.0.1:8001');
});

test('toWsUrl: https → wss', () => {
  const mod = reloadWsDaemonCore();
  assert(mod.toWsUrl('https://api.example.com') === 'wss://api.example.com');
});

test('toWsUrl: trailing slash preserved (user responsibility)', () => {
  const mod = reloadWsDaemonCore();
  const result = mod.toWsUrl('http://localhost:8001/');
  assert(result === 'ws://localhost:8001/', 'trailing slash should be preserved');
});

test('toWsUrl: port and path preserved', () => {
  const mod = reloadWsDaemonCore();
  assert(mod.toWsUrl('http://0.0.0.0:9000/v1') === 'ws://0.0.0.0:9000/v1');
});

test('toWsUrl: only replaces http prefix, not in path', () => {
  const mod = reloadWsDaemonCore();
  assert(mod.toWsUrl('http://host/http-path') === 'ws://host/http-path',
    'only the scheme prefix should change, not mid-string');
});

// ── now() tests ────────────────────────────────────────────────────────

test('now: returns ISO string', () => {
  const mod = reloadWsDaemonCore();
  const ts = mod.now();
  assert(typeof ts === 'string', 'should return string');
  assert(ts.includes('T'), 'ISO format should have T separator');
  assert(ts.endsWith('Z') || ts.includes('+') || ts.includes('-'), 'should have timezone');
});

test('now: returns different values on successive calls', () => {
  const mod = reloadWsDaemonCore();
  const a = mod.now();
  // busy-wait briefly to ensure clock tick
  const start = Date.now();
  while (Date.now() === start) { /* wait */ }
  const b = mod.now();
  assert(a !== b, 'successive calls should produce different timestamps');
});

// ── isSessionAlive() tests ─────────────────────────────────────────────

test('isSessionAlive: recent file → true', () => {
  resetMockFs();
  installMocks();
  try {
    const aliveFile = '/fake/.session-alive';
    _mockFs.existingFiles.add(aliveFile);
    _mockFs.statMtimes.set(aliveFile, Date.now() - 30_000); // 30s ago
    const mod = reloadWsDaemonCore();
    assert(mod.isSessionAlive(aliveFile, 120_000) === true, '30s old file within 120s timeout');
  } finally { restoreAll(); }
});

test('isSessionAlive: stale file → false', () => {
  resetMockFs();
  installMocks();
  try {
    const aliveFile = '/fake/.session-alive';
    _mockFs.existingFiles.add(aliveFile);
    _mockFs.statMtimes.set(aliveFile, Date.now() - 180_000); // 3 min ago
    const mod = reloadWsDaemonCore();
    assert(mod.isSessionAlive(aliveFile, 120_000) === false, '3 min old file should be beyond timeout');
  } finally { restoreAll(); }
});

test('isSessionAlive: missing file → false', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadWsDaemonCore();
    assert(mod.isSessionAlive('/nonexistent/file', 120_000) === false);
  } finally { restoreAll(); }
});

// ── resolveConfig() tests ──────────────────────────────────────────────

test('resolveConfig: env vars set correctly', () => {
  const saveUrl = process.env.SYNAPSE_API_URL;
  const saveId = process.env.SYNAPSE_WORKER_ID;
  const saveKey = process.env.SYNAPSE_API_KEY;
  try {
    process.env.SYNAPSE_API_URL = 'http://myserver:9000';
    process.env.SYNAPSE_WORKER_ID = 'ag_test123';
    process.env.SYNAPSE_API_KEY = 'sk-test-key';
    const mod = reloadWsDaemonCore();
    const cfg = mod.resolveConfig();
    assert(cfg.apiUrl === 'http://myserver:9000');
    assert(cfg.workerId === 'ag_test123');
    assert(cfg.apiKey === 'sk-test-key');
  } finally {
    process.env.SYNAPSE_API_URL = saveUrl;
    process.env.SYNAPSE_WORKER_ID = saveId;
    process.env.SYNAPSE_API_KEY = saveKey;
  }
});

test('resolveConfig: trailing slash is stripped from URL', () => {
  const saveUrl = process.env.SYNAPSE_API_URL;
  try {
    process.env.SYNAPSE_API_URL = 'http://localhost:8001/';
    process.env.SYNAPSE_WORKER_ID = 'ag_x';
    process.env.SYNAPSE_API_KEY = 'sk-x';
    const mod = reloadWsDaemonCore();
    assert(mod.resolveConfig().apiUrl === 'http://localhost:8001', 'trailing slash stripped');
  } finally {
    process.env.SYNAPSE_API_URL = saveUrl;
  }
});

test('resolveConfig: uses default URL when env not set', () => {
  const saveUrl = process.env.SYNAPSE_API_URL;
  const saveId = process.env.SYNAPSE_WORKER_ID;
  const saveKey = process.env.SYNAPSE_API_KEY;
  try {
    delete process.env.SYNAPSE_API_URL;
    process.env.SYNAPSE_WORKER_ID = 'ag_x';
    process.env.SYNAPSE_API_KEY = 'sk-x';
    const mod = reloadWsDaemonCore();
    assert(mod.resolveConfig().apiUrl === 'http://127.0.0.1:8001');
  } finally {
    process.env.SYNAPSE_API_URL = saveUrl;
    process.env.SYNAPSE_WORKER_ID = saveId;
    process.env.SYNAPSE_API_KEY = saveKey;
  }
});

test('resolveConfig: missing workerId returns empty string', () => {
  const saveId = process.env.SYNAPSE_WORKER_ID;
  const saveKey = process.env.SYNAPSE_API_KEY;
  try {
    delete process.env.SYNAPSE_WORKER_ID;
    process.env.SYNAPSE_API_KEY = 'sk-x';
    const mod = reloadWsDaemonCore();
    assert(mod.resolveConfig().workerId === '');
  } finally {
    process.env.SYNAPSE_WORKER_ID = saveId;
    process.env.SYNAPSE_API_KEY = saveKey;
  }
});

test('resolveConfig: missing apiKey returns empty string (no keychain fallback without workerId)', () => {
  const saveKey = process.env.SYNAPSE_API_KEY;
  const saveId = process.env.SYNAPSE_WORKER_ID;
  try {
    delete process.env.SYNAPSE_API_KEY;
    delete process.env.SYNAPSE_WORKER_ID;
    const mod = reloadWsDaemonCore();
    assert(mod.resolveConfig().apiKey === '');
  } finally {
    process.env.SYNAPSE_API_KEY = saveKey;
    process.env.SYNAPSE_WORKER_ID = saveId;
  }
});

// ── writeStatus() tests ─────────────────────────────────────────────────

test('writeStatus: running writes pid + since', () => {
  resetMockFs();
  installMocks();
  try {
    const statusFile = '/fake/_ws-status.json';
    const mod = reloadWsDaemonCore();
    mod.writeStatus(statusFile, 'running');
    assert(_mockFs.writeCalls.length === 1, 'should write one file');
    const payload = JSON.parse(_mockFs.writeCalls[0].content);
    assert(payload.status === 'running');
    assert(typeof payload.pid === 'number');
    assert(typeof payload.since === 'string');
    assert(_mockFs.writeCalls[0].path === statusFile);
  } finally { restoreAll(); }
});

test('writeStatus: dead writes since, no pid', () => {
  resetMockFs();
  installMocks();
  try {
    const statusFile = '/fake/_ws-status.json';
    const mod = reloadWsDaemonCore();
    mod.writeStatus(statusFile, 'dead');
    const payload = JSON.parse(_mockFs.writeCalls[0].content);
    assert(payload.status === 'dead');
    assert(payload.pid === undefined, 'dead status should not include pid');
    assert(typeof payload.since === 'string');
  } finally { restoreAll(); }
});

test('writeStatus: fs error is handled gracefully', () => {
  // The lib uses try/catch, so even if writeFileSync throws, it won't propagate
  resetMockFs();
  installMocks();
  try {
    const mod = reloadWsDaemonCore();
    // Make writeFileSync throw for this specific path
    const saveWrite = fs.writeFileSync;
    let threw = false;
    fs.writeFileSync = () => { threw = true; throw new Error('disk full'); };
    try {
      mod.writeStatus('/fake/status.json', 'running');
      assert(threw, 'writeFileSync should have been called (and error swallowed)');
    } finally {
      fs.writeFileSync = saveWrite;
    }
  } finally { restoreAll(); }
});

// ── appendEvent() tests ─────────────────────────────────────────────────

test('appendEvent: first event creates file', () => {
  resetMockFs();
  installMocks();
  try {
    const eventsFile = '/fake/_ws-events.jsonl';
    const mod = reloadWsDaemonCore();
    mod.appendEvent(eventsFile, 50, { type: 'task.create', task_id: 't1' });
    assert(_mockFs.writeCalls.length === 1);
    const content = _mockFs.writeCalls[0].content;
    assert(content.includes('task.create'), 'should contain event type');
    assert(content.includes('t1'), 'should contain task_id');
    assert(content.includes('"ts"'), 'should have ts field');
  } finally { restoreAll(); }
});

test('appendEvent: appends to existing events', () => {
  resetMockFs();
  installMocks();
  try {
    const eventsFile = '/fake/_ws-events.jsonl';
    _mockFs.fileContents.set(eventsFile, '{"ts":"old","type":"ev1"}\n');
    _mockFs.existingFiles.add(eventsFile);
    const mod = reloadWsDaemonCore();
    mod.appendEvent(eventsFile, 50, { type: 'ev2' });
    const content = _mockFs.writeCalls[0].content;
    const lines = content.trim().split('\n');
    assert(lines.length === 2, 'should have 2 lines (old + new)');
    assert(lines[0].includes('ev1'), 'first line should be old event');
    assert(lines[1].includes('ev2'), 'second line should be new event');
  } finally { restoreAll(); }
});

test('appendEvent: rotates at maxEvents', () => {
  resetMockFs();
  installMocks();
  try {
    const eventsFile = '/fake/_ws-events.jsonl';
    // Create 5 existing events
    const existing = [];
    for (let i = 0; i < 5; i++) {
      existing.push(JSON.stringify({ ts: 't' + i, type: 'e' + i }));
    }
    _mockFs.fileContents.set(eventsFile, existing.join('\n') + '\n');
    _mockFs.existingFiles.add(eventsFile);
    const mod = reloadWsDaemonCore();
    mod.appendEvent(eventsFile, 5, { type: 'new' }); // max 5, 5 existing → old gets shifted
    const content = _mockFs.writeCalls[0].content;
    const lines = content.trim().split('\n');
    assert(lines.length === 5, 'should keep exactly 5 events');
    assert(lines[0].includes('e1'), 'oldest event (e0) should be shifted');
    assert(lines[4].includes('new'), 'newest event should be last');
  } finally { restoreAll(); }
});

test('appendEvent: rotation not triggered when under limit', () => {
  resetMockFs();
  installMocks();
  try {
    const eventsFile = '/fake/_ws-events.jsonl';
    _mockFs.fileContents.set(eventsFile, '{"ts":"t1","type":"a"}\n');
    _mockFs.existingFiles.add(eventsFile);
    const mod = reloadWsDaemonCore();
    mod.appendEvent(eventsFile, 50, { type: 'b' });
    const content = _mockFs.writeCalls[0].content;
    const lines = content.trim().split('\n');
    assert(lines.length === 2, 'should keep both events when under limit');
  } finally { restoreAll(); }
});

test('appendEvent: handles disk error gracefully', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadWsDaemonCore();
    let called = false;
    const saveWrite = fs.writeFileSync;
    fs.writeFileSync = () => { called = true; throw new Error('disk full'); };
    try {
      mod.appendEvent('/fake/events.jsonl', 50, { type: 'test' });
      assert(called, 'write was attempted (and error swallowed)');
    } finally {
      fs.writeFileSync = saveWrite;
    }
  } finally { restoreAll(); }
});

// ── touchHealth() tests ─────────────────────────────────────────────────

test('touchHealth: writes timestamp to file', () => {
  resetMockFs();
  installMocks();
  try {
    const healthFile = '/fake/_ws-health.txt';
    const mod = reloadWsDaemonCore();
    mod.touchHealth(healthFile);
    assert(_mockFs.writeCalls.length === 1);
    assert(_mockFs.writeCalls[0].path === healthFile);
    const content = _mockFs.writeCalls[0].content;
    assert(content.includes('T'), 'should contain ISO timestamp');
  } finally { restoreAll(); }
});

test('touchHealth: handles fs error gracefully', () => {
  resetMockFs();
  installMocks();
  try {
    const mod = reloadWsDaemonCore();
    let called = false;
    const saveWrite = fs.writeFileSync;
    fs.writeFileSync = () => { called = true; throw new Error('permission denied'); };
    try {
      mod.touchHealth('/fake/health.txt');
      assert(called, 'write attempt should have been made');
    } finally {
      fs.writeFileSync = saveWrite;
    }
  } finally { restoreAll(); }
});

// ── Edge case tests ─────────────────────────────────────────────────────

test('edge: resolveConfig with special characters in URL', () => {
  const saveUrl = process.env.SYNAPSE_API_URL;
  const saveId = process.env.SYNAPSE_WORKER_ID;
  const saveKey = process.env.SYNAPSE_API_KEY;
  try {
    process.env.SYNAPSE_API_URL = 'http://host-with-dash:8080';
    process.env.SYNAPSE_WORKER_ID = 'ag_test';
    process.env.SYNAPSE_API_KEY = 'sk_test';
    const mod = reloadWsDaemonCore();
    const cfg = mod.resolveConfig();
    assert(cfg.apiUrl === 'http://host-with-dash:8080');
  } finally {
    process.env.SYNAPSE_API_URL = saveUrl;
    process.env.SYNAPSE_WORKER_ID = saveId;
    process.env.SYNAPSE_API_KEY = saveKey;
  }
});

test('edge: appendEvent with empty events file (just newline)', () => {
  resetMockFs();
  installMocks();
  try {
    const eventsFile = '/fake/empty.jsonl';
    _mockFs.fileContents.set(eventsFile, '\n');
    _mockFs.existingFiles.add(eventsFile);
    const mod = reloadWsDaemonCore();
    mod.appendEvent(eventsFile, 50, { type: 'first' });
    const content = _mockFs.writeCalls[0].content;
    const lines = content.trim().split('\n');
    assert(lines.length === 1, 'should ignore empty lines');
    assert(lines[0].includes('first'));
  } finally { restoreAll(); }
});

test('edge: toWsUrl with no http prefix returns unchanged', () => {
  // If there's no http prefix, regex replace is a no-op
  const mod = reloadWsDaemonCore();
  assert(mod.toWsUrl('ws://already-ws') === 'ws://already-ws', 'already ws should stay ws');
});

// ── Summary ────────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

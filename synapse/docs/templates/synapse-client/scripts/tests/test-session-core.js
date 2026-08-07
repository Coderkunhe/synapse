/**
 * P12-B32: Unit tests for lib/session-core.js — Pure logic extracted from session-init.js.
 *
 * Usage: node scripts/tests/test-session-core.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Mock strategy (per test group): mock fs.*Sync functions, reload module,
 * run assertions, restore originals.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const os = require('os');

// Save originals for restoration
const originals = {
  existsSync: fs.existsSync,
  readFileSync: fs.readFileSync,
  writeFileSync: fs.writeFileSync,
  unlinkSync: fs.unlinkSync,
  statSync: fs.statSync,
  mkdirSync: fs.mkdirSync,
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
  statMtimes: new Map(),
  realPaths: new Set(), // paths that should fall through to real fs
};

function resetMockFs() {
  _mockFs.existingFiles.clear();
  _mockFs.fileContents.clear();
  _mockFs.writeCalls.length = 0;
  _mockFs.unlinkCalls.length = 0;
  _mockFs.statMtimes.clear();
  _mockFs.realPaths.clear();
}

function installMocks() {
  fs.existsSync = (p) => {
    if (_mockFs.existingFiles.has(p)) return true;
    return originals.existsSync(p); // fall through to real fs
  };
  fs.readFileSync = (p, enc) => {
    if (_mockFs.fileContents.has(p)) return _mockFs.fileContents.get(p);
    return originals.readFileSync(p, enc); // fall through to real fs
  };
  fs.writeFileSync = (p, content, enc) => {
    _mockFs.writeCalls.push({ path: p, content });
  };
  fs.unlinkSync = (p) => {
    _mockFs.unlinkCalls.push(p);
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
  fs.mkdirSync = (p, opts) => {
    _mockFs.existingFiles.add(p);
  };
}

function restoreMocks() {
  fs.existsSync = originals.existsSync;
  fs.readFileSync = originals.readFileSync;
  fs.writeFileSync = originals.writeFileSync;
  fs.unlinkSync = originals.unlinkSync;
  fs.statSync = originals.statSync;
  fs.mkdirSync = originals.mkdirSync;
}

// Reload session-core module (clears require cache)
function reloadModule() {
  const modPath = path.resolve(__dirname, '..', 'lib', 'session-core.js');
  delete require.cache[require.resolve(modPath)];
  return require(modPath);
}

// ── Tests: now() ────────────────────────────────────────────────────────

(function() {
  const mod = reloadModule();

  test('now() returns ISO 8601 timestamp string', () => {
    const ts = mod.now();
    assert(typeof ts === 'string', 'should be a string');
    assert(ts.includes('T'), 'should contain T separator');
    assert(ts.endsWith('Z') || ts.includes('+') || ts.includes('-'), 'should have timezone');
    // Verify it parses back to a valid date
    const d = new Date(ts);
    assert(!isNaN(d.getTime()), 'should parse to valid Date');
  });

  test('now() returns different values on successive calls', () => {
    const ts1 = mod.now();
    // Small busy-wait to ensure time advances
    const start = Date.now();
    while (Date.now() - start < 5) { /* spin */ }
    const ts2 = mod.now();
    assert(ts1 !== ts2, 'successive calls should return different timestamps');
  });
})();

// ── Tests: ownerLabel() ─────────────────────────────────────────────────

(function() {
  const mod = reloadModule();

  test('ownerLabel: unassigned task (no owner_id)', () => {
    const task = { id: 't1', owner_id: null };
    assert(mod.ownerLabel(task, 'worker-1') === 'unassigned');
  });

  test('ownerLabel: unassigned task (empty owner_id)', () => {
    const task = { id: 't1', owner_id: '' };
    assert(mod.ownerLabel(task, 'worker-1') === 'unassigned');
  });

  test('ownerLabel: own task returns 🫵 YOU', () => {
    const task = { id: 't1', owner_id: 'ag_123', owner_name: 'Builder1', owner_type: 'worker' };
    assert(mod.ownerLabel(task, 'ag_123') === '🫵 YOU');
  });

  test('ownerLabel: other worker returns (NOT YOU)', () => {
    const task = { id: 't1', owner_id: 'ag_other', owner_name: 'OtherBuilder', owner_type: 'worker' };
    const label = mod.ownerLabel(task, 'ag_123');
    assert(label.includes('(NOT YOU)'), 'should include (NOT YOU) warning');
    assert(label.includes('OtherBuilder'), 'should include owner name');
  });

  test('ownerLabel: human owner (no NOT YOU)', () => {
    const task = { id: 't1', owner_id: 'member-1', owner_name: 'Alice', owner_type: 'member' };
    const label = mod.ownerLabel(task, 'ag_123');
    assert(!label.includes('(NOT YOU)'), 'human owner should not show NOT YOU');
    assert(label.includes('Alice'), 'should include owner name');
  });

  test('ownerLabel: empty myWorkerId falls back to owner name', () => {
    const task = { id: 't1', owner_id: 'ag_other', owner_name: 'Builder2', owner_type: 'worker' };
    const label = mod.ownerLabel(task, '');
    assert(label === 'owner: Builder2', 'should show owner name without NOT YOU when workerId is empty');
  });

  test('ownerLabel: missing owner_name uses owner_id', () => {
    const task = { id: 't1', owner_id: 'ag_nameless', owner_type: 'worker' };
    const label = mod.ownerLabel(task, 'ag_me');
    assert(label.includes('ag_nameless'), 'should fall back to owner_id when name missing');
  });
})();

// ── Tests: summarizeTask() ───────────────────────────────────────────────

(function() {
  const mod = reloadModule();

  test('summarizeTask: full task object', () => {
    const task = {
      id: 'tsk_001', title: 'Fix auth bug', status: 'in_progress',
      owner_id: 'ag_123', owner_name: 'Builder1',
      depends_on: ['tsk_dep1', 'tsk_dep2'],
    };
    const s = mod.summarizeTask(task);
    assert(s.id === 'tsk_001');
    assert(s.title === 'Fix auth bug');
    assert(s.status === 'in_progress');
    assert(s.owner_id === 'ag_123');
    assert(s.owner_name === 'Builder1');
    assert(s.depends_on.length === 2);
    assert(s.depends_on[0] === 'tsk_dep1');
  });

  test('summarizeTask: minimal task (missing fields)', () => {
    const task = { id: 'tsk_002' };
    const s = mod.summarizeTask(task);
    assert(s.id === 'tsk_002');
    assert(s.title === 'tsk_002'); // fallback to id
    assert(s.status === undefined);
    assert(s.owner_id === null);
    assert(s.owner_name === null);
    assert(Array.isArray(s.depends_on));
    assert(s.depends_on.length === 0);
  });

  test('summarizeTask: null depends_on defaults to empty array', () => {
    const task = { id: 'tsk_003', title: 'T', status: 'ready', depends_on: null };
    const s = mod.summarizeTask(task);
    assert(Array.isArray(s.depends_on));
    assert(s.depends_on.length === 0);
  });
})();

// ── Tests: roleBanner() ──────────────────────────────────────────────────

(function() {
  const mod = reloadModule();

  test('roleBanner: builder role', () => {
    const state = { role: 'builder', protocolData: { project_name: 'TestProject' } };
    const banner = mod.roleBanner(state);
    assert(banner.includes('🔵'), 'builder should have blue icon');
    assert(banner.includes('Builder'), 'should mention Builder');
    assert(banner.includes('TestProject'), 'should include project name');
    assert(banner.includes('接 Task'), 'should include builder responsibilities');
  });

  test('roleBanner: orchestrator role', () => {
    const state = { role: 'orchestrator', protocolData: { project_name: 'Ops' } };
    const banner = mod.roleBanner(state);
    assert(banner.includes('🟠'), 'orchestrator should have orange icon');
    assert(banner.includes('Orchestrator'), 'should mention Orchestrator');
    assert(banner.includes('验收结果'), 'should include orch responsibilities');
  });

  test('roleBanner: steward role', () => {
    const state = { role: 'steward', protocolData: { project_name: 'Audit' } };
    const banner = mod.roleBanner(state);
    assert(banner.includes('⚪'), 'steward should have white icon');
    assert(banner.includes('Steward'), 'should mention Steward');
    assert(banner.includes('安全检查'), 'should include security check');
  });

  test('roleBanner: unknown role defaults to builder', () => {
    const state = { role: 'unknown', protocolData: { project_name: 'P' } };
    const banner = mod.roleBanner(state);
    // Fallback: roleColors['unknown'] → '⚪', roleBanners['unknown'] → builder fallback
    assert(banner.includes('Builder'), 'unknown should default to builder text');
    assert(banner.includes('接 Task'), 'should include builder responsibilities');
  });

  test('roleBanner: default_fallback shows warning', () => {
    const state = { role: 'builder', protocolData: { project_name: 'P', role_source: 'default_fallback' } };
    const banner = mod.roleBanner(state);
    assert(banner.includes('default_fallback') || banner.includes('默认分配'), 'should include fallback warning');
  });

  test('roleBanner: missing protocolData handles gracefully', () => {
    const state = { role: 'builder' };
    const banner = mod.roleBanner(state);
    assert(banner.includes('unknown'), 'should show unknown project when protocolData missing');
  });
})();

// ── Tests: loadEnvFile() ─────────────────────────────────────────────────

(function() {
  resetMockFs();
  installMocks();

  const mod = reloadModule();

  test('loadEnvFile: basic parse', () => {
    _mockFs.existingFiles.add('/tmp/.env');
    _mockFs.fileContents.set('/tmp/.env', 'SYNAPSE_API_URL=http://localhost:8000\nSYNAPSE_WORKER_ID=ag_123\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.loaded === true);
    assert(result.vars.SYNAPSE_API_URL === 'http://localhost:8000');
    assert(result.vars.SYNAPSE_WORKER_ID === 'ag_123');
  });

  test('loadEnvFile: comments are ignored', () => {
    _mockFs.fileContents.set('/tmp/.env', '# This is a comment\nSYNAPSE_API_URL=http://localhost:8000\n# Another comment\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.loaded === true);
    assert(result.vars.SYNAPSE_API_URL === 'http://localhost:8000');
    assert(result.vars['# This is a comment'] === undefined);
  });

  test('loadEnvFile: blank lines are ignored', () => {
    _mockFs.fileContents.set('/tmp/.env', '\n\nSYNAPSE_API_URL=http://localhost:8000\n\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.loaded === true);
    assert(Object.keys(result.vars).length === 1);
  });

  test('loadEnvFile: double-quoted values', () => {
    _mockFs.fileContents.set('/tmp/.env', 'KEY="value with spaces"\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.vars.KEY === 'value with spaces');
  });

  test('loadEnvFile: single-quoted values', () => {
    _mockFs.fileContents.set('/tmp/.env', "KEY='single quoted'\n");
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.vars.KEY === 'single quoted');
  });

  test('loadEnvFile: inline comments after value', () => {
    _mockFs.fileContents.set('/tmp/.env', 'KEY=value # this is a comment\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.vars.KEY === 'value');
  });

  test('loadEnvFile: missing file', () => {
    const result = mod.loadEnvFile('/nonexistent/.env');
    assert(result.loaded === false);
    assert(result.errors.length === 0); // missing file is not an error
  });

  test('loadEnvFile: lines without = are skipped', () => {
    _mockFs.fileContents.set('/tmp/.env', 'KEY=value\nINVALID_LINE\nOTHER=123\n');
    const result = mod.loadEnvFile('/tmp/.env');
    assert(result.vars.KEY === 'value');
    assert(result.vars.OTHER === '123');
    assert(result.vars.INVALID_LINE === undefined);
  });

  restoreMocks();
})();

// ── Tests: readRoleFromCache() ───────────────────────────────────────────

(function() {
  resetMockFs();
  installMocks();

  const mod = reloadModule();

  test('readRoleFromCache: single role from cache', () => {
    _mockFs.existingFiles.add('/tmp/cache.json');
    _mockFs.fileContents.set('/tmp/cache.json', JSON.stringify({
      role_instructions: { builder: 'You are a builder.' },
    }));
    const role = mod.readRoleFromCache('/tmp/cache.json');
    assert(role === 'builder');
  });

  test('readRoleFromCache: missing file returns null', () => {
    const role = mod.readRoleFromCache('/nonexistent/cache.json');
    assert(role === null);
  });

  test('readRoleFromCache: invalid JSON returns null', () => {
    _mockFs.existingFiles.add('/tmp/bad.json');
    _mockFs.fileContents.set('/tmp/bad.json', 'not valid json{{{');
    const role = mod.readRoleFromCache('/tmp/bad.json');
    assert(role === null);
  });

  test('readRoleFromCache: multiple roles returns null (ambiguous)', () => {
    _mockFs.existingFiles.add('/tmp/cache.json');
    _mockFs.fileContents.set('/tmp/cache.json', JSON.stringify({
      role_instructions: { builder: '...', orchestrator: '...' },
    }));
    const role = mod.readRoleFromCache('/tmp/cache.json');
    assert(role === null, 'ambiguous multiple roles should return null');
  });

  test('readRoleFromCache: no role_instructions key returns null', () => {
    _mockFs.existingFiles.add('/tmp/cache.json');
    _mockFs.fileContents.set('/tmp/cache.json', JSON.stringify({ other: 'data' }));
    const role = mod.readRoleFromCache('/tmp/cache.json');
    assert(role === null);
  });

  restoreMocks();
})();

// ── Tests: getExistingSnapshotAge() ──────────────────────────────────────

(function() {
  resetMockFs();
  installMocks();

  const mod = reloadModule();

  test('getExistingSnapshotAge: missing file returns null', () => {
    const age = mod.getExistingSnapshotAge('/nonexistent/snapshot.md');
    assert(age === null);
  });

  test('getExistingSnapshotAge: fresh snapshot (< 1 min)', () => {
    const ts = new Date().toISOString();
    _mockFs.existingFiles.add('/tmp/snap.md');
    _mockFs.fileContents.set('/tmp/snap.md', `# Session State — ${ts}\nrest of content\n`);
    const age = mod.getExistingSnapshotAge('/tmp/snap.md');
    assert(age === '<1 min', `expected '<1 min' but got '${age}'`);
  });

  test('getExistingSnapshotAge: minutes-old snapshot', () => {
    const oldDate = new Date(Date.now() - 5 * 60 * 1000); // 5 min ago
    _mockFs.fileContents.set('/tmp/snap.md', `# Session State — ${oldDate.toISOString()}\ncontent\n`);
    const age = mod.getExistingSnapshotAge('/tmp/snap.md');
    assert(age === '5 min', `expected '5 min' but got '${age}'`);
  });

  test('getExistingSnapshotAge: hours-old snapshot', () => {
    const oldDate = new Date(Date.now() - 2.5 * 3600 * 1000); // 2.5 hr ago
    _mockFs.fileContents.set('/tmp/snap.md', `# Session State — ${oldDate.toISOString()}\ncontent\n`);
    const age = mod.getExistingSnapshotAge('/tmp/snap.md');
    assert(age && age.includes('hr'), `expected hours but got '${age}'`);
  });

  test('getExistingSnapshotAge: unparseable header returns null', () => {
    _mockFs.fileContents.set('/tmp/snap.md', '# No timestamp here\njust content\n');
    const age = mod.getExistingSnapshotAge('/tmp/snap.md');
    assert(age === null);
  });

  restoreMocks();
})();

// ── Tests: isExistingSnapshotHealthy() ───────────────────────────────────

(function() {
  resetMockFs();
  installMocks();

  const mod = reloadModule();

  test('isExistingSnapshotHealthy: healthy snapshot', () => {
    const today = new Date().toISOString().slice(0, 10);
    _mockFs.existingFiles.add('/tmp/snap.md');
    _mockFs.fileContents.set('/tmp/snap.md', `# Session State — ${today}T12:00:00.000Z\nAPI URL: http://localhost:8001\nProtocol: v1.0\n`);
    const healthy = mod.isExistingSnapshotHealthy('/tmp/snap.md');
    assert(healthy === true);
  });

  test('isExistingSnapshotHealthy: missing file returns false', () => {
    const healthy = mod.isExistingSnapshotHealthy('/nonexistent/snap.md');
    assert(healthy === false);
  });

  test('isExistingSnapshotHealthy: stale (different date) returns false', () => {
    _mockFs.fileContents.set('/tmp/snap.md', '# Session State — 2020-01-01T12:00:00.000Z\nAPI URL: http://localhost:8001\nProtocol: v1.0\n');
    const healthy = mod.isExistingSnapshotHealthy('/tmp/snap.md');
    assert(healthy === false, 'snapshot from different date should be unhealthy');
  });

  test('isExistingSnapshotHealthy: missing env section returns false', () => {
    const today = new Date().toISOString().slice(0, 10);
    _mockFs.fileContents.set('/tmp/snap.md', `# Session State — ${today}T12:00:00.000Z\nEnvironment incomplete\nProtocol fetch failed\n`);
    const healthy = mod.isExistingSnapshotHealthy('/tmp/snap.md');
    assert(healthy === false, 'snapshot with env errors should be unhealthy');
  });

  restoreMocks();
})();

// ── Tests: readRecentWsEvents() ──────────────────────────────────────────

(function() {
  resetMockFs();
  installMocks();

  const mod = reloadModule();

  test('readRecentWsEvents: valid JSONL returns parsed events', () => {
    _mockFs.existingFiles.add('/tmp/events.jsonl');
    _mockFs.fileContents.set('/tmp/events.jsonl',
      '{"type":"task.assigned","ts":"2026-01-01T00:00:00Z"}\n' +
      '{"type":"task.updated","ts":"2026-01-01T00:01:00Z"}\n' +
      '{"type":"verification.completed","ts":"2026-01-01T00:02:00Z"}\n'
    );
    const events = mod.readRecentWsEvents(5, '/tmp/events.jsonl');
    assert(events.length === 3, `expected 3 events, got ${events.length}`);
    assert(events[0].type === 'task.assigned');
    assert(events[2].type === 'verification.completed');
  });

  test('readRecentWsEvents: returns last N events only', () => {
    _mockFs.fileContents.set('/tmp/events.jsonl',
      '{"n":1}\n{"n":2}\n{"n":3}\n{"n":4}\n{"n":5}\n'
    );
    const events = mod.readRecentWsEvents(2, '/tmp/events.jsonl');
    assert(events.length === 2, `expected 2 events, got ${events.length}`);
    assert(events[0].n === 4);
    assert(events[1].n === 5);
  });

  test('readRecentWsEvents: missing file returns empty array', () => {
    const events = mod.readRecentWsEvents(5, '/nonexistent/events.jsonl');
    assert(Array.isArray(events));
    assert(events.length === 0);
  });

  test('readRecentWsEvents: invalid JSON lines are filtered out', () => {
    _mockFs.fileContents.set('/tmp/events.jsonl',
      '{"valid":true}\nnot json at all\n{"also":"valid"}\n'
    );
    const events = mod.readRecentWsEvents(10, '/tmp/events.jsonl');
    assert(events.length === 2, `expected 2 valid events, got ${events.length}`);
  });

  test('readRecentWsEvents: empty file returns empty array', () => {
    _mockFs.fileContents.set('/tmp/events.jsonl', '');
    const events = mod.readRecentWsEvents(5, '/tmp/events.jsonl');
    assert(events.length === 0);
  });

  test('readRecentWsEvents: default n=5 when not specified', () => {
    _mockFs.fileContents.set('/tmp/events.jsonl',
      '{"n":1}\n{"n":2}\n{"n":3}\n{"n":4}\n{"n":5}\n{"n":6}\n'
    );
    // Call without explicit n
    const events = mod.readRecentWsEvents(undefined, '/tmp/events.jsonl');
    assert(events.length === 5, `expected default 5, got ${events.length}`);
  });

  restoreMocks();
})();

// ── Summary ──────────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

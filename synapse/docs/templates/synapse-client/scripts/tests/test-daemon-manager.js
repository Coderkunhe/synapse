/**
 * P12-B28: Unit tests for daemon-manager.js — Daemon lifecycle management.
 *
 * Usage: node scripts/tests/test-daemon-manager.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Mock strategy: intercept fs, child_process, and process.kill via a shared
 * mock state object. Each test resets state and configures expected behavior.
 * Module is loaded once with mocks in place; createDaemonManager() produces
 * fresh instances per test with the same mocked builtins.
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
  unlinkSync: fs.unlinkSync,
  rmdirSync: fs.rmdirSync,
  execSync: child_process.execSync,
  spawn: child_process.spawn,
  kill: process.kill,
};

// ── Mock State ───────────────────────────────────────────────────────────

const S = {
  // fs.existsSync: path → boolean (only checked keys; default false)
  existingFiles: new Set(),
  // fs.readFileSync: path → string (throws if not in map)
  fileContents: new Map(),
  // fs.writeFileSync calls: [{path, content}]
  writeCalls: [],
  // fs.unlinkSync calls: [path]
  unlinkCalls: [],
  // process.kill: Set of PIDs that are "alive"
  alivePids: new Set(),
  // process.kill calls: [{pid, signal}]
  killCalls: [],
  // child_process.execSync results: command string → Buffer or throw
  execResults: new Map(),
  // child_process.spawn results
  nextSpawnPid: 9000,
  spawnCalls: [],
};

function resetMockState() {
  S.existingFiles.clear();
  S.fileContents.clear();
  S.writeCalls.length = 0;
  S.unlinkCalls.length = 0;
  S.alivePids.clear();
  S.killCalls.length = 0;
  S.execResults.clear();
  S.nextSpawnPid = 9000;
  S.spawnCalls.length = 0;
}

// ── Install Mocks ───────────────────────────────────────────────────────

function installMocks() {
  // Only intercept paths in mock state; delegate everything else to real fs.
  // This is critical: Node's module loader calls readFileSync internally to
  // load source files, and we must not break that.
  fs.existsSync = (p) => {
    if (S.existingFiles.has(p)) return true;
    return originals.existsSync(p);
  };
  fs.readFileSync = (p, enc) => {
    if (S.fileContents.has(p)) return S.fileContents.get(p);
    return originals.readFileSync(p, enc);
  };
  fs.writeFileSync = (p, content, enc) => {
    S.writeCalls.push({ path: p, content });
  };
  fs.unlinkSync = (p) => {
    S.unlinkCalls.push(p);
    S.existingFiles.delete(p);
  };
  fs.rmdirSync = (p) => { /* no-op in tests */ };
  fs.mkdtempSync = originals.mkdtempSync; // keep real for tmp dir creation

  child_process.execSync = (cmd, opts) => {
    // Find matching exec result
    for (const [pattern, result] of S.execResults) {
      if (cmd.includes(pattern)) {
        let value;
        if (typeof result === 'function') {
          value = result(cmd, opts);
        } else {
          value = result;
        }
        if (value instanceof Error) throw value;
        // If encoding is set, execSync returns a string; otherwise a Buffer.
        // Auto-convert Buffers to strings when encoding is specified.
        if (opts && opts.encoding && Buffer.isBuffer(value)) {
          return value.toString(opts.encoding);
        }
        return value;
      }
    }
    throw new Error(`execSync not mocked for: ${cmd.slice(0, 100)}`);
  };

  child_process.spawn = (cmd, args, opts) => {
    const pid = S.nextSpawnPid++;
    S.spawnCalls.push({ cmd, args, opts, pid });
    return {
      pid,
      unref: () => {},
      on: () => {},
    };
  };

  process.kill = (pid, signal) => {
    S.killCalls.push({ pid, signal });
    if (signal === 0 || signal === undefined || signal === 'SIGTERM' || signal === 'SIGKILL') {
      if (S.alivePids.has(pid)) {
        if (signal === 'SIGTERM' || signal === 'SIGKILL') {
          S.alivePids.delete(pid); // process dies
        }
        return; // signal 0 succeeds
      }
      if (signal === 0) {
        const err = new Error(`kill ESRCH: no such process ${pid}`);
        err.code = 'ESRCH';
        throw err;
      }
      // SIGTERM/SIGKILL on dead process — silently succeeds per POSIX
    }
  };
}

function restoreAll() {
  fs.existsSync = originals.existsSync;
  fs.readFileSync = originals.readFileSync;
  fs.writeFileSync = originals.writeFileSync;
  fs.unlinkSync = originals.unlinkSync;
  fs.rmdirSync = originals.rmdirSync;
  child_process.execSync = originals.execSync;
  child_process.spawn = originals.spawn;
  process.kill = originals.kill;
}

// ── Reload module with mocks ────────────────────────────────────────────

function reloadDaemonManager() {
  delete require.cache[require.resolve('../lib/daemon-manager')];
  return require('../lib/daemon-manager');
}

// ── Test Helpers ────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    resetMockState();
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

// ── Setup ────────────────────────────────────────────────────────────────

installMocks();
const { createDaemonManager } = reloadDaemonManager();

const WORKER_ROOT = '/tmp/test-worker/.claude';
const SCRIPTS_DIR = '/tmp/test-worker/scripts';

function makeDM() {
  return createDaemonManager(WORKER_ROOT, SCRIPTS_DIR);
}

// ── readPidFile ──────────────────────────────────────────────────────────

test('readPidFile returns null when file does not exist', () => {
  const dm = makeDM();
  assert(dm.readPidFile('/nonexistent.pid') === null, 'should return null');
});

test('readPidFile returns parsed PID when file exists', () => {
  const pidPath = '/tmp/valid.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '  12345\n  ');
  const dm = makeDM();
  assert(dm.readPidFile(pidPath) === 12345, 'should parse PID');
});

test('readPidFile returns null when file content is not a number', () => {
  const pidPath = '/tmp/bad.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, 'not-a-pid');
  const dm = makeDM();
  assert(dm.readPidFile(pidPath) === null, 'NaN content → null');
});

test('readPidFile returns null when PID is <= 0', () => {
  const pidPath = '/tmp/zero.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '0');
  const dm = makeDM();
  assert(dm.readPidFile(pidPath) === null, 'PID 0 → null');
});

test('readPidFile returns null when PID is negative', () => {
  const pidPath = '/tmp/neg.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '-5');
  const dm = makeDM();
  assert(dm.readPidFile(pidPath) === null, 'negative PID → null');
});

test('readPidFile returns null on read error', () => {
  // file exists but readFileSync throws (permission error, etc.)
  const pidPath = '/tmp/locked.pid';
  S.existingFiles.add(pidPath);
  // not adding to fileContents → readFileSync throws ENOENT
  const dm = makeDM();
  assert(dm.readPidFile(pidPath) === null, 'read error → null');
});

// ── writePidFile ────────────────────────────────────────────────────────

test('writePidFile writes PID to file', () => {
  const dm = makeDM();
  const pidPath = '/tmp/test.pid';
  dm.writePidFile(pidPath, 12345);
  const writeCall = S.writeCalls.find(c => c.path === pidPath);
  assert(writeCall !== undefined, 'should write to pid file');
  assert(writeCall.content === '12345', 'should write PID as string');
});

// ── isProcessAlive ──────────────────────────────────────────────────────

test('isProcessAlive returns true when process.kill(pid, 0) succeeds', () => {
  S.alivePids.add(9999);
  const dm = makeDM();
  assert(dm.isProcessAlive(9999) === true, 'should be alive');
});

test('isProcessAlive returns false when process.kill(pid, 0) throws ESRCH', () => {
  // PID not in alivePids → kill(pid, 0) throws
  const dm = makeDM();
  assert(dm.isProcessAlive(8888) === false, 'should be dead');
});

// ── killOldDaemon ───────────────────────────────────────────────────────

test('killOldDaemon returns no-op when PID file does not exist', () => {
  const dm = makeDM();
  const result = dm.killOldDaemon('/tmp/no-pid.pid');
  assert(result.killed === false, 'not killed');
  assert(result.oldPid === null, 'no old PID');
});

test('killOldDaemon cleans stale PID file when process is dead', () => {
  const pidPath = '/tmp/stale.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '7777');
  // PID 7777 not in alivePids → dead
  const dm = makeDM();
  const result = dm.killOldDaemon(pidPath);
  assert(result.killed === false, 'dead process not killed');
  assert(result.oldPid === 7777, 'old PID reported');
  // Should unlink the stale PID file
  assert(S.unlinkCalls.includes(pidPath), 'stale PID file should be removed');
});

test('killOldDaemon kills running process with SIGTERM, then SIGKILL if still alive', () => {
  const pidPath = '/tmp/running.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '5555');
  S.alivePids.add(5555); // process is alive

  const dm = makeDM();
  const result = dm.killOldDaemon(pidPath);
  assert(result.killed === true, 'should be killed');
  assert(result.oldPid === 5555, 'old PID reported');

  // Should have sent SIGTERM
  const sigtermCall = S.killCalls.find(c => c.pid === 5555 && c.signal === 'SIGTERM');
  assert(sigtermCall !== undefined, 'SIGTERM should be sent');
  // PID file should be unlinked (in finally block)
  assert(S.unlinkCalls.includes(pidPath), 'PID file should be removed after kill');
});

test('killOldDaemon sends SIGKILL when SIGTERM does not kill process', () => {
  // We can't easily test the spin-wait loop (it uses Date.now() which is allowed in test context).
  // Instead, we mock process.kill to NOT remove from alivePids on SIGTERM,
  // forcing it to try SIGKILL. We temporarily override behavior.
  const pidPath = '/tmp/stubborn.pid';
  S.existingFiles.add(pidPath);
  S.fileContents.set(pidPath, '5556');
  S.alivePids.add(5556);

  // Wrap kill to keep PID alive after SIGTERM
  const originalMockKill = process.kill;
  let sigkillSent = false;
  process.kill = (pid, signal) => {
    if (pid === 5556 && signal === 'SIGTERM') {
      S.killCalls.push({ pid, signal });
      // Do NOT remove from alivePids — simulate stubborn process
      return;
    }
    if (pid === 5556 && signal === 'SIGKILL') {
      sigkillSent = true;
      S.alivePids.delete(pid);
      S.killCalls.push({ pid, signal });
      return;
    }
    originalMockKill(pid, signal);
  };

  try {
    const dm = makeDM();
    const result = dm.killOldDaemon(pidPath);
    assert(result.killed === true, 'should be killed');
    assert(sigkillSent === true, 'SIGKILL should be sent when SIGTERM fails');
  } finally {
    process.kill = originalMockKill;
  }
});

// ── checkHeartbeatDaemon ────────────────────────────────────────────────

test('checkHeartbeatDaemon returns not running when PID file missing', () => {
  const dm = makeDM();
  const result = dm.checkHeartbeatDaemon();
  assert(result.running === false, 'should not be running');
  assert(Array.isArray(result.pids), 'pids should be array');
  assert(result.pids.length === 0, 'pids should be empty');
});

test('checkHeartbeatDaemon returns running when PID file exists and process alive', () => {
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  S.existingFiles.add(hbPidPath);
  S.fileContents.set(hbPidPath, '4200');
  S.alivePids.add(4200);
  const dm = makeDM();
  const result = dm.checkHeartbeatDaemon();
  assert(result.running === true, 'should be running');
  assert(result.pids[0] === '4200', 'should report PID');
});

test('checkHeartbeatDaemon cleans up PID file when process dead', () => {
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  S.existingFiles.add(hbPidPath);
  S.fileContents.set(hbPidPath, '4300');
  // PID 4300 not in alivePids → dead
  const dm = makeDM();
  const result = dm.checkHeartbeatDaemon();
  assert(result.running === false, 'should not be running');
  assert(S.unlinkCalls.includes(hbPidPath), 'stale PID file should be cleaned');
});

// ── checkWsDaemon ───────────────────────────────────────────────────────

test('checkWsDaemon returns not running when PID file missing', () => {
  const dm = makeDM();
  const result = dm.checkWsDaemon();
  assert(result.running === false, 'should not be running');
});

test('checkWsDaemon returns running when PID file exists and process alive', () => {
  const wsPidPath = path.join(WORKER_ROOT, '.daemon-ws.pid');
  S.existingFiles.add(wsPidPath);
  S.fileContents.set(wsPidPath, '4300');
  S.alivePids.add(4300);
  const dm = makeDM();
  const result = dm.checkWsDaemon();
  assert(result.running === true, 'should be running');
});

// ── startHeartbeatDaemon ────────────────────────────────────────────────

test('startHeartbeatDaemon returns error when script not found', () => {
  // heartbeat.js path not in existingFiles → spawn not called
  const dm = makeDM();
  const result = dm.startHeartbeatDaemon();
  assert(result.started === false, 'should not start');
  assert(result.error.includes('not found'), 'should report missing script');
});

test('startHeartbeatDaemon spawns process and writes PID file', () => {
  const hbScript = path.join(SCRIPTS_DIR, 'heartbeat.js');
  S.existingFiles.add(hbScript);
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');

  const dm = makeDM();
  const result = dm.startHeartbeatDaemon();
  assert(result.started === true, 'should start');
  assert(typeof result.pid === 'number', 'should return PID');

  // Verify spawn was called
  const spawnCall = S.spawnCalls.find(c => c.cmd === process.execPath);
  assert(spawnCall !== undefined, 'spawn should be called');
  assert(spawnCall.args[0] === hbScript, 'should spawn heartbeat.js');

  // Verify PID file was written
  const writeCall = S.writeCalls.find(c => c.path === hbPidPath);
  assert(writeCall !== undefined, 'PID file should be written');
});

// ── startWsDaemon ───────────────────────────────────────────────────────

test('startWsDaemon returns error when script not found', () => {
  const dm = makeDM();
  const result = dm.startWsDaemon();
  assert(result.started === false, 'should not start');
  assert(result.error.includes('not found'), 'should report missing script');
});

test('startWsDaemon spawns process and writes PID file', () => {
  const wsScript = path.join(SCRIPTS_DIR, 'ws-daemon.js');
  S.existingFiles.add(wsScript);
  const wsPidPath = path.join(WORKER_ROOT, '.daemon-ws.pid');

  const dm = makeDM();
  const result = dm.startWsDaemon();
  assert(result.started === true, 'should start');
  assert(typeof result.pid === 'number', 'should return PID');

  const spawnCall = S.spawnCalls.find(c => c.args[0] === wsScript);
  assert(spawnCall !== undefined, 'spawn should be called with ws-daemon.js');
  assert(spawnCall.opts.detached === true, 'should spawn detached');
  assert(spawnCall.opts.stdio === 'ignore', 'should ignore stdio');

  const writeCall = S.writeCalls.find(c => c.path === wsPidPath);
  assert(writeCall !== undefined, 'PID file should be written');
});

// Note: startWsDaemon Node < 22 version check is NOT tested here because
// process.versions is a read-only getter in Node.js and cannot be mocked.
// The check is trivially correct (parseInt + comparison) and is verified
// implicitly: on Node 22+, the check passes and daemons start normally.

// ── cleanupOrphanDaemons ────────────────────────────────────────────────

test('cleanupOrphanDaemons kills orphan daemon processes', () => {
  const hbScript = path.join(SCRIPTS_DIR, 'heartbeat.js');
  const wsScript = path.join(SCRIPTS_DIR, 'ws-daemon.js');

  // Set up ps output: 3 processes, one of which is a known daemon
  S.execResults.set('ps -eo', Buffer.from(
    `  PID COMMAND\n` +
    `    1 /sbin/launchd\n` +
    ` 5000 /usr/local/bin/node ${hbScript} --session-pid 100\n` +
    ` 5001 /usr/local/bin/node ${wsScript} --session-pid 100\n`
  ));

  // PID 5000 is known (heartbeat PID file), PID 5001 is orphan (not tracked)
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  S.existingFiles.add(hbPidPath);
  S.fileContents.set(hbPidPath, '5000');
  S.alivePids.add(5000);
  // PID 5001 is alive but not tracked → orphan
  S.alivePids.add(5001);

  const dm = makeDM();
  const result = dm.cleanupOrphanDaemons();

  // PID 5001 should be killed (orphan) — check for actual kill signals, not signal-0 liveness probes
  const orphanKill = S.killCalls.find(c => c.pid === 5001 && (c.signal === 'SIGTERM' || c.signal === 'SIGKILL'));
  assert(orphanKill !== undefined, 'orphan PID 5001 should get SIGTERM');

  // PID 5000 should NOT be killed (known) — signal-0 probes from isProcessAlive are fine
  const knownTermKill = S.killCalls.find(c => c.pid === 5000 && (c.signal === 'SIGTERM' || c.signal === 'SIGKILL'));
  assert(knownTermKill === undefined, 'known PID 5000 should NOT receive SIGTERM/SIGKILL');
});

test('cleanupOrphanDaemons skips own PID', () => {
  const hbScript = path.join(SCRIPTS_DIR, 'heartbeat.js');
  const ownPid = process.pid;

  S.execResults.set('ps -eo', Buffer.from(
    `  PID COMMAND\n` +
    ` ${ownPid} /usr/local/bin/node ${hbScript} --session-pid 1\n`
  ));
  S.alivePids.add(ownPid);

  const dm = makeDM();
  const result = dm.cleanupOrphanDaemons();

  // Own PID should never be killed
  const ownKill = S.killCalls.find(c => c.pid === ownPid);
  assert(ownKill === undefined, 'own PID should never be killed');
});

test('cleanupOrphanDaemons handles ps failure gracefully', () => {
  S.execResults.set('ps -eo', new Error('ps: command not found'));

  const dm = makeDM();
  const result = dm.cleanupOrphanDaemons();
  // Should not throw; cleaned count may be 0
  assert(typeof result.cleaned === 'number', 'should return cleaned count');
});

// ── health: self-heal ───────────────────────────────────────────────────

test('health reports both daemons running when all healthy', () => {
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  const wsPidPath = path.join(WORKER_ROOT, '.daemon-ws.pid');
  S.existingFiles.add(hbPidPath);
  S.existingFiles.add(wsPidPath);
  S.fileContents.set(hbPidPath, '100');
  S.fileContents.set(wsPidPath, '200');
  S.alivePids.add(100);
  S.alivePids.add(200);

  const dm = makeDM();
  const report = dm.health();

  assert(report.heartbeat.wasRunning === true, 'heartbeat was running');
  assert(report.heartbeat.reSpawned === false, 'heartbeat should not re-spawn');
  assert(report.heartbeat.pid === '100', 'heartbeat PID should be 100');

  assert(report.wsDaemon.wasRunning === true, 'WS daemon was running');
  assert(report.wsDaemon.reSpawned === false, 'WS daemon should not re-spawn');
  assert(report.wsDaemon.pid === '200', 'WS daemon PID should be 200');
});

test('health re-spawns heartbeat daemon when dead', () => {
  const hbScript = path.join(SCRIPTS_DIR, 'heartbeat.js');
  S.existingFiles.add(hbScript);
  // heartbeat PID file does NOT exist → dead

  // WS daemon is healthy
  const wsPidPath = path.join(WORKER_ROOT, '.daemon-ws.pid');
  S.existingFiles.add(wsPidPath);
  S.fileContents.set(wsPidPath, '200');
  S.alivePids.add(200);

  const dm = makeDM();
  const report = dm.health();

  assert(report.heartbeat.wasRunning === false, 'heartbeat was not running');
  assert(report.heartbeat.reSpawned === true, 'heartbeat should re-spawn');
  assert(typeof report.heartbeat.pid === 'string', 'should have new PID');

  assert(report.wsDaemon.wasRunning === true, 'WS daemon still running');
  assert(report.wsDaemon.reSpawned === false, 'WS daemon should not re-spawn');
});

test('health re-spawns WS daemon when dead', () => {
  const wsScript = path.join(SCRIPTS_DIR, 'ws-daemon.js');
  S.existingFiles.add(wsScript);
  // WS PID file does NOT exist → dead

  // Heartbeat is healthy
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  S.existingFiles.add(hbPidPath);
  S.fileContents.set(hbPidPath, '100');
  S.alivePids.add(100);

  const dm = makeDM();
  const report = dm.health();

  assert(report.heartbeat.wasRunning === true, 'heartbeat still running');
  assert(report.wsDaemon.wasRunning === false, 'WS daemon was not running');
  assert(report.wsDaemon.reSpawned === true, 'WS daemon should re-spawn');
});

test('health re-spawns both daemons when both dead', () => {
  const hbScript = path.join(SCRIPTS_DIR, 'heartbeat.js');
  const wsScript = path.join(SCRIPTS_DIR, 'ws-daemon.js');
  S.existingFiles.add(hbScript);
  S.existingFiles.add(wsScript);
  // Neither PID file exists → both dead

  const dm = makeDM();
  const report = dm.health();

  assert(report.heartbeat.reSpawned === true, 'heartbeat should re-spawn');
  assert(report.wsDaemon.reSpawned === true, 'WS daemon should re-spawn');
});

test('health updates session-alive file', () => {
  // Both daemons healthy
  const hbPidPath = path.join(WORKER_ROOT, '.daemon-heartbeat.pid');
  const wsPidPath = path.join(WORKER_ROOT, '.daemon-ws.pid');
  S.existingFiles.add(hbPidPath);
  S.existingFiles.add(wsPidPath);
  S.fileContents.set(hbPidPath, '100');
  S.fileContents.set(wsPidPath, '200');
  S.alivePids.add(100);
  S.alivePids.add(200);

  const dm = makeDM();
  const report = dm.health();

  assert(report.sessionAlive !== null, 'sessionAlive should be set');
  // Verify it's a valid ISO timestamp
  const ts = new Date(report.sessionAlive);
  assert(!isNaN(ts.getTime()), 'sessionAlive should be valid ISO date');

  // Verify session-alive file was written
  const alivePath = path.join(WORKER_ROOT, '.session-alive');
  const aliveWrite = S.writeCalls.find(c => c.path === alivePath);
  assert(aliveWrite !== undefined, 'session-alive file should be written');
  const aliveData = JSON.parse(aliveWrite.content);
  assert(aliveData.mode === 'health', 'should have health mode');
  assert(typeof aliveData.updated_at === 'string', 'should have timestamp');
});

// ── Path properties ─────────────────────────────────────────────────────

test('daemon manager exposes correct PID file paths', () => {
  const dm = makeDM();
  assert(dm.HEARTBEAT_PID_FILE.includes('.daemon-heartbeat.pid'), 'heartbeat PID path');
  assert(dm.WS_DAEMON_PID_FILE.includes('.daemon-ws.pid'), 'WS PID path');
  assert(dm.SESSION_ALIVE_FILE.includes('.session-alive'), 'session alive path');
});

// ── Cleanup ─────────────────────────────────────────────────────────────

restoreAll();

// ── Summary ─────────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

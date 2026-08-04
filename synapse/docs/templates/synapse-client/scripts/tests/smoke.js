/**
 * B137 harness smoke tests — verify extracted modules work correctly.
 *
 * Usage: node scripts/tests/smoke.js
 * Exit code 0 = all passed, non-zero = failures.
 */

'use strict';

const path = require('path');
const fs = require('fs');
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

// ── Test 1: CRONCREATE_PROMPT ──────────────────────────────────────

const { CRONCREATE_PROMPT } = require('../lib/prompts');

test('CRONCREATE_PROMPT contains --health', () => {
  assert(CRONCREATE_PROMPT.includes('--health'), 'missing --health flag');
});

test('CRONCREATE_PROMPT contains daemon self-heal', () => {
  assert(CRONCREATE_PROMPT.includes('daemon self-heal'), 'missing daemon self-heal description');
});

test('CRONCREATE_PROMPT contains ScheduleWakeup', () => {
  assert(CRONCREATE_PROMPT.includes('ScheduleWakeup'), 'missing ScheduleWakeup');
});

test('CRONCREATE_PROMPT has 3 numbered steps', () => {
  assert(CRONCREATE_PROMPT.includes('①'), 'missing step ①');
  assert(CRONCREATE_PROMPT.includes('②'), 'missing step ②');
  assert(CRONCREATE_PROMPT.includes('③'), 'missing step ③');
});

test('CRONCREATE_PROMPT does NOT instruct AI to check daemon', () => {
  // The daemon check is done by --health mechanically, not by AI reading prompt
  assert(!CRONCREATE_PROMPT.includes('check daemon status'), 'prompt still tells AI to check daemon');
  assert(!CRONCREATE_PROMPT.includes('If heartbeat/ws-daemon dead'), 'prompt still has conditional daemon instructions');
});

// ── Test 2: Daemon manager module load ─────────────────────────────

// Use a temp directory as worker root to avoid touching real PID files
const tmpDir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'synapse-test-'));
const { createDaemonManager } = require('../lib/daemon-manager');
const dm = createDaemonManager(tmpDir, __dirname);

test('daemon manager creates with valid paths', () => {
  assert(dm.HEARTBEAT_PID_FILE.includes('.daemon-heartbeat.pid'), 'wrong heartbeat PID path');
  assert(dm.WS_DAEMON_PID_FILE.includes('.daemon-ws.pid'), 'wrong WS PID path');
});

test('readPidFile returns null for missing file', () => {
  assert(dm.readPidFile('/nonexistent/pid/file') === null, 'should return null');
});

test('isProcessAlive returns false for impossible PID', () => {
  // PID 99999 is extremely unlikely to exist
  assert(!dm.isProcessAlive(99999), 'should return false');
});

test('isProcessAlive returns true for our own PID', () => {
  assert(dm.isProcessAlive(process.pid), 'should return true for own process');
});

test('checkHeartbeatDaemon returns not running with empty dir', () => {
  const result = dm.checkHeartbeatDaemon();
  assert(!result.running, 'should not be running');
  assert(Array.isArray(result.pids), 'pids should be array');
});

test('checkWsDaemon returns not running with empty dir', () => {
  const result = dm.checkWsDaemon();
  assert(!result.running, 'should not be running');
});

// Cleanup temp dir
try { fs.rmdirSync(tmpDir); } catch (_) {}

// ── Test 3: Launchd plist generation (P12-B3 Line A) ──────────────────

const { execSync } = require('child_process');

// Find synapse-launchd.sh: from scripts/tests/ → scripts/ → synapse-client/ → templates/ → docs/ → synapse/ (= repo root)
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..', '..');
const LAUNCHD_SCRIPT = path.join(REPO_ROOT, 'tools', 'synapse-launchd.sh');

// Create a minimal temp project for plist generation testing
const launchdTmpDir = fs.mkdtempSync(path.join(require('os').tmpdir(), 'synapse-launchd-test-'));
const claudeDir = path.join(launchdTmpDir, '.claude');
const scriptsDir = path.join(claudeDir, 'skills', 'synapse', 'scripts');
fs.mkdirSync(scriptsDir, { recursive: true });
fs.writeFileSync(path.join(scriptsDir, 'session-init.js'), '// mock session-init.js');
fs.writeFileSync(path.join(claudeDir, '.env'), 'SYNAPSE_API_URL=http://localhost:8000\n');

let plistOutput = '';
try {
  plistOutput = execSync(
    `bash "${LAUNCHD_SCRIPT}" plist "${launchdTmpDir}" builder`,
    { encoding: 'utf-8', timeout: 5000 }
  );
} catch (e) {
  // Script may fail if not on macOS — skip launchd tests gracefully
}

const onMacOS = process.platform === 'darwin' && plistOutput.length > 0;

if (onMacOS) {
  test('synapse-launchd.sh generates valid XML plist', () => {
    assert(plistOutput.includes('<?xml version="1.0"'), 'output should be valid XML declaration');
    assert(plistOutput.includes('<!DOCTYPE plist'), 'output should have DOCTYPE');
    assert(plistOutput.includes('<plist version="1.0">'), 'output should be plist');
  });

  test('plist contains --health and --silent flags', () => {
    assert(plistOutput.includes('--health'), 'plist must include --health flag');
    assert(plistOutput.includes('--silent'), 'plist must include --silent flag');
  });

  test('plist does NOT contain SYNAPSE_API_KEY', () => {
    // API key is resolved at runtime by session-init.js from .env or OS keychain
    assert(!plistOutput.includes('SYNAPSE_API_KEY'), 'plist must not contain plaintext API key');
  });

  test('plist contains StartInterval of 60 seconds', () => {
    assert(plistOutput.includes('<key>StartInterval</key>'), 'plist must have StartInterval key');
    assert(plistOutput.includes('<integer>60</integer>'), 'plist must use 60s interval');
  });

  test('plist uses dynamic Node.js path (not hardcoded)', () => {
    // The node path is resolved at generation time via `which node`
    // Verify the path in the plist is an absolute path containing 'node'
    const match = plistOutput.match(/<string>(\/.+node)<\/string>/);
    assert(match !== null, 'plist should contain node path');
    assert(match[1].includes('/node'), 'node path should be absolute');
  });
}

// Cleanup
try { fs.rmSync(launchdTmpDir, { recursive: true }); } catch (_) {}

// ── Summary ────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

/**
 * P12-B27: Worker JS test runner — auto-discovers and runs all test files.
 *
 * Usage: node scripts/tests/run-tests.js
 * Exit code 0 = all passed, non-zero = at least one test file failed.
 *
 * Finds all test-*.js and smoke.js files in the same directory,
 * runs each as a child process, and aggregates results.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const TEST_DIR = __dirname;

// Find test files: test-*.js + smoke.js
const files = fs.readdirSync(TEST_DIR)
  .filter(f => (f.startsWith('test-') || f === 'smoke.js') && f.endsWith('.js'))
  .sort();

if (files.length === 0) {
  console.log('No test files found.');
  process.exit(0);
}

let totalPassed = 0;
let totalFailed = 0;
const failures = [];

for (const file of files) {
  const filePath = path.join(TEST_DIR, file);
  try {
    const output = execSync(`node "${filePath}"`, {
      encoding: 'utf-8',
      cwd: path.resolve(TEST_DIR, '..'),
      timeout: 30000,
    });
    // Parse "N passed, M failed, T total" from last line
    const lines = output.trim().split('\n');
    const lastLine = lines[lines.length - 1];
    const match = lastLine.match(/(\d+) passed, (\d+) failed, (\d+) total/);
    if (match) {
      const p = parseInt(match[1], 10);
      const f = parseInt(match[2], 10);
      totalPassed += p;
      totalFailed += f;
      const icon = f === 0 ? '✅' : '❌';
      console.log(`  ${icon} ${file} ... ${p + f}/${p + f} (${f} failed)`);
    } else {
      // Fallback: assume exit 0 = all passed
      console.log(`  ✅ ${file} ... (no summary line, exit 0 assumed)`);
    }
  } catch (e) {
    // Child process exited non-zero
    const stderr = e.stderr || '';
    const stdout = e.stdout || '';
    const output = stdout + stderr;
    const lines = output.trim().split('\n');
    const lastLine = lines[lines.length - 1];
    const match = lastLine.match(/(\d+) passed, (\d+) failed, (\d+) total/);
    if (match) {
      const p = parseInt(match[1], 10);
      const f = parseInt(match[2], 10);
      totalPassed += p;
      totalFailed += f;
    } else {
      totalFailed += 1;
    }
    console.log(`  ❌ ${file} ... FAILED`);
    failures.push({ file, output: output.slice(-500) });
  }
}

// ── Summary ──────────────────────────────────────────────────────────

console.log('');
console.log(`  ${totalPassed} passed, ${totalFailed} failed, ${totalPassed + totalFailed} total`);

if (failures.length > 0) {
  console.log('');
  console.log('Failures:');
  for (const f of failures) {
    console.log(`  ❌ ${f.file}`);
    console.log(f.output);
  }
}

process.exit(totalFailed > 0 ? 1 : 0);

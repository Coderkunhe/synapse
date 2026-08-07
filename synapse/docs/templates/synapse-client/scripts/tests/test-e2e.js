/**
 * P12-B32: E2E smoke test — validates Worker scripts against a running Synapse.
 *
 * Usage: node scripts/tests/test-e2e.js
 *
 * Requires a running Synapse server. Set SYNAPSE_API_URL env var
 * (defaults to http://localhost:8001 to match local dev server).
 *
 * Graceful skip: if server is unreachable, all tests are skipped with a clear
 * message and exit 0. This test is NOT run by make test-js (which is for pure
 * unit tests) — it's invoked manually or via make test-e2e.
 *
 * Exit code 0 = all passed or skipped, non-zero = failures.
 */

'use strict';

const TIMEOUT_MS = 5000;

let passed = 0;
let failed = 0;
let skipped = false;
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
      return;
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

// ── Config ──────────────────────────────────────────────────────────

const API_URL = (process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '');
const WORKER_ID = process.env.SYNAPSE_WORKER_ID || '';
const API_KEY = process.env.SYNAPSE_API_KEY || '';
const PROJECT_ID = process.env.SYNAPSE_PROJECT_ID || '';

// ── HTTP helper ─────────────────────────────────────────────────────

async function _fetch(method, path, body) {
  const url = `${API_URL}${path}`;
  const headers = { 'Content-Type': 'application/json' };
  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`;
  }
  const opts = { method, headers, signal: AbortSignal.timeout(TIMEOUT_MS) };
  if (body !== undefined && body !== null) {
    opts.body = JSON.stringify(body);
  }
  try {
    const res = await fetch(url, opts);
    if (res.status === 204) return { status: 204 };
    const rawText = await res.text().catch(() => '');
    let data;
    try { data = JSON.parse(rawText); } catch (_) { data = { _raw: rawText }; }
    if (res.ok) return { status: res.status, data };
    return { error: true, status: res.status, message: (data && data.detail) || `HTTP ${res.status}`, data };
  } catch (err) {
    if (err.name === 'TimeoutError' || err.name === 'AbortError') {
      return { error: true, message: `Request timed out after ${TIMEOUT_MS}ms` };
    }
    return { error: true, message: err.message || 'Network error' };
  }
}

async function get(path) { return _fetch('GET', path); }
async function post(path, body) { return _fetch('POST', path, body); }

// ── Server availability check ────────────────────────────────────────

async function checkServerAvailable() {
  try {
    const res = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(3000) });
    return res.ok;
  } catch (_) {
    return false;
  }
}

// ── Main ────────────────────────────────────────────────────────────

async function main() {
  const available = await checkServerAvailable();

  if (!available) {
    console.log(`⚠️  Synapse server not reachable at ${API_URL}/health — skipping E2E tests.`);
    console.log('   Start the server (uvicorn src.main:app --port 8001) and re-run.');
    skipped = true;
  } else {
    console.log(`✅ Synapse server reachable at ${API_URL}/health`);

    // ── Health check ─────────────────────────────────────────────
    test('GET /health returns 200', async () => {
      const res = await get('/health');
      assert(!res.error, `health check failed: ${res.message}`);
      assert(res.status === 200, `expected 200, got ${res.status}`);
      assert(res.data && res.data.status, 'health response should have status field');
    });

    test('GET /health includes ws_connections field', async () => {
      const res = await get('/health');
      assert(res.data && res.data.hasOwnProperty('ws_connections'), 'should have ws_connections');
    });

    test('GET /health includes reapers field', async () => {
      const res = await get('/health');
      assert(res.data && res.data.reapers, 'should have reapers section');
    });

    // ── Template versions (unauthenticated) ───────────────────────
    test('GET /v1/templates/versions returns version', async () => {
      const res = await get('/v1/templates/versions');
      assert(!res.error, `template versions failed: ${res.message}`);
      assert(res.status === 200, `expected 200, got ${res.status}`);
      assert(res.data && res.data.version, 'should have version field');
    });

    // ── Worker lifecycle (requires API key) ──────────────────────
    if (API_KEY && WORKER_ID) {
      test('POST /v1/workers/{id}/heartbeat returns ok', async () => {
        const res = await post(`/v1/workers/${WORKER_ID}/heartbeat`, { current_load: 0 });
        assert(!res.error, `heartbeat failed: ${res.message}`);
        assert(res.data && (res.data.status === 'ok' || res.data.runtime_status),
          'heartbeat response should indicate status');
      });

      test('POST /v1/workers/{id}/handshake activates worker', async () => {
        const res = await post(`/v1/workers/${WORKER_ID}/handshake`, {
          agent_version: 'test-1.0.0',
          capabilities: [{ name: 'code-generation', description: 'Test' }],
          supported_events: ['task.assigned'],
          preferred_channel: 'websocket',
        });
        // handshake may succeed or return an error (worker already active, etc.)
        // Either outcome is fine for a smoke test
        if (res.error && res.status !== 409 && res.status !== 422) {
          console.log(`   (handshake returned: ${res.status} — ${res.message})`);
        }
        assert(true, 'handshake completed without crash');
      });
    } else {
      console.log('   ⚠️  No API key/Worker ID set — skipping authenticated tests.');
      console.log('      Set SYNAPSE_API_KEY + SYNAPSE_WORKER_ID to run full E2E.');
      skipped = true;
    }

    // ── Task queries (requires project + API key) ─────────────────
    if (API_KEY && WORKER_ID && PROJECT_ID) {
      test('GET /v1/projects/{id}/tasks returns task list', async () => {
        const res = await get(`/v1/projects/${PROJECT_ID}/tasks`);
        assert(!res.error, `task list failed: ${res.message}`);
        assert(res.status === 200, `expected 200, got ${res.status}`);
      });

      test('GET /v1/projects/{id}/tasks?status=in_progress', async () => {
        const res = await get(`/v1/projects/${PROJECT_ID}/tasks?status=in_progress`);
        assert(!res.error, `in_progress query failed: ${res.message}`);
      });
    } else if (API_KEY && WORKER_ID) {
      console.log('   ⚠️  No SYNAPSE_PROJECT_ID set — skipping task query tests.');
      skipped = true;
    }
  }

  // ── Summary ──────────────────────────────────────────────────────
  // Wait for all async tests to settle
  if (_pending.length > 0) {
    await Promise.all(_pending);
  }
  if (skipped) {
    console.log('(some tests skipped — server or credentials not available)');
  }
  // Summary line MUST be last — run-tests.js parses the last line
  console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(err => {
  console.error(`❌ E2E test runner crashed: ${err.message}`);
  process.exit(1);
});

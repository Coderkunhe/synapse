/**
 * P12-B27: Unit tests for api-client.js — Synapse Worker HTTP client.
 *
 * Usage: node scripts/tests/test-api-client.js
 * Exit code 0 = all passed, non-zero = failures.
 *
 * Tests cover: resolveConfig (static), constructor, _request success/error paths.
 * Mock strategy: global.fetch is mocked inline (save/restore).
 * Keychain: tested via resolveConfig with direct apiKey (bypasses keychain module).
 */

'use strict';

const { SynapseClient } = require('../api-client');

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

// ── Test 1: resolveConfig (static method) ────────────────────────────

test('resolveConfig with no env returns defaults', () => {
  const cfg = SynapseClient.resolveConfig({});
  assert(cfg.apiUrl === 'http://127.0.0.1:8001', 'default apiUrl');
  assert(cfg.workerId === '', 'default workerId empty');
  assert(cfg.apiKey === '', 'default apiKey empty');
  assert(cfg.timeout === 10000, 'resolveConfig timeout is 10000');
});

test('resolveConfig strips trailing slash from apiUrl', () => {
  const cfg = SynapseClient.resolveConfig({
    SYNAPSE_API_URL: 'http://example.com:8001/',
  });
  assert(cfg.apiUrl === 'http://example.com:8001', 'trailing slash stripped');
});

test('resolveConfig uses SYNAPSE_API_KEY from env directly', () => {
  const cfg = SynapseClient.resolveConfig({
    SYNAPSE_API_KEY: 'sk-test-key-123',
    SYNAPSE_WORKER_ID: 'ag_test123',
  });
  assert(cfg.apiKey === 'sk-test-key-123', 'apiKey from env');
});

test('resolveConfig falls back to keychain when apiKey absent but workerId present', () => {
  // getKey will return null for a fake workerId (no key stored in keychain)
  const cfg = SynapseClient.resolveConfig({
    SYNAPSE_WORKER_ID: 'ag_nonexistent_worker_99999',
  });
  // apiKey should be '' because keychain returns null for unknown worker
  assert(cfg.apiKey === '', 'apiKey empty when keychain returns null');
  assert(cfg.workerId === 'ag_nonexistent_worker_99999', 'workerId preserved');
});

test('resolveConfig skips keychain when both apiKey and workerId absent', () => {
  const cfg = SynapseClient.resolveConfig({
    SYNAPSE_API_URL: 'http://127.0.0.1:8001',
  });
  assert(cfg.apiKey === '', 'no apiKey');
  assert(cfg.workerId === '', 'no workerId');
});

// ── Test 2: Constructor ──────────────────────────────────────────────

test('constructor with valid config normalizes apiUrl', () => {
  const client = new SynapseClient({
    apiUrl: 'http://example.com:8001/',
    workerId: 'ag_test',
    apiKey: 'sk-key',
  });
  assert(client.apiUrl === 'http://example.com:8001', 'trailing slash stripped');
  assert(client.workerId === 'ag_test', 'workerId set');
  assert(client.apiKey === 'sk-key', 'apiKey set');
});

test('constructor defaults timeout to 5000', () => {
  const client = new SynapseClient({ apiUrl: 'http://x.com' });
  assert(client.timeout === 5000, 'default timeout 5000');
});

test('constructor defaults timeout when 0 is passed', () => {
  const client = new SynapseClient({ apiUrl: 'http://x.com', timeout: 0 });
  assert(client.timeout === 5000, '0 falls through || to default 5000');
});

test('constructor throws when apiUrl is missing', () => {
  let threw = false;
  try {
    new SynapseClient({});
  } catch (e) {
    threw = true;
    assert(e.message.includes('apiUrl is required'), 'correct error message');
  }
  assert(threw, 'should throw on missing apiUrl');
});

// ── Test 3: _request success paths ───────────────────────────────────

let originalFetch;

function mockFetch(responseFactory) {
  originalFetch = global.fetch;
  global.fetch = responseFactory;
}

function restoreFetch() {
  global.fetch = originalFetch;
}

const BASE_CONFIG = { apiUrl: 'http://127.0.0.1:8001', workerId: 'ag_test', apiKey: 'sk-test' };

test('_request returns { status, data } on 200 JSON response', async () => {
  mockFetch(async (url, opts) => ({
    status: 200,
    ok: true,
    text: async () => JSON.stringify({ id: 'tsk_001', title: 'Test' }),
  }));
  try {
    const client = new SynapseClient(BASE_CONFIG);
    const res = await client.get('/v1/tasks/tsk_001');
    assert(res.status === 200, 'status 200');
    assert(res.data.id === 'tsk_001', 'data parsed');
  } finally {
    restoreFetch();
  }
});

test('_request returns { status: 204 } on 204 No Content', async () => {
  mockFetch(async (url, opts) => ({
    status: 204,
    ok: true,
  }));
  try {
    const client = new SynapseClient(BASE_CONFIG);
    const res = await client.post('/v1/workers/me/heartbeat', { load: 0 });
    assert(res.status === 204, 'status 204');
    assert(res.data === undefined, 'no data key on 204');
  } finally {
    restoreFetch();
  }
});

test('_request includes Authorization header when apiKey is set', async () => {
  let capturedHeaders;
  mockFetch(async (url, opts) => {
    capturedHeaders = opts.headers;
    return { status: 200, ok: true, text: async () => '{}' };
  });
  try {
    const client = new SynapseClient(BASE_CONFIG);
    await client.get('/health');
    assert(capturedHeaders['Authorization'] === 'Bearer sk-test', 'auth header present');
  } finally {
    restoreFetch();
  }
});

test('_request omits Authorization header when apiKey is empty', async () => {
  let capturedHeaders;
  mockFetch(async (url, opts) => {
    capturedHeaders = opts.headers;
    return { status: 200, ok: true, text: async () => '{}' };
  });
  try {
    const client = new SynapseClient({ apiUrl: 'http://127.0.0.1:8001' });
    await client.get('/health');
    assert(!capturedHeaders['Authorization'], 'no auth header when apiKey empty');
  } finally {
    restoreFetch();
  }
});

// ── Test 4: _request error handling ──────────────────────────────────

test('_request returns structured error on 404 with detail', async () => {
  mockFetch(async (url, opts) => ({
    status: 404,
    ok: false,
    text: async () => JSON.stringify({ detail: 'Task not found' }),
  }));
  try {
    const client = new SynapseClient(BASE_CONFIG);
    const res = await client.get('/v1/tasks/tsk_missing');
    assert(res.error === true, 'error flag');
    assert(res.status === 404, 'status 404');
    assert(res.message === 'Task not found', 'detail as message');
  } finally {
    restoreFetch();
  }
});

test('_request returns structured error on network failure', async () => {
  mockFetch(async (url, opts) => {
    throw new Error('connect ECONNREFUSED 127.0.0.1:8001');
  });
  try {
    const client = new SynapseClient(BASE_CONFIG);
    const res = await client.get('/health');
    assert(res.error === true, 'error flag');
    assert(res.message.includes('ECONNREFUSED'), 'network error message preserved');
  } finally {
    restoreFetch();
  }
});

test('_request returns timeout message on AbortError', async () => {
  mockFetch(async (url, opts) => {
    const err = new Error('The operation was aborted');
    err.name = 'AbortError';
    throw err;
  });
  try {
    const client = new SynapseClient({ ...BASE_CONFIG, timeout: 3000 });
    const res = await client.get('/health');
    assert(res.error === true, 'error flag');
    assert(res.message.includes('timed out after 3000ms'), 'timeout message with correct ms');
  } finally {
    restoreFetch();
  }
});

// ── Summary ──────────────────────────────────────────────────────────

console.log(`\n${passed} passed, ${failed} failed, ${passed + failed} total`);
process.exit(failed > 0 ? 1 : 0);

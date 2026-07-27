/**
 * api-client.js — Shared HTTP/auth client for Synapse Worker scripts.
 *
 * Zero dependencies — uses Node.js ≥18 built-in `fetch`.
 * Designed for Worker-side scripts (heartbeat, fetch-task, sync-status).
 * Errors are returned as structured objects, never thrown — Worker scripts
 * must not be blocked by network issues.
 *
 * @module api-client
 */

/**
 * @typedef {Object} SynapseClientConfig
 * @property {string}  apiUrl   — Synapse instance base URL (e.g. http://127.0.0.1:8001)
 * @property {string}  workerId — Worker ID registered with Synapse
 * @property {string}  apiKey   — Bearer token for API authentication
 * @property {number}  [timeout=5000] — Request timeout in milliseconds
 */

/**
 * @typedef {Object} SynapseResponse
 * @property {boolean} [error]   — Present and true when the request failed
 * @property {string}  [message] — Human-readable error description
 * @property {number}  [status]  — HTTP status code (when server responded)
 * @property {*}       [data]    — Parsed response body (when successful)
 */

/**
 * Lightweight HTTP client for Synapse Worker scripts.
 *
 * Usage:
 *   const client = new SynapseClient({
 *     apiUrl:   process.env.SYNAPSE_API_URL || 'http://127.0.0.1:8001',
 *     workerId: process.env.SYNAPSE_WORKER_ID,
 *     apiKey:   process.env.SYNAPSE_API_KEY,
 *   });
 *   const res = await client.post('/v1/workers/me/heartbeat', { current_load: 0 });
 */
class SynapseClient {
  /**
   * @param {SynapseClientConfig} config
   */
  constructor(config) {
    if (!config.apiUrl) {
      throw new Error('SynapseClient: apiUrl is required');
    }
    /** @type {string} */
    this.apiUrl = config.apiUrl.replace(/\/+$/, ''); // strip trailing slash
    /** @type {string} */
    this.workerId = config.workerId || '';
    /** @type {string} */
    this.apiKey = config.apiKey || '';
    /** @type {number} */
    this.timeout = config.timeout || 5000;
  }

  /**
   * GET request.
   * @param {string} path — URL path (e.g. '/health', '/v1/workers/me')
   * @returns {Promise<SynapseResponse>}
   */
  async get(path) {
    return this._request('GET', path);
  }

  /**
   * POST request.
   * @param {string} path  — URL path
   * @param {Object} [body] — Request body (serialized as JSON)
   * @returns {Promise<SynapseResponse>}
   */
  async post(path, body) {
    return this._request('POST', path, body);
  }

  /**
   * PATCH request.
   * @param {string} path  — URL path
   * @param {Object} [body] — Request body (serialized as JSON)
   * @returns {Promise<SynapseResponse>}
   */
  async patch(path, body) {
    return this._request('PATCH', path, body);
  }

  /**
   * Internal request executor.
   * @param {string} method — HTTP method
   * @param {string} path   — URL path
   * @param {Object} [body] — Optional request body
   * @returns {Promise<SynapseResponse>}
   */
  async _request(method, path, body) {
    const url = `${this.apiUrl}${path}`;
    const headers = {
      'Content-Type': 'application/json',
    };

    if (this.apiKey) {
      headers['Authorization'] = `Bearer ${this.apiKey}`;
    }

    const opts = {
      method,
      headers,
      signal: AbortSignal.timeout(this.timeout),
    };

    if (body !== undefined && body !== null) {
      opts.body = JSON.stringify(body);
    }

    try {
      const res = await fetch(url, opts);

      // 204 No Content — no body to parse
      if (res.status === 204) {
        return { status: 204 };
      }

      // Read body as text first, then try to parse as JSON.
      // Must read text() before attempting JSON.parse() — res.json()
      // consumes the body stream, so res.text() would fail after it.
      let data;
      const rawText = await res.text().catch(() => '');
      try {
        data = JSON.parse(rawText);
      } catch (_) {
        // Response body is not valid JSON — preserve raw text
        data = { _raw: rawText };
      }

      if (res.ok) {
        return { status: res.status, data };
      }

      // Non-2xx — return structured error, don't throw
      const errMsg =
        (data && data.detail) ||
        (data && data.error && data.error.message) ||
        `HTTP ${res.status}`;
      return { error: true, status: res.status, message: errMsg, data };
    } catch (err) {
      // Network error, timeout (AbortError), DNS failure, etc.
      if (err.name === 'TimeoutError' || err.name === 'AbortError') {
        return { error: true, message: `Request timed out after ${this.timeout}ms` };
      }
      return { error: true, message: err.message || 'Network error' };
    }
  }
}

module.exports = { SynapseClient };

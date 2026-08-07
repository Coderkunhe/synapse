/**
 * session-core.js — Pure logic extracted from session-init.js for testability.
 *
 * Every function is stateless: all external inputs (filesystem) come through
 * parameters rather than hardcoded module-level constants from session-init.js.
 *
 * @version 1.0.0 — P12-B32 extraction
 * @file session-core.js
 */

'use strict';

const fs = require('fs');

// ── Helpers ─────────────────────────────────────────────────────────

/**
 * Current ISO timestamp.
 * @returns {string}
 */
function now() {
  return new Date().toISOString();
}

// ── P11-B129 (PFL-124): Ownership Labels ────────────────────────────

/**
 * Generate deterministic ownership label for a task.
 *
 * This is a DATA TRANSFORMATION — not a prompt hint. The script compares
 * task.owner_id against the Worker's own ID and produces an unambiguous label.
 * The AI doesn't need to "remember" its identity — the data already tells it.
 *
 * Returns one of:
 *   "🫵 YOU"                        — this task belongs to the current Worker
 *   "owner: <name> (NOT YOU)"       — belongs to another Worker
 *   "owner: <name>"                 — belongs to a Human/Member
 *   "unassigned"                    — no owner
 *   ""                              — owner data not available
 *
 * @param {object} task — task object from API (has owner_id, owner_type, owner_name)
 * @param {string} myWorkerId — the current Worker's ID (SYNAPSE_WORKER_ID)
 * @returns {string}
 */
function ownerLabel(task, myWorkerId) {
  if (!task.owner_id) return 'unassigned';
  if (!myWorkerId) return `owner: ${task.owner_name || task.owner_id}`;

  if (task.owner_id === myWorkerId) {
    return '🫵 YOU';
  }

  // Belongs to someone else — make it unambiguous
  const name = task.owner_name || task.owner_id;
  if (task.owner_type === 'worker') {
    return `owner: ${name} (NOT YOU)`;
  }
  return `owner: ${name}`;
}

// ── P12-B5: JSON Serialization ──────────────────────────────────────

/**
 * Minimal task summary for JSON output.
 *
 * @param {object} t — task object
 * @returns {{ id: string, title: string, status: string, owner_id: string|null, owner_name: string|null, depends_on: string[] }}
 */
function summarizeTask(t) {
  return {
    id: t.id,
    title: t.title || t.id,
    status: t.status,
    owner_id: t.owner_id || null,
    owner_name: t.owner_name || null,
    depends_on: t.depends_on || [],
  };
}

// ── Role Banners ────────────────────────────────────────────────────

/**
 * Generate role banner text for the AI to display.
 *
 * @param {object} state — state object with .role and .protocolData
 * @returns {string}
 */
function roleBanner(state) {
  const roleColors = { builder: '🔵', orchestrator: '🟠', steward: '⚪' };
  const emoji = roleColors[state.role] || '⚪';
  const roleName = state.role || 'unknown';
  const projectName = (state.protocolData && state.protocolData.project_name) || 'unknown';

  const roleBanners = {
    builder: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Builder`,
      `   项目: ${projectName}`,
      `   职责: 接 Task · 执行 · 收集 evidence · 提交验证`,
      `   边界: 不创建 Task · 不分配 Task · 不验收`,
    ],
    orchestrator: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Orchestrator`,
      `   项目: ${projectName}`,
      `   职责: 拆解 Task · 分配 Builder · 验收结果`,
      `   边界: 不写代码 · 不认领 Task · 不提交 evidence`,
    ],
    steward: [
      `${emoji} Synapse Worker 已连接`,
      `   角色: Steward`,
      `   项目: ${projectName}`,
      `   职责: 审查代码 · 安全检查 · 反馈意见`,
      `   边界: 不写代码 · 不创建 Task · 不验收`,
    ],
  };

  const lines = (roleBanners[state.role] || roleBanners.builder).slice();

  if (state.protocolData && state.protocolData.role_source === 'default_fallback') {
    lines.push('');
    lines.push('⚠️ 你的角色未在 Worker 元数据中配置，已默认分配为 Builder。');
    lines.push('如果这不是你的预期角色，请联系 Admin 更新 Worker 配置。');
  }

  return lines.join('\n');
}

// ── P11-B135 (PFL-127): .env File Parser ───────────────────────────

/**
 * Load and parse .env file.
 *
 * Format: KEY=VALUE, # comments, blank lines ignored.
 * Handles values with spaces, inline comments, and quoted values.
 *
 * @param {string} envPath — path to .env file
 * @returns {{ vars: object, errors: string[], loaded: boolean }}
 */
function loadEnvFile(envPath) {
  const result = { vars: {}, errors: [], loaded: false };
  try {
    if (!fs.existsSync(envPath)) {
      return result;
    }
    const raw = fs.readFileSync(envPath, 'utf-8');
    const lines = raw.split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      // Skip blank lines and comments
      if (!trimmed || trimmed.startsWith('#')) continue;
      // Parse KEY=VALUE
      const eqIdx = trimmed.indexOf('=');
      if (eqIdx === -1) continue;
      const key = trimmed.substring(0, eqIdx).trim();
      let value = trimmed.substring(eqIdx + 1).trim();
      // Remove inline comments (only if outside quotes)
      const hashIdx = value.indexOf(' #');
      if (hashIdx !== -1) {
        value = value.substring(0, hashIdx).trim();
      }
      // Strip surrounding quotes (single or double)
      if ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.substring(1, value.length - 1);
      }
      if (key) {
        result.vars[key] = value;
      }
    }
    result.loaded = true;
  } catch (e) {
    result.errors.push(`Failed to read .env file: ${e.message}`);
  }
  return result;
}

// ── Protocol Cache ──────────────────────────────────────────────────

/**
 * Read role from _protocol-cache.json (quick mode fallback).
 *
 * @param {string} protocolCache — absolute path to _protocol-cache.json
 * @returns {string|null} — role string, or null if cache doesn't exist or is invalid
 */
function readRoleFromCache(protocolCache) {
  try {
    if (!fs.existsSync(protocolCache)) return null;
    const raw = fs.readFileSync(protocolCache, 'utf-8');
    const cache = JSON.parse(raw);
    if (cache.role_instructions) {
      const roles = Object.keys(cache.role_instructions);
      if (roles.length === 1) return roles[0];
    }
    return null;
  } catch (_e) {
    return null;
  }
}

// ── PFL-110: Snapshot Freshness ─────────────────────────────────────

/**
 * Calculate the age of the existing _task-current.md snapshot.
 *
 * @param {string} outputFile — absolute path to _task-current.md
 * @returns {string|null} — e.g. "5 min" or "2.3 hr" or null
 */
function getExistingSnapshotAge(outputFile) {
  try {
    if (!fs.existsSync(outputFile)) return null;
    const content = fs.readFileSync(outputFile, 'utf-8');
    const match = content.match(/^# Session State — (.+)$/m);
    if (!match) return null;
    const oldTs = new Date(match[1]);
    if (isNaN(oldTs.getTime())) return null;
    const ageMs = Date.now() - oldTs.getTime();
    if (ageMs < 0) return null; // clock skew — treat as fresh
    const ageMin = Math.round(ageMs / 60000);
    if (ageMin < 1) return '<1 min';
    if (ageMin < 60) return `${ageMin} min`;
    const ageHr = (ageMs / 3600000).toFixed(1);
    return `${ageHr} hr`;
  } catch (_e) {
    return null;
  }
}

// ── PFL-115: Snapshot Health ────────────────────────────────────────

/**
 * Check if existing _task-current.md is from today and healthy.
 *
 * @param {string} outputFile — absolute path to _task-current.md
 * @returns {boolean}
 */
function isExistingSnapshotHealthy(outputFile) {
  try {
    if (!fs.existsSync(outputFile)) return false;
    const content = fs.readFileSync(outputFile, 'utf-8');
    // Check if generated today
    const today = new Date().toISOString().slice(0, 10);
    if (!content.includes(today)) return false;
    // Check for healthy indicators
    const hasEnvOk = content.includes('API URL') && !content.includes('Environment incomplete');
    const hasProtocolOk = content.includes('Protocol') && !content.includes('Protocol fetch failed');
    return hasEnvOk && hasProtocolOk;
  } catch (_e) {
    return false;
  }
}

// ── WS Events ───────────────────────────────────────────────────────

/**
 * Read recent WS events from JSONL file.
 *
 * @param {number} n — Number of recent events to return (default 5)
 * @param {string} eventsFile — absolute path to _ws-events.jsonl
 * @returns {Array<Object>}
 */
function readRecentWsEvents(n, eventsFile) {
  if (n === undefined) n = 5;
  try {
    const raw = fs.readFileSync(eventsFile, 'utf-8');
    const lines = raw.trim().split('\n').filter(Boolean);
    const recent = lines.slice(-n);
    return recent.map(function(line) {
      try { return JSON.parse(line); } catch (_) { return null; }
    }).filter(Boolean);
  } catch (_) {
    return [];
  }
}

module.exports = {
  now,
  ownerLabel,
  summarizeTask,
  roleBanner,
  loadEnvFile,
  readRoleFromCache,
  getExistingSnapshotAge,
  isExistingSnapshotHealthy,
  readRecentWsEvents,
};

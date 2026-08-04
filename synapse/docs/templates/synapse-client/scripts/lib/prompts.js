/**
 * prompts.js — Single-source-of-truth for all CronCreate prompt strings.
 *
 * P11-B137: Eliminates 3-source drift between writeState(), writeBootPrompt(),
 * and the static _boot-prompt.md template. All three now reference this module.
 *
 * When the CronCreate prompt changes, change it HERE — nowhere else.
 *
 * @version 1.0.0 — B137 structural governance
 */

'use strict';

/**
 * B137 --health mode CronCreate prompt.
 *
 * --health replaces --quick: it sends heartbeat, checks daemon liveness,
 * auto-re-spawns dead daemons, and refreshes state. The AI reads the
 * REPAIRED state — it never sees "daemon dead" because --health already fixed it.
 *
 * Design principle: shrink LLM decision surface. Daemon management is
 * mechanical — the script does it, the AI only consumes the result.
 */
const CRONCREATE_PROMPT = (
  "Wake up. "
  + "① Run: node .claude/skills/synapse/scripts/session-init.js --health (daemon self-heal + heartbeat + refresh _task-current.md). "
  + "② Read _task-current.md — check active tasks. "
  + "③ Continue working if active tasks exist, ScheduleWakeup if idle."
);

module.exports = { CRONCREATE_PROMPT };

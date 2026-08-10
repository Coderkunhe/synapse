/**
 * prompts.js — Single-source-of-truth for all CronCreate prompt strings.
 *
 * P11-B137: Eliminates 3-source drift between writeState(), writeBootPrompt(),
 * and the static _boot-prompt.md template. All three now reference this module.
 *
 * When the CronCreate prompt changes, change it HERE — nowhere else.
 *
 * @version 1.1.0 — B8 HK-3 hook sentinel check
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
 *
 * P12-B8 (HK-3): Checks .claude/_last-session-init.txt sentinel before
 * running --health. If sentinel missing (hook never fired), alerts human.
 */
const CRONCREATE_PROMPT = (
  "Wake up. "
  + "① HK-3 check: read .claude/_last-session-init.txt — if missing, SessionStart hook never fired (known Claude Code issue), run session-init.js directly to bootstrap. "
  + "② Run: node .claude/skills/synapse/scripts/session-init.js --health (daemon self-heal + heartbeat + refresh _task-current.md). "
  + "③ Read _task-current.md — check active tasks. "
  + "④ Continue working if active tasks exist, ScheduleWakeup if idle."
);

module.exports = { CRONCREATE_PROMPT };

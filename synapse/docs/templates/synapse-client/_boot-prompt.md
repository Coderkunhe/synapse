CronCreate({cron: "*/1 * * * *", prompt: "Wake up. ① Run: node .claude/skills/synapse/scripts/session-init.js --health (daemon self-heal + heartbeat + refresh _task-current.md). ② Run: bash .claude/skills/synapse/tools/synapse-health-check.sh (P13-B1: 5 项健康自检 — API · handshake · heartbeat · state file · hook sentinel). ③ Read _task-current.md — check active tasks. ④ Continue working if active tasks exist, ScheduleWakeup if idle.", recurring: true})

Then: read SKILL.md → read _task-current.md → enter work loop. You are a Synapse Worker.

🚨 P13-B1 startup health gate: After session-init.js completes, run `bash tools/synapse-health-check.sh -v` (或 `.claude/skills/synapse/tools/synapse-health-check.sh -v`). If any check fails → diagnose before claiming tasks. A Worker that skips the health check risks operating in a degraded state ("假在线").

Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.

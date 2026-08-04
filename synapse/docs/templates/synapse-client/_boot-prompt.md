CronCreate({cron: "*/1 * * * *", prompt: "Wake up. ① Run: node .claude/skills/synapse/scripts/session-init.js --health (daemon self-heal + heartbeat + refresh _task-current.md). ② Read _task-current.md — check active tasks. ③ Continue working if active tasks exist, ScheduleWakeup if idle.", recurring: true})

Then: read SKILL.md → read _task-current.md → enter work loop. You are a Synapse Worker.

Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.

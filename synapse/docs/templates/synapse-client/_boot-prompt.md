CronCreate({cron: "*/1 * * * *", prompt: "Wake up. ① Check daemon liveness: read _task-current.md daemon status lines. If heartbeat or ws-daemon dead, run: node .claude/skills/synapse/scripts/session-init.js ② Read _task-current.md for tasks. ③ Continue working if active tasks exist, ScheduleWakeup if idle.", recurring: true})

Then: read .claude/skills/synapse/SKILL.md §Daemon Liveness → read _task-current.md → enter work loop. You are a Synapse Worker.

Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.

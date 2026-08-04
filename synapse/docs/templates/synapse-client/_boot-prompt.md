CronCreate({cron: "*/1 * * * *", prompt: "Wake up. ① Run: node .claude/skills/synapse/scripts/session-init.js --quick (sends heartbeat + refreshes _task-current.md). ② Read _task-current.md Connection section — check daemon status. If heartbeat/ws-daemon dead or template fallback, run FULL session-init.js (no --quick) to re-spawn daemons. ③ Continue working if active tasks, ScheduleWakeup if idle.", recurring: true})

Then: read SKILL.md §「第二步：读取初始状态 + Daemon 自愈」（P11-B135 · PFL-127 硬约束）→ read _task-current.md → enter work loop. You are a Synapse Worker.

Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.

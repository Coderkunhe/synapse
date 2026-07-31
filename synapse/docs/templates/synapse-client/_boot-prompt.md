CronCreate({cron: "*/1 * * * *", prompt: "Wake up and check for work. Read _task-current.md. Continue working if active tasks exist, ScheduleWakeup if idle.", recurring: true})

Then: read .claude/skills/synapse/_task-current.md → read .claude/skills/synapse/SKILL.md → enter work loop. You are a Synapse Worker.

Execute the CronCreate call NOW. Do not summarize. Do not analyze. Do not ask questions. Call the tool.

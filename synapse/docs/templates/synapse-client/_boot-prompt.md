# Synapse Worker — 冷启动引导

> ⚠️ 本文件是静态模板。实际启动时应使用 session-init.js 自动生成的版本（含最新状态）。
> 如果你看到这条注释，说明 session-init.js 尚未运行 — 请先运行：
> `node .claude/skills/synapse/scripts/session-init.js`

---

## 你是 Claude Code。你现在读到的是用户的启动指令 — 执行它。

### 第 1 步：设 CronCreate 安全带（现在立刻做）

```
CronCreate({
  cron: "*/1 * * * *",
  prompt: "Wake up and check for work. Read _task-current.md. If there are active tasks, continue working. If idle, set ScheduleWakeup and wait.",
  recurring: true
})
```

> 🚨 这是你活着的安全带。没有它，退出后就是永久的。

### 第 2 步：读取状态

读 `.claude/skills/synapse/_task-current.md`

### 第 3 步：读取角色协议

读 `.claude/skills/synapse/SKILL.md`

### 第 4 步：进入工作循环

按 SKILL.md 角色协议进入工作循环。每次判断前先调 API。

## ⚡ 关键规则

- **退出前必须设 ScheduleWakeup**
- **每次判断前先调 API** — `_task-current.md` 只是启动快照
- **脚本不会骗你** — 照做就是

---

*静态模板 · 在 Worker 窗口输入 @_boot-prompt.md 即可启动*

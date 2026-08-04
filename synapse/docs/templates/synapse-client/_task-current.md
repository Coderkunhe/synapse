# ⚠️ 脚本未执行 — 模板回退（P11-B135 · PFL-127）

> 🚨 **session-init.js 未成功运行。** 你看到的是模板回退内容，不是实时状态。
> 如果 SessionStart hook 配置正确但静默失败，请执行以下自检。

## 🔍 Step 1: Env Var 自检（PFL-127 发现 2 · env 污染防御）

**先检查关键环境变量是否存在且正确：**

```bash
# 检查 env vars（Claude Code Bash 每调用独立 shell — source 不跨调用）
echo "API_URL=$SYNAPSE_API_URL"
echo "WORKER_ID=$SYNAPSE_WORKER_ID"
echo "PROJECT_ID=$SYNAPSE_PROJECT_ID"
echo "API_KEY_TAIL=$(echo $SYNAPSE_API_KEY | tail -c 9)"  # 只显示后 8 位

# 如果 env vars 缺失或错误 → source .env（如果有）
ls .claude/.env 2>/dev/null && source .claude/.env

# 如果 source 后 env vars 仍缺失 → 手动从 .env 读取关键值
cat .claude/.env 2>/dev/null | grep SYNAPSE
```

**API Key 冲突自检（PFL-127 · 旧 key 残留）：**
- `.env` 中的 `SYNAPSE_API_KEY` 和 shell env 中的 `SYNAPSE_API_KEY` 是否相同？
- 如果不一致 → `.env` 是正确的，shell env 是旧的残留
- 解决方案：运行 `session-init.js`（它会自动从 `.env` 读取并覆盖 shell env）

## 🔧 Step 2: 手动运行 session-init.js

如果 env vars 可用（或 source `.env` 后可用），手动运行脚本：

```bash
# Claude Code / Codex CLI:
node .claude/skills/synapse/scripts/session-init.js

# 如果 daemon 启动失败（env 污染导致 401）：
node .claude/skills/synapse/scripts/session-init.js --inline-env

# 快速刷新模式（跳过 daemon 管理，仅刷新 API 状态）：
node .claude/skills/synapse/scripts/session-init.js --quick
```

**如果 Node.js 不可用** → 手动启动流程见 `SKILL.md` §手动启动。

## 🩺 Step 3: SessionStart Hook 失效诊断

如果以上步骤解决了问题但下次启动又复现，说明 SessionStart hook 配置有问题。诊断步骤：

1. **检查 hook 配置**：`cat .claude/settings.local.json | grep -A5 SessionStart`
2. **验证脚本路径**：确认 `session-init.js` 路径正确（相对 `.claude/` 的路径）
3. **权限问题**：确认 `settings.local.json` 中已 allow 该脚本的执行
4. **Claude Code 版本**：某些版本可能对 hook 加载有时序要求
5. 详见 `docs/sessionstart-hook-diagnosis.md`

## 📋 模板结构（脚本运行后会被替换为以下实时数据）

脚本成功运行后，本文件会被覆盖为实时状态，包含：

- 🫵 **WHO YOU ARE**（Worker ID + 角色）
- 🚨 **FIRST ACTION — CronCreate NOW**
- ⏰ **Snapshot Freshness Check**
- 🔌 **Connection**（API URL · Worker · Project · Role · Daemon 状态）
- 📋 **Protocol**（项目上下文 + 角色指令）
- 🤝 **Handshake**（Worker 激活状态）
- 🔐 **Authorization Requests**（待处理审批）
- 💬 **Unread Messages**（评论区未读消息）
- 📝 **Active Tasks**（进行中的任务）
- 🎯 **Ready Tasks / Verification Queue**（角色特定的待处理队列）

---

*本模板最后一次更新：2026-08-04（P11-B135 · PFL-127 三合一修复）*
*PFL-127：hook 空转 + env 污染 + daemon 孤儿 — 三层回退防御*

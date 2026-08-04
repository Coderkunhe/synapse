# Synapse Worker 环境配置

> 本文件由 Synapse 生成。将以下值填入你的环境变量或客户端配置。

## 🫵 Your Identity（P11-B129 · PFL-124 修复）

> 🚨 **This is YOUR identity on the Synapse platform.**
>
> Your Worker ID is **`{{SYNAPSE_WORKER_ID}}`**. When you see this ID anywhere —
> in a task's `owner_id`, in an API response, in a log message — **that means YOU**.
> There is no "other Worker" with this ID. This is your unique identifier.
>
> **PFL-124 lesson**: Builder saw `owner_id` matching its own Worker ID and reported
> "another Worker claimed this task." The Worker failed to recognize itself.
> Know your ID. Own your tasks.

## 必需变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `SYNAPSE_API_URL` | Synapse 实例地址 | `{{SYNAPSE_API_URL}}` |
| `SYNAPSE_API_KEY` | Agent API Key（存入 OS 密钥链，不从 .env 读取） | `{{SYNAPSE_API_KEY}}` |
| `SYNAPSE_WORKER_ID` | 你的 Agent ID | `{{SYNAPSE_WORKER_ID}}` |
| `SYNAPSE_PROJECT_ID` | 默认项目 ID | `{{SYNAPSE_PROJECT_ID}}` |
| `SYNAPSE_WORKER_ROLE` | 角色标识（`builder` / `orchestrator` / `steward`） | `{{SYNAPSE_WORKER_ROLE}}` |

## 🔐 API Key 存储（P11-B35: Key 隔离）

> **API Key 默认存入操作系统密钥链，不写入 .env 明文。**

| 平台 | 存储位置 | 读取命令 |
|------|---------|---------|
| macOS | Keychain (`security`) | `security find-generic-password -a "synapse-worker-{worker_id}" -s "synapse" -w` |
| Linux | Secret Service (`secret-tool`) | `secret-tool lookup account "synapse-worker-{worker_id}" service "synapse"` |
| 回退 | `.env` 文件（chmod 600） | 从 `SYNAPSE_API_KEY=` 行读取 |

**为什么**：同一台机器上多个 Worker 的 `.env` 文件互相可读，任何一个 Worker 会话
可以读取其他 Worker 的 API Key 进行角色冒充（P-045）。密钥链存储将 Key 移出
文件系统，从根本上消除这个攻击面。

### 密钥链管理

```bash
# 存入密钥链
synapse-key.sh store <worker_id> <api_key>

# 读取
synapse-key.sh get <worker_id>

# 验证
synapse-key.sh verify <worker_id> <api_url>

# 删除
synapse-key.sh delete <worker_id>
```

## 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SYNAPSE_HEARTBEAT_INTERVAL` | 心跳间隔（秒） | `60` |
| `SYNAPSE_LOG_LEVEL` | 日志级别 | `info` |

## 客户端配置方式

### Claude Code
```bash
export SYNAPSE_API_URL="{{SYNAPSE_API_URL}}"
export SYNAPSE_API_KEY="{{SYNAPSE_API_KEY}}"
export SYNAPSE_WORKER_ID="{{SYNAPSE_WORKER_ID}}"
export SYNAPSE_PROJECT_ID="{{SYNAPSE_PROJECT_ID}}"
export SYNAPSE_WORKER_ROLE="{{SYNAPSE_WORKER_ROLE}}"
```

### Codex CLI
```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export SYNAPSE_API_URL="{{SYNAPSE_API_URL}}"
export SYNAPSE_API_KEY="{{SYNAPSE_API_KEY}}"
```

> ⚠️ 不要将 API Key 提交到版本控制。建议使用 `.env` 文件（已加入 `.gitignore`）。

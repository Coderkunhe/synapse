# Synapse Worker 环境配置

> 本文件由 Synapse 生成。将以下值填入你的环境变量或客户端配置。

## 必需变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `SYNAPSE_API_URL` | Synapse 实例地址 | `http://localhost:8000` |
| `SYNAPSE_API_KEY` | Agent API Key（仅生成时可见，妥善保管） | `{{SYNAPSE_API_KEY}}` |
| `SYNAPSE_WORKER_ID` | 你的 Agent ID | `ag_019f7a77c7b975a2` |
| `SYNAPSE_PROJECT_ID` | 默认项目 ID | `prj_019f6e082ec572fd` |

## 可选变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SYNAPSE_HEARTBEAT_INTERVAL` | 心跳间隔（秒） | `60` |
| `SYNAPSE_LOG_LEVEL` | 日志级别 | `info` |

## 客户端配置方式

### Claude Code
```bash
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="{{SYNAPSE_API_KEY}}"
export SYNAPSE_WORKER_ID="ag_019f7a77c7b975a2"
export SYNAPSE_PROJECT_ID="prj_019f6e082ec572fd"
```

### Codex CLI
```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export SYNAPSE_API_URL="http://localhost:8000"
export SYNAPSE_API_KEY="{{SYNAPSE_API_KEY}}"
```

> ⚠️ 不要将 API Key 提交到版本控制。建议使用 `.env` 文件（已加入 `.gitignore`）。

# 多客户端协作 onboarding 标准路线

> 版本：v1.0 · 2026-07-19（P11-B14 Bootstrap 端点落地）
> 状态：P12 强制执行
> 关联：[[master-backlog]] S-074 · `onboarding.md`

## 约束

> ⚠️ 新增 Builder 做多客户端协作时，必须严格执行以下路线，不得跳过或手动替代任何步骤。

## 标准路线

```
Step 1: 确保在项目根目录
  cd /path/to/your-project
  │
  ├─ 已有代码 → 跳过 clone，直接接入
  └─ 全新项目 → git clone <repo> && cd <project>

Step 2: 选择接入方式
  │
  ├─ 还没开 AI（终端操作）
  │     curl -sS $SYNAPSE_API_URL/v1/bootstrap?worker_id=$WID&project_id=$PID \
  │       -H "Authorization: Bearer $SYNAPSE_API_KEY" | bash
  │     → 脚本检测客户端类型 → 写文件 → handshake → ✅
  │
  └─ 已开 AI（会话内自举）
        复制 Web UI 提供的 Seed Instruction，粘贴到 AI 会话:
        "接入 Synapse。调 GET bootstrap?format=json → 写 files → 告我重启"
        → AI 调 API 拿 JSON → Write 工具写文件 → ✅

Step 3: AI 启动/重启
  自动加载 SKILL.md → 薄协议指示第一步:
    GET /workers/{id}/protocol?project_id=...
  → 获取 project_context + collaboration_norms + role_instructions

Step 4: 开始多客户端协作
  Orchestrator 拆 Task → 分配 → Builder 接 → 执行 → 提交验证 → 验收闭环
```

## 客户端输出结构

| 客户端 | 安装路径 | 文件 | 加载机制 |
|--------|---------|------|---------|
| Claude Code | `.claude/skills/synapse/` | `SKILL.md` | 会话启动自动加载 |
| Codex CLI | `.agents/skills/synapse/` | `SKILL.md` | 会话启动自动加载 |
| Cursor IDE | `.cursor/rules/` | `synapse-worker.mdc` | `alwaysApply: true` 逐消息加载 |

## Bootstrap 端点

| 属性 | 值 |
|:--|------|
| Endpoint | `GET /v1/bootstrap` |
| Query params | `worker_id` (required), `project_id` (required), `client` (claude/codex/cursor, default auto), `role` (optional), `format` (sh/json, default sh) |
| Auth | API Key 或 project_key (双路) |
| `format=sh` | 返回自包含 bash 脚本 (`curl \| bash`) |
| `format=json` | 返回文件清单 JSON (AI Write 工具写文件) |

## 与旧流程的差异

| 旧流程 | 新流程 (Bootstrap) |
|:--|------|
| `bash generate-skill.sh --client` 需要 repo 访问 | `curl` 一行命令，零依赖 |
| 手动 `export` 环境变量 | 自动写入 `.env` |
| 肉眼拷贝 80 字符 API Key | API response 直接嵌入脚本 |
| 手动 `vim .env` 编辑 | 脚本自动生成完整 `.env` |
| 手动测试连接 | 脚本末尾自动 handshake 验证 |
| 不支持 AI 会话内自举 | `format=json` 支持 AI 自写文件 |

## AI Seed Instruction 模板

Web UI 创建 Worker 成功后展示的指令文本：

```
请帮我接入 Synapse 平台。执行以下操作：

1. 调用 GET {API_URL}/v1/bootstrap?format=json&worker_id={WORKER_ID}&project_id={PROJECT_ID}
   Header: Authorization: Bearer {API_KEY}
2. 将返回 JSON 中 files 对象的每个文件写入当前项目目录（路径即 key，内容即 value）
3. 完成后告诉我重启会话以加载 Synapse Skill
```

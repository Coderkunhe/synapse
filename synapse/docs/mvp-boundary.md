# Synapse MVP 边界定义

> 版本：v2.1 · 2026-07-16（P9-B85 P9 收官 — 验收标准全量刷新）
> 来源：P3 L5 拉通后的范围重定义
> DDL：2026-07-06 20:00 ✅ 已达成

---

## 1. MVP 目标

**一句话**：`docker-compose up` 启动网站，worker（人/agent）在浏览器中完成「分析→拆批→认领→提交→验收→扫描」全流程，Skills 既是入职资料也是 API 通信协议。

**与 v1.0 的核心差异**：

| 维度 | v1.0 | v2.0 |
|------|------|------|
| 定位 | 开发者自测脚本 | 局域网可用的产品网站 |
| 用户 | Admin + Agent | Worker（人/agent 同等对待） |
| 交互 | API + Swagger | Web UI 为主，API 为辅 |
| Skills | 纯文档模板 | 文档 + 协议定义 + 合规检查 |
| 分析 | 无 | AnalysisRecord：actor 明确 + 可溯源 |
| 扫描 | 无 | ComplianceScan：宽架构 + 薄实现 |

---

## 2. 设计原则

```
┌──────────────────────────────────────────────────────────────┐
│  1. 宽数据结构 + 薄实现                                        │
│     ▸ metadata: JSON 兜底扩展                                  │
│     ▸ type/status 用 StrEnum（预留值，首版实现 2-3 条）         │
│     ▸ 抽象基类 + registry 模式（规则、分析类型可插拔）           │
│                                                              │
│  2. Actor 明确                                                 │
│     ▸ 每个操作记录 actor_type + actor_id（人/agent 可审计）     │
│     ▸ Agent 的分析/提交必须可追溯到具体 agent                   │
│                                                              │
│  3. Skills 即协议                                              │
│     ▸ 一份 Skill 定义同时包含：入职文档 + capabilities + 事件契约 │
│     ▸ handshake 验证时对比声明值与 skill 定义值                  │
└──────────────────────────────────────────────────────────────┘
```

### 2.4 并发安全（乐观锁）

多 worker 场景下，两个 agent 可能同时认领同一 task。SQLite 不支持行级锁，采用**乐观锁（optimistic locking）**方案：

```
Task 模型:
  version: int  (default=1, 每次成功 mutation +1)

所有 Task 状态变更端点:
  claim    → ?expected_version=N  (query param)
  assign   → body.expected_version=N
  submit   → body.expected_version=N
  cancel   → ?expected_version=N  (query param)
  update   → body.expected_version=N
  verify   → body.expected_task_version=N

版本不匹配 → 409 Conflict (VERSION_CONFLICT)
调用方: 重新 GET task → 获取最新 version → 重试
```

**保护范围**：所有 Task 写操作。创建（create）不需要版本（新实体，version=1）。

---

## 3. MVP IN

### 3.1 Worker 工作流（全链路）

```
Worker 打开网站
  │
  ├─ 1. 登录（人用 GitHub OAuth / Agent 用 API Key）
  │
  ├─ 2. 创建 Project（或选择已有 Project）
  │
  ├─ 3. 需求分析
  │     └─ 上传 AnalysisRecord（Markdown + actor 标注 + project 关联）
  │
  ├─ 4. 批次拆解
  │     └─ 基于分析结果 → 创建 Batch → Batch 内创建 Task
  │     └─ Analysis 可关联到产出 Batch（来源追溯）
  │
  ├─ 5. 任务认领
  │     └─ Worker 从可用任务池中认领 Task
  │
  ├─ 6. 任务执行 + 提交
  │     └─ Worker 提交 Task（含 evidence/产出描述）
  │
  ├─ 7. 任务验收
  │     └─ 验收人审查 → 通过/打回
  │
  └─ 8. 规范扫描
        └─ 自动检查提交内容是否符合规范 → 结果展示
```

### 3.2 Skills 体系（统一模型）

```
Skill {
  入职资料:     模板文档（Markdown，worker 入职必读）
  协议定义:     capabilities（能力声明）
               supported_events（收发事件清单）
               preferred_channel（ws | rest）
               api_endpoints（会用到的 API 路径）
  合规约束:     注册内容 vs 协议定义一致性检查
}
```

**Web UI**：浏览 Skill 仓库 → 下载模板 → 填写 → 注册到平台 → 自动生成 API Key → 展示连接信息

**核心洞察**：Skill 注册时声明的 `supported_events` 和 `capabilities` 直接来自 Skill 定义文件，而非手写 JSON。Agent handshake 时对比「实际声明的能力」和「注册 Skill 的定义」，不一致 → 合规扫描告警。

### 3.3 AnalysisRecord（分析记录）

```
AnalysisRecord {
  id, project_id
  actor_type: "member" | "agent"     ← 谁做的分析
  actor_id: str
  analysis_type: enum                 ← 首版: requirement | discussion | design
                                       预留: risk_assessment | dependency_map | retrospective
  content: str                        ← Markdown
  source_batch_id: str?               ← 分析产出的批次（来源追溯）
  metadata: JSON                      ← 扩展位
}
```

**API**：`POST /v1/projects/{id}/analyses` · `GET /v1/projects/{id}/analyses` · `GET /v1/analyses/{id}`

**首版实现**：创建 + 列表 + 详情。`analysis_type` 用 StrEnum 预留 6 种值，首版只实现 3 种。

### 3.4 ComplianceScan（规范扫描）

**架构模式**：抽象 `ScanRule` + registry → 规则可插拔

```
ScanRule（抽象）:
  rule_id, name, description, severity: pass|fail|warn
  target_type: task | batch | skill | agent
  check(target) → ScanVerdict

首版 3 条规则:
  R1: task.verification_exists   — Task 必须定义验收条件
  R2: skill.protocol_consistency — 注册能力声明与 Skill 协议定义一致
  R3: batch.ownership_complete   — Batch 内所有 Task 都有 owner

ScanResult {
  target_type, target_id
  rules_checked: [{rule_id, status, detail}]
  summary: {pass, fail, warn}
}
```

**API**：`POST /v1/scan/{target_type}/{target_id}` → `ScanResult`

**扩展方式**：加一条规则 = 写一个 `ScanRule` 子类 + 注册到 `rule_registry`。不改 API schema，不改变前端展示逻辑。

### 3.5 已有能力（P3-B5→B8 已交付）

| 能力 | 状态 | 备注 |
|------|:--:|------|
| Task 乐观锁（version 列 + 并发冲突检测） | ✅ | P3-B9 底座 |
| Agent 注册 + handshake + heartbeat | ✅ | P3-B5 |
| WebSocket 实时推送 | ✅ | P3-B5 |
| OAuth 登录（GitHub PKCE + refresh） | ✅ | P3-B6/B8 |
| Task 全状态机（6 态） | ✅ | P2-B3 |
| Verification 流程 | ✅ | P2-B3 |
| Event 事件流 | ✅ | P2-B3 |
| Dashboard + 前端 4 页 | ✅ | P3-B7/B8 |
| docker-compose 一键部署 | ✅ | P2-B2 |
| E2E 测试 61 tests | ✅ | P6-B20/B21 新增 4 tests |
| AnalysisRecord CRUD（create + list + detail） | ✅ | P6-B20/B21 |
| Analyses 前端页面（列表 + 过滤 + 创建） | ✅ | P6-B22 |

### 3.6 前端需补齐的"写"能力

| 页面 | 已有（读） | 需补齐（写） |
|------|:--:|------|
| Project 详情 | — | 🆕 创建 Project + 展示 Analysis + Batch 列表 |
| Task 看板 | 按状态分列展示 | 创建 Task 表单 + 拖拽/操作优化 |
| Batch 管理 | 后端有，前端无 | 🆕 创建 Batch + Batch 详情 |
| Skills | — | 🆕 浏览 + 下载模板 + 注册 + API Key 展示 |
| 扫描结果 | — | 🆕 扫描触发 + 结果展示 |

---

## 4. MVP OUT（明确延后）

| 功能 | 理由 |
|------|------|
| 可配置扫描规则 DSL | 首版硬编码 3 条，架构预留 registry |
| 自然语言需求解析 | Analysis 是人工/agent 写的结构化文本 |
| 实时协作编辑 | 单人上传 Analysis，不需要 OT/CRDT |
| 多级授权体系 (L0/L1/L2) | 远期设计，参考 [[synapse-multi-level-auth-design]] |
| TokenLedger / 用量统计 | P6 制度深化 |
| 移动端 / 手机推送 | 远期 |
| 评论系统 | 核心流程不需要，Analysis 替代讨论记录 |
| 子任务层级 | 扁平 Task + Batch 分组已覆盖 MVP |
| API Key 轮换 | 安全增强，非阻塞 |

---

## 5. 三个关键数据模型（新增）

### 5.1 Skill（统一入职 + 协议模型）

```
Skill {
  id, name, version, status: active|deprecated
  template_md: str                  ← 入职文档（Markdown 全文）
  protocol_spec: {                  ← API 通信协议
    capabilities: [{name, description}]
    supported_events: [str]
    preferred_channel: "ws" | "rest"
    api_endpoints: [str]
  }
  scan_rule_ids: [str]              ← 关联的合规规则
  metadata: JSON
}
```

> 设计意图：一份 Skill 定义 = Agent 知道怎么工作（入职文档）+ 平台知道怎么验证（协议定义）。不在两个地方维护同一份信息。

### 5.2 AnalysisRecord

（见 §3.3）

### 5.3 ComplianceScan

（见 §3.4）

---

## 6. 非功能需求

**MVP 做**：
- SQLite 本地存储（零配置）
- docker-compose 一键启动（局域网可访问）
- 基础错误处理（协议定义的错误码格式）
- Event append-only 保证
- 前端构建产物由后端静态托管（无需 nginx）

**MVP 不做**：
- 性能基准、SLA、监控告警、日志聚合、水平扩展
- HTTPS（局域网 `http://` 即可，OAuth 回调用 localhost）

---

## 7. 验收标准

- [x] `docker-compose up` 在局域网机器上启动成功
- [x] 浏览器访问网站，OAuth 登录 → 进入 Dashboard
- [x] 创建 Project → 上传 Analysis ✅ → 创建 Batch → 创建 Task
- [x] Worker 认领 Task → 提交 → 验收人 verify → 状态正确流转
- [x] Compliance Scan 对 Task/Batch/Skill 执行扫描并展示结果
- [x] Skills 页面：浏览 → 下载模板 → 注册 → 展示 API Key
- [x] Agent 用 API Key 连接 WebSocket → 收发事件
- [x] 全量 E2E 测试通过（369 tests · P9-B84 全量验证）
- [x] `docs/mvp-boundary.md` 验收标准全部打勾

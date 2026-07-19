# CHANGELOG

Synapse 版本更新历史 — 人机混合团队分布式协调平台。

---

## P9 — 产品主线（2026-07-07）

### P9-B37 — 全链路一步引导（S-018 闭环）

- 看板卡片快捷操作按钮：backlog→Ready / ready→Claim / in_progress→Submit
- `readyTask` API 客户端函数（暴露 `POST /v1/tasks/{id}/ready`）
- 创建成功横幅增强：一键 Move to Ready
- S-018 全量闭环（B35 步进器 + B36 任务池 + B37 快捷操作）

### P9-B36 — Worker 待认领任务池

- Tasks 页面 Tab 切换：全部任务 | 我的任务 | 待认领
- Worker 下拉框选中 → 自动切到「我的任务」tab
- 看板卡片 owner 高亮：虚线边框（未认领）+ 蓝色边框（我的）

### P9-B35 — 任务生命周期引导

- TaskDetail 5 步生命周期步进器（backlog→ready→in_progress→in_verification→completed）
- 上下文引导横幅（每步一段提示 + 可 dismiss）

### P9-B34 — 成功引导增强

- 创建成功后「继续创建」按钮 + 空看板 CTA

### P9-B33 — 错误消息修复

- ApiError 解析服务端错误体 + pre-submit 校验 + 错误码中文化

### P9-B32 — 禁用/删除 Worker

- 硬删除 + ConfirmModal + WorkerDetail 操作按钮

### P9-B31 — Worker 卡片优化

- 暂停帐号 + 状态筛选（活跃/已暂停）

### P9-B30 — 标签 autocomplete + 依赖搜索

- 标签 datalist 建议 + 依赖搜索下拉框

### P9-B29 — 截止日期快捷按钮

- 1h/2h/6h/1d/3d 预设 + 自定义

### P9-B28 — Worker 头像/type/role

- Worker 卡片区分 type + role 字段展示

### P9-B27 — Docs 分类 + Skill 下载 + CHANGELOG

- Docs 页面按 **Product Docs** / **Engineering Reference** 分组，侧边栏结构化导航
- Worker 详情页支持一键下载 SKILL.md 文件（fetch + Blob 下载，JWT 认证）
- `GET /v1/agents/{id}/skill/download` 新端点 — 渲染协议模板组装为可下载 Markdown
- 新增项目 CHANGELOG（本文档）

### P9-B26 — Dogfooding

- 用 Synapse 管 Synapse 自身开发
- Track 指针规范化（`tracks/synapse.md`）
- 种子数据 P9 化（`seed-synapse-project.py`）
- DB 回填 — 8 个 Batch 的 phase/batch_number 统一修复

### P9-B25 — 文档挂载 Web UI

- Docs 页面：侧边栏文档列表 + HTML 渲染 + 中英双语
- `GET /v1/docs` + `GET /v1/docs/{filename}?format=html` API
- Worker 详情页接入接入指引（Onboarding card）

### P9-B24 — B20-B23 端到端拉通验证

- F1 API key 前缀修复
- 12 E2E tests + migration 幂等性修复
- 352 tests 全量通过

### P9-B23 — 多客户端转换层闭环

- canonical base → 3 targets（Claude Code / Codex CLI / Cursor IDE）
- L5 拉通完成

### P9-B22 — Skill 包开发

- Claude Code 客户端 Skill（薄协议层 — B21 Protocol API + 启动引导）
- `generate-skill.sh --client` 多目标生成
- L5 拉通完成

### P9-B21 — 模板渲染引擎 + Agent Protocol API

- `GET /agents/{id}/protocol` — 四段渲染模板（project_context / collaboration_norms / role_instructions / env_template）
- `{{VAR}}` 占位符从 Agent / Team / Project DB 记录实时解析
- 340 tests

### P9-B20 — 接入指南

- `onboarding.md` — Agent API + 人类 Web UI 双视角接入文档

### P9-B19 — Batch 详情页

- Batch 穿透视图 — info card + task stats + task list
- 对标 WorkerDetail 设计模式

### P9-B18 — Task 全景过滤

- 关键词搜索 + Worker/Batch 下拉框
- API `batch_id` / `search` 查询参数

### P9-B17 — Worker 注册表单

- type / role / provider / model / expiry + API key 一次性展示
- ChipSelect 组件（P-013 经验沉淀）

### P9-B16 — Worker 详情页

- Agent card 点击 → 详情视图（info card + task stats + task list）
- `owner_id` API 过滤

### P9-B15 — Batch badge 一键跳转

- TaskCard / TaskDetail → Batches 页面（`?batch=` auto-expand + back-link）

### P9-B14 — 侧边栏回滚

- 回滚 B12 — Batches 是 Task 二级视图，非一级入口
- 侧边栏恢复 3 项

### P9-B13 — 任务包中文化 + 徽章关联

- 17 keys 中文化
- 彩色哈希徽章 + hover 联动

### P9-B12 — 导航补全（已回滚）

- Batches 加入侧边栏 → B14 回滚

### P9-B11 — Batch 创建表单

- 补 `phase` / `batch_number` 字段

### P9-B10 — Task 编辑/更新 UI

- 编辑模式 + 批量选择/取消
- 批量操作支持

### P9-B9 — depends_on 创建 UI

- TaskCard 增强 + BatchSelect 过滤
- `type` 字段修复

### P9-B8 — 前端 depends_on / Batch 展示

- 前端 TaskCard depends_on 标签 + Batch 徽章
- 多 Worker E2E + L5 拉通

### P9-B7 — depends_on 校验补刀

- 自举数据录入（seed 脚本）
- 309 tests

### P9-B6 — Task depends_on

- `depends_on` 字段 + Batch `phase` / `batch_number`
- claim 依赖就绪检查
- 306 tests + L5 拉通

### P9-B5 — 3 修复

- Dashboard Worker 命名修复
- 401 跳转 + Tasks 404 恢复

### P9-B4 — Tasks 404 修复 + Dogfooding

- 全量列表端点 + DB 修复 + L5 拉通

### P9-B3 — Task 工作流闭环

- claim / submit / verify 按钮 + 状态机

### P9-B2 — Workers 页面

- 合并 Agents + Team，标签化切换（`?tab=` query param）
- `/agents` → `/workers` redirect

### P9-B1 — 侧边栏精简

- Task 入口放松（不强制要求 project_id）
- 302 tests + 4 new

---

## P8 — 人机协调引擎（2026-07-06）

### P8-B1→B10 — 全量收官（298 tests）

- Agent 生命周期（注册 / 握手 / 心跳 / 激活）
- Task 状态机 + 验证驱动开发（VDD）
- `depends_on` 依赖管理
- WebSocket 实时事件推送
- 多租户权限模型（JWT + API Key）
- Event Store 追加写入审计链
- Compliance Scan 引擎
- Analysis Record 复盘分析

---

## P1-P7 — 平台基建（2026-07-01→06）

- **P7**：战略路线制定（D1-D5 讨论闭环）
- **P6**：前端 MVP + E2E 测试（B1-B34 · 34 批次）
- **P5**：WebSocket + 实时事件（A1 + B1-B9 · 10 批次）
- **P1-P4**：数据模型 + API + 核心引擎（14 批次）

---

> 格式参照 [Keep a Changelog](https://keepachangelog.com/)，项目内按 Phase → Batch 层级组织。

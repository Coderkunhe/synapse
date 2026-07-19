# Synapse 开发 Batch 状态
> 来源：数据库导出 · 2026-07-15 04:58 UTC
> Project: prj_019f3c7f4aa0711e

| Order | 名称 | 状态 |
|:-----:|------|:--:|
| 1 | P9-B1: 侧边栏精简 + Task 入口放松 | ✅ |
| 2 | P9-B2: Workers 页面（合并 Agents + Team） | ✅ |
| 3 | P9-B3: Task 工作流闭环（claim/submit/verify） | ✅ |
| 4 | P9-B4: Tasks 404 修复 + Dogfooding | ✅ |
| 5 | P9-B5: Dashboard Worker 命名 + 401 跳转 + Tasks 404 | ✅ |
| 6 | P9-B6: Task depends_on + Batch phase/batch_number | ✅ |
| 7 | P9-B7: depends_on 校验补刀 + Synapse 自举数据 | ✅ |
| 8 | P9-B8: 前端 depends_on/Batch 展示 + 多 Worker E2E | ✅ |
| 9 | P9-B9: depends_on 创建 UI + TaskCard 增强 | ✅ |
| 10 | P9-B10: Task 编辑/更新 UI + 批量操作 | ✅ |
| 11 | P9-B11: Batch 创建表单补 phase/batch_number | ✅ |
| 12 | P9-B12: 导航补全 — Batches 加入侧边栏（已回滚） | ✅ |
| 13 | P9-B13: 任务包中文化 + 徽章关联 | ✅ |
| 14 | P9-B14: 回滚 B12 — 侧边栏恢复 3 项 | ✅ |
| 15 | P9-B15: Batch badge 一键跳转 Tasks↔Batches | ✅ |
| 16 | P9-B16: Worker 详情页 | ✅ |
| 17 | P9-B17: Worker 注册表单 | ✅ |
| 18 | P9-B18: Task 全景过滤 | ✅ |
| 19 | P9-B19: Batch 详情页 | ✅ |
| 20 | P9-B20: 接入指南 — onboarding.md | ✅ |
| 21 | P9-B21: 模板渲染引擎 + Agent Protocol API | ✅ |
| 22 | P9-B22: Skill 包开发 — Claude Code 客户端 | ✅ |
| 23 | P9-B23: 多客户端转换层闭环 | ✅ |
| 24 | P9-B24: B20-B23 端到端拉通验证 | ✅ |
| 25 | P9-B25: 文档挂载 Web UI | ✅ |
| 26 | P9-B26: Dogfooding — track 指针 + Makefile fix | ✅ |
| 27 | P9-B27: Docs 分类 + Skill 下载 + CHANGELOG | ✅ |
| 28 | P9-B28: Dogfooding — Worker 头像/type/role | ✅ |
| 29 | P9-B29: 截止日期快捷按钮 + 任务创建后引导 | ✅ |
| 30 | P9-B30: 标签 autocomplete + 依赖搜索 | ✅ |
| 31 | P9-B31: Worker 卡片优化 + 暂停帐号 + 状态筛选 | ✅ |
| 32 | P9-B32: 禁用/删除 Worker | ✅ |
| 33 | P9-B33: 错误消息修复 — ApiError 解析 | ✅ |
| 34 | P9-B34: 成功引导增强 | ✅ |
| 35 | P9-B35: 任务生命周期引导 | ✅ |
| 36 | P9-B36: Worker 待认领任务池 | ✅ |
| 37 | P9-B37: 全链路一步引导 | ✅ |
| 38 | P9-B38: 认领按钮错误中文化 | ✅ |
| 39 | P9-B39: P7 架构评审提交 — Guardian→Steward | ✅ |
| 40 | P9-B40: 前端 typecheck 修复 | ✅ |
| 41 | P9-B41: Dogfooding v2 — 种子数据刷新 + 防呆验证 | ⬜ |
| 42 | P9-B42: Dogfood v3 — 纯 API 认领 flow E2E | ✅ |
| 43 | P9-B43: onboarding.md 全量修复（S-024 前半段） | ✅ |
| 44 | P9-B44: S-024(b) doc curl 块 subprocess E2E 机械门禁 | ✅ |
| 45 | P9-B45: S-025 seed Task 数据层 — _ensure_tasks + B42-B44 补登记 | ✅ |
| 46 | P9-B46: 文档闭环 — 五文档同步 + Web UI Dogfood 验证 · S-025 收尾 | ✅ |
| 47 | P6-B47: 数据库底座 — AuditMixin 升级 | ⬜ |
| 47 | P9-B47: S-026 Tasks 历史视图 方案A 双Tab | ✅ |
| 48 | P6-B48: i18n 末梢清零 | ⬜ |
| 48 | P9-B48: P7-006 闭环 — Batch 概念重定义代码层对齐 | ✅ |
| 49 | P6-B49: 连接 + 导航修复 | ⬜ |
| 49 | P9-B49: P7-002 流程化 — 自举同步规范落地 · 种子数据追平 B48 | ✅ |
| 50 | P6-B50: 品牌 + 表单体验 | ⬜ |
| 50 | P9-B50: S-006 TokenLedger — API + 数据模型（第一阶段） | ✅ |
| 51 | P6-B51: 组织/团队管理前端 | ⬜ |
| 51 | P9-B51: 自举同步 B49+B50 — seed 脚本补 B49/B50 数据 + 标准文档闭环 | ✅ |
| 52 | P9-B52: S-006 TokenLedger 前端 — WorkerDetail 使用统计面板 | ✅ |
| 53 | P9-B53: S-027/S-028 L5 发现补刀 — data-model + requirements-log | ✅ |
| 54 | P9-B54: S-006 TokenLedger 增强 — 双页面可见性 + 日粒度时间序列 + cost 启用 | ✅ |
| 55 | P9-B55: P7-004 数据防误删 — is_protected + 7 天冷静期 + 硬删除 | ✅ |
| 56 | P9-B56: S-029 data-model.md §3.5 Project 字段补齐 + deleted 终态 | ✅ |
| 57 | P9-B57: P7-007 Batch 原子性 — 分配原子落地 | ✅ |
| 58 | P9-B58: P7-007 前端补齐 — batch_size + assigned worker UI | ✅ |
| 59 | P9-B59/60: Dogfooding v4 — 种子数据刷新 + backlog tasks 补充 | ✅ |
| 60 | P9-B60: Dogfooding v4 backlog tasks 补充 | ✅ |
| 61 | P9-B61: Dogfooding 实操验证 — claim→submit→verify 全链路通过 · 7 friction 登记 | ✅ |
| 62 | P9-B62: F-B61-1 Human claim 权限修复 — claim 端点允许 member actor · S-030 闭环 | ✅ |
| 63 | P9-B63: API 一致性 — expected_version body 统一 + Verify 字段对齐 · F-B61-2/3 闭环 | ✅ |
| 64 | P9-B64: B61 friction 三合一清扫 — 81 Agent 清理 + Bearer 前缀 + API key 警告 · F-B61-5/6/7 闭环 | ✅ |
| 65 | P9-B65: F-B61-4 Handshake 简化 — agent_version 可选 + capabilities 接受 str 简写 | ✅ |
| 66 | P9-B66: F-B61-1 service 层补刀 — claim_task/claim_batch actor_type 动态化 | ✅ |

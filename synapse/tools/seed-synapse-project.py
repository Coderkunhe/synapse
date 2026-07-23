#!/usr/bin/env python3
"""播种脚本：创建 Synapse 自身的第一个真实 Project。

「用 Synapse 管 Synapse」— 本脚本在数据库中创建 Synapse 项目的
Team、Project 和开发 Batch，使 Synapse 成为其自身的第一个用户。

当前阶段：一式两份（DB + docs），DB 是权威源。
安全要求：运行前自动备份（make db-backup），所有写入通过 service 层。

P11-B39: 种子数据修复 — 新增 Hunter email/password User 创建，
使 Hunter 可直接从浏览器登录→审批→验证。密码通过环境变量
SYNAPSE_HUNTER_PASSWORD 配置（dev 默认: __REDACTED_PASSWORD__）。

用法:
    cd /path/to/synapse
    make db-backup                           # 先备份
    .venv/bin/python tools/seed-synapse-project.py          # 创建初始数据
    .venv/bin/python tools/seed-synapse-project.py --dry-run # 预览将要创建的内容
    .venv/bin/python tools/seed-synapse-project.py --sync    # 同步: DB → docs/batch-status.md

环境变量:
    SYNAPSE_HUNTER_EMAIL     Hunter 登录邮箱（默认: dev@example.com）
    SYNAPSE_HUNTER_PASSWORD  Hunter 登录密码（默认: __REDACTED_PASSWORD__）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_session_factory
from src.models.team import Team
from src.models.member import Member
from src.models.project import Project
from src.models.batch import Batch
from src.models.task import Task
from src.models.user import User
from src.models.user_auth_method import UserAuthMethod
from src.models.worker import Worker
from src.models.project_actor_role import ProjectActorRole
from src.services import project_service, batch_service, task_service
from src.utils.id_gen import derive_id, generate_id
from src.utils.security import hash_password

# ── 常量 ──────────────────────────────────────────────────

SYNAPSE_TEAM_SLUG = "synapse-core"
SYNAPSE_PROJECT_SLUG = "synapse"
SYNAPSE_DEV_MEMBER_ID = "mbr_dev_hunter"

# P9 Batch 定义（来源：2026-07-14 · P9-B67 自举同步 B60-B66）
# B1-B66 全量 completed。通过 Web UI 可增删改后续批次。
P9_BATCHES = [
    # ── B1-B10: 产品内核 + 工作流闭环 ──
    {"phase": "P9", "batch_number": 1,  "order": 1,  "name": "P9-B1: 侧边栏精简 + Task 入口放松",              "description": "侧边栏从 7 项精简到 3 项 + Task 创建按钮从 Dashboard 移到全局。", "status": "completed"},
    {"phase": "P9", "batch_number": 2,  "order": 2,  "name": "P9-B2: Workers 页面（合并 Agents + Team）",         "description": "Agents+Team 合并为 Workers 标签化页面，/agents→/workers 重定向。", "status": "completed"},
    {"phase": "P9", "batch_number": 3,  "order": 3,  "name": "P9-B3: Task 工作流闭环（claim/submit/verify）",     "description": "Task 三态流转按钮：claim→submit→verify，Agent+人类双角色。", "status": "completed"},
    {"phase": "P9", "batch_number": 4,  "order": 4,  "name": "P9-B4: Tasks 404 修复 + Dogfooding",                "description": "全量列表端点 + DB 连接修复 + L5 拉通。首次 Dogfooding。", "status": "completed"},
    {"phase": "P9", "batch_number": 5,  "order": 5,  "name": "P9-B5: Dashboard Worker 命名 + 401 跳转 + Tasks 404", "description": "Dashboard 统一 Worker→Agent 命名 + 401 自动跳转登录 + Tasks 404 恢复。", "status": "completed"},
    {"phase": "P9", "batch_number": 6,  "order": 6,  "name": "P9-B6: Task depends_on + Batch phase/batch_number",  "description": "Task 依赖链 + Batch phase/batch_number 字段 + claim 依赖就绪检查。306 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 7,  "order": 7,  "name": "P9-B7: depends_on 校验补刀 + Synapse 自举数据",     "description": "自引用依赖校验 + seed 脚本播种。309 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 8,  "order": 8,  "name": "P9-B8: 前端 depends_on/Batch 展示 + 多 Worker E2E",  "description": "依赖链前端渲染 + Batch 信息展示 + E2E 覆盖多 Worker 场景。L5 拉通。", "status": "completed"},
    {"phase": "P9", "batch_number": 9,  "order": 9,  "name": "P9-B9: depends_on 创建 UI + TaskCard 增强",         "description": "创建任务时选择依赖 + TaskCard 展示 Batch/依赖 + BatchSelect 过滤。", "status": "completed"},
    {"phase": "P9", "batch_number": 10, "order": 10, "name": "P9-B10: Task 编辑/更新 UI + 批量操作",               "description": "编辑模式 + 批量选择/取消/操作。B10→B11 L5 拉通。", "status": "completed"},
    # ── B11-B20: 表单 + 导航 + Worker/Batch 详情 ──
    {"phase": "P9", "batch_number": 11, "order": 11, "name": "P9-B11: Batch 创建表单补 phase/batch_number",       "description": "Batch 创建表单增加 phase 和 batch_number 字段。", "status": "completed"},
    {"phase": "P9", "batch_number": 12, "order": 12, "name": "P9-B12: 导航补全 — Batches 加入侧边栏（已回滚）",   "description": "Batches 作为一级入口加入侧边栏。P9-B14 回滚：Batches 是 Task 二级视图。", "status": "completed"},
    {"phase": "P9", "batch_number": 13, "order": 13, "name": "P9-B13: 任务包中文化 + 徽章关联",                    "description": "17 keys 中文化 + 彩色哈希徽章 + hover 联动。B12→B13 L5 拉通。", "status": "completed"},
    {"phase": "P9", "batch_number": 14, "order": 14, "name": "P9-B14: 回滚 B12 — 侧边栏恢复 3 项",                "description": "Batches 从侧边栏移除，恢复 Dashboard/Workers/Tasks 三入口。", "status": "completed"},
    {"phase": "P9", "batch_number": 15, "order": 15, "name": "P9-B15: Batch badge 一键跳转 Tasks↔Batches",        "description": "TaskCard/TaskDetail batch badge 点击跳转到 Batches 页面并自动展开。", "status": "completed"},
    {"phase": "P9", "batch_number": 16, "order": 16, "name": "P9-B16: Worker 详情页",                              "description": "点击 Agent 卡片查看详情 + 任务统计 + 任务列表 + owner_id API 过滤。", "status": "completed"},
    {"phase": "P9", "batch_number": 17, "order": 17, "name": "P9-B17: Worker 注册表单",                            "description": "type/role/provider/model/expiry 字段 + API key 一次性展示 + ChipSelect 组件。", "status": "completed"},
    {"phase": "P9", "batch_number": 18, "order": 18, "name": "P9-B18: Task 全景过滤",                              "description": "关键词搜索 + Worker/Batch 下拉框 + API batch_id/search 查询参数。", "status": "completed"},
    {"phase": "P9", "batch_number": 19, "order": 19, "name": "P9-B19: Batch 详情页",                               "description": "对标 WorkerDetail 穿透视图：info card + task stats + task list。", "status": "completed"},
    {"phase": "P9", "batch_number": 20, "order": 20, "name": "P9-B20: 接入指南 — onboarding.md",                    "description": "Agent API + 人类 Web UI 双视角接入文档。", "status": "completed"},
    # ── B21-B30: 协议 + Skill + Dogfooding ──
    {"phase": "P9", "batch_number": 21, "order": 21, "name": "P9-B21: 模板渲染引擎 + Agent Protocol API",          "description": "GET /agents/{id}/protocol 端点 + Jinja2 模板渲染。340 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 22, "order": 22, "name": "P9-B22: Skill 包开发 — Claude Code 客户端",          "description": "薄协议层 Skill + generate-skill.sh --client + onboarding §3.0。L5 拉通。", "status": "completed"},
    {"phase": "P9", "batch_number": 23, "order": 23, "name": "P9-B23: 多客户端转换层闭环",                         "description": "canonical base → 3 targets（Claude Code/Codex/Cursor）转换。L5 拉通。", "status": "completed"},
    {"phase": "P9", "batch_number": 24, "order": 24, "name": "P9-B24: B20-B23 端到端拉通验证",                     "description": "F1 API key 前缀修复 + 12 E2E tests。B20-B23 全链路验证。", "status": "completed"},
    {"phase": "P9", "batch_number": 25, "order": 25, "name": "P9-B25: 文档挂载 Web UI",                            "description": "Docs 页面 + onboarding 渲染 + WorkerDetail 接入指引。", "status": "completed"},
    {"phase": "P9", "batch_number": 26, "order": 26, "name": "P9-B26: Dogfooding — track 指针 + Makefile fix",     "description": "用 Synapse 管 Synapse：track 指针 + Makefile + 种子数据更新。", "status": "completed"},
    {"phase": "P9", "batch_number": 27, "order": 27, "name": "P9-B27: Docs 分类 + Skill 下载 + CHANGELOG",         "description": "文档按类别分组 + Skill 包下载端点 + CHANGELOG.md。352 tests。L5 拉通。", "status": "completed"},
    {"phase": "P9", "batch_number": 28, "order": 28, "name": "P9-B28: Dogfooding — Worker 头像/type/role",         "description": "Worker 卡片区分人类/Agent 头像 + type/role 字段展示。", "status": "completed"},
    {"phase": "P9", "batch_number": 29, "order": 29, "name": "P9-B29: 截止日期快捷按钮 + 任务创建后引导",          "description": "due_date 预设按钮（今天/明天/本周/下周）+ 创建成功后引导提示。", "status": "completed"},
    {"phase": "P9", "batch_number": 30, "order": 30, "name": "P9-B30: 标签 autocomplete + 依赖搜索",               "description": "标签输入支持 autocomplete + 依赖任务搜索增强。B29→B30 L5 拉通。", "status": "completed"},
    # ── B31-B41: Worker 管理 + 引导 + 架构 + 防呆验证 ──
    {"phase": "P9", "batch_number": 31, "order": 31, "name": "P9-B31: Worker 卡片优化 + 暂停帐号 + 状态筛选",     "description": "Worker 卡片视觉优化 + 暂停/恢复帐号 + Worker 列表状态筛选。", "status": "completed"},
    {"phase": "P9", "batch_number": 32, "order": 32, "name": "P9-B32: 禁用/删除 Worker",                           "description": "硬删除 + ConfirmModal + WorkerDetail 操作按钮。", "status": "completed"},
    {"phase": "P9", "batch_number": 33, "order": 33, "name": "P9-B33: 错误消息修复 — ApiError 解析",               "description": "ApiError 解析服务端错误体 + pre-submit 校验 + 错误码中文化。", "status": "completed"},
    {"phase": "P9", "batch_number": 34, "order": 34, "name": "P9-B34: 成功引导增强",                               "description": "继续创建按钮 + 空看板 CTA。", "status": "completed"},
    {"phase": "P9", "batch_number": 35, "order": 35, "name": "P9-B35: 任务生命周期引导",                           "description": "步进器（Stepper）+ 上下文横幅（ContextBanner）。", "status": "completed"},
    {"phase": "P9", "batch_number": 36, "order": 36, "name": "P9-B36: Worker 待认领任务池",                        "description": "Tab 切换（进行中/待认领）+ 快捷过滤 + owner 高亮。", "status": "completed"},
    {"phase": "P9", "batch_number": 37, "order": 37, "name": "P9-B37: 全链路一步引导",                             "description": "快捷操作按钮 + 上下文引导横幅增强。S-018 全量闭环。", "status": "completed"},
    {"phase": "P9", "batch_number": 38, "order": 38, "name": "P9-B38: 认领按钮错误中文化",                         "description": "6 个错误码翻译 + 快捷操作错误映射。", "status": "completed"},
    {"phase": "P9", "batch_number": 39, "order": 39, "name": "P9-B39: P7 架构评审提交 — Guardian→Steward",         "description": "Guardian→Steward 重命名 + 三层团队模型 + PITCH.md。353 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 40, "order": 40, "name": "P9-B40: 前端 typecheck 修复",                        "description": "TaskDetail task null check 前移。353 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 41, "order": 41, "name": "P9-B41: Dogfooding v2 — 种子数据刷新 + 防呆验证",   "description": "种子数据同步到 B41 + Dogfooding 实战 + V-019 登记防呆首次验证。", "status": "completed"},
    {"phase": "P9", "batch_number": 42, "order": 42, "name": "P9-B42: Dogfood v3 — 纯 API 认领 flow E2E",           "description": "纯 curl 认领 flow E2E · 12 项 friction 登记（P-019~P-022, LL13, S-024/S-025）。", "status": "completed"},
    {"phase": "P9", "batch_number": 43, "order": 43, "name": "P9-B43: onboarding.md 全量修复（S-024 前半段）",        "description": "12 处 doc↔code drift 全量修 · 版本升 v2.0 · Prep pytest E2E 拿真实响应回贴。", "status": "completed"},
    {"phase": "P9", "batch_number": 44, "order": 44, "name": "P9-B44: S-024(b) doc curl 块 subprocess E2E 机械门禁", "description": "check-doc-curl.sh 工具 · 7 gate tests 全绿 · S-024 全量闭环。", "status": "completed"},
    # ── B45-B48: 基础设施 + 文档闭环 + 历史视图 + 概念对齐 ──
    {"phase": "P9", "batch_number": 45, "order": 45, "name": "P9-B45: S-025 seed Task 数据层 — _ensure_tasks + B42-B44 补登记", "description": "_ensure_tasks() 函数 + 52 tasks 全生命周期示例 · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 46, "order": 46, "name": "P9-B46: 文档闭环 — 五文档同步 + Web UI Dogfood 验证 · S-025 收尾", "description": "roadmap/requirements-log/daily/tracks/master-backlog 五文档同步 + Web UI 实操验证 claim→submit→verify。", "status": "completed"},
    {"phase": "P9", "batch_number": 47, "order": 47, "name": "P9-B47: S-026 Tasks 历史视图 方案A 双Tab", "description": "进行中 4 列看板 + 历史列表视图（按 Batch 分组折叠·时间倒序·可展开详情）。7 files。", "status": "completed"},
    {"phase": "P9", "batch_number": 48, "order": 48, "name": "P9-B48: P7-006 闭环 — Batch 概念重定义代码层对齐", "description": "BatchStatus 枚举值对齐 + 模型 docstring 更新 · commit 92a30a9。P7-006 全量闭环。", "status": "completed"},
    # ── B49-B50: 自举流程化 + TokenLedger ──
    {"phase": "P9", "batch_number": 49, "order": 49, "name": "P9-B49: P7-002 流程化 — 自举同步规范落地 · 种子数据追平 B48", "description": "execution-checklist 🧬 自举同步步骤 + seed 脚本 P9_BATCHES/P9_TASKS 刷新到 B48 + master-backlog P7-002 闭环。4 files。", "status": "completed"},
    {"phase": "P9", "batch_number": 50, "order": 50, "name": "P9-B50: S-006 TokenLedger — API + 数据模型（第一阶段）", "description": "TokenUsage 模型（BigInteger token 计数 + cost 预埋）+ POST/GET /v1/agents/{id}/token-usage + migration + id_gen tku 前缀。10 files · 369 tests。", "status": "completed"},
    # ── B51-B55: TokenLedger 全线 + 数据防误删 ──
    {"phase": "P9", "batch_number": 51, "order": 51, "name": "P9-B51: 自举同步 B49+B50 — seed 脚本补 B49/B50 数据 + 标准文档闭环", "description": "seed 脚本 P9_BATCHES/P9_TASKS 补 B49/B50 + 标准文档五件套同步。5 files · commit feb0d5a。", "status": "completed"},
    {"phase": "P9", "batch_number": 52, "order": 52, "name": "P9-B52: S-006 TokenLedger 前端 — WorkerDetail 使用统计面板", "description": "WorkerDetail 新增 StatCard + 纯 CSS 柱状图（8 色轮换·GM tokens 适配）+ 7 i18n keys。9 files · commit bb083ac。", "status": "completed"},
    {"phase": "P9", "batch_number": 53, "order": 53, "name": "P9-B53: S-027/S-028 L5 发现补刀 — data-model + requirements-log", "description": "data-model.md §3.11 TokenUsage 新增 + requirements-log B46/B47 从 git log 反推补登记。2 files · commit eebeaf7。", "status": "completed"},
    {"phase": "P9", "batch_number": 54, "order": 54, "name": "P9-B54: S-006 TokenLedger 增强 — 双页面可见性 + 日粒度时间序列 + cost 启用", "description": "Dashboard token stats + WorkerDetail 日粒度柱状图 + cost 字段启用。7 files · commit fdb9dce。S-006 三阶段闭环。", "status": "completed"},
    {"phase": "P9", "batch_number": 55, "order": 55, "name": "P9-B55: P7-004 数据防误删 — is_protected + 7 天冷静期 + 硬删除", "description": "Project 防误删：is_protected + archived_at + 7 天冷静期 + 硬删除 + 前端保护锁。9 files · commit 9eba0a6。P7-004 闭环。", "status": "completed"},
    # ── B56-B58: 字段补齐 + P7-007 Batch 原子性 ──
    {"phase": "P9", "batch_number": 56, "order": 56, "name": "P9-B56: S-029 data-model.md §3.5 Project 字段补齐 + deleted 终态", "description": "data-model.md §3.5 Project +5 字段（isProtected·archivedAt·apiDocsUrl·frontendTestUrl·organization）+ 状态机扩展 deleted 终态。1 file · commit f7165e2。", "status": "completed"},
    {"phase": "P9", "batch_number": 57, "order": 57, "name": "P9-B57: P7-007 Batch 原子性 — 分配原子落地", "description": "Agent.batch_size + Batch.assigned_to FK + POST /batches/{id}/assign 端点。8 files · 369 tests · commit 6de7140。P7-007 短期落地。", "status": "completed"},
    {"phase": "P9", "batch_number": 58, "order": 58, "name": "P9-B58: P7-007 前端补齐 — batch_size + assigned worker UI", "description": "WorkerDetail batch_size 展示 + BatchDetail assigned worker link + WorkerList 注册表单 batch_size input。4 files · commit c97e982。P7-007 全量闭环。", "status": "completed"},
    # ── B59: Dogfooding v4 种子数据刷新 ──
    {"phase": "P9", "batch_number": 59, "order": 59, "name": "P9-B59: Dogfooding v4 — 种子数据刷新 B51-B58", "description": "种子数据 B51-B58 刷新 · B59 合并提交。", "status": "completed"},
    # ── B60-B66: Dogfooding + B61 friction 全量闭环 ──
    {"phase": "P9", "batch_number": 60, "order": 60, "name": "P9-B60: Dogfooding v4 backlog tasks 补充", "description": "+4 tasks（2 ready + 2 backlog）· _ensure_tasks ready 状态修复。", "status": "completed"},
    {"phase": "P9", "batch_number": 61, "order": 61, "name": "P9-B61: Dogfooding 实操验证 — claim→submit→verify 全链路通过 · 7 friction 登记", "description": "Web UI 全链路 dogfooding 验证通过 · 7 项 friction → B62-B66 一一批复。", "status": "completed"},
    {"phase": "P9", "batch_number": 62, "order": 62, "name": "P9-B62: F-B61-1 Human claim 权限修复 — claim 端点允许 member actor · S-030 闭环", "description": "claim/batch_claim 端点 actor_type 从 agent-only 放宽到 member。1 file · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 63, "order": 63, "name": "P9-B63: API 一致性 — expected_version body 统一 + Verify 字段对齐 · F-B61-2/3 闭环", "description": "expected_version 迁移到 body（向后兼容 qp）+ Verify 接受 approved/rejected。6 files · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 64, "order": 64, "name": "P9-B64: B61 friction 三合一清扫 — 81 Agent 清理 + Bearer 前缀 + API key 警告 · F-B61-5/6/7 闭环", "description": "cleanup-b24-agents.py · onboarding Bearer 前缀说明 · WorkerList API key AlertTriangle。6 files · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 65, "order": 65, "name": "P9-B65: F-B61-4 Handshake 简化 — agent_version 可选 + capabilities 接受 str 简写", "description": "agent_version 默认 0.0.0 · capabilities 自动转 CapabilityDeclaration · curl -d '{}' 可用。3 files · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 66, "order": 66, "name": "P9-B66: F-B61-1 service 层补刀 — claim_task/claim_batch actor_type 动态化", "description": "service 层 agent_id 硬编码修复 · owner_type/actor_type 动态跟随。3 files · 369 tests。B61 friction 真正全量闭环 🎉。", "status": "completed"},
    # ── B67-B70: Dogfooding v6 + friction 闭环 + L5 ──
    {"phase": "P9", "batch_number": 67, "order": 67, "name": "P9-B67: F-B66-N2/N4 friction 清扫 — API key 警告 + 种子数据 B60-B66 追平", "description": "API key 警告文案 + 种子数据 B60-B66 追平 · commit bd0373c。3+2 files。", "status": "completed"},
    {"phase": "P9", "batch_number": 68, "order": 68, "name": "P9-B68: Dogfooding v6 — PM 视角结构体验审计", "description": "PM 视角从零搭建项目全链路审计：8 项 schema/文档 friction + 5 项 PM 缺失能力登记。0 代码变更。", "status": "completed"},
    {"phase": "P9", "batch_number": 69, "order": 69, "name": "P9-B69: F-B68-N5/N3 Blocking Friction 闭环 — description required + verifications optional", "description": "description 改 required · verifications 改 optional · ready 时自动创建默认 verification。4 files (+7 test mechanical)。", "status": "completed"},
    {"phase": "P9", "batch_number": 70, "order": 70, "name": "P9-B70: L5 B63→B67 拉通 — priority/effort/evidence/summary 字段描述文档化", "description": "F-B68-N1 priority 格式文档化 + F-B68-N2 effort 格式文档化 + F-B68-N6 evidence dict 类型说明 + F-B68-N7 summary 必填文档化。2 files。", "status": "completed"},
    # ── B71-B74: S-032/S-033/S-034 缺失能力实现 ──
    {"phase": "P9", "batch_number": 71, "order": 71, "name": "P9-B71: M-B68-N1 项目进度视图 — Dashboard per-project breakdown", "description": "Dashboard 增加 per-project task 状态分布 + 完成率进度条。5 files · S-032。", "status": "completed"},
    {"phase": "P9", "batch_number": 72, "order": 72, "name": "P9-B72: M-B68-N3 批量任务操作 — batch ready/assign/priority", "description": "批量 ready / 批量 priority 修改 / 批量 assign。6 files · S-033。", "status": "completed"},
    {"phase": "P9", "batch_number": 73, "order": 73, "name": "P9-B73: M-B68-N4 Worker 负载视图 — 任务计数 + 容量指示", "description": "S-034 前半段 — Worker 列表卡片显示 active/completed task count + 容量指示器。6 files。", "status": "completed"},
    {"phase": "P9", "batch_number": 74, "order": 74, "name": "P9-B74: M-B68-N2 deadline 提醒 — is_overdue + 红色标记 + 过滤器", "description": "S-034 后半段 — Task 列表 overdue 红色左边框 + status=overdue 虚拟过滤器。7 files · S-034 全量闭环。B68 Dogfooding v6 全量闭环 🎉。", "status": "completed"},
    # ── B75-B77: 归档 + L5 拉通 + Dogfooding v7 ──
    {"phase": "P9", "batch_number": 75, "order": 75, "name": "P9-B75: Dogfooding v6 总结 — ADR-003 归档 + 编号纠正", "description": "ADR-003 归档 B68 审计方法论、8 friction + 5 missing cap 全链路。纯文档 · 6 files。", "status": "completed"},
    {"phase": "P9", "batch_number": 76, "order": 76, "name": "P9-B76: L5 B68→B75 拉通 — B73+B74 requirements-log 补登记", "description": "B73+B74 requirements-log 补登记 · 文档新鲜度统一刷新至 2026-07-15。纯文档。", "status": "completed"},
    {"phase": "P9", "batch_number": 77, "order": 77, "name": "P9-B77: Dogfooding v7 — PM 全链路审计", "description": "用 B73 Worker 负载 + B74 deadline 新能力走 PM 全链路，验证 v6 痛点修复效果。5 findings（3 P1 + 2 P2）。0 代码变更。", "status": "completed"},
    # ── B78-B80: v7 friction 修复 + v8 验证闭环 ──
    {"phase": "P9", "batch_number": 78, "order": 78, "name": "P9-B78: F-v7-01/02/03 P1 friction 修复 — provider Literal + handshake 引导 + claim expected_version 引导", "description": "provider+preferred_channel 从 regex 改为 Literal · 5 处 AGENT_NOT_ACTIVE 加 handshake 引导 · claim 422 expected_version 引导。6 files · 369 tests。", "status": "completed"},
    {"phase": "P9", "batch_number": 79, "order": 79, "name": "P9-B79: F-v7-04 + M-v7-01 P2 — overdue_only→status=overdue + Worker active_batches count", "description": "overdue_only→status=overdue 参数命名对齐 · AgentResponse 新增 active_batches 子查询字段。7 files · B77 Dogfooding v7 全量闭环 🎉。", "status": "completed"},
    {"phase": "P9", "batch_number": 80, "order": 80, "name": "P9-B80: Dogfooding v8 修复验证 — 5/5 全绿", "description": "验证 B78+B79 4 项修复在真实 API 环境中生效 · 5/5 全绿 · 0 代码变更 · B77 v7 质量闭环 🎉 · L5 B78→B80 拉通。", "status": "completed"},
]


# P9 Task 定义（来源：requirements-log + roadmap · 2026-07-14 · P9-B67 自举同步 B60-B66）
# 每 Batch 1-3 个代表性 Task。状态：B1-B66 全量 completed
# 格式: (batch_number, title, description, priority, status, effort, tags)
# 去重 key: (project_id, title) — 重复运行幂等
P9_TASKS: list[dict] = [
    # ── B1: 侧边栏精简 + Task 入口放松 ──
    {"batch": 1, "title": "精简侧边栏：7 项 → 3 项", "desc": "侧边栏从 Dashboard/Workers/Tasks/Agents/Teams/Projects/ Batches 精简为 Dashboard/Workers/Tasks 三项核心入口。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "UI"]},
    {"batch": 1, "title": "Task 创建入口放松 — ProjectSelect 改为可选文本", "desc": "ProjectSelect 组件改为可选文本输入，不强制选 Project。新增 /projects/resolve API 按 slug 解析 project_id。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "API"]},
    # ── B2: Workers 页面 ──
    {"batch": 2, "title": "Agents + Team 合并为 Workers 标签化页面", "desc": "原 Agents 页面和 Team 页面合并为 /workers 统一入口，Tab 切换（Agents / Members）。/agents→/workers 重定向。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "路由"]},
    # ── B3: Task 工作流闭环 ──
    {"batch": 3, "title": "claim/submit/verify 三按钮 + 状态流转", "desc": "TaskDetail 页面新增 claim→submit→verify 工作流按钮，人类和 Agent 双角色均可操作。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["前端", "工作流"]},
    {"batch": 3, "title": "Verify 端点 — 多验证项聚合判定", "desc": "POST /tasks/{id}/verify 端点，支持批量执行 verification，聚合判定（全部 passed → DONE，任一 failed → REJECTED）。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "API"]},
    # ── B4: Tasks 404 修复 + Dogfooding ──
    {"batch": 4, "title": "Tasks 页面 404 — 全量列表端点 + DB 连接修复", "desc": "修复 Tasks 页面白屏（DB schema 不匹配 + 缺少全量列表端点）+ L5 拉通验证。", "priority": "p0", "status": "completed", "effort": "m", "tags": ["后端", "Bug"]},
    # ── B5: 3 fixes ──
    {"batch": 5, "title": "Dashboard Worker 命名 + 401 跳转 + Tasks 404 恢复", "desc": "Dashboard 统一 Agent→Worker 命名 + 401 自动跳转登录页 + Tasks 页面 404 恢复。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["前端", "Bug"]},
    # ── B6: Task depends_on + Batch phase/batch_number ──
    {"batch": 6, "title": "Task 依赖链 — depends_on 字段 + claim 依赖就绪检查", "desc": "Task 新增 depends_on JSON 字段，claim 前校验所有依赖任务是否 completed。306 tests。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "数据模型"]},
    {"batch": 6, "title": "Batch phase/batch_number 字段 + 前端展示", "desc": "Batch 模型新增 phase 和 batch_number 字段，前端 Batch 列表展示 phase badge。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["后端", "前端", "数据模型"]},
    # ── B7: depends_on 校验补刀 + 自举数据 ──
    {"batch": 7, "title": "depends_on 三段校验 — 去重·存在性·循环检测", "desc": "新建 task_validation.py，校验收到的依赖列表中无重复 ID、目标 task 存在且同 project、无循环依赖。309 tests。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "验证"]},
    {"batch": 7, "title": "Synapse 自举数据录入 — seed 脚本首次播种", "desc": "seed-synapse-project.py 首次运行，在 DB 中创建 Synapse Team/Project + P6 历史 Batch 记录。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["工具", "Dogfooding"]},
    # ── B8: 前端 depends_on/Batch 展示 + 多 Worker E2E ──
    {"batch": 8, "title": "TaskDetail 依赖链渲染 + Batch 信息展示", "desc": "TaskDetail 页面展示 depends_on 链接列表 + Batch 信息（phase badge + batch_number）。L5 拉通。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B9: depends_on 创建 UI + TaskCard 增强 ──
    {"batch": 9, "title": "创建 Task 时选择依赖 + TaskCard 增强", "desc": "Task 创建表单新增依赖选择器（添加/移除 task ID + type 下拉）。TaskCard 展示 depends_on 徽章 + batch 标识。BatchSelect 按 phase 分组。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B10: Task 编辑/更新 UI + 批量操作 ──
    {"batch": 10, "title": "Task 编辑模式 + 批量选择/取消", "desc": "TaskDetail 页面新增内联编辑表单 + Tasks 页面新增批量选择/取消操作。B10→B11 L5 拉通。309 tests。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B11: Batch 创建表单补字段 ──
    {"batch": 11, "title": "Batch 创建表单增加 phase/batch_number 字段", "desc": "Batch 创建表单新增 phase 和 batch_number 输入框。2 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端"]},
    # ── B13: 中文化 + 徽章关联 ──
    {"batch": 13, "title": "17 键中文化 — 批次→任务包 + Batch→任务包", "desc": "17 个 i18n key 中文化（批次→任务包、Batch→任务包）+ 彩色哈希徽章 + hover 联动 tooltip。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "i18n"]},
    # ── B14: 回滚 B12 — 侧边栏恢复 ──
    {"batch": 14, "title": "回滚 B12 — 侧边栏恢复 3 项入口", "desc": "Batches 从侧边栏移除，恢复 Dashboard/Workers/Tasks 三入口。Batches 是 Task 二级视图，非一级入口。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "路由"]},
    # ── B15: Batch badge 一键跳转 ──
    {"batch": 15, "title": "Batch badge 一键跳转 Task↔Batch", "desc": "TaskCard/TaskDetail 的 batch badge 变为可点击按钮，跳转 Batches 页面（?batch= 自动展开 + 返回链接）。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "UI"]},
    # ── B16: Worker 详情页 ──
    {"batch": 16, "title": "Worker 详情页 — 点击卡片查看信息+任务统计+任务列表", "desc": "新增 WorkerDetail 页面（/workers/:id）。Info card + 任务统计 + 任务列表。后端新增 owner_id API 过滤参数。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "后端", "API"]},
    # ── B17: Worker 注册表单 ──
    {"batch": 17, "title": "Worker 注册表单 — type/role/provider/model/expiry", "desc": "Worker 创建表单新增 type/role/provider/model/expiry 字段 + API key 一次性展示 + ChipSelect 组件。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B18: Task 全景过滤 ──
    {"batch": 18, "title": "Task 关键词搜索 + Worker/Batch 下拉框过滤", "desc": "Tasks 页面新增关键词搜索（ILIKE）+ Worker/Batch 下拉框过滤 + API 查询参数扩展。300ms debounce + AND 组合。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端", "API"]},
    # ── B19: Batch 详情页 ──
    {"batch": 19, "title": "Batch 详情页 — 对标 WorkerDetail 穿透视图", "desc": "新增 BatchDetail 页面（/batches/:batchId）。Info card + task stats + task list。8 files。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "后端"]},
    # ── B20: 接入指南 ──
    {"batch": 20, "title": "onboarding.md — Agent + 人类双视角接入文档", "desc": "编写 onboarding.md 接入指南，覆盖 Agent API 接入和人类 Web UI 使用两个视角。6 章。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["文档"]},
    # ── B21: 模板渲染引擎 + Agent Protocol API ──
    {"batch": 21, "title": "模板渲染引擎 — Jinja2 + GET /agents/{id}/protocol", "desc": "新建 template_service.py（~160 行）Jinja2 渲染引擎。GET /agents/{id}/protocol 端点返回项目上下文+规范+角色指令+环境变量模板。340 tests。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "API"]},
    # ── B22: Skill 包开发 ──
    {"batch": 22, "title": "Claude Code 客户端 Skill — 薄协议层 + generate-skill.sh", "desc": "开发 Claude Code 客户端 Skill（薄协议层 SKILL.md）+ generate-skill.sh --client 模式 + onboarding §3.0。L5 拉通。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["工具", "Skill"]},
    # ── B23: 多客户端转换层闭环 ──
    {"batch": 23, "title": "canonical base → 3 targets 转换层闭环", "desc": "canonical base 模板 → claude/codex/cursor 三 target 转换。Bash dispatch + 3 个生成函数。L5 拉通。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["工具", "Skill"]},
    # ── B24: B20-B23 端到端拉通验证 ──
    {"batch": 24, "title": "B20-B23 全链路 E2E 验证 — Agent 注册→Skill→Protocol→Handshake→Heartbeat", "desc": "首次全链路拉通：F1 API key 前缀修复（sk-synapse-→sk-syn-）+ 12 E2E tests + migration 幂等性修复。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "测试", "Bug"]},
    # ── B25: 文档挂载 Web UI ──
    {"batch": 25, "title": "Docs 页面 + WorkerDetail 接入指引卡片", "desc": "新增 Docs 页面（侧边栏 + HTML 渲染）+ WorkerDetail 嵌入 onboarding 接入指引。后端 docs API + 白名单。12 files。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "后端", "文档"]},
    # ── B26: Dogfooding — track 指针 + 种子数据 ──
    {"batch": 26, "title": "用 Synapse 管 Synapse — track 指针 + Makefile fix + 种子数据 P9 化", "desc": "track/synapse.md 指针建立 + Makefile 修复 + seed 脚本从 P6_BATCHES 迁移到 P9_BATCHES。首次 Dogfooding。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["工具", "Dogfooding"]},
    # ── B27: Docs 分类 + Skill 下载 + CHANGELOG ──
    {"batch": 27, "title": "Docs 分组侧边栏 + Skill 下载端点 + CHANGELOG.md", "desc": "文档按 DOC_GROUPS 分类展示 + GET /agents/{id}/skill/download 端点 + CHANGELOG.md（27 批）。352 tests。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端", "文档"]},
    # ── B28: Worker 头像区分 ──
    {"batch": 28, "title": "Worker 卡片 — 人类/Agent 图标区分 + type/role 彩色 chip", "desc": "Worker 卡片区分人类和 Agent 头像图标 + type/role 字段彩色 chip 展示。5 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "UI"]},
    # ── B29: 截止日期快捷按钮 ──
    {"batch": 29, "title": "截止日期快捷按钮 — 1h/2h/6h/1d/3d + 创建成功引导", "desc": "Task 创建表单新增 due_date 预设按钮 + 创建成功后显示成功提示条含「查看详情」链接。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B30: 标签 autocomplete + 依赖搜索 ──
    {"batch": 30, "title": "标签 autocomplete（datalist）+ 依赖搜索（debounced dropdown）", "desc": "标签输入支持 datalist autocomplete + 依赖任务搜索增强（debounced dropdown + 后端 ID 前缀搜索）。B29→B30 L5 拉通。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端"]},
    # ── B31: Worker 卡片优化 + 暂停帐号 ──
    {"batch": 31, "title": "Worker 卡片优化 — human 隐藏 provider + 暂停/恢复帐号 + 状态筛选", "desc": "human worker 隐藏 provider 字段 + 暂停/恢复帐号（is_disabled toggle）+ Worker 列表状态筛选 tabs。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端"]},
    # ── B32: 禁用/删除 Worker ──
    {"batch": 32, "title": "禁用/删除 Worker — 硬删除 + ConfirmModal + WorkerDetail 操作按钮", "desc": "新增硬删除端点 + ConfirmModal 组件（Portal）+ WorkerDetail 页面操作按钮（暂停/恢复/删除）。11 files。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端", "UI"]},
    # ── B33: 错误消息修复 ──
    {"batch": 33, "title": "ApiError 解析服务端错误体 + pre-submit 校验 + 错误码中文化", "desc": "ApiError 类解析 body.error.message/body.detail + pre-submit 校验 + 6 个错误码中文翻译。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["前端", "Bug"]},
    # ── B34: 成功引导增强 ──
    {"batch": 34, "title": "继续创建按钮 + 空看板 CTA", "desc": "创建成功后显示「继续创建」按钮 + 空看板 CTA（引导创建第一个 Task/Worker/Batch）。3 i18n keys。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "UI"]},
    # ── B35: 任务生命周期引导 ──
    {"batch": 35, "title": "步进器（Stepper）+ 上下文横幅（ContextBanner）", "desc": "TaskDetail 页面新增 5 步状态步进器 + 按状态显示上下文引导横幅 + 可关闭。6 i18n keys。S-018 第 1/3 段。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B36: Worker 待认领任务池 ──
    {"batch": 36, "title": "Worker 待认领任务池 — Tab 切换 + 快捷过滤 + owner 高亮", "desc": "Tasks 页面新增 Tab 切换（全部/我的/待认领）+ worker 过滤 + 待认领虚线边框 + owner 蓝色边框高亮。S-018 第 2/3 段。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B37: 全链路一步引导 ──
    {"batch": 37, "title": "快捷操作按钮 + 上下文引导横幅增强", "desc": "TaskDetail 新增快捷操作按钮（claim/submit/verify）+ 上下文横幅增强引导文字。S-018 全量闭环。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B38: 认领按钮错误中文化 ──
    {"batch": 38, "title": "6 个错误码翻译 + 快捷操作错误映射", "desc": "claim 按钮 6 个错误码中文翻译 + 快捷操作按钮错误码映射。2 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "i18n"]},
    # ── B39: P7 架构评审提交 ──
    {"batch": 39, "title": "Guardian→Steward 重命名 + 三层团队模型 + PITCH.md", "desc": "全量 Guardian→Steward 重命名（8 files）+ architecture.md §4.5 三层团队模型 + PITCH.md 对外项目介绍。353 tests。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["文档", "架构"]},
    # ── B40: 前端 typecheck 修复 ──
    {"batch": 40, "title": "TaskDetail task null check 前移 — 3 TS18047 errors 修复", "desc": "TaskDetail 组件 task null check 前移到解构之前，消除 3 个 TS18047 类型错误。353 tests。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["前端", "Bug"]},
    # ── B41: Dogfooding v2（当前进行中）──
    {"batch": 41, "title": "种子数据刷新到 B41 — V-019 防呆首次实战验证", "desc": "P9_BATCHES 常量从 B26 刷新到 B41 + V-019 登记防呆机制首次实战验证 + P-018 idempotency bug 修复。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["工具", "Dogfooding"]},
    {"batch": 41, "title": "P9-B46: 文档闭环 + Web UI 验证 — S-025 收尾", "desc": "docs/ roadmap.md + requirements-log.md + daily + tracks + master-backlog 五文档同步 · Web UI Dogfood 实操验证 claim→submit→verify 完整 flow。", "priority": "p2", "status": "backlog", "effort": "m", "tags": ["文档", "Dogfooding"]},
    # ── B42: Dogfooding v3 ──
    {"batch": 42, "title": "纯 curl 认领 flow E2E — 6 步全部 200", "desc": "不依赖前端，纯 curl 走通 Agent 注册→handshake→heartbeat→claim→submit→verify 全链路。12 项 friction 登记。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "Dogfooding", "API"]},
    {"batch": 42, "title": "P-019~P-022 + LL13 + S-024/S-025 登记", "desc": "Dogfood v3 发现的 12 项 doc↔code drift 登记为 P-019~P-022 + LL13 方法论 + S-024/S-025 backlog。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["文档", "治理"]},
    # ── B43: onboarding.md 全量修复 ──
    {"batch": 43, "title": "12 处 doc↔code drift 全量修复 — 版本升 v2.0", "desc": "onboarding.md §1+§3 按 P9-B42 实测 curl 输出重写。认证 header、handshake body、heartbeat body、响应结构、端点路径全部修正。", "priority": "p0", "status": "completed", "effort": "l", "tags": ["文档", "Bug"]},
    {"batch": 43, "title": "Prep pytest E2E 9 步真跑 — 真实 request/response 回贴", "desc": "用 pytest E2E 测试真跑 9 步流程，拿真实 request/response 替换 onboarding.md 中的占位符。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["测试", "文档"]},
    {"batch": 43, "title": "Fresh eyes 复审抓 /cancel 端点表 2 处漏修 + LL14", "desc": "Fresh eyes 逐行复审发现 /cancel 端点表 2 处 drift（expected_version body→query · auth JWT admin/lead）+ /terminate 补齐 + LL14 契约层方法论。", "priority": "p0", "status": "completed", "effort": "m", "tags": ["文档", "治理", "Bug"]},
    # ── B44: doc curl 块 subprocess E2E 机械门禁 ──
    {"batch": 44, "title": "check-doc-curl.sh — doc curl 块结构校验 + Live 模式 subprocess E2E", "desc": "新建 check-doc-curl.sh 工具：扫描 .md 中 curl 代码块 → 校验 URL/方法/Auth/JSON body → Live 模式 subprocess 真跑 assert 2xx。7 gate tests 全绿。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["工具", "门禁"]},
    {"batch": 44, "title": "Makefile check-doc-curl target + 接入 check 管道", "desc": "Makefile 新增 check-doc-curl target + 接入 make check 管道（首部署警告级）+ 7 gate tests。S-024 全量闭环。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["工具", "门禁"]},
    # ── B45: S-025 seed Task 数据层 ──
    {"batch": 45, "title": "S-025 _ensure_tasks() — 52 tasks 全生命周期示例 + B42-B44 补登记", "desc": "_ensure_tasks() 函数实现 + 从 requirements-log 反向生成 52 个 mock Task + Verification 全生命周期覆盖。369 tests。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["工具", "数据"]},
    # ── B46: 文档闭环 ──
    {"batch": 46, "title": "五文档同步 + Web UI Dogfood 验证 — S-025 全量闭环", "desc": "roadmap/requirements-log/daily/tracks/master-backlog 五文档同步 · Web UI Dogfood 实操验证 claim→submit→verify 完整 flow。S-025 收尾。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["文档", "Dogfooding"]},
    # ── B47: Tasks 历史视图 ──
    {"batch": 47, "title": "S-026 Tasks 历史视图 方案A 双Tab — 进行中/历史", "desc": "Tasks 页面拆双Tab：进行中 4 列看板 + 历史列表视图（按 Batch 分组折叠·时间倒序·Worker/关键词筛选·可展开详情）。7 files · 纯前端。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "UI"]},
    # ── B48: P7-006 闭环 ──
    {"batch": 48, "title": "P7-006 闭环 — Batch 概念重定义代码层对齐", "desc": "BatchStatus 枚举值对齐（active→open）+ 模型 docstring 更新（Batch 从逻辑集合→执行原子）。commit 92a30a9。P7-006 代码层闭环。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["后端", "架构"]},
    # ── B49: P7-002 流程化 ──
    {"batch": 49, "title": "🧬 自举同步规范落地 — execution-checklist 步骤 + 种子数据追平 B48", "desc": "execution-checklist 新增「🧬 Synapse 自举同步」提交后步骤 + seed 脚本 P9_BATCHES/P9_TASKS 从 B44 刷新到 B48 + master-backlog P7-002 ⬜→✅。4 files。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["工具", "治理"]},
    # ── B50: S-006 TokenLedger 第一阶段 ──
    {"batch": 50, "title": "S-006 TokenLedger — TokenUsage 数据模型（BigInteger + cost 预埋）", "desc": "TokenUsage SQLAlchemy 模型：BigInteger prompt_tokens/completion_tokens/total_tokens + cost String(30) 预埋 + AuditMixin + FK agent/task/project。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "数据模型"]},
    {"batch": 50, "title": "S-006 TokenLedger — POST/GET API 端点 + agent 自报 403 门禁", "desc": "POST /v1/agents/{id}/token-usage（agent 自报，403 门禁 + task 归属校验）+ GET 游标分页查询。id_gen tku 前缀 + Alembic 迁移。369 tests。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "API"]},
    # ── B51: 自举同步 B49+B50 ──
    {"batch": 51, "title": "🧬 自举同步追平 — seed 脚本补 B49/B50 batch + task 数据", "desc": "P9_BATCHES 新增 B49/B50 + P9_TASKS 新增 3 tasks + 标准文档闭环五件套。5 files · commit feb0d5a。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["工具", "治理"]},
    # ── B52: TokenLedger 前端 ──
    {"batch": 52, "title": "S-006 TokenLedger 前端 — WorkerDetail 使用统计面板（StatCard + CSS 柱状图）", "desc": "WorkerDetail 新增 TokenUsage 数据获取 + useMemo 聚合 + 统计面板 UI + 纯 CSS bar chart（渐变色·8 色轮换）。9 files · commit bb083ac。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "UI"]},
    # ── B53: L5 发现补刀 ──
    {"batch": 53, "title": "S-027/S-028 L5 发现补刀 — data-model.md §3.11 + requirements-log B46/B47", "desc": "data-model.md 新增 §3.11 TokenUsage 实体 + ER 图同步 + requirements-log 从 git log + session memory 反推补登记 B46/B47。2 files · commit eebeaf7。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["文档", "治理"]},
    # ── B54: TokenLedger 增强 ──
    {"batch": 54, "title": "S-006 TokenLedger 增强 — 双页面可见性 + 日粒度时间序列 + cost 启用", "desc": "Dashboard token stats + WorkerDetail 日粒度柱状图 + cost 字段启用 + GET /token-usage/stats 聚合端点。7 files · commit fdb9dce。S-006 三阶段闭环。", "priority": "p2", "status": "completed", "effort": "l", "tags": ["前端", "后端", "API"]},
    # ── B55: P7-004 数据防误删 ──
    {"batch": 55, "title": "P7-004 数据防误删 — is_protected + archived_at + 7 天冷静期 + 硬删除", "desc": "Project 防误删：is_protected bool + archived_at datetime + toggle_protection API + delete_project（三重前置条件：已归档·满 7 天·未保护）+ 前端保护锁 toggle + 条件删除按钮。9 files · commit 9eba0a6。P7-004 闭环。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "前端", "数据模型"]},
    # ── B56: S-029 字段补齐 ──
    {"batch": 56, "title": "S-029 data-model.md §3.5 Project 字段补齐 + deleted 终态", "desc": "data-model.md §3.5 Project 属性表 +5 字段（isProtected·archivedAt·apiDocsUrl·frontendTestUrl·organization）+ 状态机扩展 deleted 终态。1 file · commit f7165e2。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["文档"]},
    # ── B57: P7-007 Batch 原子性 — 分配原子 ──
    {"batch": 57, "title": "P7-007 Batch 原子性 — Agent.batch_size + Batch.assigned_to + assign 端点", "desc": "Agent 模型新增 batch_size int 列（default 3, ge=1 le=20）+ Batch 模型新增 assigned_to FK + POST /batches/{id}/assign 端点（三重验证：batch open·agent active·同 team）。8 files · 369 tests · commit 6de7140。", "priority": "p1", "status": "completed", "effort": "l", "tags": ["后端", "数据模型", "API"]},
    # ── B58: P7-007 前端补齐 ──
    {"batch": 58, "title": "P7-007 前端补齐 — batch_size + assigned worker UI", "desc": "WorkerDetail info card 展示 batch_size（仅 Agent）+ BatchDetail 加载并展示 assigned worker 可点击链接 + WorkerList 注册表单新增 batch_size number input（1-20 default 3）+ 6 i18n keys。4 files · commit c97e982。P7-007 全量闭环。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "UI"]},
    # ── B59: Dogfooding v4 tasks（backlog/ready — 为狗食提供可操作的活）──
    {"batch": 59, "title": "清理测试残留 Worker — B24/B25 E2E 创建的 71 个 Agent 帐号", "desc": "Synapse 项目 Worker 列表被 B24/B25 时期的 E2E 测试残留 Agent 占据。需批量清理：确认无活跃任务关联 → 硬删除残留 Worker → 验证列表干净。", "priority": "p2", "status": "ready", "effort": "m", "tags": ["运维", "Dogfooding"]},
    {"batch": 59, "title": "Dashboard 空状态 CTA — Synapse 项目无 open task 时显示创建引导", "desc": "B59 Dogfooding 发现：Synapse 项目 0 open tasks，Dashboard 空看板无引导。需新增空状态组件：显示「暂无进行中任务」+ 「创建第一个任务」CTA 按钮，提升首次用户体验。", "priority": "p2", "status": "backlog", "effort": "s", "tags": ["前端", "UI", "UX"]},
    {"batch": 59, "title": "S-016 agent_count→worker_count API 命名裂缝修复", "desc": "B51 Dogfooding 发现：Dashboard stats 端点返回 agent_count 字段，但前端已统一使用 Worker 命名。需全局重命名 agent_count→worker_count（API schema + 前端类型 + 文档），保持向后兼容或做 breaking change 版本升级。", "priority": "p3", "status": "backlog", "effort": "m", "tags": ["后端", "API", "重构"]},
    {"batch": 59, "title": "B60 Dogfooding 全链路验证 — Web UI claim→submit→verify 实操走通", "desc": "用 Web UI 走通完整任务生命周期：创建 Agent Worker → handshake → 浏览待认领任务池 → claim task → submit 结果 → verify 验收。记录每一步的 friction 和体验问题，产出至少 3 条改进建议登记到 master-backlog。", "priority": "p1", "status": "ready", "effort": "m", "tags": ["Dogfooding", "验证"]},
    # ── B60-B66: Dogfooding + B61 friction 全量闭环 ──
    {"batch": 60, "title": "Dogfooding v4 backlog tasks — +4 tasks（2 ready + 2 backlog）+ ready 状态修复", "desc": "B59 合并提交 · _ensure_tasks ready 状态修复：status==ready 时 set owner_id/owner_type=None · 新增 2 ready + 2 backlog Dogfooding 弹药。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["工具", "Dogfooding"]},
    {"batch": 61, "title": "Dogfooding 实操验证 — claim→submit→verify 全链路通过 · 7 friction 登记", "desc": "Web UI 全链路实操：用人类账号 + B60 Dogfooding 全链路验证 task → claim → submit verification → verify 全通。F-B61-1~F-B61-7 共 7 项 friction 登记到 master-backlog · S-030 建项。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["Dogfooding", "验证"]},
    {"batch": 62, "title": "F-B61-1 Human claim 权限修复 — claim/batch_claim 端点允许 member actor · S-030 闭环", "desc": "claim 端点 actor_type 检查从 agent-only 放宽到 not in (agent, member) → member 可通过 Web UI 正常 claim task。1 file · 369 tests。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["后端", "API", "Bug修复"]},
    {"batch": 63, "title": "F-B61-2/3 API 一致性 — expected_version body 统一 + Verify 字段对齐", "desc": "expected_version 从 query param 迁移到 request body（向后兼容旧客户端 qp）+ Verify status 接受 approved/rejected 双输入映射到 passed/failed。6 files · 369 tests。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "API", "重构"]},
    {"batch": 64, "title": "F-B61-5/6/7 三合一清扫 — 81 Agent 清理 + Bearer 前缀 + API key 警告", "desc": "cleanup-b24-agents.py 清理 81 残留 Agent · onboarding.md 补 Bearer 自动区分说明（sk-syn- vs eyJ）· WorkerList API key AlertTriangle + 确认 checkbox。6 files · 369 tests。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["运维", "文档", "前端"]},
    {"batch": 65, "title": "F-B61-4 Handshake 简化 — agent_version 可选 + capabilities 接受 str 简写", "desc": "agent_version 默认 0.0.0 兼容不传客户端 · capabilities 接受 str 自动转 CapabilityDeclaration · curl -d '{}' 即可完成 handshake。3 files · 369 tests。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["后端", "API", "UX"]},
    {"batch": 66, "title": "F-B61-1 service 层补刀 — claim_task/claim_batch actor_type 动态化", "desc": "service 层 agent_id 硬编码修复：+actor_type 参数 → owner_type/actor_type 动态跟随认领者类型 · 三处硬编码 Agent 表查询改为条件查询。3 files · 369 tests · B61 friction 真正全量闭环 🎉。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "Bug修复"]},
    # ── B67: F-B66-N2/N4 friction 清扫 ──
    {"batch": 67, "title": "API key 警告文案 — WorkerList AlertTriangle + 确认 checkbox", "desc": "Worker 注册表单新增 API key AlertTriangle 醒目警告 + 确认 checkbox 后方可复制。1 file。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["前端", "UI", "Dogfooding"]},
    {"batch": 67, "title": "种子数据 B60-B66 追平 — P9_BATCHES/P9_TASKS 刷新", "desc": "seed 脚本 B60-B66 batch+task 数据补全到 P9_BATCHES/P9_TASKS 常量。2 files。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["工具", "治理"]},
    # ── B68: Dogfooding v6 ──
    {"batch": 68, "title": "PM 视角全链路审计 — 13 项发现登记（8 friction + 5 missing cap）", "desc": "PM 从零搭建 Phoenix 项目审计：8 项 schema/文档 friction + 5 项 PM 缺失能力全部登记到 master-backlog S-031~S-034。0 代码变更。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["Dogfooding", "验证"]},
    # ── B69: Blocking friction ──
    {"batch": 69, "title": "description 改 required + verifications 改 optional", "desc": "F-B68-N5/N3: TaskCreate description: str 必填 · verifications 默认 [] 可选。4 files (+7 test mechanical)。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "API", "Bug修复"]},
    {"batch": 69, "title": "ready 时自动创建默认 Manual PM review verification", "desc": "task_service.py: ready 状态转换时若 verifications 为空则自动创建一条 Manual PM review。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["后端", "UX"]},
    # ── B70: Field descriptions ──
    {"batch": 70, "title": "priority/effort/evidence/summary Field description 文档化 + onboarding 速查表", "desc": "4 个 Pydantic Field 加 description 注明格式约束 + onboarding.md §2.3 核操表更新。2 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["后端", "文档"]},
    # ── B71: 项目进度视图 ──
    {"batch": 71, "title": "Dashboard per-project breakdown 端点 + 前端进度条", "desc": "GET /teams/{team_id}/projects-breakdown 端点 · 前端 ProjectBreakdownSection 组件（进度条 + 状态 chips）。5 files · S-032。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["前端", "后端", "API"]},
    # ── B72: 批量任务操作 ──
    {"batch": 72, "title": "批量 ready/priority/assign — 端点 + 前端按钮", "desc": "POST /tasks/batch-ready + POST /tasks/batch-update · 前端批量操作 UI（Ready/Priority/Assign）。6 files · S-033。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["前端", "后端", "API"]},
    # ── B73: Worker 负载视图 ──
    {"batch": 73, "title": "Worker 列表任务计数 + 容量指示器", "desc": "AgentDetail 新增 active_tasks/completed_tasks/active_batches 三个 int 字段 · Worker 卡片容量条。6 files。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端", "API"]},
    # ── B74: deadline 提醒 ──
    {"batch": 74, "title": "is_overdue 计算字段 + TaskCard 红色标记 + status=overdue 过滤器", "desc": "TaskSummary is_overdue 计算字段 · overdue 红色左边框 · GET /tasks?status=overdue 虚拟过滤器。7 files · S-034。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["前端", "后端", "API"]},
    # ── B75: Dogfooding v6 总结 ──
    {"batch": 75, "title": "ADR-003 归档 — Dogfooding v6 方法论沉淀", "desc": "ADR-003 归档 B68 审计方法论、8 friction + 5 missing cap 全链路、Dogfooding 作为迭代引擎决策。纯文档 · 6 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["文档", "治理"]},
    # ── B76: L5 拉通 ──
    {"batch": 76, "title": "B73+B74 requirements-log 补登记 + 文档新鲜度统一刷新", "desc": "B73/B74 从 git log + session memory 反推补登记 · 全 7 文档日期统一刷新至 2026-07-15。纯文档。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["文档", "治理"]},
    # ── B77: Dogfooding v7 ──
    {"batch": 77, "title": "PM 全链路审计 — 5 findings 登记（3 P1 + 2 P2）", "desc": "用 B73+B74 新能力走 PM 全链路：5 项发现（F-v7-01~F-v7-04 + M-v7-01）。0 代码变更。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["Dogfooding", "验证"]},
    # ── B78: F-v7 P1 friction 修复 ──
    {"batch": 78, "title": "provider Literal 友好错误消息 + handshake/claim 引导", "desc": "F-v7-01: provider+preferred_channel regex→Literal · F-v7-02: 5 处 AGENT_NOT_ACTIVE 加 handshake 引导 · F-v7-03: claim 422 加 expected_version 引导。6 files · 369 tests。", "priority": "p1", "status": "completed", "effort": "m", "tags": ["后端", "API", "UX"]},
    # ── B79: F-v7-04 + M-v7-01 P2 ──
    {"batch": 79, "title": "overdue_only→status=overdue 参数命名对齐", "desc": "GET /tasks 删除 overdue_only 参数，status 扩展支持 overdue 虚拟状态。3 files。", "priority": "p2", "status": "completed", "effort": "s", "tags": ["后端", "API", "重构"]},
    {"batch": 79, "title": "AgentResponse 新增 active_batches 字段", "desc": "AgentResponse 加 active_batches: int=0 · 子查询 COUNT batches WHERE assigned_to=agent.id · 前端 WorkerList 显示 {N} batches。4 files。", "priority": "p2", "status": "completed", "effort": "m", "tags": ["后端", "前端", "API"]},
    # ── B80: Dogfooding v8 ──
    {"batch": 80, "title": "B78+B79 4 项修复 API 验证 — 5/5 全绿", "desc": "纯 curl 验证：provider Literal 消息 · handshake 引导 · claim expected_version 引导 · status=overdue 过滤 · active_batches 计数。0 代码变更。", "priority": "p1", "status": "completed", "effort": "s", "tags": ["Dogfooding", "验证"]},
]


async def main(dry_run: bool = False, sync: bool = False, check: bool = False) -> None:
    """主入口。"""
    async with async_session_factory() as db:
        if sync:
            await sync_to_docs(db)
            return
        if check:
            exit_code = await check_consistency(db)
            sys.exit(exit_code)

        # ── Step 1: Ensure Team exists ─────────────────
        team = await _ensure_team(db, dry_run)

        # ── Step 2: Ensure Hunter User exists (P11-B39) ──
        user = await _ensure_hunter_user(db, team, dry_run)

        # ── Step 3: Ensure Dev Member exists ───────────
        member = await _ensure_member(db, team, user, dry_run)

        # ── Step 4: Ensure Synapse Project exists ──────
        project = await _ensure_project(db, team, member, dry_run)

        # ── Step 5: Ensure Project Actor Role ──────────
        await _ensure_actor_role(db, project, user, dry_run)

        # ── Step 6: Ensure Batches exist ───────────────
        batches = await _ensure_batches(db, project, member, dry_run)

        # ── Step 7: Ensure Tasks exist ────────────────
        tasks = await _ensure_tasks(db, project, member, batches, dry_run)

        if dry_run:
            print("\n📋 以上为预览，未实际写入。去掉 --dry-run 执行写入。")
        else:
            await db.commit()
            task_count = len(tasks)
            print(f"\n✅ Synapse 项目数据已创建")
            print(f"   Team:    {team.id}  ({team.name})")
            print(f"   User:    {user.id}  ({user.email})")
            print(f"   Member:  {member.id}  ({member.display_name})")
            print(f"   Project: {project.id}  ({project.name})")
            print(f"   Batches: {len(P9_BATCHES)} 个")
            print(f"   Tasks:   {task_count} 个（新增）")
            print(f"\n💡 运行 'make db-backup' 备份当前状态。")


# ── Internal helpers ──────────────────────────────────────

async def _ensure_team(db: AsyncSession, dry_run: bool) -> Team:
    """Get or create the Synapse core team.

    NOTE: team_service has no ``create_team`` (teams are created via
    setup/auth flow).  For seeding we create the ORM object directly.
    """
    result = await db.execute(
        select(Team).where(Team.slug == SYNAPSE_TEAM_SLUG)
    )
    existing = result.scalar_one_or_none()
    if existing:
        print(f"⏭️  Team 已存在: {existing.id} ({existing.name})")
        return existing

    print(f"➕ 创建 Team: {SYNAPSE_TEAM_SLUG}")
    team = Team(
        id=generate_id("team"),
        name="Synapse Core",
        slug=SYNAPSE_TEAM_SLUG,
        description="Synapse 项目自身开发团队 — 用 Synapse 管 Synapse",
    )
    if not dry_run:
        db.add(team)
        await db.flush()
    return team


async def _ensure_member(
    db: AsyncSession, team: Team, user: User, dry_run: bool
) -> Member:
    """Get or create the dev member linked to Hunter's User record.

    P11-B39: Member.user_id now references the actual User.id
    (usr_xxx) instead of the legacy "github_hunter" string.
    Handles backward migration of legacy members.
    """
    # Try new-style lookup first (user_id = User.id)
    result = await db.execute(
        select(Member).where(
            Member.team_id == team.id,
            Member.user_id == user.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        print(f"⏭️  Member 已存在: {existing.id} ({existing.display_name})")
        if existing.email != user.email and not dry_run:
            existing.email = user.email
        return existing

    # P11-B39 backward compat: migrate legacy member with user_id="github_hunter"
    result = await db.execute(
        select(Member).where(
            Member.team_id == team.id,
            Member.user_id == "github_hunter",
        )
    )
    legacy = result.scalar_one_or_none()
    if legacy:
        print(f"🔄 迁移 legacy Member: user_id github_hunter → {user.id}")
        if not dry_run:
            legacy.user_id = user.id
            if not legacy.email:
                legacy.email = user.email
        return legacy

    print(f"➕ 创建 Member: hunter (admin)")
    member = Member(
        id=generate_id("member"),
        team_id=team.id,
        user_id=user.id,
        display_name="Hunter",
        role="admin",
        email=user.email,
    )
    if not dry_run:
        db.add(member)
        await db.flush()
    return member


async def _ensure_hunter_user(
    db: AsyncSession, team: Team, dry_run: bool
) -> User:
    """Ensure Hunter has an email/password User account (P11-B39).

    Reads credentials from env vars with dev defaults.
    Idempotent — checks UserAuthMethod(provider="email") by subject.
    Also creates the derived human Worker.
    """
    email = os.environ.get("SYNAPSE_HUNTER_EMAIL", "dev@example.com")
    password = os.environ.get("SYNAPSE_HUNTER_PASSWORD", "__REDACTED_PASSWORD__")

    # Check existing by email UserAuthMethod
    result = await db.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == "email",
            UserAuthMethod.subject == email,
        )
    )
    existing_auth = result.scalar_one_or_none()
    if existing_auth:
        user = await db.get(User, existing_auth.user_id)
        if user:
            print(f"⏭️  Hunter User 已存在: {user.id} ({user.email})")
            # Ensure derived Worker exists
            await _ensure_derived_worker(db, user, team, dry_run)
            return user

    if dry_run:
        print(f"➕ 创建 Hunter User: {email}")
        return User(id="usr_will_be_generated", email=email, display_name="Hunter")

    # Create User
    user = User(
        id=generate_id("user"),
        email=email,
        password_hash=hash_password(password),
        display_name="Hunter",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    print(f"✅ 创建 Hunter User: {user.id} ({email})")

    # Create UserAuthMethod(provider="email")
    auth_method = UserAuthMethod(
        id=generate_id("user_auth_method"),
        user_id=user.id,
        provider="email",
        subject=email,
    )
    db.add(auth_method)

    # Create derived human Worker
    await _ensure_derived_worker(db, user, team, dry_run)

    return user


async def _ensure_derived_worker(
    db: AsyncSession, user: User, team: Team, dry_run: bool
) -> Worker:
    """Create the derived human Worker for a User if it doesn't exist."""
    worker_id = derive_id(user.id, "worker")
    existing = await db.get(Worker, worker_id)
    if existing:
        # Update team if not set
        if existing.team_id is None and not dry_run:
            existing.team_id = team.id
        return existing

    if dry_run:
        return Worker(id=worker_id, name=user.display_name)

    worker = Worker(
        id=worker_id,
        name=user.display_name,
        user_id=user.id,
        team_id=team.id,
        actor_type="human",
        status="active",
        api_key_hash=None,
    )
    db.add(worker)
    await db.flush()
    return worker


async def _ensure_actor_role(
    db: AsyncSession, project: Project, user: User, dry_run: bool
) -> None:
    """Grant Hunter's Worker admin role on the Synapse project (P11-B39)."""
    worker_id = derive_id(user.id, "worker")
    par_id = derive_id(f"{project.id}:{worker_id}", "project_actor_role")

    existing = await db.get(ProjectActorRole, par_id)
    if existing:
        if existing.role != "admin" and not dry_run:
            existing.role = "admin"
        return

    if dry_run:
        return

    par = ProjectActorRole(
        id=par_id,
        project_id=project.id,
        worker_id=worker_id,
        role="admin",
    )
    db.add(par)


async def _ensure_project(
    db: AsyncSession, team: Team, member: Member, dry_run: bool
) -> Project:
    """Get or create the Synapse project via project_service."""
    result = await db.execute(
        select(Project).where(
            Project.team_id == team.id,
            Project.slug == SYNAPSE_PROJECT_SLUG,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        print(f"⏭️  Project 已存在: {existing.id} ({existing.name})")
        return existing

    print(f"➕ 创建 Project: {SYNAPSE_PROJECT_SLUG}")
    if dry_run:
        return Project(
            id="prj_will_be_generated",
            team_id=team.id,
            name="Synapse",
            slug=SYNAPSE_PROJECT_SLUG,
            description="人机混合团队分布式协调平台 — 不存代码，只协调工作。",
            default_branch="master",
            git_repo_url="https://github.com/hunter/synapse",
        )

    project = await project_service.create_project(
        db,
        team_id=team.id,
        name="Synapse",
        slug=SYNAPSE_PROJECT_SLUG,
        description="人机混合团队分布式协调平台 — 不存代码，只协调工作。",
        default_branch="master",
        git_repo_url="https://github.com/hunter/synapse",
        metadata={"motto": "不存代码，只协调工作", "org": "personal"},
        actor_type="member",
        actor_id=member.id,
    )
    return project


async def _ensure_batches(
    db: AsyncSession, project: Project, member: Member, dry_run: bool
) -> list[Batch]:
    """Create planned batches via batch_service if they don't exist.

    Dedup by (phase, batch_number) rather than name — batch names may be
    renamed between seed runs, but phase+batch_number is the stable identity.
    See pitfalls.md P-018.
    """
    result = await db.execute(
        select(Batch).where(Batch.project_id == project.id)
    )
    existing_batches = list(result.scalars().all())
    # Build dedup map: (phase, batch_number) -> Batch
    existing_by_key = {}
    for b in existing_batches:
        key = (b.phase, b.batch_number)
        if key not in existing_by_key:
            existing_by_key[key] = b

    all_batches: list[Batch] = list(existing_batches)
    for bdef in P9_BATCHES:
        key = (bdef["phase"], bdef["batch_number"])
        if key in existing_by_key:
            print(f"⏭️  Batch 已存在: {bdef['name']}")
            continue

        print(f"➕ 创建 Batch: {bdef['name']}")
        if dry_run:
            continue

        batch = await batch_service.create_batch(
            db,
            project_id=project.id,
            name=bdef["name"],
            description=bdef["description"],
            order=bdef["order"],
            phase=bdef.get("phase"),
            batch_number=bdef.get("batch_number"),
            actor_type="member",
            actor_id=member.id,
            team_id=project.team_id,
        )

        # Set status if specified (create_batch defaults to "open")
        bdef_status = bdef.get("status")
        if bdef_status == "completed":
            batch.status = "closed"
            batch.completed_at = datetime.now(timezone.utc)
        elif bdef_status == "in_progress":
            batch.status = "open"

        all_batches.append(batch)

    return all_batches


async def _ensure_tasks(
    db: AsyncSession,
    project: Project,
    member: Member,
    batches: list[Batch],
    dry_run: bool,
) -> list[Task]:
    """为每个 Batch 创建代表性 Task。

    去重 key: (project_id, title) — 重复运行幂等。
    B1-B66: completed。
    """
    # Batch lookup map: (phase, batch_number) -> Batch
    batch_by_key = {}
    for b in batches:
        key = (b.phase, b.batch_number)
        if key not in batch_by_key:
            batch_by_key[key] = b

    # 查询已有 tasks，按 (project_id, title) 去重
    result = await db.execute(
        select(Task).where(Task.project_id == project.id)
    )
    existing_tasks = list(result.scalars().all())
    existing_titles = {t.title for t in existing_tasks}

    created: list[Task] = []
    for tdef in P9_TASKS:
        title = tdef["title"]
        if title in existing_titles:
            print(f"⏭️  Task 已存在: {title}")
            continue

        # Resolve batch
        batch_key = ("P9", tdef["batch"])
        batch = batch_by_key.get(batch_key)
        if batch is None:
            print(f"⚠️  Task「{title}」引用的 Batch P9-B{tdef['batch']} 不存在，跳过")
            continue

        target_status = tdef["status"]

        if dry_run:
            print(f"➕ 创建 Task: [{target_status}] {title}")
            continue

        # Create via service (always starts as backlog)
        task = await task_service.create_task(
            db,
            project_id=project.id,
            title=title,
            description=tdef.get("desc"),
            priority=tdef.get("priority", "p2"),
            parent_task_id=None,
            batch_id=batch.id,
            estimated_effort=tdef.get("effort"),
            tags=tdef.get("tags"),
            metadata=None,
            deadline_at=None,
            verifications=[{
                "type": "manual",
                "description": f"功能验收：{title}",
            }],
            actor_type="member",
            actor_id=member.id,
            team_id=project.team_id,
        )

        # Set final status (create_task always starts as backlog)
        status = tdef["status"]
        if status == "completed":
            task.status = "completed"
            task.completed_at = datetime.now(timezone.utc)
        elif status == "in_progress":
            task.status = "in_progress"
            task.owner_type = "member"
            task.owner_id = member.id
        elif status == "ready":
            task.status = "ready"
        # "backlog" is already the default from create_task

        created.append(task)
        print(f"➕ 创建 Task: [{status}] {title}")

    return created


# ── Sync to docs (dual-write backup direction) ────────────

async def sync_to_docs(db: AsyncSession) -> None:
    """从数据库导出 Batch 列表到 docs/batch-status.md（双写 — 备份方向）。"""
    result = await db.execute(
        select(Project).where(Project.slug == SYNAPSE_PROJECT_SLUG)
    )
    project = result.scalar_one_or_none()
    if not project:
        print("❌ Synapse 项目尚未创建，先运行 seed 脚本（不加 --sync）。")
        return

    batches_result = await db.execute(
        select(Batch)
        .where(Batch.project_id == project.id)
        .order_by(Batch.order)
    )
    batches = batches_result.scalars().all()

    output_path = (
        Path(__file__).resolve().parent.parent / "docs" / "batch-status.md"
    )
    lines = [
        "# Synapse 开发 Batch 状态",
        f"> 来源：数据库导出 · "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"> Project: {project.id}",
        "",
        "| Order | 名称 | 状态 |",
        "|:-----:|------|:--:|",
    ]
    STATUS_ICON = {
        "closed": "✅",     # 当前 DB 实际值
        "completed": "✅",  # BatchStatus 枚举值（远期统一后）
        "in_progress": "🟡",
        "open": "⬜",
        "cancelled": "❌",
    }
    for b in batches:
        status_icon = STATUS_ICON.get(b.status, "⬜")
        lines.append(f"| {b.order} | {b.name} | {status_icon} |")

    output_path.write_text("\n".join(lines) + "\n")
    print(f"✅ 已导出 {len(batches)} 个 Batch 到 {output_path}")


async def check_consistency(db: AsyncSession) -> int:
    """检查 DB 与 docs/batch-status.md 的一致性。

    Returns:
        0 = 一致，1 = 不一致/文件缺失/DB为空。
    """
    result = await db.execute(
        select(Project).where(Project.slug == SYNAPSE_PROJECT_SLUG)
    )
    project = result.scalar_one_or_none()
    if not project:
        print("⚠️  Synapse 项目尚未创建，跳过一致性检查。")
        return 0  # 不阻断新环境

    batches_result = await db.execute(
        select(Batch)
        .where(Batch.project_id == project.id)
        .order_by(Batch.order)
    )
    db_batches = batches_result.scalars().all()
    db_count = len(db_batches)

    if db_count == 0:
        print("⚠️  DB 中无 Batch 数据，跳过一致性检查。")
        return 0  # 不阻断空 DB

    output_path = (
        Path(__file__).resolve().parent.parent / "docs" / "batch-status.md"
    )
    if not output_path.exists():
        print(f"⚠️  不一致：DB 有 {db_count} 个 Batch，"
              f"docs/batch-status.md 文件不存在。运行 make db-sync 同步。")
        return 1

    # Parse doc: count table rows (lines matching "| N | ... | icon |")
    doc_content = output_path.read_text()
    doc_count = 0
    for line in doc_content.splitlines():
        stripped = line.strip()
        # Skip header row, separator row, and non-table lines
        if not stripped.startswith("|"):
            continue
        if stripped.startswith("|:---"):  # separator like "|:-----:|------|:--:|"
            continue
        if stripped.startswith("| Order"):  # header row
            continue
        # Count data rows (must start with | followed by a digit or None)
        doc_count += 1

    if db_count == doc_count:
        print(f"✅ DB↔docs 一致：{db_count} 个 Batch")
        return 0
    else:
        print(f"⚠️  不一致：DB 有 {db_count} 个 Batch，"
              f"docs 记录了 {doc_count} 个 Batch。运行 make db-sync 同步。")
        return 1


# ── CLI ───────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse 种子数据管理")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览将要创建的内容，不实际写入",
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="从数据库导出 Batch 状态到 docs/batch-status.md",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="检查 DB 与 docs/batch-status.md 的一致性（exit 0=一致 1=不一致）",
    )
    args = parser.parse_args()

    if args.sync and args.check:
        print("❌ --sync 和 --check 不能同时使用。")
        sys.exit(2)

    asyncio.run(main(dry_run=args.dry_run, sync=args.sync, check=args.check))

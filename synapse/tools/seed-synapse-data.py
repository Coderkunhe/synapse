#!/usr/bin/env python3
"""Synapse 自举数据录入 — 用 Synapse 管 Synapse 自己的开发历史。

将 P1-P9 的 Phase/Batch 结构录入为 Batch + Task：
- 每个 Batch 创建一个 Batch 记录（含 phase + batch_number）
- 每个 Batch 创建一个 Task（title = Batch 描述，status = completed）
- Task 间用 depends_on 表达 Phase 内顺序 + Phase 间依赖

安全要求：运行前自动备份（make db-backup），所有写入通过 service 层。
依赖：需要已有团队和项目（先运行 seed-synapse-project.py）。

用法:
    cd /path/to/synapse
    make db-backup
    .venv/bin/python tools/seed-synapse-data.py          # 写入数据
    .venv/bin/python tools/seed-synapse-data.py --dry-run # 预览
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import async_session_factory
from src.models.team import Team
from src.models.project import Project
from src.models.batch import Batch
from src.models.task import Task
from src.services import batch_service
from src.services.task_service import create_task

# ── 常量 ──────────────────────────────────────────────────

SYNAPSE_TEAM_SLUG = "synapse-core"
SYNAPSE_PROJECT_SLUG = "synapse"
DEFAULT_ACTOR_ID = "mbr_dev_hunter"

# ── Synapse 开发历史：Phase → Batch 映射 ─────────────────

# 格式: (batch_number, title, description)
SYNAPSE_PHASES: dict[str, dict] = {
    "P1": {
        "name": "Phase 1：项目启动",
        "batches": [
            (1, "项目命名 + 目录结构 + CLAUDE.md 铁律移植", "Synapse 项目初始化，Glassmind 铁律移植：五层自检金字塔、发现即待办、Batch 隔离等 9 条工程规则"),
            (2, "五层自检框架 + methodology.md 落地", "L1-L5 自检金字塔文档化，methodology.md 核心方法论"),
            (3, "Glassmind 全盘审计 + 5 项机械门禁落地", "审计 Glassmind 项目，移植 5 项机械门禁到 Synapse"),
            (4, "PRD 初稿 + 产品边界定义", "产品需求文档 + mvp-boundary.md"),
            (5, "三个地基文档", "data-model.md + protocol.md + security-model.md 三大地基"),
            (6, "Round 1 产品对齐 + architecture.md", "16 条设计决策 + 系统架构定稿"),
        ],
    },
    "P2": {
        "name": "Phase 2：MVP Sprint",
        "batches": [
            (1, "Skill 模板 + generate-skill.sh", "Worker Skill 模板（7 文件）+ Claude + Codex 双客户端生成器"),
            (2, "MVP 边界定义 + FastAPI 骨架 + docker-compose", "FastAPI 项目骨架 + SQLAlchemy + Docker 本地开发环境"),
            (3, "核心 API 端点", "Agent 注册/Task 流转/Verification 端点"),
            (4, "端到端验收 + L5 拉通", "E2E 测试 + 全链路闭环验证"),
        ],
    },
    "P3": {
        "name": "Phase 3：Post-MVP 增强",
        "batches": [
            (1, "WebSocket 实时通道", "WS 连接管理 + 事件推送 + 心跳"),
            (2, "OAuth 接入", "OAuth 2.0 流程 + Token 管理 + GitHub provider"),
            (3, "前端页面补全", "Agents + TaskDetail 前端页面"),
            (4, "OAuth 前端 UI + E2E 测试", "登录页面 + OAuth 回调 + E2E 测试覆盖"),
        ],
    },
    "P4": {
        "name": "Phase 4：质量治理",
        "batches": [
            (1, "Bug 修复", "datetime 混用/CORS/count 查询/slug 约束 修复"),
            (2, "文档同步", "protocol.md §7/§8 + README.md 同步更新"),
            (3, "设计改善", "索引优化 + JSON 去重"),
            (4, "错误统一", "HTTPException → SynapseError 全量迁移"),
            (5, "常量化", "9 StrEnum + 模型接入"),
        ],
    },
    "P5": {
        "name": "Phase 5：制度基础设施",
        "batches": [
            (1, "Makefile + check-docs 增强 + master-backlog", "门禁基础设施搭建"),
            (2, "methodology.md 补章（10 缺失章节）", "五层分级矩阵 + 反模式速查 + L5 模板等"),
            (3, "Batch 编号连续性 + LRN 防呆 + check-comments", "编号门禁 + 经验编号检查 + 注释质量扫描"),
            (4, "TaskContinuityDetector", "SessionBoundaryDetector 改编为任务连续性检测器"),
            (5, "check-all 全栈门禁 + 文件行数上限", "全栈门禁管道 + check-line-count"),
            (6, "router.py 拆分 + check-line-count 入标准门禁", "Router 模块化拆分"),
            (7, "check-contracts + ADR + 关注点分离契约", "API schema 快照 + 契约测试 + ADR 文档"),
            (8, "Batch + Project Service 抽取", "Batch 服务层 + Project 服务层抽取"),
            (9, "Team + Member Service 抽取 + EventStore 查询", "Team/Member 服务层 + EventStore 查询能力"),
        ],
    },
    "P6": {
        "name": "Phase 6：MVP v2.0 — 制度深化 + Worker 全流程",
        "batches": [
            (1, "AnalysisRecord 数据模型 + 基础设施", "模型/常量/ID/Schema 全栈"),
            (2, "AnalysisRecord 服务 + 路由 + 测试", "Service + Router + E2E 测试"),
            (3, "AnalysisRecord 前端页面", "列表 + 详情 + 创建表单"),
            (4, "pre-commit 项目隔离 + 文档同步补刀", "Hook 增强 + 文档对齐"),
            (5, "ComplianceScan 数据模型 + Schema + 常量", "合规扫描模型基础设施"),
            (6, "ComplianceScan Service + Router + Tests", "规则引擎 + 2 rules + E2E"),
            (7, "ComplianceScan GET endpoints + team_id 列", "查询端点 + 数据模型增强"),
            (8, "ComplianceScan 前端页面", "list + trigger scan + nav"),
            (9, "Skill 数据模型 + Schema + 常量 + 迁移", "Skill 模型全栈"),
            (10, "Skill Service + Router + Tests", "17 tests + CRUD 端点"),
            (11, "Skill 前端页面", "list + create + edit + deprecate + nav"),
            (12, "前端写能力补齐", "list_projects/list_batches 端点 + Projects 前端页面"),
            (13, "Batches 前端页面", "list + create + expand"),
            (14, "Task 创建表单", "verifications 子表单 + create Task UI"),
            (15, "前端重构 — 工具层", "useApi/useWebSocket/formatters"),
            (16, "前端重构 — 组件抽取", "TaskCard/ConfirmModal/IntentPill"),
            (17, "前端重构 — Auth 迁移", "ProtectedRoute/OAuthCallback"),
            (18, "前端重构 — i18n 基础设施", "t()/TranslationsProvider/lang switch"),
            (19, "前端重构 — 导航修复 + 布局统一", "侧边栏 + 面包屑 + 布局统一"),
            (20, "前端重构 — 违纪体系建立", "process-violations.md + V-NNN 注册"),
            (21, "违纪体系闭环", "check-violations + violations-review + 防呆评估"),
            (22, "i18n 全量翻译", "8 页 EN/中文切换"),
            (23, "UX 修复 4 项", "ProjectSelect/BatchSelect/nav highlight"),
            (24, "批次重编号 B40→B43", "违纪升级触发重编号"),
            (25, "DB 底座 — AuditMixin 核心 + 6 表简单继承", "AuditMixin 升级第一批"),
            (26, "DB 底座 — 复杂模型 8 表 AuditMixin 升级", "AuditMixin 升级第二批"),
            (27, "DB 底座 — Alembic 迁移 + Schema Response 同步", "Migration + Schema 同步"),
            (28, "DB 底座 — Service create_user_id 接入", "Service 层 create_user_id 统一"),
            (29, "i18n 表单页清零", "7 页硬编码全部接入 t()"),
            (30, "i18n 展示页清零", "badge/date/fallback + formatDate lang"),
            (31, "WS 修复 + ProtectedRoute + 404 + 品牌基础", "5 文件修复"),
            (32, "品牌标语 + 表单体验", "slogan/motto/textarea/字段扩展"),
            (33, "Teams 前端 + 架构收敛", "列表/详情/成员管理/导航"),
            (34, "文档刷新 + L5 拉通 + track 同步", "全量收官"),
        ],
    },
    "P7": {
        "name": "Phase 7：战略路线制定",
        "batches": [
            (1, "Batch 概念重定义", "从「逻辑集合」升级为「执行原子（任务包）」"),
            (2, "P0 审计迁移（重分类至 P100）", "GlassCortex 制度扫描 + 4 项方法论落地"),
        ],
    },
    "P8": {
        "name": "Phase 8：人机协调引擎",
        "batches": [
            (1, "Agent 生命周期管理", "handshake → heartbeat → drain"),
            (2, "Task 状态机", "BACKLOG→READY→IN_PROGRESS→REVIEW→DONE"),
            (3, "Worker 调度器", "claim/complete/release + 乐观锁"),
            (4, "故障检测器", "heartbeat 超时 → ERROR + 任务释放"),
            (5, "Verification 系统", "多验证项 + 聚合判定"),
            (6, "Event Store", "完整审计链 + cursor 分页"),
            (7, "Block/Blocker 报告机制", "blocker 上报 + 追踪"),
            (8, "report_blocker 收敛", "apply_transition + override_event_type"),
            (9, "Gate + Signal recovery 闭环", "门禁 + 信号恢复机制"),
            (10, "E2E 测试全覆盖", "298 tests 全通过"),
        ],
    },
    "P9": {
        "name": "Phase 9：产品主线",
        "batches": [
            (1, "侧边栏精简 + Task 入口放松", "9→3 + ProjectSelect → 可选文本 + resolve API"),
            (2, "Workers 页面", "合并 Agents + Team 标签化"),
            (3, "Task 工作流闭环", "claim/submit/verify 按钮"),
            (4, "Tasks 404 修复 + Dogfooding", "全量列表端点 + DB schema + Dogfooding 验证"),
            (5, "3 fixes", "Dashboard Worker 命名 + 401 跳转 + Tasks 404 恢复"),
            (6, "Task depends_on + Batch phase/batch_number", "depends_on JSON 列 + phase/batch_number 结构化 + claim 依赖检查"),
        ],
    },
    "P100": {
        "name": "Phase 100：治理块",
        "batches": [
            (1, "Phase 治理基础设施", "G-003 phase-criteria + G-004 check-phase"),
            (2, "中文化 — 状态机 + 常量 + 配置", "状态机/常量/配置中文化"),
            (3, "中文化 — src/models/ 模型层", "8 files 中文化"),
            (4, "中文化 — src/models/ 模型层(下)", "7 files 中文化"),
            (5, "中文化 — src/services/ 服务层(上)", "8 files 中文化"),
            (6, "中文化 — src/services/ 服务层(下)-A", "5 files 中文化"),
            (7, "中文化 — src/services/ 服务层(下)-B", "5 files 中文化"),
            (8, "中文化 — src/api/ + schemas/ 核心", "8 files 中文化"),
            (9, "中文化 — src/schemas/ 实体层", "8 files 中文化"),
            (10, "中文化 — tests/ 第一批", "8 files 中文化"),
            (11, "中文化 — tests/ 第二批", "8 files 中文化"),
            (12, "中文化 — tests/ 第三批", "7 files, 111 tests"),
            # B13 跳号
            (14, "讨论→登记管道 + 批次顺序前置校验", "G-005-a+b + track 指针"),
            (15, "P8 遗留技术债清零", "C1+C2+C3 · 5 files"),
            (16, "GlassCortex 深度扫描第二轮 → P1 迁移", "Shared Module Governance + 违纪闭环升级 + 依赖升级纪律 + 文件健康诊断"),
        ],
    },
}

# Phase 间依赖：每个 Phase 的第一个 Batch 依赖于上一个 Phase 的最后一个 Batch
PHASE_ORDER = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P100", "P9"]


async def main(dry_run: bool = False) -> None:
    """主入口。"""
    async with async_session_factory() as db:
        # ── 定位 Team + Project ──────────────────────
        team_result = await db.execute(
            select(Team).where(Team.slug == SYNAPSE_TEAM_SLUG)
        )
        team = team_result.scalar_one_or_none()
        if team is None:
            print("❌ Synapse Core 团队不存在，先运行 seed-synapse-project.py")
            return

        proj_result = await db.execute(
            select(Project).where(
                Project.team_id == team.id,
                Project.slug == SYNAPSE_PROJECT_SLUG,
            )
        )
        project = proj_result.scalar_one_or_none()
        if project is None:
            print("❌ Synapse 项目不存在，先运行 seed-synapse-project.py")
            return

        if dry_run:
            print(f"📋 DRY RUN — Team: {team.id} · Project: {project.id}\n")
        else:
            print(f"✅ Team: {team.id} · Project: {project.id}\n")

        # ── Phase 间依赖追踪 ──────────────────────────
        prev_phase_last_task_id: str | None = None
        created_count = 0
        skipped_count = 0

        for phase_key in PHASE_ORDER:
            phase_info = SYNAPSE_PHASES[phase_key]
            print(f"── {phase_info['name']} ──")

            prev_batch_task_id: str | None = None

            for batch_num, title, description in phase_info["batches"]:
                batch_name = f"{phase_key}-B{batch_num}"

                # 1) 查找或创建 Batch
                batch_result = await db.execute(
                    select(Batch).where(
                        Batch.project_id == project.id,
                        Batch.name == batch_name,
                    )
                )
                batch = batch_result.scalar_one_or_none()
                if batch is None:
                    if not dry_run:
                        batch = await batch_service.create_batch(
                            db,
                            project_id=project.id,
                            name=batch_name,
                            description=description,
                            order=None,
                            phase=phase_key,
                            batch_number=batch_num,
                            actor_type="member",
                            actor_id=DEFAULT_ACTOR_ID,
                            team_id=team.id,
                        )
                    else:
                        print(f"  [DRY RUN] Batch: {batch_name}")
                else:
                    print(f"  ⏭️  Batch 已存在: {batch_name}")

                # 2) 查找或创建对应 Task
                task_result = await db.execute(
                    select(Task).where(
                        Task.project_id == project.id,
                        Task.title == f"[{phase_key}-B{batch_num}] {title}",
                    )
                )
                existing_task = task_result.scalar_one_or_none()
                if existing_task is not None:
                    print(f"  ⏭️  Task 已存在: {batch_name}")
                    # Track for dependency chaining even if skipped
                    prev_batch_task_id = existing_task.id
                    if prev_phase_last_task_id is None and batch_num == 1:
                        pass  # first batch of first phase
                    skipped_count += 1
                    continue

                # 构建 depends_on
                depends_on = []
                # Phase 内顺序依赖
                if prev_batch_task_id:
                    depends_on.append({"task_id": prev_batch_task_id, "type": "sequential"})
                # Phase 间依赖（第一个 Batch）
                elif prev_phase_last_task_id:
                    depends_on.append({"task_id": prev_phase_last_task_id, "type": "sequential"})

                if dry_run:
                    print(f"  [DRY RUN] Task: [{phase_key}-B{batch_num}] {title}"
                          f"{' depends_on ' + str(depends_on) if depends_on else ''}")
                    prev_batch_task_id = f"tsk_would_be_{phase_key}_B{batch_num}"
                    continue

                task = await create_task(
                    db,
                    project_id=project.id,
                    title=f"[{phase_key}-B{batch_num}] {title}",
                    description=description,
                    priority="p2",
                    parent_task_id=None,
                    batch_id=batch.id if batch else None,
                    estimated_effort=None,
                    tags=[phase_key, f"B{batch_num}"],
                    metadata={"phase": phase_key, "batch_number": batch_num},
                    deadline_at=None,
                    verifications=[{"type": "manual", "description": "Batch 完成验收"}],
                    actor_type="member",
                    actor_id=DEFAULT_ACTOR_ID,
                    team_id=team.id,
                    depends_on=depends_on if depends_on else None,
                )
                # 直接设置 status 为 completed（历史数据）
                task.status = "completed"
                created_count += 1
                print(f"  ✅ Task: [{phase_key}-B{batch_num}] {title}")
                prev_batch_task_id = task.id

            # 更新 Phase 间指针
            prev_phase_last_task_id = prev_batch_task_id

        if dry_run:
            total = sum(
                len(info["batches"]) for info in SYNAPSE_PHASES.values()
            )
            print(f"\n📋 DRY RUN 完成 — 将创建 {total} 个 Task（跳过 {skipped_count} 个已存在）")
        else:
            await db.commit()
            print(f"\n✅ Synapse 自举数据录入完成")
            print(f"   新建: {created_count} 个 Task")
            print(f"   跳过: {skipped_count} 个已存在")
            print(f"   Phase: {len(PHASE_ORDER)} 个")
            print(f"\n💡 运行 'make db-backup' 备份当前状态。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synapse 自举数据录入")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="预览将要创建的内容，不实际写入",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))

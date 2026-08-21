"""State-Router 服务 — heartbeat 的确定性路由（P16-B2）。

把 heartbeat 从「纯健康检查」升级为「路由信号源」：给定 worker + project，
返回 role / next_action / active_task_id / queue 计数，供 headless worker
driver loop（P16-B3 ``start-worker.sh``）轮询决策，无需人类读任务列表。

队列计数是 **project 全局共享真相**；``next_action`` 是**角色特定**的解读：

- orchestrator：``verify`` > ``split`` > ``assign`` > ``monitor`` > ``idle``
  （对应 role-orchestrator.md §「5 态路由矩阵」）
- builder（及非 orchestrator 角色）：``execute`` > ``claim`` > ``idle``
  （对应 role-builder.md §「自主驱动循环」）

设计依据：docs/plans/p16-scope.md §「O 驱动模型」+ §「机制方案」。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ProjectRole, TaskStatus
from src.models.task import Task
from src.models.worker import Worker
from src.services.project_role_service import get_project_role, get_worker_projects
from src.services.template_service import resolve_role

# ── next_action 取值 ────────────────────────────────────────────────
NEXT_ACTION_VERIFY = "verify"      # O：有 in_verification 待验收
NEXT_ACTION_SPLIT = "split"        # O：有 backlog 待拆解
NEXT_ACTION_ASSIGN = "assign"      # O：有 ready 待分配
NEXT_ACTION_MONITOR = "monitor"    # O：in_progress 监工
NEXT_ACTION_EXECUTE = "execute"    # B：有活跃任务执行/提交
NEXT_ACTION_CLAIM = "claim"        # B：有 ready 待认领
NEXT_ACTION_IDLE = "idle"          # 全空 / 无法路由

# 队列桶用 API 状态名（in_verification → awaiting_verify），
# 避免 scope 中「submitted」这个不存在的状态名踩坑。
_QUEUE_KEYS = ("backlog", "ready", "in_progress", "awaiting_verify")


async def _count_queue(db: AsyncSession, project_id: str) -> dict[str, int]:
    """单条 grouped query 计数 project 任务队列。

    rejected / paused / 终态不入桶 —— rejected 重做走 B 既有 claim fallback
    （claim 端点接受 REJECTED → IN_PROGRESS），不重复计数。
    """
    result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.project_id == project_id)
        .group_by(Task.status)
    )
    counts: dict[str, int] = {status: n for status, n in result.all()}
    return {
        "backlog": counts.get(TaskStatus.BACKLOG.value, 0),
        "ready": counts.get(TaskStatus.READY.value, 0),
        "in_progress": counts.get(TaskStatus.IN_PROGRESS.value, 0),
        "awaiting_verify": counts.get(TaskStatus.IN_VERIFICATION.value, 0),
    }


def _route(role: str, queue: dict[str, int], active_task_id: str | None) -> str:
    """按角色路由 next_action（确定性，命中即停）。"""
    if role == ProjectRole.ORCHESTRATOR:
        if queue["awaiting_verify"] > 0:
            return NEXT_ACTION_VERIFY
        if queue["backlog"] > 0:
            return NEXT_ACTION_SPLIT
        if queue["ready"] > 0:
            return NEXT_ACTION_ASSIGN
        if queue["in_progress"] > 0:
            return NEXT_ACTION_MONITOR
        return NEXT_ACTION_IDLE

    # builder（及 steward 等非 orchestrator 角色）
    if active_task_id:
        return NEXT_ACTION_EXECUTE
    if queue["ready"] > 0:
        return NEXT_ACTION_CLAIM
    return NEXT_ACTION_IDLE


async def compute_state_router(
    db: AsyncSession,
    worker: Worker,
    project_id: str | None,
) -> dict:
    """Compute heartbeat 的确定性路由。

    返回 ``{role, next_action, active_task_id, queue, role_warnings}``。
    project 解析失败（无/多项目且未显式给 ``project_id``）时返回
    ``next_action="idle"`` + ``queue=None``，并附加 role_warnings 提示。
    """
    role: str | None
    # ── 1. 解析 project（入参优先 → 单项目自动回退）───────────────
    if project_id is None:
        projects = await get_worker_projects(db, worker.id)
        if len(projects) == 0:
            role, _ = resolve_role(worker)
            return {
                "role": role,
                "next_action": NEXT_ACTION_IDLE,
                "active_task_id": worker.active_task_id,
                "queue": None,
                "role_warnings": [
                    "Worker 无 Project 归属，state-router 无法路由，返回 idle。"
                ],
            }
        if len(projects) > 1:
            role, _ = resolve_role(worker)
            return {
                "role": role,
                "next_action": NEXT_ACTION_IDLE,
                "active_task_id": worker.active_task_id,
                "queue": None,
                "role_warnings": [
                    f"Worker 归属 {len(projects)} 个 Project，"
                    "请在 heartbeat 请求体带 project_id 指定作用域。"
                ],
            }
        project_id = projects[0]["project_id"]

    # ── 2. 解析 role（project role 优先 → worker metadata 回退）────
    role = await get_project_role(db, project_id, worker.id)
    if role is None:
        role, _ = resolve_role(worker)

    # ── 3. queue 计数 + 4. next_action 路由 ────────────────────────
    queue = await _count_queue(db, project_id)
    next_action = _route(role, queue, worker.active_task_id)

    return {
        "role": role,
        "next_action": next_action,
        "active_task_id": worker.active_task_id,
        "queue": queue,
        "role_warnings": [],
    }

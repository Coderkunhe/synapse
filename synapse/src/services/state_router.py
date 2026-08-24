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
from src.services.task_query import filter_dependency_blocked
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

    # P16-B5 (PFL-248): ready 桶必须排除 depends_on 未满足的任务。
    # 端点层 claim/assign 会以 TASK_DEPENDENCY_NOT_READY 拒绝它们，若路由层
    # 仍按 ready 计数，O 每轮 assign、B 每轮 claim 同一个 blocked task，双双
    # 空转（B4 狗粮实测）。复用 /tasks/available 的同一份定义，保证两层一致。
    ready_count = counts.get(TaskStatus.READY.value, 0)
    if ready_count:
        ready_rows = await db.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.status == TaskStatus.READY,
            )
        )
        ready_count = len(
            await filter_dependency_blocked(db, list(ready_rows.scalars().all()))
        )

    return {
        "backlog": counts.get(TaskStatus.BACKLOG.value, 0),
        "ready": ready_count,
        "in_progress": counts.get(TaskStatus.IN_PROGRESS.value, 0),
        "awaiting_verify": counts.get(TaskStatus.IN_VERIFICATION.value, 0),
    }


async def _resolve_active_task_id(db: AsyncSession, worker: Worker) -> str | None:
    """返回**仍可执行**的活跃任务 id，否则 None（P16-B5 · 只读）。

    ``worker.active_task_id`` 可能是陈旧指针：任务被取消/暂停/租约回收/改派
    之后，清理并非在所有路径上都发生（``terminate_task``/``pause_task``/
    ``lease_detector`` 原先白嫖「下次心跳会擦」这条路径，而 PFL-247 修复后
    心跳不再无条件擦）。路由层若照单全收，B 会被派去 execute 一个死任务。

    这里做**收口防御**：只有任务存在、仍归本 worker、且处于可继续工作的状态
    时才认。防的是所有 stale 来源，不只已知的那几处。

    只读——``compute_state_router`` 在 ``db.commit()`` 之后运行，此处的写入
    不会被持久化，所以不做清理，只做判断。
    """
    if not worker.active_task_id:
        return None

    task = await db.get(Task, worker.active_task_id)
    if task is None:
        return None
    if task.owner_id != worker.id:
        return None
    if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.REJECTED):
        return None
    return worker.active_task_id


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
    # P16-B5: 活跃任务先过一遍「还能不能干」，陈旧指针不参与路由
    active_task_id = await _resolve_active_task_id(db, worker)
    queue = await _count_queue(db, project_id)
    next_action = _route(role, queue, active_task_id)

    return {
        "role": role,
        "next_action": next_action,
        "active_task_id": active_task_id,
        "queue": queue,
        "role_warnings": [],
    }

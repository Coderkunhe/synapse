"""State-Router 服务 — heartbeat 的确定性路由（P16-B2）。

把 heartbeat 从「纯健康检查」升级为「路由信号源」：给定 worker + project，
返回 role / next_action / active_task_id / queue 计数，供 headless worker
driver loop（P16-B3 ``start-worker.sh``）轮询决策，无需人类读任务列表。

队列计数是 **project 全局共享真相**；``next_action`` 是**角色特定**的解读：

- orchestrator：``verify`` > ``split`` > ``assign`` > ``monitor`` > ``idle``
  （对应 role-orchestrator.md §「5 态路由矩阵」）
- builder（及非 orchestrator 角色）：``execute`` > ``claim`` >
  ``respond_to_mention`` > ``idle``（对应 role-builder.md §「自主驱动循环」）
  —— mention 是「空闲唤醒」非「抢占」：只有落到 idle 才查未读 mention。

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
from src.services.worker_scheduler import get_next_task
from src.services.template_service import resolve_role
from src.services.conversation_service import count_unread_mentions

# ── next_action 取值 ────────────────────────────────────────────────
NEXT_ACTION_VERIFY = "verify"      # O：有 in_verification 待验收
NEXT_ACTION_SPLIT = "split"        # O：有 backlog 待拆解
NEXT_ACTION_ASSIGN = "assign"      # O：有 ready 待分配
NEXT_ACTION_MONITOR = "monitor"    # O：in_progress 监工
NEXT_ACTION_EXECUTE = "execute"    # B：有活跃任务执行/提交
NEXT_ACTION_CLAIM = "claim"        # B：有 ready 待认领
NEXT_ACTION_RESPOND_TO_MENTION = "respond_to_mention"  # B：idle 且有未读 mention（P17-B13）
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


# P16-B5：「Worker 还有没有活」的判定只有一份，与写入层（attach_active_task
# 要不要抢占陈旧指针）共用同一个 resolve_workable_active_task。两层若各自实现，
# 就会重演 PFL-248「端点层拦了、路由层还当它可操作」那一类不一致（PFL-256）。


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
                "unread_mentions": 0,
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
                "unread_mentions": 0,
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
    # P16-B10 (PFL-257): 用 get_next_task 取代 resolve_workable_active_task。
    # 它先过「活跃指针还能不能干」（内部收敛到 resolve_workable_active_task），
    # 指针失效/为空时回落到 FIFO 队列（其它 IN_PROGRESS → REJECTED），
    # 让「已有活跃任务时被 assign/claim 的第二个任务」不再成孤儿。
    next_task = await get_next_task(db, worker.id)
    active_task_id = next_task.id if next_task else None
    queue = await _count_queue(db, project_id)
    next_action = _route(role, queue, active_task_id)

    # ── 5. mention 维度（P17-B13 · 方案 A）─────────────────────────
    # 空闲唤醒而非抢占：有任务先做任务（active→execute > ready→claim），
    # 只有 _route 落到 idle 才查未读 mention，且仅非 orchestrator 角色。
    unread_mentions = 0
    if role != ProjectRole.ORCHESTRATOR and next_action == NEXT_ACTION_IDLE:
        unread_mentions = await count_unread_mentions(
            db, worker.id, project_id=project_id
        )
        if unread_mentions > 0:
            next_action = NEXT_ACTION_RESPOND_TO_MENTION

    return {
        "role": role,
        "next_action": next_action,
        "active_task_id": active_task_id,
        "queue": queue,
        "unread_mentions": unread_mentions,
        "role_warnings": [],
    }

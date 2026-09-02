"""Worker 调度器 — FIFO 任务队列 + 主动状态校验 (P8-B4)。

依据 D5 B4：解决 ``active_task_id``（单任务）与 Batch（多任务）之间的张力。
实现 5 条调度规则：

  1. 同一时间仅一个活跃 Task（由 ``active_task_id`` 单值强制保证）
  2. Creator 驳回的 Task 进入重做队列 — 不抢占当前活跃任务
  3. PAUSED Task 不消耗租约、不阻塞队列
  4. FIFO：先 claimed IN_PROGRESS，再 REJECTED（重做队列）
  5. 阻塞报告 → 自动出队（schema 预留，B7 实现）

同时提供主动状态校验：Worker 在 submit/heartbeat 前检查 Task 状态，
以检测外部状态变更（如 Creator 暂停了任务）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.worker_state_machine import apply_transition as worker_apply_transition
from src.constants import ActorType, OwnerType, TaskStatus, WorkerRuntimeStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.worker import Worker
from src.models.task import Task
from src.services.event_store import event_store
from src.task_state_machine import apply_transition


async def _get_worker(db: AsyncSession, worker_id: str) -> Worker:
    """获取 Worker，不存在则抛出 NotFoundError。"""
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)
    return worker


# ── 队列 / 调度 ─────────────────────────────────────────────────


async def get_next_task(db: AsyncSession, worker_id: str) -> Task | None:
    """返回 Worker 应处理的下一个任务（FIFO）。

    优先级（规则 4）：
      1. 当前活跃任务（若仍处于可工作状态）
      2. Worker 拥有的其他 IN_PROGRESS 任务（已认领，尚未激活）
      3. Worker 拥有的 REJECTED 任务（重做队列）

    PAUSED 和 CANCELLED 任务被排除（规则 3）。
    每个优先级层级内按 claimed_at 排序。

    P16-B10 (PFL-257)：``state_router`` 用它作为路由回落——活跃指针失效/为空时，
    这里仍能按 FIFO 找到 Worker 拥有的其它未完成任务，让「已有活跃任务时被
    assign/claim 的第二个任务」不再成孤儿。
    """
    worker = await _get_worker(db, worker_id)

    # 规则 1：活跃任务——收敛到 resolve_workable_active_task（PFL-256 教训：
    # 「什么算活跃」只有一个判定，不再手写第二份）。它覆盖 owner 校验，且排除
    # PAUSED/CANCELLED/已提交/改派（旧手写实现漏了 owner_type 检查）。
    workable_active_id = await resolve_workable_active_task(db, worker)
    if workable_active_id:
        return await db.get(Task, workable_active_id)

    # 查找下一个：先 IN_PROGRESS（按认领时间），再 REJECTED
    # SQL 排序：False (IN_PROGRESS) 排在 True (REJECTED) 之前
    stmt = (
        select(Task)
        .where(
            Task.owner_id == worker_id,
            Task.owner_type == OwnerType.WORKER,
            Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.REJECTED]),
        )
        .order_by(
            (Task.status == TaskStatus.REJECTED).asc(),  # IN_PROGRESS 优先于 REJECTED
            Task.claimed_at.asc().nulls_last(),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def resolve_workable_active_task(
    db: AsyncSession, worker: Worker
) -> str | None:
    """返回 Worker **仍可执行**的活跃任务 id，否则 None（只读）。

    P16-B5：``worker.active_task_id`` 可能是陈旧指针——任务被取消/暂停/租约
    回收/改派之后，并非所有路径都会清理它（``terminate_task``/``pause_task``/
    ``lease_detector`` 原先白嫖「下次心跳会擦」这条路径，见 PFL-254）。

    **「Worker 到底有没有活」必须只有一个判定。** 写入层（``attach_active_task``
    要不要抢占）和路由层（``state_router`` 要不要派 execute）都用这一个，
    否则两层各说各话：路由层认为陈旧值无效、写入层却认为它有效不可抢占 →
    新认领的任务永远挂不上，B 卡死（PFL-256）。

    只读——``state_router`` 在 ``db.commit()`` 之后调用，写入不会被持久化。
    """
    if not worker.active_task_id:
        return None

    task = await db.get(Task, worker.active_task_id)
    if task is None:
        return None
    if task.owner_id != worker.id or task.owner_type != OwnerType.WORKER:
        return None
    if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.REJECTED):
        return None
    return worker.active_task_id


async def attach_active_task(
    db: AsyncSession, worker: Worker, task_id: str
) -> Worker:
    """把 ``task_id`` 挂为 Worker 的活跃任务（幂等 · 不抢占）。

    P16-B5 (PFL-247)：``claim``/``assign``/``start`` 三条「让 Worker 有活干」
    的路径共用此入口——**谁让 Worker 有活干，谁就要告诉 state_router**。
    此前只有 ``start`` 写 ``active_task_id``，而 headless driver 的循环里
    根本没有 ``start`` 这一步，导致 ``state_router`` 永远路由不到 ``execute``
    （B4 狗粮 claim→execute 断裂）。

    语义：
      - 已挂同一个 task → 幂等（仅在 IDLE 时补一次 IDLE→BUSY）
      - 已挂**其它** task → 不抢占，保持 FIFO 首个（调度规则 1/2），静默返回
      - 未挂 → 挂上 + 刷新 ``last_progress_at``，且**仅当 IDLE** 才转 BUSY
        （状态机禁止 BUSY→BUSY / ERROR→BUSY，见 worker_state_machine._TRANSITIONS）
    """
    if worker.active_task_id is not None and worker.active_task_id != task_id:
        # 已有其它活跃任务 —— 但先确认它「还能不能干」。仍可执行 → 不抢占
        # （规则 1：同一时间仅一个活跃 Task）；已失效（取消/改派/已提交）→
        # 陈旧指针必须让位，否则新认领的任务永远挂不上，B 卡死（PFL-256）。
        if await resolve_workable_active_task(db, worker) is not None:
            return worker
        worker.active_task_id = None   # 顺手清掉陈旧指针（本函数在写事务内）

    if worker.active_task_id is None:
        worker.active_task_id = task_id
        worker.last_progress_at = datetime.now(timezone.utc)

    if worker.runtime_status == WorkerRuntimeStatus.IDLE:
        rt_event_type, rt_payload = worker_apply_transition(
            worker, WorkerRuntimeStatus.BUSY,
            actor_type=ActorType.WORKER, actor_id=worker.id,
            context={"task_id": task_id},
        )
        await event_store.record(
            db,
            event_type=rt_event_type,
            team_id=worker.team_id,
            actor_type=ActorType.WORKER,
            actor_id=worker.id,
            target_type="worker",
            target_id=worker.id,
            payload=rt_payload,
        )

    return worker


async def start_task(
    db: AsyncSession, worker_id: str, task_id: str
) -> Worker:
    """设置 Worker 的活跃任务并将运行时状态转为 BUSY。

    当 Worker 开始处理任务时调用。
    校验任务属于此 Worker。
    若任务为 REJECTED (P8-B5)，通过状态机将其转回 IN_PROGRESS。

    P16-B5：``claim``/``assign`` 现在已经把任务挂上了，所以对**同一个** task
    再调 start 是幂等 no-op（此前会因 BUSY→BUSY 抛 InvalidStateTransition）。
    Worker 持有**其它**活跃任务时抛 ``WORKER_BUSY``——保住「同一时间仅一个
    活跃 Task」不变式，且比 InvalidStateTransition 的报错清晰。
    """
    worker = await _get_worker(db, worker_id)

    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("task", task_id)
    if task.owner_id != worker_id or task.owner_type != OwnerType.WORKER:
        raise ConflictError(
            "TASK_NOT_OWNED_BY_WORKER",
            f"Task {task_id} is not owned by worker {worker_id}",
        )
    if worker.active_task_id is not None and worker.active_task_id != task_id:
        raise ConflictError(
            "WORKER_BUSY",
            f"Worker {worker_id} is already active on task {worker.active_task_id}. "
            f"Submit or release it before starting {task_id}.",
            {"workerId": worker_id, "activeTaskId": worker.active_task_id},
        )

    # P8-B5: Worker 重新介入时将 REJECTED → IN_PROGRESS
    if task.status == TaskStatus.REJECTED:
        event_type, payload = apply_transition(
            task, TaskStatus.IN_PROGRESS,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            context={"rework": True, "redo_count": task.redo_count},
        )
        # 内联写入事件（start_task 在 DB 事务内调用）
        await event_store.record(
            db,
            event_type=event_type,
            team_id=worker.team_id,
            actor_type=ActorType.WORKER,
            actor_id=worker_id,
            target_type="task",
            target_id=task.id,
            payload=payload,
        )

    # P16-B5: 挂载/幂等复用统一走 attach_active_task（含 IDLE→BUSY 状态机转换）
    return await attach_active_task(db, worker, task_id)


async def finish_current_task(db: AsyncSession, worker_id: str) -> Worker:
    """清除活跃任务并将运行时状态转为 IDLE。

    在 Worker 提交任务或任务以其他方式完成/释放后调用。

    P8-B8: Worker 运行时 BUSY → IDLE 通过状态机（替代直接赋值）。
    """
    worker = await _get_worker(db, worker_id)
    worker.active_task_id = None

    # P8-B8: 通过状态机写入 Worker 运行时事件
    if worker.runtime_status == WorkerRuntimeStatus.BUSY:
        rt_event_type, rt_payload = worker_apply_transition(
            worker, WorkerRuntimeStatus.IDLE,
            actor_type=ActorType.SYSTEM, actor_id="worker_scheduler",
            context={"previous_task_complete": True},
        )
        await event_store.record(
            db,
            event_type=rt_event_type,
            team_id=worker.team_id,
            actor_type=ActorType.SYSTEM,
            actor_id="worker_scheduler",
            target_type="worker",
            target_id=worker.id,
            payload=rt_payload,
        )
    else:
        # 已处于 IDLE 或 ERROR — 仅清除引用
        # P100-B15 C1: ERROR 状态不覆盖为 IDLE，保持故障语义
        if worker.runtime_status != WorkerRuntimeStatus.ERROR:
            worker.runtime_status = WorkerRuntimeStatus.IDLE

    return worker


async def release_active_task(
    db: AsyncSession, worker_id: str | None, task_id: str
) -> Worker | None:
    """仅当 ``worker.active_task_id`` 指向 ``task_id`` 时清空（PFL-254）。

    比 ``finish_current_task`` 保守：后者**无条件**清空指针。若 Worker 同时拥有
    多个任务（如 claim t1 后又 claim t2，t2 成孤儿，active 仍 t1），租约回收 t2
    时无条件清空会误杀 t1 的指针 —— 必须只清「指向本 task」的那个。

    ``worker_id`` 为 None / 非 Worker（member / 已删）时安全 no-op ——
    ``db.get(Worker, ...)`` 返回 None，天然挡掉。
    """
    if worker_id is None:
        return None
    worker = await db.get(Worker, worker_id)
    if worker is not None and worker.active_task_id == task_id:
        await finish_current_task(db, worker_id)
    return worker


# ── 主动状态校验 ─────────────────────────────────────────


async def validate_task_active(db: AsyncSession, worker_id: str) -> dict:
    """主动状态检查 — 验证 Worker 的活跃任务是否仍可继续工作。

    依据 D5 B4：Worker 应在 ``submit`` / ``heartbeat`` 前检查 Task 状态，
    以检测外部状态变更（如 Creator 在 Worker 计算期间暂停或取消了任务）。
    WS 通知是尽力而为的；此检查是权威检查。

    返回：
        ``{"ok": True}`` 或 ``{"ok": False, "reason": str, "task_status": str}``。
        当 ``ok=False`` 时 Worker 应停止计算并同步状态。
    """
    worker = await _get_worker(db, worker_id)

    if not worker.active_task_id:
        return {"ok": True, "reason": "no_active_task"}

    task = await db.get(Task, worker.active_task_id)
    if task is None:
        # 任务已被删除 — 清除过时引用
        worker.active_task_id = None
        return {"ok": False, "reason": "task_deleted"}

    # Worker 必须停止工作的状态
    if task.status == TaskStatus.PAUSED:
        return {"ok": False, "reason": "task_paused", "task_status": TaskStatus.PAUSED}
    if task.status == TaskStatus.CANCELLED:
        return {"ok": False, "reason": "task_cancelled", "task_status": TaskStatus.CANCELLED}
    if task.status == TaskStatus.IN_VERIFICATION:
        return {"ok": False, "reason": "task_already_submitted", "task_status": TaskStatus.IN_VERIFICATION}
    if task.status in (TaskStatus.COMPLETED, TaskStatus.REJECTED):
        return {"ok": False, "reason": "task_no_longer_active", "task_status": task.status}
    if task.owner_id != worker_id:
        return {"ok": False, "reason": "task_reassigned", "task_status": task.status}

    return {"ok": True}


async def get_owned_tasks(
    db: AsyncSession, worker_id: str, *, limit: int = 20
) -> list[Task]:
    """返回 Worker 当前拥有的所有任务，按队列优先级排序。

    用于 Worker 展示其完整队列（仪表盘/调试）。
    """
    stmt = (
        select(Task)
        .where(
            Task.owner_id == worker_id,
            Task.owner_type == OwnerType.WORKER,
            Task.status.in_([TaskStatus.IN_PROGRESS, TaskStatus.REJECTED]),
        )
        .order_by(
            (Task.status == TaskStatus.REJECTED).asc(),
            Task.claimed_at.asc().nulls_last(),
        )
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())

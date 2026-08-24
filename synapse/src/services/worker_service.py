"""Worker 服务 — 注册、握手、心跳、CRUD。

Worker 注册时生成 API 密钥（明文仅返回一次）。
握手激活 Worker 并持久化声明的能力。
心跳更新运行时列（P8-B2：使用专用列，而非 JSON metadata）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.worker_state_machine import apply_transition as apply_runtime_transition
from src.auth import generate_api_key
from src.constants import ActorType, BatchStatus, TaskStatus, WorkerActorType, WorkerRuntimeStatus, WorkerStatus
from src.exceptions import ConflictError, NotFoundError
from src.models.worker import Worker
from src.models.batch import Batch
from src.models.capability import Capability
from src.models.task import Task
from src.services.event_store import event_store
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps, safe_loads


class _UnsetType:
    """哨兵类型 — 区分「字段缺省」与「显式传 null」（P16-B5 PFL-247）。

    心跳请求体里 ``current_task_id`` 缺省时不能等同于 ``None``：driver 每轮
    心跳都不带这个字段，若按 ``None`` 处理就会把 claim 挂上的活跃任务擦掉。
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - 仅调试可读性
        return "<UNSET>"


UNSET = _UnsetType()


# ── Worker CRUD ────────────────────────────────────────────────────

async def register_worker(
    db: AsyncSession,
    *,
    team_id: str,
    name: str,
    provider: str,
    provider_model: str | None,
    system_prompt: str | None,
    metadata: dict | None,
    registered_by: str | None = None,  # 注册此 Agent 的 worker_id — 系统自建为 None
    actor_type: str,
    actor_id: str,
    batch_size: int = 3,  # P9-B57
    worker_actor_type: str = WorkerActorType.AGENT,  # P10-B2: human | agent
    project_id: str | None = None,  # PFL-105 (B106)
    project_role: str | None = None,  # PFL-105 (B106)
) -> tuple[Worker, str]:
    """注册新 Worker 并生成 API 密钥。

    返回：
        (worker, plaintext_api_key) — 明文密钥仅显示一次。
    """
    worker_id = generate_id("worker")
    plaintext_key, key_hash = generate_api_key(worker_id)

    worker = Worker(
        id=worker_id,
        actor_type=worker_actor_type,
        team_id=team_id,
        name=name,
        provider=provider,
        provider_model=provider_model,
        registered_by=registered_by,
        api_key_hash=key_hash,
        api_key_prefix=plaintext_key[:12],
        status=WorkerStatus.PENDING,
        system_prompt=system_prompt,
        metadata_=safe_dumps(metadata),
        batch_size=batch_size,  # P9-B57
        create_user_id=actor_id,
    )
    db.add(worker)

    # 记录事件
    await event_store.record(
        db,
        event_type="worker.registered",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={
            "name": name,
            "provider": provider,
            "status": WorkerStatus.PENDING,
        },
    )

    # PFL-105 (B106): 自动分配 Project 角色
    if project_id is not None:
        from src.services.project_role_service import set_project_role

        effective_role = project_role or "builder"
        await set_project_role(
            db,
            project_id=project_id,
            worker_id=worker_id,
            role=effective_role,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
        )

    return worker, plaintext_key


async def worker_handshake(
    db: AsyncSession,
    worker_id: str,
    *,
    worker_version: str,
    capabilities: list[dict],
    supported_events: list[str],
    preferred_channel: str,
) -> Worker:
    """Worker 握手：激活 Worker 并持久化声明的能力。"""
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    # 更新 Worker 状态和元数据
    previous_status = worker.status
    worker.status = WorkerStatus.ACTIVE

    # P11-B81 PFL-065: handshake 同步更新 last_heartbeat_at
    # handshake 已完成一次网络往返证明 Worker 在线 → 更新心跳时间戳
    # 避免 stale detector 误杀刚握手的 Worker（只调 handshake 不调 heartbeat）
    worker.last_heartbeat_at = datetime.now(timezone.utc)

    # 在 worker 上存储握手元数据
    handshake_meta = {
        "worker_version": worker_version,
        "supported_events": supported_events,
        "preferred_channel": preferred_channel,
        "last_handshake_at": datetime.now(timezone.utc).isoformat(),
    }
    existing_meta = safe_loads(worker.metadata_) or {}
    existing_meta.update(handshake_meta)
    worker.metadata_ = safe_dumps(existing_meta)

    # 移除旧能力并持久化新能力
    existing_caps = await db.execute(
        select(Capability).where(Capability.worker_id == worker_id)
    )
    for cap in existing_caps.scalars().all():
        await db.delete(cap)

    cap_names: list[str] = []
    for cap_decl in capabilities:
        cap = Capability(
            id=generate_id("capability"),
            worker_id=worker_id,
            name=cap_decl["name"],
            description=cap_decl.get("description"),
            input_schema=safe_dumps(cap_decl.get("input_schema")),
            output_schema=safe_dumps(cap_decl.get("output_schema")),
        )
        db.add(cap)
        cap_names.append(cap_decl["name"])

    # 填充反范式化的能力标签（P8-B2：数据驱动，来自真实数据）
    worker.capability_tags = {"names": cap_names, "count": len(cap_names)}

    # 首次握手时初始化运行时字段；OFFLINE 恢复时重置为 IDLE（P11-B128）
    if worker.runtime_status is None or worker.runtime_status == WorkerRuntimeStatus.OFFLINE:
        worker.runtime_status = WorkerRuntimeStatus.IDLE

    # 记录事件
    await event_store.record(
        db,
        event_type="worker.handshake",
        team_id=worker.team_id,
        actor_type=ActorType.WORKER,
        actor_id=worker_id,
        target_type="worker",
        target_id=worker_id,
        payload={
            "previous_status": previous_status,
            "new_status": WorkerStatus.ACTIVE,
            "worker_version": worker_version,
            "capability_count": len(capabilities),
            "supported_events": supported_events,
            "preferred_channel": preferred_channel,
        },
    )

    return worker


async def worker_heartbeat(
    db: AsyncSession,
    worker_id: str,
    *,
    current_load: int = 0,
    current_task_id: str | None | _UnsetType = UNSET,
    progress_summary: str | None = None,
) -> tuple[Worker, str | None]:
    """Worker 心跳 — 更新运行时列 (P8-B2)。

    更新 ``last_heartbeat_at`` 和可选的 ``active_task_id``。
    如果 Worker 之前处于 ERROR 状态，成功的心跳会将其转回 IDLE（恢复）。

    ``current_task_id`` 三态语义（P16-B5 PFL-247）：

    ==================  ====================================
    传入                 行为
    ==================  ====================================
    缺省（``UNSET``）    **保持** 现有 ``active_task_id`` 不变
    显式 ``None``        清空活跃任务（BUSY→IDLE）
    task id              挂上/切换活跃任务（IDLE→BUSY）
    ==================  ====================================

    返回：
        (worker, recovery_event_type_or_None)。
    """
    worker = await db.get(Worker, worker_id)
    if worker is None:
        raise NotFoundError("worker", worker_id)

    now = datetime.now(timezone.utc)
    recovery_event: str | None = None

    # 心跳始终更新 last_heartbeat_at
    worker.last_heartbeat_at = now

    # ── 追踪活跃任务变更（P16-B5 PFL-247：缺省 = 保持，显式 null = 清空）──
    # 旧实现无条件 `worker.active_task_id = current_task_id`，而 headless
    # driver 每轮心跳都不带这个字段 → 每跳把 claim 挂上的活跃任务擦成 None
    # → state_router 永远路由不到 execute（B4 狗粮死循环的读取端根因）。
    if not isinstance(current_task_id, _UnsetType):
        if current_task_id is not None and current_task_id != worker.active_task_id:
            # Worker 开始或切换任务 → 标记进度
            worker.last_progress_at = now
        worker.active_task_id = current_task_id

    # 运行时状态按「Worker 实际有没有活」判定，而不是按本次心跳带没带字段
    effective_task_id = worker.active_task_id

    # 将负载和摘要存入 metadata 以保持向后兼容（现有消费者）
    existing_meta = safe_loads(worker.metadata_) or {}
    existing_meta["current_load"] = current_load
    if effective_task_id:
        existing_meta["current_task_id"] = effective_task_id
    if progress_summary:
        existing_meta["progress_summary"] = progress_summary
    worker.metadata_ = safe_dumps(existing_meta)

    # 运行时状态转换
    if worker.runtime_status in (WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE):
        # Worker 已恢复 → IDLE（ERROR 恢复 or OFFLINE 重连）
        event_type, payload = apply_runtime_transition(
            worker, WorkerRuntimeStatus.IDLE,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            context={
                "recovery": True,
                "previous_status": worker.runtime_status,
                "current_task_id": effective_task_id,
            },
        )
        await event_store.record(
            db, event_type=event_type, team_id=worker.team_id,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            target_type="worker", target_id=worker_id, payload=payload,
        )
        recovery_event = event_type
    elif effective_task_id and worker.runtime_status == WorkerRuntimeStatus.IDLE:
        # Worker 接收到工作 → BUSY
        event_type, payload = apply_runtime_transition(
            worker, WorkerRuntimeStatus.BUSY,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            context={"current_task_id": effective_task_id},
        )
        await event_store.record(
            db, event_type=event_type, team_id=worker.team_id,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            target_type="worker", target_id=worker_id, payload=payload,
        )
    elif not effective_task_id and worker.runtime_status == WorkerRuntimeStatus.BUSY:
        # Worker 完成工作 → IDLE
        event_type, payload = apply_runtime_transition(
            worker, WorkerRuntimeStatus.IDLE,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            context={"previous_task_complete": True},
        )
        await event_store.record(
            db, event_type=event_type, team_id=worker.team_id,
            actor_type=ActorType.WORKER, actor_id=worker_id,
            target_type="worker", target_id=worker_id, payload=payload,
        )

    return worker, recovery_event


async def get_worker(db: AsyncSession, worker_id: str) -> Worker:
    """按 ID 获取 Worker（含任务计数子查询），未找到则抛出 NotFoundError。"""
    active_subq = (
        select(func.count(Task.id))
        .where(Task.owner_id == Worker.id, Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]))
        .correlate(Worker)
        .scalar_subquery()
        .label("active_task_count")
    )
    completed_subq = (
        select(func.count(Task.id))
        .where(Task.owner_id == Worker.id, Task.status == TaskStatus.COMPLETED)
        .correlate(Worker)
        .scalar_subquery()
        .label("completed_task_count")
    )
    active_batches_subq = (
        select(func.count(Batch.id))
        .where(
            Batch.assigned_worker_id == Worker.id,
            Batch.status.notin_([BatchStatus.COMPLETED, BatchStatus.CANCELLED]),
        )
        .correlate(Worker)
        .scalar_subquery()
        .label("active_batches")
    )
    result = await db.execute(
        select(Worker, active_subq, completed_subq, active_batches_subq).where(Worker.id == worker_id)
    )
    row = result.one_or_none()
    if row is None:
        raise NotFoundError("worker", worker_id)
    worker = row[0]
    worker._active_task_count = row[1]  # type: ignore[attr-defined]
    worker._completed_task_count = row[2]  # type: ignore[attr-defined]
    worker._active_batches = row[3]  # type: ignore[attr-defined]
    return worker


async def list_workers(
    db: AsyncSession,
    team_id: str,
    *,
    cursor: str | None = None,
    limit: int = 50,
    status: str | None = None,
) -> tuple[list[Worker], str | None, int | None]:
    """游标分页列出团队中的 Worker。

    status 可选过滤：
    - ``"active"`` — 仅未暂停（is_disabled=False）
    - ``"suspended"`` — 仅已暂停（is_disabled=True）
    - ``None`` 或 ``"all"`` — 不过滤
    """
    conditions = [Worker.team_id == team_id]
    if cursor:
        conditions.append(Worker.id > cursor)
    if status == WorkerStatus.ACTIVE:
        conditions.append(Worker.is_disabled == False)
    elif status == "suspended":
        conditions.append(Worker.is_disabled == True)

    # ── Task count subqueries (P9-B73a) ──────────────────────────
    active_subq = (
        select(func.count(Task.id))
        .where(Task.owner_id == Worker.id, Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]))
        .correlate(Worker)
        .scalar_subquery()
        .label("active_task_count")
    )
    completed_subq = (
        select(func.count(Task.id))
        .where(Task.owner_id == Worker.id, Task.status == TaskStatus.COMPLETED)
        .correlate(Worker)
        .scalar_subquery()
        .label("completed_task_count")
    )
    active_batches_subq = (
        select(func.count(Batch.id))
        .where(
            Batch.assigned_worker_id == Worker.id,
            Batch.status.notin_([BatchStatus.COMPLETED, BatchStatus.CANCELLED]),
        )
        .correlate(Worker)
        .scalar_subquery()
        .label("active_batches")
    )

    stmt = (
        select(Worker, active_subq, completed_subq, active_batches_subq)
        .where(*conditions)
        .order_by(Worker.id)
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.all()

    has_more = len(rows) > limit
    row_slice = rows[:limit]
    next_cursor = row_slice[-1][0].id if has_more and row_slice else None

    # Attach task counts to Worker objects
    items: list[Worker] = []
    for worker, active_cnt, completed_cnt, active_batches_cnt in row_slice:
        worker._active_task_count = active_cnt  # type: ignore[attr-defined]
        worker._completed_task_count = completed_cnt  # type: ignore[attr-defined]
        worker._active_batches = active_batches_cnt  # type: ignore[attr-defined]
        items.append(worker)

    count_stmt = select(func.count(Worker.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


async def suspend_worker(
    db: AsyncSession,
    worker_id: str,
    *,
    actor_type: str,
    actor_id: str,
) -> Worker:
    """暂停 Worker 帐号（设置 is_disabled = True）。"""
    worker = await get_worker(db, worker_id)

    if worker.is_disabled:
        raise ConflictError(code="WORKER_ALREADY_SUSPENDED", message=f"Worker {worker_id} is already suspended")

    worker.is_disabled = True

    await event_store.record(
        db,
        event_type="worker.suspended",
        team_id=worker.team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={"previous_status": worker.status},
    )

    return worker


async def resume_worker(
    db: AsyncSession,
    worker_id: str,
    *,
    actor_type: str,
    actor_id: str,
) -> Worker:
    """恢复 Worker 帐号（设置 is_disabled = False）。"""
    worker = await get_worker(db, worker_id)

    if not worker.is_disabled:
        raise ConflictError(code="WORKER_NOT_SUSPENDED", message=f"Worker {worker_id} is not suspended")

    worker.is_disabled = False

    await event_store.record(
        db,
        event_type="worker.resumed",
        team_id=worker.team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={"previous_status": worker.status},
    )

    return worker


async def deactivate_worker(
    db: AsyncSession,
    worker_id: str,
    *,
    actor_type: str,
    actor_id: str,
) -> Worker:
    """软停用 Worker（状态 → inactive）。"""
    worker = await get_worker(db, worker_id)

    previous_status = worker.status
    worker.status = WorkerStatus.INACTIVE

    await event_store.record(
        db,
        event_type="worker.deactivated",
        team_id=worker.team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={
            "previous_status": previous_status,
            "new_status": WorkerStatus.INACTIVE,
        },
    )

    return worker


async def hard_delete_worker(
    db: AsyncSession,
    worker_id: str,
    *,
    actor_type: str,
    actor_id: str,
) -> None:
    """硬删除 Worker — 物理删除行 + 级联清理 capabilities。

    ORM ``cascade="all, delete-orphan"`` 自动清理关联的 capabilities。
    Tasks/Events/Scans 中的字符串引用会成为悬空引用（已知 trade-off）。
    """
    worker = await get_worker(db, worker_id)
    team_id = worker.team_id

    # ORM delete — cascade 自动清理 capabilities
    await db.delete(worker)

    # 记录事件（在 commit 前，worker 对象仍可访问）
    await event_store.record(
        db,
        event_type="worker.deleted",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="worker",
        target_id=worker_id,
        payload={
            "name": worker.name,
            "status": worker.status,
        },
    )


def worker_to_response(worker: Worker) -> dict:
    """将 Worker ORM 对象转换为带 JSON 反序列化的响应字典。"""
    return {
        "id": worker.id,
        "actor_type": worker.actor_type,
        "user_id": worker.user_id,
        "team_id": worker.team_id,
        "name": worker.name,
        "provider": worker.provider,
        "provider_model": worker.provider_model,
        "status": worker.status,
        "runtime_status": worker.runtime_status,
        "last_heartbeat_at": worker.last_heartbeat_at,
        "last_progress_at": worker.last_progress_at,
        "active_task_id": worker.active_task_id,
        "capability_tags": worker.capability_tags,
        "system_prompt": worker.system_prompt,
        "metadata": safe_loads(worker.metadata_),
        "is_disabled": worker.is_disabled,
        "create_user_id": worker.create_user_id,
        "last_update_user_id": worker.last_update_user_id,
        "remark": worker.remark,
        "version_no": worker.version_no,
        "created_at": worker.created_at,
        "updated_at": worker.updated_at,
        "batch_size": worker.batch_size,  # P9-B57
        "active_task_count": getattr(worker, "_active_task_count", 0),
        "completed_task_count": getattr(worker, "_completed_task_count", 0),
        "active_batches": getattr(worker, "_active_batches", 0),
    }


# B92: O 活动事件类型 — 证明 O 在线（即使 heartbeat daemon 短暂故障）
_O_ACTIVITY_EVENT_TYPES = frozenset({
    "task.created",
    "task.assigned",
    "verification.executed",
    "batch.created",
    "batch.assigned",
})


async def _get_latest_activity_age(
    db: AsyncSession,
    worker_id: str,
    cutoff: datetime,
) -> int | None:
    """查询 Worker 在 cutoff 之后的最新 Event 活动年龄（秒）。

    Event.created_at 是 naive UTC（SQLite），需 normalize 后再计算。
    返回 None 表示 cutoff 内无活动。
    """
    from src.models.event import Event

    stmt = (
        select(Event.created_at)
        .where(
            Event.actor_id == worker_id,
            Event.event_type.in_(_O_ACTIVITY_EVENT_TYPES),
            Event.created_at >= cutoff,
        )
        .order_by(Event.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None

    latest = row
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    return int((datetime.now(timezone.utc) - latest).total_seconds())


async def get_orchestrator_status(
    db: AsyncSession,
    project_id: str,
    *,
    heartbeat_timeout_seconds: int = 120,
) -> dict:
    """查询 Project 中 O 的心跳状态（PFL-070 · B87 · B92 双源增强）。

    通过 project_actor_roles 找到 orchestrator 角色的 Worker，
    双源判定在线状态：
    1. 主源：last_heartbeat_at 是否在阈值内
    2. 次源（B92）：heartbeat 过期时检查 Event 表近期 O 活动事件

    Returns:
        dict with keys: online, worker_id, worker_name,
        last_heartbeat_at, heartbeat_age_seconds, detection_source
    """
    from datetime import datetime, timedelta, timezone

    from src.models.project_actor_role import ProjectActorRole

    # 查找 project 中 role=orchestrator 的 Worker
    result = await db.execute(
        select(Worker)
        .join(ProjectActorRole, ProjectActorRole.worker_id == Worker.id)
        .where(
            ProjectActorRole.project_id == project_id,
            ProjectActorRole.role == "orchestrator",
            Worker.status == WorkerStatus.ACTIVE,
        )
        .limit(1)
    )
    orchestrator = result.scalar_one_or_none()

    if orchestrator is None:
        return {
            "online": False,
            "worker_id": None,
            "worker_name": None,
            "last_heartbeat_at": None,
            "heartbeat_age_seconds": None,
            "detection_source": None,
        }

    now = datetime.now(timezone.utc)
    last_hb = orchestrator.last_heartbeat_at
    # Normalize to UTC-aware: SQLite stores naive UTC, subtraction requires same type
    if last_hb is not None and last_hb.tzinfo is None:
        last_hb = last_hb.replace(tzinfo=timezone.utc)
    hb_age = (
        int((now - last_hb).total_seconds())
        if last_hb is not None
        else None
    )

    # 主源：心跳判定
    if hb_age is not None and hb_age <= heartbeat_timeout_seconds:
        return {
            "online": True,
            "worker_id": orchestrator.id,
            "worker_name": orchestrator.name,
            "last_heartbeat_at": orchestrator.last_heartbeat_at,
            "heartbeat_age_seconds": hb_age,
            "detection_source": "heartbeat",
        }

    # 次源（B92）：心跳过期 → 检查 Event 活动
    cutoff = now - timedelta(seconds=heartbeat_timeout_seconds)
    event_age = await _get_latest_activity_age(db, orchestrator.id, cutoff)
    if event_age is not None:
        return {
            "online": True,
            "worker_id": orchestrator.id,
            "worker_name": orchestrator.name,
            "last_heartbeat_at": orchestrator.last_heartbeat_at,
            "heartbeat_age_seconds": hb_age,
            "detection_source": "event_activity",
        }

    # 双源皆无 → 离线
    return {
        "online": False,
        "worker_id": orchestrator.id,
        "worker_name": orchestrator.name,
        "last_heartbeat_at": orchestrator.last_heartbeat_at,
        "heartbeat_age_seconds": hb_age,
        "detection_source": None,
    }

"""Worker 运行时状态机 — 所有 Worker 运行时转换的唯一权威来源。

所有 Worker 运行时状态变更必须通过本模块。禁止直接对 ``worker.runtime_status`` 赋值。

设计（依据 P7 D5 B2 + P11-B128 OFFLINE 扩展）：
- 4 个运行时状态：IDLE → BUSY → ERROR → OFFLINE
- IDLE：Worker 空闲，可接受工作（无活跃任务）
- BUSY：Worker 正在处理任务
- ERROR：Worker 心跳/进度检查失败（需恢复）
- OFFLINE：Worker 长时间无心跳，疑似断连（P11-B128 · PFL-126）
- 每次转换产出 (event_type, payload) 元组供 EventStore 使用
- 调用方持有 DB 事务

与 WorkerStatus（生命周期：pending/active/inactive）分离。
只有 WorkerStatus.ACTIVE 的 Worker 参与运行时池。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.constants import WorkerRuntimeStatus
from src.exceptions import InvalidStateTransition

if TYPE_CHECKING:
    from src.models.worker import Worker


# ── 转换白名单 ──────────────────────────────────────────────────────

_TRANSITIONS: dict[str, frozenset[str]] = {
    WorkerRuntimeStatus.IDLE:    frozenset({WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE}),
    WorkerRuntimeStatus.BUSY:    frozenset({WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE}),
    WorkerRuntimeStatus.ERROR:   frozenset({WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.OFFLINE}),
    WorkerRuntimeStatus.OFFLINE: frozenset({WorkerRuntimeStatus.IDLE}),
}


# ── 事件类型映射 ────────────────────────────────────────────────────

_EVENT_TYPE_MAP: dict[tuple[str, str], str] = {
    (WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.BUSY):    "worker.runtime.busy",
    (WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.ERROR):   "worker.runtime.error",
    (WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.OFFLINE): "worker.runtime.offline",
    (WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.IDLE):    "worker.runtime.idle",
    (WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.ERROR):   "worker.runtime.error",
    (WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.OFFLINE): "worker.runtime.offline",
    (WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.IDLE):   "worker.runtime.idle",
    (WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE): "worker.runtime.offline",
    (WorkerRuntimeStatus.OFFLINE, WorkerRuntimeStatus.IDLE): "worker.runtime.idle",
}


# ── 公共 API ────────────────────────────────────────────────────────


def validate_transition(current_status: str, target_status: str) -> None:
    """若转换不被允许则抛出 InvalidStateTransition。

    Args:
        current_status: Worker 当前运行时状态。
        target_status: 期望的目标运行时状态。

    Raises:
        InvalidStateTransition: 若转换不在白名单中。
    """
    allowed = _TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed:
        raise InvalidStateTransition("worker", "(unknown)", current_status, target_status)


def get_event_type(current_status: str, target_status: str) -> str:
    """返回此运行时转换的规范事件类型。

    Args:
        current_status: Worker 当前运行时状态。
        target_status: 期望的目标运行时状态。

    Returns:
        事件类型字符串（如 ``"worker.runtime.busy"``）。

    Raises:
        KeyError: 若转换对未被映射。
    """
    key = (current_status, target_status)
    if key not in _EVENT_TYPE_MAP:
        raise KeyError(f"No event type mapped for transition {current_status!r} → {target_status!r}")
    return _EVENT_TYPE_MAP[key]


def build_event_payload(
    worker: Worker,
    target_status: str,
    *,
    actor_type: str,
    actor_id: str,
    context: dict | None = None,
) -> dict:
    """为运行时状态转换构建 EventStore 负载。

    Args:
        worker: Worker ORM 对象。
        target_status: 目标运行时状态。
        actor_type: ``ActorType.WORKER`` 或 ``ActorType.HUMAN``。
        actor_id: 执行转换的参与者 ID。
        context: 可选额外字段，合并进负载。

    Returns:
        适用于 ``event_store.record(payload=...)`` 的字典。
    """
    payload: dict = {
        "worker_id": worker.id,
        "previous_runtime_status": worker.runtime_status,
        "new_runtime_status": target_status,
        "actor_type": actor_type,
        "actor_id": actor_id,
    }
    if context:
        payload.update(context)
    return payload


def apply_transition(
    worker: Worker,
    target_status: str,
    *,
    actor_type: str,
    actor_id: str,
    context: dict | None = None,
) -> tuple[str, dict]:
    """在一次调用中验证、应用并返回事件元数据。

    这是服务函数的主要入口点。它：
    1. 验证转换（若不合法则抛出 InvalidStateTransition）。
    2. 更新 ``worker.runtime_status = target_status``。
    3. 返回 ``(event_type, payload)`` 供调用方写入 EventStore。

    调用方必须在同一 DB 事务中调用 ``event_store.record()`` 并传入返回值。

    Args:
        worker: Worker ORM 对象（原地修改）。
        target_status: 期望的目标运行时状态。
        actor_type: ``ActorType.WORKER`` 或 ``ActorType.HUMAN``。
        actor_id: 执行转换的参与者 ID。
        context: 可选额外字段，合并进事件负载。

    Returns:
        ``(event_type, payload)`` 元组。

    Raises:
        InvalidStateTransition: 若转换不被允许。
    """
    validate_transition(worker.runtime_status, target_status)
    event_type = get_event_type(worker.runtime_status, target_status)
    payload = build_event_payload(worker, target_status, actor_type=actor_type, actor_id=actor_id, context=context)
    worker.runtime_status = target_status
    return event_type, payload


# ── 便捷导出 ───────────────────────────────────────────────────────

ALLOWED_TRANSITIONS = _TRANSITIONS
TRANSITIONS = _TRANSITIONS  # alias

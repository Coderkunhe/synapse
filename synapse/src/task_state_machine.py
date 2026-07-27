"""Task 状态机 — 所有 Task 状态转换的唯一权威来源。

所有 Task 状态变更必须通过本模块。禁止直接对 ``task.status`` 赋值
（由 code review 强制执行，非运行时）。

设计（依据 P7 D5 B1）：
- 8 个状态：BACKLOG（链前）→ READY → IN_PROGRESS → PAUSED → IN_VERIFICATION
  → COMPLETED/REJECTED/CANCELLED（7 核心链 + BACKLOG）
- 每次转换产出 (event_type, payload) 元组供 EventStore 使用
- 调用方持有 DB 事务：状态变更 + 事件写入同成功或同失败
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.constants import ActorType, TaskStatus
from src.exceptions import InvalidStateTransition

if TYPE_CHECKING:
    from src.models.task import Task


# ── 转换白名单 ──────────────────────────────────────────────────────
# 映射 当前状态 → 允许的目标状态集合。
# 此为权威定义；Task.ALLOWED_TRANSITIONS 委托至此以保证向后兼容。

_TRANSITIONS: dict[str, frozenset[str]] = {
    TaskStatus.BACKLOG:         frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY:           frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS:     frozenset({TaskStatus.PAUSED, TaskStatus.IN_VERIFICATION, TaskStatus.CANCELLED, TaskStatus.READY}),
    TaskStatus.PAUSED:          frozenset({TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}),
    TaskStatus.IN_VERIFICATION: frozenset({TaskStatus.COMPLETED, TaskStatus.REJECTED, TaskStatus.CANCELLED}),
    TaskStatus.REJECTED:        frozenset({TaskStatus.IN_PROGRESS}),
    TaskStatus.COMPLETED:       frozenset(),
    TaskStatus.CANCELLED:       frozenset(),
}


# ── 事件类型映射 ────────────────────────────────────────────────────
# 映射 (from_status, to_status) → event_type 字符串。
# 覆盖所有合法转换；缺失条目将抛出 ValueError。

_EVENT_TYPE_MAP: dict[tuple[str, str], str] = {
    (TaskStatus.BACKLOG, TaskStatus.READY):             "task.readied",
    (TaskStatus.BACKLOG, TaskStatus.CANCELLED):         "task.cancelled",
    (TaskStatus.READY, TaskStatus.IN_PROGRESS):         "task.claimed",
    (TaskStatus.READY, TaskStatus.CANCELLED):           "task.cancelled",
    (TaskStatus.IN_PROGRESS, TaskStatus.PAUSED):        "task.paused",
    (TaskStatus.IN_PROGRESS, TaskStatus.IN_VERIFICATION): "task.submitted",
    (TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED):     "task.cancelled",
    (TaskStatus.IN_PROGRESS, TaskStatus.READY):         "task.lease_expired",
    (TaskStatus.PAUSED, TaskStatus.IN_PROGRESS):        "task.resumed",
    (TaskStatus.PAUSED, TaskStatus.CANCELLED):          "task.cancelled",
    (TaskStatus.IN_VERIFICATION, TaskStatus.COMPLETED): "task.completed",
    (TaskStatus.IN_VERIFICATION, TaskStatus.REJECTED):  "task.rejected",
    (TaskStatus.IN_VERIFICATION, TaskStatus.CANCELLED): "task.cancelled",
    (TaskStatus.REJECTED, TaskStatus.IN_PROGRESS):      "task.claimed",
}


# ── 终态 ───────────────────────────────────────────────────────────
# 处于这些状态的任务不可再转换。

_TERMINAL_STATES: frozenset[str] = frozenset({TaskStatus.COMPLETED, TaskStatus.CANCELLED})


# ── 公共 API ────────────────────────────────────────────────────────

def validate_transition(current_status: str, target_status: str) -> None:
    """若转换不被允许则抛出 InvalidStateTransition。

    Args:
        current_status: 任务当前状态。
        target_status: 期望的目标状态。

    Raises:
        InvalidStateTransition: 若转换不在白名单中。
    """
    allowed = _TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed:
        raise InvalidStateTransition("task", "(unknown)", current_status, target_status)


def get_event_type(current_status: str, target_status: str) -> str:
    """返回此转换的规范事件类型。

    Args:
        current_status: 任务当前状态。
        target_status: 期望的目标状态。

    Returns:
        事件类型字符串（如 ``"task.paused"``）。

    Raises:
        KeyError: 若转换对未被映射。
    """
    key = (current_status, target_status)
    if key not in _EVENT_TYPE_MAP:
        raise KeyError(f"No event type mapped for transition {current_status!r} → {target_status!r}")
    return _EVENT_TYPE_MAP[key]


def build_event_payload(
    task: Task,
    target_status: str,
    *,
    actor_type: str,
    actor_id: str,
    context: dict | None = None,
) -> dict:
    """为状态转换构建 EventStore 负载。

    调用方负责：
    1. 在调用此函数前先调用 ``validate_transition``。
    2. 通过 ``event_store.record()`` 写入事件。
    3. 更新 ``task.status`` 及相关字段。
    4. 提交事务。

    Args:
        task: Task ORM 对象（用于 ``task.id`` 和当前状态）。
        target_status: 目标状态。
        actor_type: ``ActorType.HUMAN`` 或 ``ActorType.WORKER``。
        actor_id: 执行转换的参与者 ID。
        context: 可选额外字段，合并进负载。

    Returns:
        适用于 ``event_store.record(payload=...)`` 的字典。
    """
    payload: dict = {
        "task_id": task.id,
        "previous_status": task.status,
        "new_status": target_status,
        "actor_type": actor_type,
        "actor_id": actor_id,
    }
    if context:
        payload.update(context)
    return payload


def apply_transition(
    task: Task,
    target_status: str,
    *,
    actor_type: str,
    actor_id: str,
    context: dict | None = None,
    override_event_type: str | None = None,
) -> tuple[str, dict]:
    """在一次调用中验证、应用并返回事件元数据。

    这是服务函数的主要入口点。它：
    1. 验证转换（若不合法则抛出 InvalidStateTransition）。
    2. 保存之前的状态。
    3. 更新 ``task.status = target_status``。
    4. 返回 ``(event_type, payload)`` 供调用方写入 EventStore。

    调用方必须在同一 DB 事务中调用 ``event_store.record()`` 并传入返回值。

    Args:
        task: Task ORM 对象（原地修改）。
        target_status: 期望的目标状态。
        actor_type: ``ActorType.HUMAN`` 或 ``ActorType.WORKER``。
        actor_id: 执行转换的参与者 ID。
        context: 可选额外字段，合并进事件负载。
        override_event_type: 可选，覆盖事件映射表中该转换的默认事件类型。
            用于状态转换物理路径相同但语义不同的场景（如阻塞报告 vs 租约过期，
            两者均为 IN_PROGRESS → READY 但事件类型不同）。

    Returns:
        ``(event_type, payload)`` 元组。

    Raises:
        InvalidStateTransition: 若转换不被允许。
    """
    validate_transition(task.status, target_status)
    event_type = override_event_type if override_event_type else get_event_type(task.status, target_status)
    payload = build_event_payload(task, target_status, actor_type=actor_type, actor_id=actor_id, context=context)
    task.status = target_status
    return event_type, payload


def is_terminal(status: str) -> bool:
    """若状态为终态（不可再转换）则返回 True。"""
    return status in _TERMINAL_STATES


def is_active(status: str) -> bool:
    """若任务处于活跃（非终态、非 backlog）状态则返回 True。"""
    return status not in _TERMINAL_STATES and status != TaskStatus.BACKLOG


# ── 服务函数便捷导出 ─────────────────────────────────────────────────
# 这些是转换表的直接查找；使得服务函数可以在不硬编码状态字符串的情况下检查前置条件。

ALLOWED_TRANSITIONS = _TRANSITIONS
TRANSITIONS = _TRANSITIONS  # alias for readability

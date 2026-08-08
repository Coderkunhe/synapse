"""时间操纵工具 — 让测试以语义化方式控制时间。

P13-B6: 直接操作 ORM 字段（D-P13-006 — 不引入 freezegun）。
与现有 741 tests 的时间操纵模式一致。

用法:
    tt = TimeTravel(db)
    await tt.age_heartbeat(worker_id, beyond_timeout=True)
    await tt.expire_lease(task_id)
    await tt.advance_updated_at(task_id, minutes=30)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.task import Task
from src.models.worker import Worker


class TimeTravel:
    """时间操纵工具 — 以语义化 API 控制测试中的时间相关字段。

    所有方法直接操作 ORM 对象并 flush，不 commit —
    调用者负责事务边界。

    Provider 超时优先从 provider_config (JSON) 读取，
    若不存在则回退到默认值（D-P13-007: dict mock → B6+ DB 字段）。
    """

    # 默认超时（当 provider_config 不可用时）
    DEFAULT_HEARTBEAT_TIMEOUT = 300

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Heartbeat 时间操纵 ──────────────────────────────────────

    async def age_heartbeat(
        self,
        worker_id: str,
        *,
        seconds: int | None = None,
        beyond_timeout: bool = False,
    ) -> datetime:
        """将 Worker 的 last_heartbeat_at 设为过去。

        Args:
            worker_id: Worker ID。
            seconds: 具体秒数。与 beyond_timeout 互斥。
            beyond_timeout: 设为超过该 Worker 的 provider timeout。
                           自动从 provider_config 读取 timeout_seconds；
                           若不可用则使用 DEFAULT_HEARTBEAT_TIMEOUT。

        Returns:
            设置的过去时间戳。
        """
        worker = await self._db.get(Worker, worker_id)
        if worker is None:
            raise ValueError(f"Worker {worker_id} not found")

        if beyond_timeout:
            timeout = self.DEFAULT_HEARTBEAT_TIMEOUT
            # provider_config 可能是 JSON dict（B6+ DB 字段）或空
            if hasattr(worker, "provider_config") and worker.provider_config:
                timeout = worker.provider_config.get("heartbeat", {}).get(
                    "timeout_seconds", self.DEFAULT_HEARTBEAT_TIMEOUT
                )
            seconds = timeout + 60  # 超过 timeout 1 分钟

        if seconds is None:
            raise ValueError("Must specify seconds or beyond_timeout=True")

        past = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        worker.last_heartbeat_at = past
        await self._db.flush()
        return past

    # ── 租约时间操纵 ────────────────────────────────────────────

    async def expire_lease(self, task_id: str) -> datetime:
        """将 Task 的 lease_expires_at 设为过去（1 秒前）。

        直接触发租约过期 — 下一步 release_expired_leases 应释放此任务。
        """
        task = await self._db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        task.lease_expires_at = past
        await self._db.flush()
        return past

    # ── 通用时间回退 ────────────────────────────────────────────

    async def advance_updated_at(
        self, task_id: str, *, minutes: int = 0, seconds: int = 0
    ) -> datetime:
        """将 Task 的 updated_at 设为过去。

        用于触发 stale task 检测、梯度响应等场景。
        """
        task = await self._db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        delta = timedelta(minutes=minutes, seconds=seconds)
        past = datetime.now(timezone.utc) - delta
        task.updated_at = past
        await self._db.flush()
        return past

    async def age_claimed_at(
        self, task_id: str, *, minutes: int = 0, seconds: int = 0
    ) -> datetime:
        """将 Task 的 claimed_at 设为过去。

        用于测试 stale task 检测 — claimed 已久但无进展的 task。
        """
        task = await self._db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        delta = timedelta(minutes=minutes, seconds=seconds)
        past = datetime.now(timezone.utc) - delta
        task.claimed_at = past
        await self._db.flush()
        return past

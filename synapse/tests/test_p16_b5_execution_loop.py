"""P16-B5: headless 执行环闭环回归 — claim→execute→submit 不再断裂。

B4 狗粮第一轮（2026-08-24）实测：headless 执行环卡死在 claim→execute，
B 无限循环 claim 一个被 depends_on 锁住的任务。双边根因：

- **写入端**（PFL-247）：``claim``/``assign`` 只写 ``task.owner_id``，
  不挂 ``worker.active_task_id`` —— state_router 无信号可路由 ``execute``。
- **读取端**（PFL-247）：``start-worker.sh`` 的心跳体不带 ``current_task_id``，
  而旧实现无条件 ``worker.active_task_id = current_task_id`` —— 每跳（≤20s）
  把刚挂上的活跃任务擦成 None。
- **计数端**（PFL-248）：``_count_queue`` 把 depends_on 未满足的任务也算进
  ``ready`` —— O 每轮 assign、B 每轮 claim 同一个不可操作的任务，双双空转。

**这个文件里的测试变红 = B4 死循环复现。**
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient

from src.auth import hash_api_key
from src.constants import (
    ActorType,
    OwnerType,
    TaskStatus,
    WorkerActorType,
    WorkerRuntimeStatus,
    WorkerStatus,
)
from src.db import async_session_factory
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.task import Task
from src.models.worker import Worker
from src.services.task_service import claim_task, submit_task
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps

from tests.conftest import SeedData


# ── 夹具工具 ────────────────────────────────────────────────────────


async def _setup(team_id: str, role: str) -> tuple[str, str, str]:
    """建 project + 指定角色的 worker（带 API key）。

    Returns: (project_id, worker_id, raw_key)
    """
    raw_key = "sk-test-" + secrets.token_hex(16)
    worker_id = generate_id("worker")
    project_id = generate_id("project")

    async with async_session_factory() as db:
        db.add(Worker(
            id=worker_id, name=f"p16b5-{role}", team_id=team_id,
            actor_type=WorkerActorType.AGENT, status=WorkerStatus.ACTIVE,
            api_key_hash=hash_api_key(raw_key),
        ))
        db.add(Project(
            id=project_id, team_id=team_id,
            name="P16-B5 Loop", slug=f"p16b5-{project_id[-8:]}",
        ))
        db.add(ProjectActorRole(
            id=generate_id("project_actor_role"),
            project_id=project_id, worker_id=worker_id, role=role,
        ))
        await db.commit()

    return project_id, worker_id, raw_key


async def _add_task(
    project_id: str,
    *,
    status: str = TaskStatus.READY,
    depends_on: list[str] | None = None,
) -> str:
    """建一个任务，可选 depends_on 依赖链。"""
    task_id = generate_id("task")
    async with async_session_factory() as db:
        db.add(Task(
            id=task_id, project_id=project_id, title="loop task", status=status,
            depends_on=(
                safe_dumps([{"task_id": t} for t in depends_on])
                if depends_on else None
            ),
        ))
        await db.commit()
    return task_id


async def _bare_heartbeat(
    client: AsyncClient, worker_id: str, raw_key: str, project_id: str,
) -> dict:
    """发一条 **和 start-worker.sh 一模一样** 的心跳——不带 current_task_id。

    driver 的真实请求体见 ``tools/start-worker.sh``：
    ``{"current_load":0,"project_id":"..."}``。B4 就是挂在这一跳上。
    """
    resp = await client.post(
        f"/v1/workers/{worker_id}/heartbeat",
        json={"current_load": 0, "project_id": project_id},
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    return resp.json()


async def _claim(task_id: str, worker_id: str, team_id: str) -> None:
    async with async_session_factory() as db:
        task = await db.get(Task, task_id)
        await claim_task(
            db, task_id,
            worker_id=worker_id, worker_team_id=team_id,
            expected_version=task.version_no,
        )
        await db.commit()


# ── 核心回归 ────────────────────────────────────────────────────────


class TestClaimToExecuteHandoff:
    """claim → （不带字段的心跳）→ execute —— B4 断掉的那一跳。"""

    @pytest.mark.asyncio
    async def test_claim_then_bare_heartbeat_routes_execute(
        self, client: AsyncClient, seed: SeedData,
    ):
        """认领后，driver 的裸心跳必须把 B 路由到 execute（而不是又去 claim）。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)

        # 认领前：有 ready 任务 → claim
        before = await _bare_heartbeat(client, worker_id, key, project_id)
        assert before["next_action"] == "claim"
        assert before["active_task_id"] is None

        await _claim(task_id, worker_id, seed.team_id)

        # 认领后：必须 execute —— B4 在这里返回了 claim，于是无限循环
        after = await _bare_heartbeat(client, worker_id, key, project_id)
        assert after["next_action"] == "execute", (
            "claim 后裸心跳仍未路由到 execute — B4 的 claim→execute 断裂复现了"
        )
        assert after["active_task_id"] == task_id
        assert after["runtime_status"] == WorkerRuntimeStatus.BUSY

    @pytest.mark.asyncio
    async def test_execute_survives_repeated_bare_heartbeats(
        self, client: AsyncClient, seed: SeedData,
    ):
        """连续多跳裸心跳不得把活跃任务擦掉（driver 每 ≤20s 一跳）。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)
        await _claim(task_id, worker_id, seed.team_id)

        for i in range(3):
            data = await _bare_heartbeat(client, worker_id, key, project_id)
            assert data["next_action"] == "execute", f"第 {i + 1} 跳掉回了 claim"
            assert data["active_task_id"] == task_id

    @pytest.mark.asyncio
    async def test_explicit_null_still_clears(
        self, client: AsyncClient, seed: SeedData,
    ):
        """显式传 null 仍然清空活跃任务 —— 老契约不能被顺手改掉。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)
        await _claim(task_id, worker_id, seed.team_id)

        resp = await client.post(
            f"/v1/workers/{worker_id}/heartbeat",
            json={"current_load": 0, "project_id": project_id, "current_task_id": None},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["active_task_id"] is None
        assert resp.json()["runtime_status"] == WorkerRuntimeStatus.IDLE

    @pytest.mark.asyncio
    async def test_submit_releases_worker_and_reroutes(
        self, client: AsyncClient, seed: SeedData,
    ):
        """提交后必须放开活跃任务，否则 B 会卡在 execute 上（反向死循环）。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)
        await _claim(task_id, worker_id, seed.team_id)

        assert (await _bare_heartbeat(
            client, worker_id, key, project_id))["next_action"] == "execute"

        async with async_session_factory() as db:
            task = await db.get(Task, task_id)
            await submit_task(
                db, task_id,
                summary="done",
                evidence={"output_access": {"type": "inline", "value": "ok"}},
                verification_results=[],
                expected_version=task.version_no,
                actor_type=ActorType.WORKER, actor_id=worker_id,
                team_id=seed.team_id,
            )
            await db.commit()

        after = await _bare_heartbeat(client, worker_id, key, project_id)
        assert after["next_action"] != "execute", "提交后仍被路由 execute — 反向卡死"
        assert after["active_task_id"] is None


class TestStaleActiveTaskDefense:
    """陈旧 ``active_task_id`` 不得把 B 派去执行一个死任务（P16-B5 收口防御）。"""

    @pytest.mark.asyncio
    async def test_cancelled_active_task_not_routed_execute(
        self, client: AsyncClient, seed: SeedData,
    ):
        """任务被取消后（cancel 路径不清 active_task_id）→ 不得路由 execute。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)
        await _claim(task_id, worker_id, seed.team_id)

        async with async_session_factory() as db:
            task = await db.get(Task, task_id)
            task.status = TaskStatus.CANCELLED
            await db.commit()

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["next_action"] != "execute"
        assert data["active_task_id"] is None

    @pytest.mark.asyncio
    async def test_reassigned_active_task_not_routed_execute(
        self, client: AsyncClient, seed: SeedData,
    ):
        """任务被改派给别人后 → 不得路由 execute。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        task_id = await _add_task(project_id)
        await _claim(task_id, worker_id, seed.team_id)

        async with async_session_factory() as db:
            task = await db.get(Task, task_id)
            task.owner_id = generate_id("worker")
            task.owner_type = OwnerType.WORKER
            await db.commit()

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["next_action"] != "execute"


class TestDependencyBlockedNotReady:
    """depends_on 未满足的任务不得计入 ready（PFL-248 · O/B 双向空转）。"""

    @pytest.mark.asyncio
    async def test_builder_idle_when_only_blocked_ready(
        self, client: AsyncClient, seed: SeedData,
    ):
        """只有 blocked 任务时 B 应 idle —— 而不是反复 claim 到 409。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        blocker = await _add_task(project_id, status=TaskStatus.IN_PROGRESS)
        await _add_task(project_id, depends_on=[blocker])

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["queue"]["ready"] == 0, "被 depends_on 锁住的任务仍被计为 ready"
        assert data["next_action"] == "idle"

    @pytest.mark.asyncio
    async def test_orchestrator_does_not_assign_blocked(
        self, client: AsyncClient, seed: SeedData,
    ):
        """只有 blocked 任务时 O 应 monitor（盯依赖）而不是空转 assign。"""
        project_id, worker_id, key = await _setup(seed.team_id, "orchestrator")
        blocker = await _add_task(project_id, status=TaskStatus.IN_PROGRESS)
        await _add_task(project_id, depends_on=[blocker])

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["queue"]["ready"] == 0
        assert data["next_action"] == "monitor"

    @pytest.mark.asyncio
    async def test_ready_counted_once_dependency_met(
        self, client: AsyncClient, seed: SeedData,
    ):
        """依赖完成后，被解锁的任务重新计入 ready → B 恢复 claim。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        blocker = await _add_task(project_id, status=TaskStatus.IN_PROGRESS)
        await _add_task(project_id, depends_on=[blocker])

        assert (await _bare_heartbeat(
            client, worker_id, key, project_id))["next_action"] == "idle"

        async with async_session_factory() as db:
            task = await db.get(Task, blocker)
            task.status = TaskStatus.COMPLETED
            await db.commit()

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["queue"]["ready"] == 1
        assert data["next_action"] == "claim"


class TestStalePointerDoesNotBlockNewClaim:
    """陈旧指针不得挡住新认领（PFL-256 · B5 自检发现的自伤 bug）。

    ``resolve_workable_active_task``（路由层）认为陈旧指针无效，而
    ``attach_active_task``（写入层）却认为「已有活跃任务」不可抢占 ——
    两层对「Worker 到底有没有活」判断不一致，新认领的任务永远挂不上，
    B 卡死。与 PFL-248 同一种缺陷（两层各说各话），修法也一样：共用判定。
    """

    @pytest.mark.asyncio
    async def test_cancelled_pointer_then_claim_routes_execute(
        self, client: AsyncClient, seed: SeedData,
    ):
        """指针指向已取消任务时，认领新任务必须能挂上并路由 execute。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        t1 = await _add_task(project_id)
        await _claim(t1, worker_id, seed.team_id)

        # t1 取消 —— cancel 路径不清 worker.active_task_id（PFL-254）
        async with async_session_factory() as db:
            task = await db.get(Task, t1)
            task.status = TaskStatus.CANCELLED
            await db.commit()

        t2 = await _add_task(project_id)
        assert (await _bare_heartbeat(
            client, worker_id, key, project_id))["next_action"] == "claim"

        await _claim(t2, worker_id, seed.team_id)

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["next_action"] == "execute", (
            f"陈旧指针挡住了新认领（得到 {data['next_action']}）— B4 死循环复现"
        )
        assert data["active_task_id"] == t2

    @pytest.mark.asyncio
    async def test_workable_active_task_is_not_preempted(
        self, client: AsyncClient, seed: SeedData,
    ):
        """反向保证：活跃任务仍可执行时，第二次认领不得抢占（FIFO 规则 1）。"""
        project_id, worker_id, key = await _setup(seed.team_id, "builder")
        t1 = await _add_task(project_id)
        t2 = await _add_task(project_id)
        await _claim(t1, worker_id, seed.team_id)
        await _claim(t2, worker_id, seed.team_id)

        data = await _bare_heartbeat(client, worker_id, key, project_id)
        assert data["active_task_id"] == t1, "第二次认领不应抢占仍在执行的 t1"
        assert data["next_action"] == "execute"

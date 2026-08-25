"""P16-B2 Heartbeat State-Router 测试 — heartbeat 响应的 next_action + queue 路由。"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient

from src.auth import hash_api_key
from src.constants import OwnerType, TaskStatus, WorkerActorType, WorkerStatus
from src.db import async_session_factory
from src.models.project import Project
from src.models.project_actor_role import ProjectActorRole
from src.models.task import Task
from src.models.worker import Worker
from src.utils.id_gen import generate_id

from tests.conftest import SeedData


class TestStateRouter:
    """POST /workers/{id}/heartbeat 的确定性路由（P16-B2）。

    queue 是 project 全局计数；next_action 是角色特定解读：
    - orchestrator：verify > split > assign > monitor > idle
    - builder：execute > claim > idle
    """

    async def _setup(
        self,
        *,
        team_id: str,
        role: str,
        statuses: tuple[str, ...] = (),
        projects: int = 1,
        project_ids: list[str] | None = None,
    ) -> tuple[list[str], str, str]:
        """创建 project(s) + worker(带 API key) + project role + 任务。

        Returns: (project_ids, worker_id, raw_key)
        """
        raw_key = "sk-test-" + secrets.token_hex(16)
        worker_id = generate_id("worker")
        pids = project_ids or [generate_id("project") for _ in range(projects)]

        async with async_session_factory() as db:
            # Worker
            db.add(Worker(
                id=worker_id, name=f"{role}-worker", team_id=team_id,
                actor_type=WorkerActorType.AGENT, status=WorkerStatus.ACTIVE,
                api_key_hash=hash_api_key(raw_key),
            ))
            # Project(s) + role 映射
            for i, pid in enumerate(pids):
                db.add(Project(
                    id=pid, team_id=team_id,
                    name=f"SR Project {i}", slug=f"sr-proj-{pid[-8:]}",
                ))
                db.add(ProjectActorRole(
                    id=generate_id("project_actor_role"),
                    project_id=pid, worker_id=worker_id, role=role,
                ))
            # 任务全部落在第一个 project
            for status in statuses:
                db.add(Task(
                    id=generate_id("task"), project_id=pids[0],
                    title=f"{status} task", status=status,
                ))
            await db.commit()

        return pids, worker_id, raw_key

    async def _add_owned_task(
        self, *, project_id: str, worker_id: str, status: str,
    ) -> str:
        """建一个归属该 worker 的任务，返回 task id（P16-B5）。

        路由 execute 需要**真实存在且仍归本人**的任务——见
        ``worker_scheduler.resolve_workable_active_task`` 的 stale 防御。
        """
        task_id = generate_id("task")
        async with async_session_factory() as db:
            db.add(Task(
                id=task_id, project_id=project_id, title=f"owned {status} task",
                status=status, owner_type=OwnerType.WORKER, owner_id=worker_id,
            ))
            await db.commit()
        return task_id

    async def _heartbeat(
        self, client: AsyncClient, worker_id: str, raw_key: str, body: dict | None = None,
    ) -> dict:
        resp = await client.post(
            f"/v1/workers/{worker_id}/heartbeat",
            json=body or {},
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        assert resp.status_code == 200, f"heartbeat failed: {resp.status_code} {resp.text}"
        return resp.json()

    # ── Orchestrator 路由优先级 ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_orchestrator_verify_priority(self, client: AsyncClient, seed: SeedData):
        """in_verification > backlog > ready > in_progress → 最高优先 verify。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator",
            statuses=("in_verification", "backlog", "ready", "in_progress"),
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "verify"
        assert data["role"] == "orchestrator"

    @pytest.mark.asyncio
    async def test_orchestrator_split(self, client: AsyncClient, seed: SeedData):
        """仅 backlog → split。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator", statuses=("backlog",),
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "split"

    @pytest.mark.asyncio
    async def test_orchestrator_assign(self, client: AsyncClient, seed: SeedData):
        """仅 ready → assign。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator", statuses=("ready",),
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "assign"

    @pytest.mark.asyncio
    async def test_orchestrator_monitor(self, client: AsyncClient, seed: SeedData):
        """仅 in_progress → monitor。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator", statuses=("in_progress",),
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "monitor"

    @pytest.mark.asyncio
    async def test_orchestrator_idle(self, client: AsyncClient, seed: SeedData):
        """空队列 → idle。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator",
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "idle"

    # ── Builder 路由 ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_builder_execute(self, client: AsyncClient, seed: SeedData):
        """有 active task（current_task_id）→ execute。"""
        pids, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder", statuses=("ready",),
        )
        task_id = await self._add_owned_task(
            project_id=pids[0], worker_id=worker_id, status=TaskStatus.IN_PROGRESS,
        )
        data = await self._heartbeat(
            client, worker_id, key, body={"current_task_id": task_id},
        )
        assert data["next_action"] == "execute"
        assert data["active_task_id"] == task_id

    @pytest.mark.asyncio
    async def test_builder_claim(self, client: AsyncClient, seed: SeedData):
        """无 active task + ready>0 → claim。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder", statuses=("ready",),
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "claim"

    @pytest.mark.asyncio
    async def test_builder_idle(self, client: AsyncClient, seed: SeedData):
        """空队列 + 无 active task → idle。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder",
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "idle"

    # ── queue 计数 ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_queue_counts(self, client: AsyncClient, seed: SeedData):
        """1 backlog + 2 ready + 3 in_progress + 4 in_verification → 各桶计数。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="orchestrator",
            statuses=(
                "backlog",
                "ready", "ready",
                "in_progress", "in_progress", "in_progress",
                "in_verification", "in_verification", "in_verification", "in_verification",
            ),
        )
        data = await self._heartbeat(client, worker_id, key)
        q = data["queue"]
        assert q["backlog"] == 1
        assert q["ready"] == 2
        assert q["in_progress"] == 3
        assert q["awaiting_verify"] == 4
        assert data["next_action"] == "verify"

    # ── project 作用域解析 ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_single_project_autoresolve(self, client: AsyncClient, seed: SeedData):
        """单 project 缺省 project_id → 自动解析并路由。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder", statuses=("ready",),
        )
        data = await self._heartbeat(client, worker_id, key)  # 不带 project_id
        assert data["next_action"] == "claim"
        assert data["queue"] is not None

    @pytest.mark.asyncio
    async def test_multi_project_no_project_id(self, client: AsyncClient, seed: SeedData):
        """多 project 缺省 project_id → idle + queue=None + warning。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder", statuses=("ready",), projects=2,
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["next_action"] == "idle"
        assert data["queue"] is None
        assert any("project_id" in w for w in data["role_warnings"])

    @pytest.mark.asyncio
    async def test_explicit_project_id(self, client: AsyncClient, seed: SeedData):
        """多 project 显式 project_id → 命中指定 project 队列。"""
        pids, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder", statuses=("ready",), projects=2,
        )
        # 显式指定第一个 project（有 ready task）
        data = await self._heartbeat(
            client, worker_id, key, body={"project_id": pids[0]},
        )
        assert data["next_action"] == "claim"
        assert data["queue"]["ready"] == 1

    # ── 向后兼容 ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_backward_compat_fields_present(self, client: AsyncClient, seed: SeedData):
        """老 heartbeat 请求（无 project_id）仍 200，新字段存在且类型正确。"""
        _, worker_id, key = await self._setup(
            team_id=seed.team_id, role="builder",
        )
        data = await self._heartbeat(client, worker_id, key)
        assert data["status"] == "ok"
        assert data["role"] == "builder"
        assert data["next_action"] == "idle"
        assert data["active_task_id"] is None
        assert data["queue"]["ready"] == 0

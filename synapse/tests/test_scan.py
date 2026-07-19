"""E2E 测试：ComplianceScan — 任务 verification 存在性 + 批次归属检查。"""

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


def _uniq_slug(prefix: str) -> str:
    """生成唯一 slug 用于测试隔离。"""
    from src.utils.id_gen import generate_id

    return f"{prefix}-{generate_id('project').replace('prj_', '')[-8:]}"


class TestComplianceScan:
    """ComplianceScan：规则执行 + 结果持久化 + 操作者追踪。"""

    @pytest.mark.asyncio
    async def test_scan_task_passes_with_verifications(
        self, client: AsyncClient, seed: SeedData
    ):
        """R1：带 verification 条件的任务 → 通过。"""
        headers = auth_header(seed.token)

        # 准备：创建带 verification 的项目 + 任务
        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Scan Test", "slug": _uniq_slug("scan")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Task with verifications",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Code review", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # 扫描
        resp = await client.post(
            f"/v1/scans/task/{task_id}",
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["target_type"] == "task"
        assert data["target_id"] == task_id
        assert data["actor_type"] == "human"
        assert data["actor_id"] == seed.worker_id
        assert data["id"].startswith("scn_")
        assert "created_at" in data

        # 摘要
        assert data["summary"]["pass"] >= 1
        assert data["summary"]["fail"] == 0

        # 规则判定
        rules = {v["rule_id"]: v for v in data["rules_checked"]}
        assert "task.verification_exists" in rules
        assert rules["task.verification_exists"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_scan_task_fails_without_verifications(
        self, client: AsyncClient, seed: SeedData
    ):
        """R1：无 verification 条件的任务 → 失败。

        使用直接 DB 插入的方式创建，因为 API 在任务创建时
        强制要求至少一个 verification。
        """
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "No Verify", "slug": _uniq_slug("noverify")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # 通过 DB 创建无 verification 的任务（API 要求 >=1）
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        task_id = generate_id("task")
        async with async_session_factory() as session:
            from src.models.task import Task

            task = Task(
                id=task_id,
                project_id=project_id,
                title="Task without verifications",
                status="backlog",
            )
            session.add(task)
            await session.commit()

        resp = await client.post(
            f"/v1/scans/task/{task_id}",
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["target_type"] == "task"
        assert data["summary"]["fail"] >= 1

        rules = {v["rule_id"]: v for v in data["rules_checked"]}
        assert rules["task.verification_exists"]["status"] == "fail"
        assert "no verification" in rules["task.verification_exists"]["detail"].lower()

    @pytest.mark.asyncio
    async def test_scan_batch_mixed_ownership(
        self, client: AsyncClient, seed: SeedData
    ):
        """R3：批次中部分任务有归属、部分无归属 → warn。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Batch Ownership", "slug": _uniq_slug("batchown")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        # 创建批次
        batch_resp = await client.post(
            f"/v1/projects/{project_id}/batches",
            json={"name": "Mixed Ownership Batch"},
            headers=headers,
        )
        assert batch_resp.status_code == 201, batch_resp.text
        batch_id = batch_resp.json()["id"]

        # 创建任务 1 — 有归属人（通过 update 或直接分配）
        task1_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Owned Task",
                "description": "test",
                "batch_id": batch_id,
                "verifications": [
                    {"type": "manual", "description": "Check ownership", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task1_resp.status_code == 201, task1_resp.text
        task1_id = task1_resp.json()["id"]

        # 为任务 1 分配归属人
        assign_resp = await client.post(
            f"/v1/tasks/{task1_id}/assign",
            json={
                "owner_type": "member",
                "owner_id": seed.member_id,
                "expected_version": 1,
            },
            headers=headers,
        )
        assert assign_resp.status_code == 200, assign_resp.text

        # 创建任务 2 — 无归属人
        task2_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Unowned Task",
                "description": "test",
                "batch_id": batch_id,
                "verifications": [
                    {"type": "manual", "description": "Check ownership", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task2_resp.status_code == 201, task2_resp.text

        # 扫描
        resp = await client.post(
            f"/v1/scans/batch/{batch_id}",
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["target_type"] == "batch"
        assert data["summary"]["warn"] >= 1

        rules = {v["rule_id"]: v for v in data["rules_checked"]}
        assert rules["batch.ownership_complete"]["status"] == "warn"
        assert "1/2" in rules["batch.ownership_complete"]["detail"]

    @pytest.mark.asyncio
    async def test_scan_cross_team_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨团队扫描任务返回 404（而非 403）。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Cross-team Scan", "slug": _uniq_slug("crossscan")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Team 1 Task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Cross-team test", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"Other Team {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="Other Admin",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        resp = await client.post(
            f"/v1/scans/task/{task_id}",
            headers=headers2,
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_scan_records_actor(
        self, client: AsyncClient, seed: SeedData
    ):
        """验证 actor_type + actor_id 从认证上下文正确记录。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Actor Scan", "slug": _uniq_slug("actorscan")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Actor tracking task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Verify actor", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        resp = await client.post(
            f"/v1/scans/task/{task_id}",
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()

        assert data["actor_type"] == "human"
        assert data["actor_id"] == seed.worker_id

    @pytest.mark.asyncio
    async def test_scan_invalid_target_type_returns_400(
        self, client: AsyncClient, seed: SeedData
    ):
        """扫描不支持的目标类型返回 400。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            "/v1/scans/foobar/some-id",
            headers=headers,
        )
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_scan_nonexistent_target_returns_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """扫描不存在的任务返回 404。"""
        headers = auth_header(seed.token)

        resp = await client.post(
            "/v1/scans/task/tsk_nonexistent01",
            headers=headers,
        )
        assert resp.status_code == 404, resp.text


class TestComplianceScanRetrieval:
    """GET 端点：列表 + 详情，带团队作用域认证。"""

    @pytest.mark.asyncio
    async def test_list_scans_by_team(
        self, client: AsyncClient, seed: SeedData
    ):
        """列出团队所有扫描，按最新优先排序。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "List Scans", "slug": _uniq_slug("listscans")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_ids = []
        for i in range(2):
            task_resp = await client.post(
                f"/v1/projects/{project_id}/tasks",
                json={
                    "title": f"Scan list task {i}",
                    "description": "test",
                    "verifications": [
                        {"type": "manual", "description": f"Check {i}", "criteria": {}}
                    ],
                },
                headers=headers,
            )
            assert task_resp.status_code == 201, task_resp.text
            task_ids.append(task_resp.json()["id"])

        for tid in task_ids:
            scan_resp = await client.post(
                f"/v1/scans/task/{tid}", headers=headers
            )
            assert scan_resp.status_code == 201, scan_resp.text

        # 列表
        resp = await client.get(
            f"/v1/teams/{seed.team_id}/scans", headers=headers
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
        for item in data["items"]:
            assert item["id"].startswith("scn_")
            assert item["target_type"] in ("task", "batch")

    @pytest.mark.asyncio
    async def test_list_scans_filter_by_target_type(
        self, client: AsyncClient, seed: SeedData
    ):
        """按 target_type 过滤仅返回匹配的扫描。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Filter Scans", "slug": _uniq_slug("filterscans")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Filtered task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Filter", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        await client.post(f"/v1/scans/task/{task_id}", headers=headers)

        # 过滤列表
        resp = await client.get(
            f"/v1/teams/{seed.team_id}/scans?target_type=task",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["target_type"] == "task"

    @pytest.mark.asyncio
    async def test_list_scans_cursor_pagination(
        self, client: AsyncClient, seed: SeedData
    ):
        """游标分页：创建 3 个扫描，limit=2，验证游标行为。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Cursor Scans", "slug": _uniq_slug("cursorscans")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        import asyncio

        task_ids = []
        for i in range(3):
            task_resp = await client.post(
                f"/v1/projects/{project_id}/tasks",
                json={
                    "title": f"Cursor task {i}",
                    "description": "test",
                    "verifications": [
                        {"type": "manual", "description": f"C{i}", "criteria": {}}
                    ],
                },
                headers=headers,
            )
            assert task_resp.status_code == 201, task_resp.text
            task_ids.append(task_resp.json()["id"])
            await client.post(
                f"/v1/scans/task/{task_ids[-1]}", headers=headers
            )
            await asyncio.sleep(0.01)  # 确保 created_at 时间戳不同

        # 第 1 页：limit=2
        resp1 = await client.get(
            f"/v1/teams/{seed.team_id}/scans?limit=2",
            headers=headers,
        )
        assert resp1.status_code == 200, resp1.text
        data1 = resp1.json()
        assert len(data1["items"]) == 2
        assert data1["next_cursor"] is not None
        assert data1["total"] == 3

        # 第 2 页：使用第 1 页的游标
        resp2 = await client.get(
            f"/v1/teams/{seed.team_id}/scans?limit=2&cursor={data1['next_cursor']}",
            headers=headers,
        )
        assert resp2.status_code == 200, resp2.text
        data2 = resp2.json()
        assert len(data2["items"]) == 1
        assert data2["total"] == 3

    @pytest.mark.asyncio
    async def test_get_scan_by_id(
        self, client: AsyncClient, seed: SeedData
    ):
        """GET /scans/{id} 返回完整 ScanResponse。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Get Scan", "slug": _uniq_slug("getscan")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Get scan task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Verify get", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        scan_resp = await client.post(
            f"/v1/scans/task/{task_id}", headers=headers
        )
        assert scan_resp.status_code == 201, scan_resp.text
        scan_id = scan_resp.json()["id"]

        # 获取详情
        resp = await client.get(f"/v1/scans/{scan_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["id"] == scan_id
        assert data["target_type"] == "task"
        assert data["target_id"] == task_id
        assert data["actor_type"] == "human"
        assert data["actor_id"] == seed.worker_id
        assert isinstance(data["rules_checked"], list)
        for v in data["rules_checked"]:
            assert "rule_id" in v
            assert v["status"] in ("pass", "fail", "warn")
            assert "detail" in v
        assert "pass" in data["summary"]
        assert "fail" in data["summary"]
        assert "warn" in data["summary"]

    @pytest.mark.asyncio
    async def test_get_scan_cross_team_404(
        self, client: AsyncClient, seed: SeedData
    ):
        """跨团队访问扫描返回 404。"""
        headers = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Team1 Scan", "slug": _uniq_slug("t1scan")},
            headers=headers,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Team 1 task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "T1", "criteria": {}}
                ],
            },
            headers=headers,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        scan_resp = await client.post(
            f"/v1/scans/task/{task_id}", headers=headers
        )
        assert scan_resp.status_code == 201, scan_resp.text
        scan_id = scan_resp.json()["id"]

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"Other Team {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="Other Admin",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        resp = await client.get(f"/v1/scans/{scan_id}", headers=headers2)
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_get_scan_not_found(self, client: AsyncClient, seed: SeedData):
        """不存在的扫描 ID 返回 404。"""
        headers = auth_header(seed.token)
        resp = await client.get("/v1/scans/scn_nonexistent01", headers=headers)
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_list_scans_team_isolation(
        self, client: AsyncClient, seed: SeedData
    ):
        """团队 A 在列表中看不到团队 B 的扫描。"""
        headers1 = auth_header(seed.token)

        proj_resp = await client.post(
            f"/v1/teams/{seed.team_id}/projects",
            json={"name": "Isolation", "slug": _uniq_slug("isolation")},
            headers=headers1,
        )
        assert proj_resp.status_code == 201, proj_resp.text
        project_id = proj_resp.json()["id"]

        task_resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": "Isolation task",
                "description": "test",
                "verifications": [
                    {"type": "manual", "description": "Iso", "criteria": {}}
                ],
            },
            headers=headers1,
        )
        assert task_resp.status_code == 201, task_resp.text
        task_id = task_resp.json()["id"]

        await client.post(f"/v1/scans/task/{task_id}", headers=headers1)

        # 创建第二个团队
        from src.auth import create_access_token
        from src.db import async_session_factory
        from src.utils.id_gen import generate_id

        team2_id = generate_id("team")
        member2_id = generate_id("member")
        async with async_session_factory() as session:
            from src.models.member import Member
            from src.models.team import Team

            short = team2_id.replace("tea_", "")[-12:]
            team2 = Team(
                id=team2_id, name=f"Other Team {short}", slug=f"other-{short}"
            )
            member2 = Member(
                id=member2_id,
                team_id=team2_id,
                user_id=f"user-{member2_id[:8]}",
                display_name="Other Admin",
                role="admin",
            )
            session.add_all([team2, member2])
            await session.commit()

        token2 = create_access_token(
            user_id=f"user-{member2_id[:8]}",
            member_id=member2_id,
            team_id=team2_id,
            role="admin",
        )
        headers2 = auth_header(token2)

        # 团队 2 列出扫描 — 应为空（团队 2 无扫描）
        resp = await client.get(
            f"/v1/teams/{team2_id}/scans", headers=headers2
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

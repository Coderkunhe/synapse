"""P11-B119 PFL-120: Proposal gate (_check_proposal_confirmed) 测试。

覆盖四条路径 + 跨 project 隔离 + 跨 actor 隔离：
- 无历史 proposal → bootstrap 放行
- 最新 proposal confirmed → 放行
- 最新 proposal pending → 422 PROPOSAL_NOT_CONFIRMED
- 最新 proposal rejected → 422 PROPOSAL_REJECTED
- 跨 project 隔离：project A 的 proposal 不阻断 project B
- 跨 actor 隔离：O1 的 proposal 不阻断 O2（PFL-122 · B120）
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import SeedData, auth_header


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════


async def _create_project(client: AsyncClient, seed: SeedData) -> str:
    """创建测试项目，返回 project_id。"""
    slug = f"prop-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        f"/v1/teams/{seed.team_id}/projects",
        json={"name": f"ProposalTest-{uuid.uuid4().hex[:8]}", "slug": slug},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_task(
    client: AsyncClient, project_id: str, seed: SeedData, title: str = "Test Task"
) -> str:
    """创建测试 Task，返回 task_id。"""
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": title,
            "description": "Test task for proposal gate",
            "verifications": [{"type": "manual", "description": "Check it works correctly"}],
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_proposal(
    client: AsyncClient,
    project_id: str,
    task_id: str,
    seed: SeedData,
    body: str = "I plan to refactor the auth module.",
) -> dict:
    """在 Task 上发一条 proposal 消息，返回 message 对象。"""
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks/{task_id}/messages",
        json={
            "task_id": task_id,
            "message_type": "proposal",
            "body": body,
        },
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _update_proposal_status(
    client: AsyncClient,
    project_id: str,
    task_id: str,
    message_id: str,
    seed: SeedData,
    proposal_status: str,
) -> None:
    """更新 proposal 消息的 proposal_status。"""
    resp = await client.patch(
        f"/v1/projects/{project_id}/tasks/{task_id}/messages/{message_id}",
        json={"proposal_status": proposal_status},
        headers=auth_header(seed.token),
    )
    assert resp.status_code == 200, resp.text


async def _try_create_task(
    client: AsyncClient, project_id: str, seed: SeedData
) -> tuple[int, dict]:
    """尝试在 project 下创建 Task，返回 (status_code, body)。"""
    resp = await client.post(
        f"/v1/projects/{project_id}/tasks",
        json={
            "title": f"Second Task {uuid.uuid4().hex[:6]}",
            "description": "Should be blocked if proposal gate active",
            "verifications": [{"type": "manual", "description": "Manual verification check"}],
        },
        headers=auth_header(seed.token),
    )
    return resp.status_code, resp.json()


# ═════════════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════════════


class TestProposalGateBootstrap:
    """无历史 proposal → bootstrap 模式，放行。"""

    @pytest.mark.asyncio
    async def test_bootstrap_no_proposal_allows_task_create(
        self, client: AsyncClient, seed: SeedData
    ):
        """新项目无任何 proposal 时，Task 创建应直接成功（bootstrap 模式）。"""
        project_id = await _create_project(client, seed)
        status, body = await _try_create_task(client, project_id, seed)
        assert status == 201, f"Bootstrap should allow task creation, got {status}: {body}"


class TestProposalGateConfirmed:
    """最新 proposal 为 confirmed → 放行。"""

    @pytest.mark.asyncio
    async def test_confirmed_proposal_allows_next_task(
        self, client: AsyncClient, seed: SeedData
    ):
        """O 的 proposal 被 Human 确认后，可以继续创建 Task。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "Initial Task")
        msg = await _post_proposal(client, project_id, task_id, seed)
        await _update_proposal_status(
            client, project_id, task_id, msg["id"], seed, "confirmed"
        )

        status, body = await _try_create_task(client, project_id, seed)
        assert status == 201, f"Confirmed proposal should allow task creation, got {status}: {body}"


class TestProposalGatePending:
    """最新 proposal 为 pending → 422 PROPOSAL_NOT_CONFIRMED。"""

    @pytest.mark.asyncio
    async def test_pending_proposal_blocks_task_create(
        self, client: AsyncClient, seed: SeedData
    ):
        """O 的 proposal 尚未被 Human 确认时，新 Task 创建应被阻断。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "Initial Task")
        await _post_proposal(client, project_id, task_id, seed)

        status, body = await _try_create_task(client, project_id, seed)
        assert status == 422, f"Pending proposal should block task creation, got {status}: {body}"
        assert body["error"]["code"] == "PROPOSAL_NOT_CONFIRMED", (
            f"Expected PROPOSAL_NOT_CONFIRMED, got {body.get('error', {}).get('code')}"
        )

    @pytest.mark.asyncio
    async def test_proposal_with_null_status_blocks(
        self, client: AsyncClient, seed: SeedData
    ):
        """proposal_status 为 None（默认值）等价于 pending，应阻断。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "Initial Task")
        msg = await _post_proposal(client, project_id, task_id, seed)
        # proposal_status 默认为 None → 等同 pending
        assert msg.get("proposal_status") is None

        status, body = await _try_create_task(client, project_id, seed)
        assert status == 422, f"Null proposal_status should block, got {status}: {body}"
        assert body["error"]["code"] == "PROPOSAL_NOT_CONFIRMED", (
            f"Expected PROPOSAL_NOT_CONFIRMED, got {body.get('error', {}).get('code')}"
        )


class TestProposalGateRejected:
    """最新 proposal 为 rejected → 422 PROPOSAL_REJECTED。"""

    @pytest.mark.asyncio
    async def test_rejected_proposal_blocks_task_create(
        self, client: AsyncClient, seed: SeedData
    ):
        """O 的 proposal 被 Human 驳回后，新 Task 创建应返回 PROPOSAL_REJECTED。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "Initial Task")
        msg = await _post_proposal(client, project_id, task_id, seed)
        await _update_proposal_status(
            client, project_id, task_id, msg["id"], seed, "rejected"
        )

        status, body = await _try_create_task(client, project_id, seed)
        assert status == 422, f"Rejected proposal should block task creation, got {status}: {body}"
        assert body["error"]["code"] == "PROPOSAL_REJECTED", (
            f"Expected PROPOSAL_REJECTED, got {body.get('error', {}).get('code')}"
        )


class TestProposalGateCrossProject:
    """跨 project 隔离：project A 的 proposal 不阻断 project B。"""

    @pytest.mark.asyncio
    async def test_proposal_in_project_a_does_not_block_project_b(
        self, client: AsyncClient, seed: SeedData
    ):
        """Project A 有 pending proposal，Project B 的新 Task 创建不受影响。"""
        project_a = await _create_project(client, seed)
        task_a = await _create_task(client, project_a, seed, "Task in A")
        await _post_proposal(client, project_a, task_a, seed)

        # Project B — 无任何 proposal
        project_b = await _create_project(client, seed)
        status, body = await _try_create_task(client, project_b, seed)
        assert status == 201, (
            f"Project B should not be affected by Project A's proposal, got {status}: {body}"
        )

    @pytest.mark.asyncio
    async def test_confirmed_in_a_pending_in_b(
        self, client: AsyncClient, seed: SeedData
    ):
        """Project A proposal 已 confirmed，Project B proposal 仍 pending — 各自独立判断。"""
        # Project A: confirmed
        project_a = await _create_project(client, seed)
        task_a = await _create_task(client, project_a, seed, "Task A")
        msg_a = await _post_proposal(client, project_a, task_a, seed)
        await _update_proposal_status(
            client, project_a, task_a, msg_a["id"], seed, "confirmed"
        )

        # Project B: pending
        project_b = await _create_project(client, seed)
        task_b = await _create_task(client, project_b, seed, "Task B")
        await _post_proposal(client, project_b, task_b, seed)

        # A → 放行
        status_a, body_a = await _try_create_task(client, project_a, seed)
        assert status_a == 201, f"Project A should allow, got {status_a}: {body_a}"

        # B → 阻断
        status_b, body_b = await _try_create_task(client, project_b, seed)
        assert status_b == 422, f"Project B should block, got {status_b}: {body_b}"
        assert body_b["error"]["code"] == "PROPOSAL_NOT_CONFIRMED"


# ═════════════════════════════════════════════════════════════════════════
# Cross-actor helpers (PFL-122 · B120)
# ═════════════════════════════════════════════════════════════════════════


async def _create_second_actor_token(
    client: AsyncClient, seed: SeedData, project_id: str
) -> tuple[str, str]:
    """在同一 team 中创建第二个 Worker（模拟 O2），并分配 orchestrator 角色。

    O1 = seed.token 的 actor。O2 = 同 team 不同 worker，有同 project 的 orchestrator 角色。
    返回 (token, worker_id)。
    """
    from src.auth import create_access_token
    from src.db import async_session_factory
    from src.models.member import Member
    from src.models.worker import Worker
    from src.constants import WorkerActorType, WorkerStatus
    from src.utils.id_gen import derive_id, generate_id

    member2_id = generate_id("member")
    worker2_id = derive_id(member2_id, "worker")
    # 使用完整 member_id 避免 UUIDv7 时间戳相近导致 [:8] 前缀碰撞
    user2_id = f"user-{member2_id}"

    async with async_session_factory() as session:
        member2 = Member(
            id=member2_id,
            team_id=seed.team_id,
            user_id=user2_id,
            display_name="Orchestrator2",
            role="admin",
        )
        worker2 = Worker(
            id=worker2_id,
            name="Orchestrator2",
            team_id=seed.team_id,
            user_id=None,
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
            api_key_hash="",
        )
        session.add_all([member2, worker2])
        await session.commit()

    token2 = create_access_token(
        user_id=user2_id,
        actor_id=worker2_id,
        team_id=seed.team_id,
        role="admin",
    )

    # 为 O2 分配 orchestrator 角色，使其有 task:create 权限
    from tests.conftest import ensure_project_role
    await ensure_project_role(
        client, project_id, worker2_id, "orchestrator", auth_header(seed.token)
    )

    return token2, worker2_id


# ═════════════════════════════════════════════════════════════════════════
# Cross-actor isolation tests (PFL-122 · B120)
# ═════════════════════════════════════════════════════════════════════════


class TestProposalGateCrossActor:
    """跨 actor 隔离：O1 的 proposal 不阻断 O2 的 task 创建。

    _check_proposal_confirmed 按 sender_worker_id == actor_id 过滤 —
    O1 的 proposal 状态与 O2 无关。
    """

    @pytest.mark.asyncio
    async def test_o1_pending_proposal_does_not_block_o2(
        self, client: AsyncClient, seed: SeedData
    ):
        """O1 有 pending proposal，O2 在同一 project 创建 Task — 不应阻断。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "O1 Initial Task")
        # O1 发 proposal（使用 seed.token = O1）
        await _post_proposal(client, project_id, task_id, seed)

        # 创建 O2 的 token
        token_o2, _ = await _create_second_actor_token(client, seed, project_id)

        # O2 尝试创建 Task — 应成功（O1 的 proposal 不关 O2 的事）
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": f"O2 Task {uuid.uuid4().hex[:6]}",
                "description": "O2 should not be blocked by O1's proposal",
                "verifications": [{"type": "manual", "description": "Verify O2 work"}],
            },
            headers=auth_header(token_o2),
        )
        assert resp.status_code == 201, (
            f"O2 should NOT be blocked by O1's pending proposal. "
            f"Got {resp.status_code}: {resp.json()}"
        )

    @pytest.mark.asyncio
    async def test_o1_rejected_proposal_does_not_block_o2(
        self, client: AsyncClient, seed: SeedData
    ):
        """O1 的 proposal 被 rejected，O2 仍可创建 Task。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "O1 Initial Task")
        msg = await _post_proposal(client, project_id, task_id, seed)
        await _update_proposal_status(
            client, project_id, task_id, msg["id"], seed, "rejected"
        )

        token_o2, _ = await _create_second_actor_token(client, seed, project_id)

        resp = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": f"O2 Task {uuid.uuid4().hex[:6]}",
                "description": "O2 should not be blocked by O1's rejected proposal",
                "verifications": [{"type": "manual", "description": "Verify O2 work"}],
            },
            headers=auth_header(token_o2),
        )
        assert resp.status_code == 201, (
            f"O2 should NOT be blocked by O1's rejected proposal. "
            f"Got {resp.status_code}: {resp.json()}"
        )

    @pytest.mark.asyncio
    async def test_o2_own_pending_proposal_blocks_o2(
        self, client: AsyncClient, seed: SeedData
    ):
        """O2 自己的 pending proposal 应阻断 O2 自己 — 隔离是对 actor 的，不是全局豁免。"""
        project_id = await _create_project(client, seed)
        # O1 创建初始 task
        task_id = await _create_task(client, project_id, seed, "O1 Initial Task")

        token_o2, _ = await _create_second_actor_token(client, seed, project_id)

        # O2 发 proposal
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/{task_id}/messages",
            json={
                "task_id": task_id,
                "message_type": "proposal",
                "body": "O2's proposal for next work",
            },
            headers=auth_header(token_o2),
        )
        assert resp.status_code == 201, resp.text

        # O2 尝试创建新 Task — 应被自己 pending proposal 阻断
        resp2 = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": f"O2 Second Task {uuid.uuid4().hex[:6]}",
                "description": "O2 should be blocked by own pending proposal",
                "verifications": [{"type": "manual", "description": "Verify"}],
            },
            headers=auth_header(token_o2),
        )
        assert resp2.status_code == 422, (
            f"O2 should be blocked by OWN pending proposal. "
            f"Got {resp2.status_code}: {resp2.json()}"
        )
        assert resp2.json()["error"]["code"] == "PROPOSAL_NOT_CONFIRMED"

    @pytest.mark.asyncio
    async def test_o2_confirmed_proposal_allows_o2(
        self, client: AsyncClient, seed: SeedData
    ):
        """O2 的 proposal 被 confirmed 后，O2 可继续创建 Task。"""
        project_id = await _create_project(client, seed)
        task_id = await _create_task(client, project_id, seed, "O1 Initial Task")

        token_o2, _ = await _create_second_actor_token(client, seed, project_id)

        # O2 发 proposal 并确认
        resp = await client.post(
            f"/v1/projects/{project_id}/tasks/{task_id}/messages",
            json={
                "task_id": task_id,
                "message_type": "proposal",
                "body": "O2's proposal",
            },
            headers=auth_header(token_o2),
        )
        assert resp.status_code == 201, resp.text
        msg_o2 = resp.json()

        await _update_proposal_status(
            client, project_id, task_id, msg_o2["id"], seed, "confirmed"
        )

        # O2 创建新 Task — 应成功
        resp2 = await client.post(
            f"/v1/projects/{project_id}/tasks",
            json={
                "title": f"O2 Task {uuid.uuid4().hex[:6]}",
                "description": "O2 confirmed → should allow",
                "verifications": [{"type": "manual", "description": "Verify"}],
            },
            headers=auth_header(token_o2),
        )
        assert resp2.status_code == 201, (
            f"O2 with confirmed proposal should be allowed. "
            f"Got {resp2.status_code}: {resp2.json()}"
        )

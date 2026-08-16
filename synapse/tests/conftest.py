"""Synapse E2E 测试夹具。

架构：
- Session 级临时 SQLite 数据库（一次测试运行共享一个 DB）
- 表在 session 启动时创建一次
- 每个测试通过辅助函数自行播种数据，避免跨测试污染
- ASGI transport — 无需真实 HTTP 服务器

注意：DATABASE_URL 必须在任何 src.* 导入之前设置，
因为 src/db.py 在模块级别通过 settings.database_url 创建引擎。
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

# ── 在任何项目导入之前设置测试数据库 URL ──────────────────────
# 临时文件在整个测试 session 期间持久存在；在
# pytest_sessionfinish 中清理。

_test_dir = Path(tempfile.gettempdir()) / "synapse_tests"
_test_dir.mkdir(exist_ok=True)
_test_db_fd, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="test_", dir=str(_test_dir))
os.close(_test_db_fd)

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["DEBUG"] = "false"  # 测试中禁用 SQL echo
os.environ["JWT_SECRET"] = "test-secret-not-for-production"  # P100-B105: 防止 placeholder 校验报错
os.environ["RATE_LIMIT_ENABLED"] = "false"  # P100-B105: 测试中禁用速率限制中间件
os.environ["RATE_LIMIT_LOGIN"] = "999999/minute"  # 测试中设置极高限制避免 429
os.environ["RATE_LIMIT_REGISTER"] = "999999/minute"
os.environ["RATE_LIMIT_FORGOT_PASSWORD"] = "999999/minute"
os.environ["RATE_LIMIT_RESET_PASSWORD"] = "999999/minute"

# 现在可以安全导入 — 引擎将指向我们的临时数据库。
# mypy: ignore-all-unimports
from src.config import settings  # noqa: E402
from src.db import async_session_factory, engine  # noqa: E402
from src.main import create_app  # noqa: E402
from src.models.base import Base  # noqa: E402


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """所有测试完成后清理临时数据库。"""
    try:
        Path(_TEST_DB_PATH).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def app():
    """创建所有表并返回 FastAPI app（session 级）。"""
    # 在临时数据库中创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()
    yield app

    # 清理
    await engine.dispose()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """基于 ASGI transport 的异步 HTTP 客户端。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── 播种辅助 ───────────────────────────────────────────────────

class SeedData:
    """保存已播种的 Team + Admin Member 的 ID 和 token。

    使用 :func:`seed_team` 来创建。每个测试应创建自己的
    种子数据，避免实体在测试间泄漏。
    """

    def __init__(self, team_id: str, member_id: str, token: str, worker_id: str):
        self.team_id = team_id
        self.member_id = member_id
        self.token = token
        self.worker_id = worker_id  # P10-B7: derived from member_id via derive_id


@pytest_asyncio.fixture
async def seed(client) -> AsyncGenerator[SeedData, None]:
    """播种一个 Team + Admin Member 并返回其 token。

    每个测试一个 fixture — 每个测试获得一个全新的 team 以实现隔离。
    """
    from src.auth import create_access_token
    from src.utils.id_gen import generate_id

    team_id = generate_id("team")
    member_id = generate_id("member")

    # 我们直接写入数据库，因为没有 POST /teams 端点。
    async with async_session_factory() as session:
        from src.models.member import Member
        from src.models.team import Team
        from src.models.worker import Worker
        from src.constants import WorkerActorType, WorkerStatus

        # 使用 ID 的后 12 个字符（包含 UUIDv7 的随机部分）以保证唯一性
        short = team_id.replace("tea_", "")[-12:]
        team = Team(id=team_id, name=f"Test Team {short}", slug=f"test-{short}")
        member = Member(
            id=member_id,
            team_id=team_id,
            user_id=f"user-{member_id[:8]}",
            display_name="Admin",
            role="admin",
        )
        # P10-B7: Create human Worker alongside Member (aligns with upsert_member_via_oauth)
        from src.utils.id_gen import derive_id
        worker_id = derive_id(member_id, "worker")
        worker = Worker(
            id=worker_id,
            name="Admin",
            team_id=team_id,
            user_id=None,  # P100-B106: FK PRAGMA 启用后 user_id 必须指向存在的 User；测试中无 User 记录故设为 None
            actor_type=WorkerActorType.HUMAN,
            status=WorkerStatus.ACTIVE,
            api_key_hash=None,  # human workers use JWT, not API keys (nullable since P10-B8)
        )
        session.add_all([team, member, worker])
        await session.commit()

    token = create_access_token(
        user_id=f"user-{member_id[:8]}",
        actor_id=worker_id,
        team_id=team_id,
        role="admin",
    )
    yield SeedData(team_id=team_id, member_id=member_id, token=token, worker_id=worker_id)

    # 无需清理：每个测试使用唯一的 UUIDv7 ID，并且
    # 临时数据库在 session 结束时删除。清理可能会触发 FK
    # 违规（workers 通过 registered_by 引用 workers 自引用）。


def auth_header(token: str) -> dict[str, str]:
    """便捷函数：Bearer 认证头字典。"""
    return {"Authorization": f"Bearer {token}"}


async def ready_task(client, task: dict, token: str) -> dict:
    """P11-B72: 将 Task 从 BACKLOG 提升为 READY，返回更新后的 task。

    Ready gate 要求 task.description 非空且至少有 1 个可判定的 verification。
    所有使用 _create_task 后紧跟 assign/claim 的测试必须先调此函数。
    """
    resp = await client.post(
        f"/v1/tasks/{task['id']}/ready",
        json={"expected_version": task["version_no"]},
        headers=auth_header(token),
    )
    assert resp.status_code == 200, f"ready_task failed: {resp.status_code} {resp.text}"
    return resp.json()


async def ensure_project_role(
    client,
    project_id: str,
    worker_id: str,
    role: str,
    admin_headers: dict,
) -> None:
    """B55 (GAP-7): 为 Worker 分配项目角色，用于 submit/ready/cancel 等守卫端点。

    在 Worker handshake 后调用，确保 Worker 有权限调用 require_permission
    守卫的端点（如 submit 需要 builder 角色）。
    """
    resp = await client.post(
        f"/v1/admin/projects/{project_id}/roles",
        json={"worker_id": worker_id, "role": role},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Role assignment failed: {resp.text}"


# ── P100-B15 C3: 测试隔离 — 防止跨测试 Worker 状态泄漏 ──────────
# 故障检测器 (detect_heartbeat_failures) 全局扫描所有 active Worker，
# 不按 team_id 过滤。E2E 测试中若前一个测试遗留心跳过期的 Worker，
# 后续测试运行故障检测器时会产生误报。
#
# 此 fixture 在每个测试结束后停用该 team 下所有 Worker，
# 确保每个测试的 Worker 不会污染后续测试。


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_team_agents(seed: SeedData):
    """每个测试后停用该 team 的所有 Worker，防止全局扫描误报。"""
    yield
    from src.models.worker import Worker

    async with async_session_factory() as db:
        stmt = select(Worker).where(Worker.team_id == seed.team_id)
        result = await db.execute(stmt)
        workers = result.scalars().all()
        for worker in workers:
            if worker.status == "active":
                worker.status = "inactive"
        await db.commit()

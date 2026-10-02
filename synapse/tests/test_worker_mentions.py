"""P17-B12: GET /workers/me/mentions 端点测试 — worker 维度未读 mention 查询."""

from __future__ import annotations

import pytest
import pytest_asyncio

from src.auth import create_access_token
from src.constants import ActorType
from src.db import async_session_factory
from src.models.project import Project
from src.models.task import Task
from src.models.worker import Worker
from src.services.conversation_service import create_message
from src.utils.id_gen import generate_id


@pytest_asyncio.fixture
async def mention_setup(seed):
    """创建 target worker（被 @ 者）+ sender worker + project + task。

    返回 target token（actor_id=target），供 GET /workers/me/mentions 以
    target 身份调用。target/sender 用无空格唯一名，避免 resolve_mentions
    的模糊 LIKE 跨测试串味。
    """
    async with async_session_factory() as session:
        target = Worker(
            id=generate_id("worker"),
            name="MentionTarget",
            team_id=seed.team_id,
            actor_type="agent",
            status="active",
            api_key_hash=None,
        )
        sender = Worker(
            id=generate_id("worker"),
            name="MentionSender",
            team_id=seed.team_id,
            actor_type="agent",
            status="active",
            api_key_hash=None,
        )
        project = Project(
            id=generate_id("project"),
            name="Mention Project",
            slug=f"mention-{generate_id('project')[-8:]}",
            team_id=seed.team_id,
        )
        session.add_all([target, sender, project])
        await session.commit()
        task = Task(
            id=generate_id("task"),
            project_id=project.id,
            title="Mention Task",
            status="pending",
        )
        session.add(task)
        await session.commit()

    token = create_access_token(
        user_id=f"user-{target.id[:8]}",
        actor_id=target.id,
        team_id=seed.team_id,
        role="builder",
        actor_type=ActorType.WORKER,
    )
    return {
        "target_id": target.id,
        "sender_id": sender.id,
        "project_id": project.id,
        "task_id": task.id,
        "token": token,
        "team_id": seed.team_id,
    }


async def _mention(mention_setup, body: str, *, in_reply_to_id=None, sender=None):
    """以 sender 身份创建一条消息，返回 message id."""
    async with async_session_factory() as session:
        msg = await create_message(
            session,
            task_id=mention_setup["task_id"],
            workflow_id=None,
            message_type="clarification",
            body=body,
            in_reply_to_id=in_reply_to_id,
            sender_worker_id=sender or mention_setup["sender_id"],
            team_id=mention_setup["team_id"],
            actor_type=ActorType.WORKER,
            actor_id=sender or mention_setup["sender_id"],
        )
        await session.commit()
        return msg.id


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ══ 端点测试 ══


@pytest.mark.asyncio
async def test_get_my_mentions_returns_unread(client, mention_setup):
    """指向我的未读 mention 被返回."""
    msg_id = await _mention(mention_setup, "@worker:MentionTarget 请看一下。")

    resp = await client.get("/v1/workers/me/mentions", headers=_headers(mention_setup["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert msg_id in [m["id"] for m in data["messages"]]


@pytest.mark.asyncio
async def test_get_my_mentions_empty(client, mention_setup):
    """无指向我的 mention → 空列表."""
    resp = await client.get("/v1/workers/me/mentions", headers=_headers(mention_setup["token"]))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["messages"] == []


@pytest.mark.asyncio
async def test_get_my_mentions_unread_false_includes_replied(client, mention_setup):
    """unread=false 返回已回复的 mention · unread=true 不返回."""
    msg_id = await _mention(mention_setup, "@worker:MentionTarget 请看一下。")

    # target 回复
    await _mention(mention_setup, "收到。", in_reply_to_id=msg_id, sender=mention_setup["target_id"])

    unread = await client.get("/v1/workers/me/mentions", headers=_headers(mention_setup["token"]))
    assert unread.status_code == 200
    assert msg_id not in [m["id"] for m in unread.json()["messages"]]

    all_mentions = await client.get(
        "/v1/workers/me/mentions?unread=false", headers=_headers(mention_setup["token"])
    )
    assert all_mentions.status_code == 200
    assert msg_id in [m["id"] for m in all_mentions.json()["messages"]]


@pytest.mark.asyncio
async def test_get_my_mentions_requires_auth(client):
    """无 token → 401."""
    resp = await client.get("/v1/workers/me/mentions")
    assert resp.status_code == 401

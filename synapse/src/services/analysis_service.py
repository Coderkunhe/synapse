"""Analysis 服务 — 创建 + 查询 + 事件记录。

所有状态变更操作通过 EventStore 记录事件。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import NotFoundError
from src.models.analysis import AnalysisRecord
from src.services.event_store import event_store
from src.utils.id_gen import generate_id
from src.utils.json_utils import safe_dumps, safe_loads


async def create_analysis(
    db: AsyncSession,
    *,
    project_id: str,
    title: str,
    content: str,
    analysis_type: str,
    source_batch_id: str | None,
    metadata: dict | None,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> AnalysisRecord:
    """创建不可变的 AnalysisRecord。记录 ``analysis.created`` 事件。"""
    analysis = AnalysisRecord(
        id=generate_id("analysis_record"),
        project_id=project_id,
        actor_type=actor_type,
        actor_id=actor_id,
        analysis_type=analysis_type,
        title=title,
        content=content,
        source_batch_id=source_batch_id,
        metadata_=safe_dumps(metadata),
        create_user_id=actor_id,
    )
    db.add(analysis)

    await event_store.record(
        db,
        event_type="analysis.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="analysis",
        target_id=analysis.id,
        payload={
            "project_id": project_id,
            "analysis_type": analysis_type,
            "title": title,
        },
    )

    return analysis


async def get_analysis(db: AsyncSession, analysis_id: str) -> AnalysisRecord:
    """按 ID 获取 AnalysisRecord，未找到则抛出 NotFoundError。"""
    analysis = await db.get(AnalysisRecord, analysis_id)
    if analysis is None:
        raise NotFoundError("analysis", analysis_id)
    return analysis


async def list_analyses(
    db: AsyncSession,
    project_id: str,
    *,
    analysis_type: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[AnalysisRecord], str | None, int | None]:
    """游标分页列出项目的分析记录，最新优先。
    可按 analysis_type 过滤。
    """
    conditions = [AnalysisRecord.project_id == project_id]
    if analysis_type:
        conditions.append(AnalysisRecord.analysis_type == analysis_type)
    if cursor:
        conditions.append(AnalysisRecord.id > cursor)

    stmt = (
        select(AnalysisRecord)
        .where(*conditions)
        .order_by(AnalysisRecord.created_at.desc())
        .limit(limit + 1)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    count_stmt = select(func.count(AnalysisRecord.id)).where(*conditions)
    total = (await db.execute(count_stmt)).scalar()

    return items, next_cursor, total


def analysis_to_response(analysis: AnalysisRecord) -> dict:
    """将 AnalysisRecord ORM 对象转换为带 JSON 反序列化的响应字典。"""
    return {
        "id": analysis.id,
        "project_id": analysis.project_id,
        "actor_type": analysis.actor_type,
        "actor_id": analysis.actor_id,
        "analysis_type": analysis.analysis_type,
        "title": analysis.title,
        "content": analysis.content,
        "source_batch_id": analysis.source_batch_id,
        "metadata": safe_loads(analysis.metadata_),
        "is_disabled": analysis.is_disabled,
        "create_user_id": analysis.create_user_id,
        "last_update_user_id": analysis.last_update_user_id,
        "remark": analysis.remark,
        "version_no": analysis.version_no,
        "created_at": analysis.created_at,
        "updated_at": analysis.updated_at,
    }

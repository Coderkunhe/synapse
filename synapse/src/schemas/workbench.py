"""个人工作台响应模型（P17-B29 · GET /v1/me/tasks）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class WorkbenchTask(BaseModel):
    """「我」名下单个任务的轻量切片 — 卸载「任务 + 依赖」上下文。"""

    task_id: str
    title: str
    status: str
    priority: str
    project_id: str
    project_name: str | None = None
    claimed_at: datetime | None = None
    deadline_at: datetime | None = None
    depends_on: list[dict] | None = None
    dependency_blocked: bool = False


class WorkbenchResponse(BaseModel):
    """个人工作台响应 — 跨项目聚合的「我的任务」列表。"""

    tasks: list[WorkbenchTask]

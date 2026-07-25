"""Synapse API 路由 — 薄入口层。

所有路由处理器位于 ``src.api.routers.*`` 模块中。
本模块仅负责导入并挂载子路由。
"""

from __future__ import annotations

from fastapi import APIRouter

from .routers import admin, authorization_requests, bootstrap, capabilities, capability_audits, circuit_breakers, conversation, decision_audits, protection_reports, webpush, workers, workflow, analyses, auth, batches, docs, events, features, projects, scans, skills, tasks, teams, token_usage
from . import dashboard

api_router = APIRouter(prefix="/v1")

api_router.include_router(teams.router)
api_router.include_router(workers.router)
api_router.include_router(workers.agents_router)  # deprecated /agents/* backward compat
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(conversation.router, prefix="/projects/{project_id}/tasks/{task_id}/messages")
api_router.include_router(batches.router)
api_router.include_router(events.router)
api_router.include_router(auth.router)
api_router.include_router(bootstrap.router)
api_router.include_router(analyses.router)
api_router.include_router(scans.router)
api_router.include_router(skills.router)
api_router.include_router(token_usage.router)
api_router.include_router(docs.router)
api_router.include_router(features.router)
api_router.include_router(authorization_requests.router)
api_router.include_router(capabilities.router)
api_router.include_router(admin.router, prefix="/admin")
api_router.include_router(workflow.router, prefix="/admin/projects/{project_id}/workflows")
api_router.include_router(protection_reports.router)
api_router.include_router(capability_audits.router)
api_router.include_router(circuit_breakers.router)
api_router.include_router(decision_audits.router)
api_router.include_router(webpush.router)
api_router.include_router(dashboard.dashboard_router)

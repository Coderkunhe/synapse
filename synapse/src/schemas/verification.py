"""Verification schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, AliasChoices

from src.schemas.common import AuditFields


class VerificationCreateRequest(BaseModel):
    """创建新 Verification 的请求体（PFL-106 · B106）。"""
    task_id: str = Field(..., max_length=40, description="父 Task ID")
    type: str = Field(default="manual", pattern=r"^(manual|automated|check_list)$")
    description: str = Field(
        ...,
        min_length=6,
        max_length=1000,
        description="可判定的验证条件描述（≥6 字符）",
    )
    criteria: dict | None = Field(None, description="结构化判定规则（可选）")


class VerificationVerifyRequest(BaseModel):
    """执行验证的请求体（protocol.md §6.3）。"""
    status: str = Field(..., pattern=r"^(passed|failed|approved|rejected)$")
    comment: str | None = None
    evidence: dict | None = None
    rejection_reason: str | None = Field(None, max_length=2000)
    expected_version: int = Field(..., ge=1, validation_alias=AliasChoices("expected_version", "expected_task_version"))


# ── P8-B6: 批量验证 ───────────────────────────────────────────────────

class VerificationBatchItem(BaseModel):
    """批量请求中的单个验证项。"""
    verification_id: str
    status: str = Field(..., pattern=r"^(passed|failed|approved|rejected)$")
    comment: str | None = None
    rejection_reason: str | None = Field(None, max_length=2000)
    review_flag: bool = False
    expected_version: int = Field(..., ge=1, validation_alias=AliasChoices("expected_version", "expected_task_version"))


class VerificationBatchRequest(BaseModel):
    """批量验证请求 — 在单次调用中处理多个验证。

    auto_approved=True 表示 Claude（Creator 助理）执行了初审。
    人类 Creator 仍持有最终裁决权。
    """
    items: list[VerificationBatchItem] = Field(..., min_length=1, max_length=50)
    auto_approved: bool = False


class VerificationBatchItemResult(BaseModel):
    """批量验证响应中的单条结果。"""
    verification_id: str
    task_id: str
    status: str  # "passed" | "failed" | "error"
    error: str | None = None  # 当 status == "error" 时设置


class VerificationBatchTaskOutcome(BaseModel):
    """批量验证后每个 Task 的结果。"""
    task_id: str
    task_status: str  # "completed" | "rejected" | "in_verification"
    redo_count: int


class VerificationBatchResponse(BaseModel):
    """批量验证的响应体。"""
    results: list[VerificationBatchItemResult]
    task_outcomes: list[VerificationBatchTaskOutcome]
    summary: dict  # {"passed": N, "failed": N, "error": N, "flagged": N}


# ── 响应 ─────────────────────────────────────────────────────────────

class VerificationResponse(AuditFields):
    """Verification 读取操作的响应体。"""
    id: str
    task_id: str
    type: str
    description: str
    criteria: dict | None = None
    status: str
    verified_by: str | None = None
    verified_at: datetime | None = None
    evidence: dict | None = None
    rejection_reason: str | None = None
    # P8-B6: 二级验收字段
    review_flag: bool = False
    auto_approved: bool = False

"""Verification 服务 — 执行验证、检查任务完成状态。

验证后，若全部通过 → 任务完成。
若有任一失败 → 任务 REJECTED（redo_count 递增）。

P8-B6: 批量验证 + 二级验收（Claude初审 → 人工终审）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exceptions import (
    ConflictError,
    InvalidStateTransition,
    NotFoundError,
)
from src.models.authorization_request import AuthorizationRequest
from src.models.event import Event
from src.models.task import Task
from src.models.verification import Verification
from src.services.event_store import event_store
from src.services.ws_manager import ws_manager
from src.constants import TaskStatus, VerificationStatus, VerificationType
from src.config import settings
from src.task_state_machine import apply_transition
from src.utils.json_utils import safe_dumps, safe_loads
import logging

logger = logging.getLogger(__name__)


# ── 幂等 guard (P11-B76) ─────────────────────────────────────


async def _check_verify_idempotent(
    db: AsyncSession,
    *,
    verification_id: str,
    actor_id: str,
    task_id: str,
) -> None:
    """检查同一 actor 对同一 verification 是否在幂等窗口内已执行过 verify。

    查询 Event 表（append-only），跨 resubmit 周期有效。
    若窗口内有 ``verification.executed`` 事件，且此后 Verification 未被 reset
    （P8-B8: verification.reset 事件），则返回 409 DUPLICATE_VERIFICATION。

    合法 rework 周期：verify failed → task.rejected → resubmit → verification 被
    reset 为 PENDING（记录 verification.reset）→ 再 verify。不拦截。
    """
    from datetime import datetime, timedelta, timezone

    window_start = datetime.now(timezone.utc) - timedelta(
        seconds=settings.verify_idempotent_window_seconds
    )
    result = await db.execute(
        select(Event).where(
            Event.event_type == "verification.executed",
            Event.actor_id == actor_id,
            Event.target_type == "verification",
            Event.target_id == verification_id,
            Event.created_at >= window_start,
        ).order_by(Event.created_at.desc()).limit(1)
    )
    prev = result.scalars().first()
    if prev is None:
        return  # 窗口内无历史 verify → OK

    # 若上次 verify 是 review_flag（待人工复核）→ 放行
    # review_flag 的 verification 保持 PENDING，不应被幂等 guard 拦截
    prev_payload = safe_loads(prev.payload) if prev.payload else {}
    if prev_payload.get("review_flag"):
        return  # 待人工复核 → OK

    # 若 Verification 在本次 verify 之后被 reset → 合法 rework 周期 → 放行
    # P8-B8 (task_execution.py): 当已执行的验证在 task resubmit 时被重置为 PENDING，
    # 会记录 verification.reset 事件。这是 rework 的直接信号，比 task.rejected 更可靠。
    # 时序约束：仅当 reset 发生在 prev verification.executed 之后（含同时），
    # 才是"验证失败→返工→重验"的合法周期。历史的 reset 不应放行。
    # 使用 >= 是因为 execute_verification 在同一事务中先记录
    # verification.executed 再记录 task.rejected，reset 在后续的 submit_task 中记录。
    reset_result = await db.execute(
        select(Event).where(
            Event.event_type == "verification.reset",
            Event.target_type == "verification",
            Event.target_id == verification_id,
            Event.created_at >= prev.created_at,
        ).limit(1)
    )
    if reset_result.scalars().first() is not None:
        return  # 合法 rework → Verification 被显式 reset

    # P12-B18: 防御纵深 — 若 verification.reset 事件缺失（如 Worker 提交遗漏），
    # 检查 task.rejected 事件作为合法 rework 的补充信号。
    # 如果 Task 在上次 verification.executed 后被拒绝过，说明经历了
    # "验证失败→返工→重新提交" 的合法周期，应放行。
    rejected_result = await db.execute(
        select(Event).where(
            Event.event_type == "task.rejected",
            Event.target_type == "task",
            Event.target_id == task_id,
            Event.created_at >= prev.created_at,
        ).limit(1)
    )
    if rejected_result.scalars().first() is not None:
        return  # 合法 rework → Task 在上次 verify 后被拒绝（防御纵深）

    raise ConflictError(
        "DUPLICATE_VERIFICATION",
        f"Verification {verification_id} was already executed by {actor_id} "
        f"at {prev.created_at.isoformat()}. "
        f"Idempotent window: {settings.verify_idempotent_window_seconds}s. "
        f"Wait before re-verifying.",
        {
            "verificationId": verification_id,
            "verifierId": actor_id,
            "previousExecutionAt": prev.created_at.isoformat(),
            "idempotentWindowSeconds": settings.verify_idempotent_window_seconds,
        },
    )


# ── P14-B9: Server 侧 auto-verify ─────────────────────────

# Built-in heuristics for evidence parsing (design doc §5.2)
_AUTO_FAIL_INDICATORS = [
    "FAILED", "error:", "Error:", "assert",
    "0 passed", "no tests ran", "command not found",
    "FAIL", "Traceback", "exception", "exit code 1",
    "SyntaxError", "ImportError", "ModuleNotFoundError",
]
_AUTO_PASS_INDICATORS = [
    "passed", "ok", "success", "0 errors",
    "All checks passed", "no issues found",
    "PASSED", "OK", "0 failed",
]


def _parse_evidence_for_verdict(
    evidence_json: str | None,
    auto_pass_pattern: str | None,
    auto_fail_pattern: str | None,
) -> str:
    """Parse verification evidence and return "passed" | "failed" | "undetermined".

    Order: fail indicators first (safety-side), then pass indicators.
    Custom patterns (from O's auto_pass_pattern / auto_fail_pattern) override built-in heuristics.
    """
    if not evidence_json:
        return "undetermined"

    evidence_dict = safe_loads(evidence_json) or {}
    # Extract searchable text from evidence
    # Prefer submitter_note for string evidence, fall back to full dict
    search_text = ""
    if isinstance(evidence_dict.get("submitter_note"), str):
        search_text = evidence_dict["submitter_note"]
    else:
        # Stringify the whole evidence dict for pattern matching
        search_text = str(evidence_dict)

    if not search_text:
        return "undetermined"

    # 1. Check custom fail pattern first (O-configured, highest priority)
    if auto_fail_pattern:
        import re
        if re.search(auto_fail_pattern, search_text):
            return "failed"

    # 2. Check built-in fail indicators
    for indicator in _AUTO_FAIL_INDICATORS:
        if indicator in search_text:
            # "passed" and "failed" overlap — check both
            if indicator == "FAILED" and "FAILED" in search_text:
                return "failed"
            return "failed"

    # 3. Check custom pass pattern
    if auto_pass_pattern:
        import re
        if re.search(auto_pass_pattern, search_text):
            return "passed"

    # 4. Check built-in pass indicators
    has_pass = False
    for indicator in _AUTO_PASS_INDICATORS:
        if indicator in search_text:
            has_pass = True
            break

    if has_pass:
        return "passed"

    # Neither clear → safety: leave for O
    return "undetermined"


async def _try_auto_verify(
    db: AsyncSession,
    task: "Task",
    team_id: str,
) -> str | None:
    """Attempt auto-verification for a task. Called from submit_task.

    Only updates Verification records (status, verified_by, verified_at) and
    records verification.executed events. Does NOT transition the task —
    the caller (submit_task) handles task-level state transitions.

    Preconditions (all must be true, else return None):
      1. ALL verifications have _auto_verifiable == True in criteria
      2. ALL verifications have non-empty evidence

    Returns:
      "all_passed" — all verifications auto-passed, caller should complete task
      "any_failed" — some verifications auto-failed, caller should reject task
      None — undetermined / not all auto_verifiable, leave for O
    """
    # Read all verifications for this task
    all_vers_result = await db.execute(
        select(Verification).where(Verification.task_id == task.id)
    )
    all_vers = all_vers_result.scalars().all()

    if not all_vers:
        return None  # No verifications — shouldn't happen, but safe

    # Precondition: ALL verifications must be auto_verifiable
    auto_vers = []
    for ver in all_vers:
        criteria = safe_loads(ver.criteria) or {}
        if not criteria.get("_auto_verifiable"):
            return None  # At least one verification is not auto-verifiable
        auto_vers.append(ver)

    # Precondition: ALL verifications must have evidence
    for ver in auto_vers:
        if not ver.evidence:
            return None  # Evidence missing — can't auto-verify

    # Parse evidence for each verification
    verdicts: list[tuple[Verification, str]] = []  # (ver, "passed"|"failed"|"undetermined")
    for ver in auto_vers:
        criteria = safe_loads(ver.criteria) or {}
        auto_pass = criteria.get("_auto_pass_pattern")
        auto_fail = criteria.get("_auto_fail_pattern")
        verdict = _parse_evidence_for_verdict(ver.evidence, auto_pass, auto_fail)
        verdicts.append((ver, verdict))

    # If any verification is undetermined → skip auto-verify entirely
    if any(v == "undetermined" for _, v in verdicts):
        logger.info(
            "auto_verify_skipped_undetermined",
            task_id=task.id,
            verdicts=[{"ver_id": v.id, "verdict": vd} for v, vd in verdicts],
        )
        return None

    # Apply verdicts to verifications
    now = datetime.now(timezone.utc)
    for ver, verdict in verdicts:
        ver.status = verdict
        ver.verified_by = "auto_verify"
        ver.verified_at = now

        await event_store.record(
            db,
            event_type="verification.executed",
            team_id=team_id,
            actor_type="SYSTEM",
            actor_id="auto_verify",
            target_type="verification",
            target_id=ver.id,
            payload={
                "task_id": task.id,
                "verification_status": verdict,
                "verified_by": "auto_verify",
                "auto_verified": True,
            },
        )

    # Return overall verdict — caller handles task transition
    all_passed = all(v == "passed" for _, v in verdicts)
    outcome = "all_passed" if all_passed else "any_failed"

    logger.info(
        "auto_verify_executed" if all_passed else "auto_verify_failed",
        task_id=task.id,
        outcome=outcome,
        verification_count=len(verdicts),
        failed=[ver.id for ver, v in verdicts if v == "failed"],
    )
    return outcome


# ── 验证操作 ───────────────────────────────────────

async def execute_verification(
    db: AsyncSession,
    verification_id: str,
    *,
    status: str,  # "passed" | "failed"
    comment: str | None,
    evidence: dict | None,
    rejection_reason: str | None,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
    review_flag: bool = False,
    auto_approved: bool = False,
) -> tuple[Verification, Task]:
    """执行单条验证检查并相应更新父任务状态。

    使用乐观锁：expected_version 必须匹配当前 task.version_no。
    通过状态机 (apply_transition) 转换任务：
      - 全部通过 → COMPLETED
      - 任一失败 → REJECTED（redo_count += 1）

    P8-B6: review_flag 标记边界案例供人工复核。
    auto_approved 标记 Claude初审 自动决策（人工仍需签批）。
    """
    from src.services.task_service import _check_version, _bump_version

    ver = await db.get(Verification, verification_id)
    if ver is None:
        raise NotFoundError("verification", verification_id)

    # 验证必须处于 pending 状态
    if ver.status != VerificationStatus.PENDING:
        raise ConflictError(
            "VERIFICATION_ALREADY_EXECUTED",
            f"Verification {verification_id} has already been executed (status: {ver.status})",
            {"verificationId": verification_id, "currentStatus": ver.status},
        )

    # 校验父任务存在且处于 in_verification 状态
    task = await db.get(Task, ver.task_id)
    if task is None:
        raise NotFoundError("task", ver.task_id)
    _check_version(task, expected_version)
    # PFL-046: 检查是否有 pending 授权请求
    auth_result = await db.execute(
        select(AuthorizationRequest).where(
            AuthorizationRequest.worker_id == actor_id,
            AuthorizationRequest.target_resource_type == "task",
            AuthorizationRequest.target_resource_id == task.id,
            AuthorizationRequest.status == "pending",
        )
    )
    pending_auths = auth_result.scalars().all()
    if pending_auths:
        request_ids = [r.id for r in pending_auths]
        raise ConflictError(
            "PENDING_AUTHORIZATION",
            f"Worker {actor_id} has {len(pending_auths)} pending authorization "
            f"request(s) for Task {task.id}: {request_ids}. "
            f"Wait for approval before retrying this operation.",
            {"pendingRequestIds": request_ids, "taskId": task.id, "workerId": actor_id},
        )
    if task.status != TaskStatus.IN_VERIFICATION:
        raise InvalidStateTransition(
            "verification_execute",
            verification_id,
            f"task_status:{task.status}",
            "requires task in in_verification",
        )

    # P11-B72: 手动验证禁止自验 — verifier 不能是 task owner（职责分离）
    if ver.type == VerificationType.MANUAL:
        if actor_id == task.owner_id:
            raise ConflictError(
                "SELF_VERIFICATION_NOT_ALLOWED",
                f"Manual verification requires a different person than the task owner. "
                f"The person who executed the work (owner: {task.owner_id}) "
                f"cannot verify their own task. "
                f"Ask an orchestrator or admin to execute this verification.",
                {"taskId": task.id, "ownerId": task.owner_id, "verifierId": actor_id},
            )

    # P11-B76: 幂等 guard — 同一 verifier 对同一 verification 在窗口内不可重复执行
    await _check_verify_idempotent(
        db, verification_id=verification_id, actor_id=actor_id, task_id=task.id,
    )

    # 更新验证记录
    now = datetime.now(timezone.utc)

    if review_flag:
        # 已标记：保持状态为 "pending"，将 Claude 的建议存入 evidence。
        # 人工稍后通过单条验证来解决。
        existing_evidence = safe_loads(ver.evidence) or {}
        existing_evidence["claude_recommendation"] = status
        if comment:
            existing_evidence["claude_comment"] = comment
        ver.evidence = safe_dumps(existing_evidence)
        ver.review_flag = True
        ver.auto_approved = auto_approved
        ver.verified_by = actor_id
        ver.verified_at = now
    else:
        ver.status = status
        ver.verified_by = actor_id
        ver.verified_at = now
        ver.review_flag = False
        ver.auto_approved = auto_approved
        if comment:
            existing_evidence = safe_loads(ver.evidence) or {}
            existing_evidence["comment"] = comment
            ver.evidence = safe_dumps(existing_evidence)
        if evidence:
            existing_evidence = safe_loads(ver.evidence) or {}
            existing_evidence.update(evidence)
            ver.evidence = safe_dumps(existing_evidence)
        if rejection_reason:
            ver.rejection_reason = rejection_reason

    # 记录验证事件
    await event_store.record(
        db,
        event_type="verification.executed",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="verification",
        target_id=verification_id,
        payload={
            "task_id": ver.task_id,
            "verification_status": status if not review_flag else "flagged",
            "verified_by": actor_id,
            "rejection_reason": rejection_reason,
            "review_flag": review_flag,
            "auto_approved": auto_approved,
        },
    )

    # 若设置了 review_flag，不改变任务状态 — 等待人工处理
    if review_flag:
        return ver, task

    # 检查此任务的所有验证
    all_vers = await db.execute(
        select(Verification).where(Verification.task_id == ver.task_id)
    )
    all_vers_list = all_vers.scalars().all()

    all_processed = all(v.status != VerificationStatus.PENDING for v in all_vers_list)
    if not all_processed:
        return ver, task  # 仍有待处理的验证

    all_passed = all(v.status == VerificationStatus.PASSED for v in all_vers_list)

    if all_passed:
        # 使用状态机：IN_VERIFICATION → COMPLETED
        event_type, payload = apply_transition(
            task, TaskStatus.COMPLETED,
            actor_type=actor_type, actor_id=actor_id,
            context={
                "verification_count": len(all_vers_list),
                "all_verifications_passed": True,
                "auto_approved": auto_approved,
            },
        )
        task.completed_at = now

        # P8-B9: 任务到达终态后检查批次完成状态
        from src.services.batch_service import check_batch_completion
        await check_batch_completion(db, task, team_id, actor_type, actor_id)
        # P12-B33 G5: unblock downstream tasks that depend on this completed task
        await _unblock_downstream_tasks(db, task, team_id)
    else:
        # 使用状态机：IN_VERIFICATION → REJECTED
        event_type, payload = apply_transition(
            task, TaskStatus.REJECTED,
            actor_type=actor_type, actor_id=actor_id,
            context={
                "verification_count": len(all_vers_list),
                "all_verifications_passed": False,
            },
        )
        task.redo_count += 1

    _bump_version(task)

    await event_store.record(
        db,
        event_type=event_type,
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="task",
        target_id=task.id,
        payload=payload,
    )

    # P11-B21 PFL-041: WS push — notify owner and creator of completion/rejection
    verify_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
            "verification_count": len(all_vers_list),
            "all_passed": all_passed,
        },
    }
    if task.owner_id:
        await ws_manager.broadcast_to_actor(task.owner_id, verify_event)
    if task.create_user_id and task.create_user_id != task.owner_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, verify_event)

    return ver, task


# ── P8-B6: 批量验证 ─────────────────────────────────────

async def execute_batch_verification(
    db: AsyncSession,
    *,
    items: list[dict],
    auto_approved: bool,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> dict:
    """单批次执行多条验证。

    每项：{verification_id, status, comment?, rejection_reason?,
           review_flag?, expected_version}

    处理所有项后，检查每个受影响的父任务的完成状态。
    返回逐项结果和逐任务结果。

    原子性：所有项在同一事务内处理。逐项错误（未找到、已执行、
    任务状态错误）被捕获并返回 — 不会中止批次。
    """
    from src.services.task_service import _check_version, _bump_version

    now = datetime.now(timezone.utc)
    item_results: list[dict] = []
    affected_task_ids: set[str] = set()

    for item in items:
        verification_id = item["verification_id"]
        status = item["status"]
        review_flag = item.get("review_flag", False)

        ver = await db.get(Verification, verification_id)
        if ver is None:
            item_results.append({
                "verification_id": verification_id,
                "task_id": "",
                "status": "error",
                "error": f"Verification {verification_id} not found",
            })
            continue

        task_id = ver.task_id
        affected_task_ids.add(task_id)

        # 检查前置条件
        if ver.status != VerificationStatus.PENDING:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": f"Already executed (status: {ver.status})",
            })
            continue

        task = await db.get(Task, task_id)
        if task is None:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": f"Parent task {task_id} not found",
            })
            continue

        expected_version = item["expected_version"]
        try:
            _check_version(task, expected_version)
        except ConflictError as e:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": str(e.message),
            })
            continue

        if task.status != TaskStatus.IN_VERIFICATION:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": f"Task not in_verification (status: {task.status})",
            })
            continue

        # P11-B72: 手动验证禁止自验
        if ver.type == VerificationType.MANUAL and actor_id == task.owner_id:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": (
                    f"SELF_VERIFICATION_NOT_ALLOWED: "
                    f"Manual verification requires a different person than the task owner. "
                    f"The person who executed the work (owner: {task.owner_id}) "
                    f"cannot verify their own task."
                ),
            })
            continue

        # P11-B76: 幂等 guard — 同一 verifier 对同一 verification 在窗口内不可重复执行
        try:
            await _check_verify_idempotent(
                db, verification_id=verification_id, actor_id=actor_id, task_id=task_id,
            )
        except ConflictError as e:
            item_results.append({
                "verification_id": verification_id,
                "task_id": task_id,
                "status": "error",
                "error": str(e.message),
            })
            continue

        # 执行验证
        rejection_reason = item.get("rejection_reason")
        comment = item.get("comment")
        if review_flag:
            # 已标记：保持状态为 "pending"，将 Claude 的建议存入 evidence
            existing = safe_loads(ver.evidence) or {}
            existing["claude_recommendation"] = status
            if comment:
                existing["claude_comment"] = comment
            ver.evidence = safe_dumps(existing)
            ver.review_flag = True
            ver.auto_approved = auto_approved
            ver.verified_by = actor_id
            ver.verified_at = now
        else:
            ver.status = status
            ver.verified_by = actor_id
            ver.verified_at = now
            ver.review_flag = False
            ver.auto_approved = auto_approved
            if rejection_reason:
                ver.rejection_reason = rejection_reason
            if comment:
                existing = safe_loads(ver.evidence) or {}
                existing["comment"] = comment
                ver.evidence = safe_dumps(existing)

        # 记录事件
        await event_store.record(
            db,
            event_type="verification.executed",
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="verification",
            target_id=verification_id,
            payload={
                "task_id": task_id,
                "verification_status": status if not review_flag else "flagged",
                "verified_by": actor_id,
                "rejection_reason": rejection_reason if not review_flag else None,
                "review_flag": review_flag,
                "auto_approved": auto_approved,
                "batch": True,
            },
        )

        item_results.append({
            "verification_id": verification_id,
            "task_id": task_id,
            "status": "flagged" if review_flag else status,
            "error": None,
        })

    # 第二阶段：检查每个受影响任务的完成状态
    # 跳过仅有 review_flagged 验证的任务 — 这些保持 IN_VERIFICATION
    # 跳过已处于终态的任务（COMPLETED、REJECTED、CANCELLED）
    TERMINAL_STATES = {TaskStatus.COMPLETED, TaskStatus.REJECTED, TaskStatus.CANCELLED}
    task_outcomes: list[dict] = []
    for task_id in affected_task_ids:
        task = await db.get(Task, task_id)
        if task is None:
            continue

        # 若任务已处于终态则跳过
        if task.status in TERMINAL_STATES:
            task_outcomes.append({
                "task_id": task_id,
                "task_status": task.status,
                "redo_count": task.redo_count,
            })
            continue

        all_vers = await db.execute(
            select(Verification).where(Verification.task_id == task_id)
        )
        all_vers_list = all_vers.scalars().all()

        # 检查是否有验证被标记 — 若有则跳过任务转换
        has_flagged = any(v.review_flag for v in all_vers_list)
        all_processed = all(v.status != VerificationStatus.PENDING for v in all_vers_list)

        if not all_processed:
            task_outcomes.append({
                "task_id": task_id,
                "task_status": task.status,  # 保持 in_verification
                "redo_count": task.redo_count,
            })
            continue

        if has_flagged:
            # 标记项需要人工复核 — 任务保持 IN_VERIFICATION
            task_outcomes.append({
                "task_id": task_id,
                "task_status": "in_verification",
                "redo_count": task.redo_count,
            })
            continue

        all_passed = all(v.status == VerificationStatus.PASSED for v in all_vers_list)

        if all_passed:
            event_type, payload = apply_transition(
                task, TaskStatus.COMPLETED,
                actor_type=actor_type, actor_id=actor_id,
                context={
                    "verification_count": len(all_vers_list),
                    "all_verifications_passed": True,
                    "auto_approved": auto_approved,
                    "batch": True,
                },
            )
            task.completed_at = now

            # P8-B9: 任务到达终态后检查批次完成状态
            from src.services.batch_service import check_batch_completion
            await check_batch_completion(db, task, team_id, actor_type, actor_id)
            # P12-B33 G5: unblock downstream tasks that depend on this completed task
            await _unblock_downstream_tasks(db, task, team_id)
        else:
            event_type, payload = apply_transition(
                task, TaskStatus.REJECTED,
                actor_type=actor_type, actor_id=actor_id,
                context={
                    "verification_count": len(all_vers_list),
                    "all_verifications_passed": False,
                    "batch": True,
                },
            )
            task.redo_count += 1

        _bump_version(task)

        await event_store.record(
            db,
            event_type=event_type,
            team_id=team_id,
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="task",
            target_id=task.id,
            payload=payload,
        )

        task_outcomes.append({
            "task_id": task_id,
            "task_status": task.status,
            "redo_count": task.redo_count,
        })

    # 构建摘要
    passed = sum(1 for r in item_results if r["status"] == VerificationStatus.PASSED)
    failed = sum(1 for r in item_results if r["status"] == VerificationStatus.FAILED)
    errors = sum(1 for r in item_results if r["status"] == "error")
    flagged = sum(1 for r in item_results if r["status"] != "error"
                  and any(it.get("review_flag") for it in items
                          if it["verification_id"] == r["verification_id"]))

    return {
        "results": item_results,
        "task_outcomes": task_outcomes,
        "summary": {
            "passed": passed,
            "failed": failed,
            "error": errors,
            "flagged": flagged,
        },
    }


async def create_verification(
    db: AsyncSession,
    *,
    task_id: str,
    type: str = "manual",
    description: str,
    criteria: dict | None = None,
    actor_type: str,
    actor_id: str,
    team_id: str,
    auto_created: bool = False,
) -> Verification:
    """创建新的 Verification 记录（PFL-106 · B106）。

    校验父 Task 存在且尚未进入终态（COMPLETED/CANCELLED）。
    """
    from src.utils.id_gen import generate_id

    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("task", task_id)
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise ConflictError(
            "TASK_IN_TERMINAL_STATE",
            f"Cannot add verification to task in terminal state: {task.status}",
        )

    ver = Verification(
        id=generate_id("verification"),
        task_id=task_id,
        type=type,
        description=description,
        criteria=safe_dumps(criteria) if criteria else None,
        status=VerificationStatus.PENDING,
    )
    db.add(ver)

    await event_store.record(
        db,
        event_type="verification.created",
        team_id=team_id,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type="verification",
        target_id=ver.id,
        payload={
            "task_id": task_id,
            "type": type,
            "auto_created": auto_created,
        },
    )

    return ver


async def get_task_verifications(
    db: AsyncSession,
    task_id: str,
) -> list[Verification]:
    """获取任务的所有验证记录。"""
    # 校验任务存在
    task = await db.get(Task, task_id)
    if task is None:
        raise NotFoundError("task", task_id)

    result = await db.execute(
        select(Verification).where(Verification.task_id == task_id)
    )
    return list(result.scalars().all())


def verification_to_response(ver: Verification) -> dict:
    """将 Verification ORM 对象转换为响应字典，含 JSON 反序列化。"""
    return {
        "id": ver.id,
        "task_id": ver.task_id,
        "type": ver.type,
        "description": ver.description,
        "criteria": safe_loads(ver.criteria),
        "status": ver.status,
        "verified_by": ver.verified_by,
        "verified_at": ver.verified_at,
        "evidence": safe_loads(ver.evidence),
        "rejection_reason": ver.rejection_reason,
        "review_flag": ver.review_flag,
        "auto_approved": ver.auto_approved,
        "is_disabled": ver.is_disabled,
        "create_user_id": ver.create_user_id,
        "last_update_user_id": ver.last_update_user_id,
        "remark": ver.remark,
        "version_no": ver.version_no,
        "created_at": ver.created_at,
        "updated_at": ver.updated_at,
    }


# ── P12-B33 G5: downstream task unblocking ─────────────────

_NON_TERMINAL_STATES = {
    TaskStatus.BACKLOG,
    TaskStatus.READY,
    TaskStatus.IN_PROGRESS,
    TaskStatus.PAUSED,
    TaskStatus.IN_VERIFICATION,
    TaskStatus.REJECTED,
}


async def _unblock_downstream_tasks(
    db: AsyncSession,
    completed_task: Task,
    team_id: str,
) -> list[Task]:
    """Find and notify tasks that depend on ``completed_task``.

    When a task reaches COMPLETED status, check all non-terminal tasks
    in the same project. For each task whose ``depends_on`` includes
    ``completed_task.id``, verify ALL dependencies are now satisfied.
    If so, broadcast a ``task.dependencies_met`` WS event so Workers
    know the task is ready to claim.

    Returns the list of unblocked tasks.

    P12-B33 G5: This closes the last major gap in the depends_on chain.
    Without this, downstream Workers must blind-poll on 409
    TASK_DEPENDENCY_NOT_READY until the upstream completes.
    """
    from sqlalchemy import or_

    unblocked: list[Task] = []

    # Find candidates: same project, has depends_on, non-terminal
    candidates = await db.execute(
        select(Task).where(
            Task.project_id == completed_task.project_id,
            Task.depends_on.isnot(None),
            Task.depends_on != "[]",
            Task.depends_on != "null",
            Task.status.in_(_NON_TERMINAL_STATES),
        )
    )
    candidates_list = candidates.scalars().all()

    if not candidates_list:
        return unblocked

    completed_id = completed_task.id

    for downstream in candidates_list:
        deps = safe_loads(downstream.depends_on)
        if not deps:
            continue

        dep_ids = {d["task_id"] for d in deps}
        if completed_id not in dep_ids:
            continue

        # Check if ALL dependencies are now completed
        all_met = True
        for dep_id in dep_ids:
            dep_task = await db.get(Task, dep_id)
            if dep_task is None:
                logger.warning(
                    "deps_unblock_dangling_ref",
                    downstream_id=downstream.id,
                    missing_dep_id=dep_id,
                )
                continue
            if dep_task.status != TaskStatus.COMPLETED:
                all_met = False
                break

        if not all_met:
            continue

        unblocked.append(downstream)

        # Record event
        await event_store.record(
            db,
            event_type="task.dependencies_met",
            team_id=team_id,
            actor_type="system",
            actor_id="synapse",
            target_type="task",
            target_id=downstream.id,
            payload={
                "unblocked_by": completed_id,
                "dependency_count": len(dep_ids),
            },
        )

        # WS push — notify team that this task is now ready to claim
        unblock_event = {
            "type": "event",
            "data": {
                "event_type": "task.dependencies_met",
                "task_id": downstream.id,
                "unblocked_by": completed_id,
                "status": downstream.status,
            },
        }
        # Broadcast to team (so all Workers see it) and to task creator
        await ws_manager.broadcast_to_team(team_id, unblock_event)

    if unblocked:
        logger.info(
            "deps_unblocked",
            completed_task_id=completed_id,
            unblocked_count=len(unblocked),
            unblocked_ids=[t.id for t in unblocked],
        )

    return unblocked

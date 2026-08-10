"""Task 执行服务 — submit/pause/resume/terminate 状态转换。

涵盖 in_progress→in_verification→completed 执行管线，
以及 pause/resume 生命周期控制和 terminate 强制终态。
调用方持有事务 — 本服务不提交。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants import ActorType, OwnerType, TaskStatus, VerificationStatus
from src.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from src.models.task import Task
from src.models.verification import Verification
from src.services.event_store import event_store
from src.services.task_core import (
    _bump_version,
    _check_no_pending_auth,
    _check_version,
    _validate_transition,
    get_task,
)
from src.services.verification_service import _try_auto_verify, _unblock_downstream_tasks
from src.services.ws_manager import ws_manager
from src.task_state_machine import apply_transition
from src.utils.id_gen import derive_id
from src.utils.json_utils import safe_dumps


async def submit_task(
    db: AsyncSession,
    task_id: str,
    *,
    summary: str,
    evidence: dict | None,
    verification_results: list[dict],
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """提交任务进行验证。提交者必须是任务 owner。

    P8-B4: 使用状态机的 ``apply_transition``，与其他 B1 转换保持一致。
    当提交者是 Worker 时，清除 Worker 的 active_task_id 并将运行时状态转为 IDLE。
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)
    ok = task.owner_type == actor_type and task.owner_id == actor_id  # P10-B7
    if not ok and task.owner_type == OwnerType.MEMBER and actor_type == ActorType.HUMAN:
        ok = derive_id(task.owner_id, "worker") == actor_id
    if not ok:
        raise ForbiddenError(
            "NOT_TASK_OWNER",
            f"Only the task owner ({task.owner_type}:{task.owner_id}) can submit",
            {"ownerType": task.owner_type, "ownerId": task.owner_id},
        )

    # P11-B70: evidence 必须包含 output_access — 客户如何获取产出
    if not evidence or "output_access" not in evidence:
        raise ConflictError(
            "OUTPUT_ACCESS_REQUIRED",
            "Evidence must include 'output_access' field specifying how to access "
            "the completed output. output_access must have: "
            'type (git_branch|file_url|web_link|inline) and value.\n'
            'Example: {"output_access": {"type": "git_branch", "value": "https://github.com/x/y@feature/z"}}',
        )
    oa = evidence["output_access"]
    if not isinstance(oa, dict):
        raise ConflictError(
            "OUTPUT_ACCESS_INVALID",
            "output_access must be an object with 'type' and 'value' fields.",
        )
    valid_oa_types = {"git_branch", "file_url", "web_link", "inline"}
    oa_type = oa.get("type", "")
    if oa_type not in valid_oa_types:
        raise ConflictError(
            "OUTPUT_ACCESS_INVALID_TYPE",
            f"output_access.type must be one of: {', '.join(sorted(valid_oa_types))}. "
            f"Got: '{oa_type}'",
        )
    if not oa.get("value") or not isinstance(oa.get("value"), str):
        raise ConflictError(
            "OUTPUT_ACCESS_INVALID",
            "output_access.value is required and must be a non-empty string.",
        )

    # P12-B18: 先拉取该 Task 的全部 Verification，确保 rework 时全量 reset，
    # 不依赖 Worker 在 verification_results 中列出所有 verification。
    all_task_vers = await db.execute(
        select(Verification).where(Verification.task_id == task_id)
    )
    all_task_vers_list = all_task_vers.scalars().all()
    ver_by_id = {v.id: v for v in all_task_vers_list}

    # 第一阶段：全量 reset — 将该 Task 下所有非 PENDING 的 Verification 重置
    # 确保即使 Worker 的 submit 请求遗漏了某个 verification，reset 仍会触发
    for ver in all_task_vers_list:
        if ver.status != VerificationStatus.PENDING:
            previous_ver_status = ver.status
            ver.status = VerificationStatus.PENDING
            ver.verified_by = None
            ver.verified_at = None
            ver.rejection_reason = None
            await event_store.record(
                db,
                event_type="verification.reset",
                team_id=team_id,
                actor_type=actor_type,
                actor_id=actor_id,
                target_type="verification",
                target_id=ver.id,
                payload={
                    "task_id": task_id,
                    "previous_status": previous_ver_status,
                    "new_status": VerificationStatus.PENDING,
                    "reason": "task_resubmitted",
                },
            )

    # 第二阶段：处理 Worker 提交的 evidence（仅匹配 Worker 传入的 verification）
    for vr in verification_results:
        ver = ver_by_id.get(vr["verification_id"])
        if ver is None:
            raise NotFoundError("verification", vr["verification_id"])
        if ver.task_id != task_id:
            raise ConflictError(
                "VERIFICATION_TASK_MISMATCH",
                f"Verification {vr['verification_id']} does not belong to task {task_id}",
            )
        # Owner 可提交自评证据，但最终状态由验证者设定
        if vr.get("evidence"):
            evidence_val = vr["evidence"]
            if isinstance(evidence_val, str):
                ver.evidence = safe_dumps({"submitter_note": evidence_val})
            else:
                ver.evidence = safe_dumps(evidence_val)

    # 使用状态机进行转换 (P8-B4: 与 B1 模式一致)
    event_type, payload = apply_transition(
        task, TaskStatus.IN_VERIFICATION,
        actor_type=actor_type, actor_id=actor_id,
        context={
            "summary": summary,
            "verification_results_count": len(verification_results),
        },
    )
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

    # P14-B9: 尝试 auto-verify — 在 IN_VERIFICATION 后立即检查是否可以自动判定。
    # 如果所有 verification 都是 auto_verifiable，Server 解析 evidence 并直接
    # 完成/拒绝任务，绕过 O 手动验收。
    auto_outcome = await _try_auto_verify(db, task, team_id)
    if auto_outcome is not None:
        from src.services.batch_service import check_batch_completion

        if auto_outcome == "all_passed":
            final_event_type, final_payload = apply_transition(
                task, TaskStatus.COMPLETED,
                actor_type="SYSTEM", actor_id="auto_verify",
                context={
                    "summary": summary,
                    "verification_count": len(all_task_vers_list),
                    "all_verifications_passed": True,
                    "auto_verified": True,
                },
            )
            task.completed_at = datetime.now(timezone.utc)
        else:  # any_failed
            final_event_type, final_payload = apply_transition(
                task, TaskStatus.REJECTED,
                actor_type="SYSTEM", actor_id="auto_verify",
                context={
                    "summary": summary,
                    "verification_count": len(all_task_vers_list),
                    "all_verifications_passed": False,
                    "auto_verified": True,
                },
            )
            task.redo_count += 1

        _bump_version(task)

        await event_store.record(
            db,
            event_type=final_event_type,
            team_id=team_id,
            actor_type="SYSTEM",
            actor_id="auto_verify",
            target_type="task",
            target_id=task.id,
            payload=final_payload,
        )

        await check_batch_completion(db, task, team_id, "SYSTEM", "auto_verify")
        await _unblock_downstream_tasks(db, task, team_id)

        # P8-B4: 提交后清除 Worker 的活跃任务
        if actor_type == ActorType.WORKER:
            from src.services.worker_scheduler import finish_current_task
            await finish_current_task(db, actor_id)

        # WS push — notify submitter and creator of auto-verify result
        auto_event = {
            "type": "event",
            "data": {
                "event_type": final_event_type,
                "task_id": task.id,
                "status": task.status,
                "summary": summary,
                "auto_verified": True,
            },
        }
        await ws_manager.broadcast_to_actor(actor_id, auto_event)
        if task.create_user_id and task.create_user_id != actor_id:
            await ws_manager.broadcast_to_actor(task.create_user_id, auto_event)

        return task

    # P8-B4: 提交后清除 Worker 的活跃任务
    if actor_type == ActorType.WORKER:
        from src.services.worker_scheduler import finish_current_task
        await finish_current_task(db, actor_id)

    # P11-B21 PFL-041: WS push — notify submitter and creator
    submit_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
            "summary": summary,
        },
    }
    await ws_manager.broadcast_to_actor(actor_id, submit_event)
    if task.create_user_id and task.create_user_id != actor_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, submit_event)

    return task


async def pause_task(
    db: AsyncSession,
    task_id: str,
    *,
    reason: str,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """暂停进行中的任务。仅任务 owner 或管理员可暂停。

    PAUSED 是独立状态 (D-P7-020)：
    - 暂停的任务不消耗租约
    - 暂停的任务不阻塞 Worker 队列
    - Worker 应在下次心跳时停止计算
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    event_type, payload = apply_transition(
        task, TaskStatus.PAUSED,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"reason": reason},
    )
    task.paused_at = datetime.now(timezone.utc)
    task.paused_by = actor_id
    task.pause_reason = reason
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

    # P11-B21 PFL-041: WS push — notify owner and creator
    pause_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
            "reason": reason,
        },
    }
    if task.owner_id:
        await ws_manager.broadcast_to_actor(task.owner_id, pause_event)
    if task.create_user_id and task.create_user_id != task.owner_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, pause_event)

    return task


async def resume_task(
    db: AsyncSession,
    task_id: str,
    *,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """将暂停的任务恢复为 IN_PROGRESS。"""
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    event_type, payload = apply_transition(
        task, TaskStatus.IN_PROGRESS,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"resumed_from": TaskStatus.PAUSED},
    )
    task.paused_at = None
    task.paused_by = None
    task.pause_reason = None
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

    # P11-B21 PFL-041: WS push — notify owner and creator
    resume_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
        },
    }
    if task.owner_id:
        await ws_manager.broadcast_to_actor(task.owner_id, resume_event)
    if task.create_user_id and task.create_user_id != task.owner_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, resume_event)

    return task


async def terminate_task(
    db: AsyncSession,
    task_id: str,
    *,
    reason: str,
    expected_version: int,
    actor_type: str,
    actor_id: str,
    team_id: str,
) -> Task:
    """永久终止任务 → CANCELLED（终态）。

    与 pause/resume 不同，CANCELLED 是永久的 — 任务永远不会完成。
    可从以下状态转入：READY、IN_PROGRESS、PAUSED（任意终态前状态）。

    若任务有活跃 Worker，Worker 的 active_task_id 将在下次心跳时释放
    （心跳检测到 status != IN_PROGRESS）。
    """
    task = await get_task(db, task_id)
    _check_version(task, expected_version)
    await _check_no_pending_auth(db, task_id=task_id, actor_id=actor_id)

    previous_owner_id = task.owner_id

    event_type, payload = apply_transition(
        task, TaskStatus.CANCELLED,
        actor_type=actor_type,
        actor_id=actor_id,
        context={"reason": reason, "previous_owner_id": previous_owner_id},
    )
    # 释放所有权，使任务不可被重新认领
    task.owner_type = None
    task.owner_id = None
    task.paused_at = None
    task.paused_by = None
    task.pause_reason = None
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

    # P8-B9: 终态转换后检查批次完成状态
    from src.services.batch_service import check_batch_completion
    await check_batch_completion(db, task, team_id, actor_type, actor_id)

    # P11-B21 PFL-041: WS push — notify previous owner and creator
    term_event = {
        "type": "event",
        "data": {
            "event_type": event_type,
            "task_id": task.id,
            "status": task.status,
            "reason": reason,
        },
    }
    if previous_owner_id:
        await ws_manager.broadcast_to_actor(previous_owner_id, term_event)
    if task.create_user_id and task.create_user_id != previous_owner_id:
        await ws_manager.broadcast_to_actor(task.create_user_id, term_event)

    return task

"""Task 服务 — 重导出层。

本模块是薄重导出层，实际实现分散在子模块中：
- task_core.py: 共享 helper + 基础 CRUD + 响应序列化
- task_create.py: Task 创建
- task_activation.py: ready/assign/claim/cancel 状态转换
- task_execution.py: submit/pause/resume/terminate 状态转换

调用方持有事务 — 本服务不提交。
保持向后兼容：所有现有 ``from src.services.task_service import X`` 调用无需变更。
"""

from __future__ import annotations

# ── Core helpers + CRUD ──────────────────────────────────
from src.services.task_core import (  # noqa: F401
    _bump_version,
    _check_no_pending_auth,
    _check_version,
    _count_verifications,
    _get_verifications,
    _validate_transition,
    get_task,
    task_to_response,
    update_task,
)

# ── Task creation ───────────────────────────────────────
from src.services.task_create import create_task  # noqa: F401

# ── Activation: ready → assign/claim → in_progress ─────
from src.services.task_activation import (  # noqa: F401
    LEASE_DURATION_SECONDS,
    assign_task,
    cancel_task,
    claim_task,
    ready_task,
)

# ── Execution: submit + lifecycle control ──────────────
from src.services.task_execution import (  # noqa: F401
    pause_task,
    resume_task,
    submit_task,
    terminate_task,
)

# ── P8-B3/P8-B4: 批量协作函数重导出 ─────────────────────
from src.services.cooperation import assign_batch, claim_batch  # noqa: E402, F401
import src.services.cooperation as _coop  # noqa: E402

# 注入私有辅助函数，使 cooperation.py 可使用 _check_version / _bump_version
_coop._inject_deps(_check_version, _bump_version)

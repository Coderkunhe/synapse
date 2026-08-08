"""P13-B6: 多 Worker 集成测试 Harness 工具库。

三层架构：
- providers.py   — Provider config 工厂函数（dict 级 mock，无 DB 依赖）
- time_travel.py — 时间操纵 API（直接 ORM 字段操作，无 freezegun）
- fixtures.py    — Provider-aware Worker fixtures（注册+握手+心跳+角色）
- assertions.py  — 专用断言（时序窗口 / 并发结果 / Provider 差异）

设计决策见 docs/plans/p13-b5-integration-test-harness.md §九。
"""

from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)
from tests.harness.time_travel import TimeTravel
from tests.harness.assertions import (
    assert_task_released,
    assert_task_still_owned,
    assert_within_window,
    assert_worker_offline,
    assert_worker_still_active,
    concurrent_claim,
)

__all__ = [
    # providers
    "claude_code_provider_config",
    "codex_cli_provider_config",
    "custom_provider_config",
    # time_travel
    "TimeTravel",
    # assertions
    "assert_within_window",
    "assert_worker_offline",
    "assert_worker_still_active",
    "assert_task_released",
    "assert_task_still_owned",
    "concurrent_claim",
]

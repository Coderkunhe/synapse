"""P8-B2：Worker 运行时状态机 — 单元测试（无数据库）。

覆盖：
- 所有合法转换（3 种状态 × N 条边）
- 所有非法转换尝试
- 事件类型映射
"""

from __future__ import annotations

import pytest

from src.worker_state_machine import (
    ALLOWED_TRANSITIONS,
    get_event_type,
    validate_transition,
)
from src.constants import WorkerRuntimeStatus
from src.exceptions import InvalidStateTransition


# ═══════════════════════════════════════════════════════════════════
# 单元测试：状态机模块（无数据库）
# ═══════════════════════════════════════════════════════════════════


class TestTransitionWhitelist:
    """验证转换表覆盖全部 3 种运行时状态。"""

    ALL_STATES = frozenset(WorkerRuntimeStatus)

    def test_all_statuses_have_transition_entries(self):
        """每个 WorkerRuntimeStatus 必须在 ALLOWED_TRANSITIONS 中有条目。"""
        for status in self.ALL_STATES:
            assert status in ALLOWED_TRANSITIONS, f"缺少 {status} 的转换条目"

    def test_idle_transitions(self):
        """IDLE → BUSY、ERROR、OFFLINE（P11-B128 新增 OFFLINE）。"""
        targets = ALLOWED_TRANSITIONS[WorkerRuntimeStatus.IDLE]
        assert targets == frozenset({WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE})

    def test_busy_transitions(self):
        """BUSY → IDLE、ERROR、OFFLINE（P11-B128 新增 OFFLINE）。"""
        targets = ALLOWED_TRANSITIONS[WorkerRuntimeStatus.BUSY]
        assert targets == frozenset({WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.OFFLINE})

    def test_error_transitions(self):
        """ERROR → IDLE、OFFLINE（P11-B128 新增 OFFLINE）。"""
        targets = ALLOWED_TRANSITIONS[WorkerRuntimeStatus.ERROR]
        assert targets == frozenset({WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.OFFLINE})

    def test_offline_transitions(self):
        """OFFLINE → IDLE（恢复心跳/握手后重回 IDLE）。"""
        targets = ALLOWED_TRANSITIONS[WorkerRuntimeStatus.OFFLINE]
        assert targets == frozenset({WorkerRuntimeStatus.IDLE})

    def test_error_cannot_go_to_busy(self):
        """ERROR → BUSY 非法（必须先恢复到 IDLE）。"""
        assert WorkerRuntimeStatus.BUSY not in ALLOWED_TRANSITIONS[WorkerRuntimeStatus.ERROR]

    def test_all_states_have_outgoing_except_none(self):
        """每个状态至少有 1 条出边（无终态）。"""
        for status in self.ALL_STATES:
            assert len(ALLOWED_TRANSITIONS[status]) > 0, (
                f"{status} 应有出边"
            )


class TestValidateTransition:
    """validate_transition() 对非法转换抛异常，对合法转换通过。"""

    def test_all_valid_transitions_pass(self):
        """白名单中的每条转换都必须无错误地通过验证。"""
        for from_status, targets in ALLOWED_TRANSITIONS.items():
            for to_status in targets:
                validate_transition(from_status, to_status)

    def test_idle_to_busy_valid(self):
        validate_transition(WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.BUSY)

    def test_idle_to_error_valid(self):
        validate_transition(WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.ERROR)

    def test_busy_to_idle_valid(self):
        validate_transition(WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.IDLE)

    def test_busy_to_error_valid(self):
        validate_transition(WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.ERROR)

    def test_error_to_idle_valid(self):
        validate_transition(WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.IDLE)

    def test_error_to_busy_invalid(self):
        """ERROR → BUSY 非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.BUSY)

    def test_error_to_error_invalid(self):
        """ERROR → ERROR（自循环）非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.ERROR)

    def test_idle_to_idle_invalid(self):
        """IDLE → IDLE（自循环）非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.IDLE)

    def test_busy_to_busy_invalid(self):
        """BUSY → BUSY（自循环）非法。"""
        with pytest.raises(InvalidStateTransition):
            validate_transition(WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.BUSY)


class TestEventTypeMapping:
    """get_event_type() 为每条转换返回正确的事件类型。"""

    def test_idle_to_busy(self):
        assert get_event_type(WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.BUSY) == "worker.runtime.busy"

    def test_idle_to_error(self):
        assert get_event_type(WorkerRuntimeStatus.IDLE, WorkerRuntimeStatus.ERROR) == "worker.runtime.error"

    def test_busy_to_idle(self):
        assert get_event_type(WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.IDLE) == "worker.runtime.idle"

    def test_busy_to_error(self):
        assert get_event_type(WorkerRuntimeStatus.BUSY, WorkerRuntimeStatus.ERROR) == "worker.runtime.error"

    def test_error_to_idle(self):
        assert get_event_type(WorkerRuntimeStatus.ERROR, WorkerRuntimeStatus.IDLE) == "worker.runtime.idle"

    def test_unmapped_transition_raises(self):
        """未映射的 (from, to) 对抛出 KeyError。"""
        with pytest.raises(KeyError):
            get_event_type("unknown", "idle")

"""Provider 配置注册中心 — 五维契约的单点真相来源 (P13-B9 · B4 设计原则 #3)。

B4 设计原则 #3：Server 侧消费者不分支 — stale_task_detector/failure_detector
通过 Provider 配置获取参数，不硬编码客户端名。

本模块提供 ``get_provider_config()`` 和维度级便捷查询函数，替代 ``failure_detector.py``
和 ``stale_task_detector.py`` 中的 ``if worker.provider == "codex"`` 硬编码分支。

Provider 配置定义五维契约（B4 §2）：
- heartbeat: 心跳方法 + 间隔 + 超时
- offline:   离线判定超时 + 恢复策略
- evidence:  证据格式 + 大小限制
- state:     状态主数据源
- startup:   启动触发器
"""

from __future__ import annotations

from typing import Any

# ── Provider 配置注册表 ────────────────────────────────────────────
# key = Worker.provider 字段值（与 Worker 模型 provider 列对齐）

_PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "claude": {
        "type": "claude_code",
        "version": "1.0.0",
        "heartbeat": {
            "method": "daemon",
            "interval_seconds": 55,
            "max_skew_seconds": 10,
            "timeout_seconds": 300,  # 5 min — daemon-based persistent connection
        },
        "offline": {
            "timeout_seconds": 300,
            "recovery": "daemon_auto_restart",
        },
        "evidence": {
            "format": "structured",
            "max_size_bytes": 65536,
            "supports_files": True,
            "supports_diff": True,
            "supports_screenshot": True,
        },
        "state": {
            "primary_source": "file",
            "refresh_on_startup": True,
            "cache_ttl_seconds": 60,
        },
        "startup": {
            "trigger": "hook",
            "health_check": True,
        },
    },
    "codex": {
        "type": "codex_cli",
        "version": "0.146.0",
        "heartbeat": {
            "method": "cron",
            "interval_seconds": 60,
            "max_skew_seconds": 30,
            "timeout_seconds": 1800,  # 30 min — CronCreate-based, no daemon
        },
        "offline": {
            "timeout_seconds": 1800,
            "recovery": "cron_window",
        },
        "evidence": {
            "format": "free_text",
            "max_size_bytes": 65536,
            "supports_files": False,
            "supports_diff": False,
            "supports_screenshot": False,
        },
        "state": {
            "primary_source": "api",
            "refresh_on_startup": False,
            "cache_ttl_seconds": 0,
        },
        "startup": {
            "trigger": "prompt",
            "health_check": False,
        },
    },
}

# 默认 provider 类型（Worker.provider 的默认值）
_DEFAULT_PROVIDER = "claude"


def get_provider_config(provider_type: str | None) -> dict[str, Any]:
    """获取指定 provider 的完整五维配置。

    Args:
        provider_type: Worker.provider 字段值（"claude" / "codex"），None 时使用默认值。

    Returns:
        五维配置 dict。未知 provider 类型降级为 claude 默认配置。

    >>> cfg = get_provider_config("codex")
    >>> cfg["heartbeat"]["timeout_seconds"]
    1800
    """
    key = provider_type or _DEFAULT_PROVIDER
    return _PROVIDER_CONFIGS.get(key, _PROVIDER_CONFIGS[_DEFAULT_PROVIDER])


def get_provider_heartbeat_timeout(provider_type: str | None) -> int:
    """获取 provider 的 heartbeat 超时（秒）。

    这是 failure_detector.py 硬编码分支的替代品——
    替换 ``timeout = codex_timeout if worker.provider == "codex" else standard_timeout``。

    Args:
        provider_type: Worker.provider 字段值。

    Returns:
        heartbeat timeout in seconds。

    >>> get_provider_heartbeat_timeout("claude")
    300
    >>> get_provider_heartbeat_timeout("codex")
    1800
    """
    cfg = get_provider_config(provider_type)
    return cfg["heartbeat"]["timeout_seconds"]


def get_provider_offline_timeout(provider_type: str | None) -> int:
    """获取 provider 的 offline 判定超时（秒）。

    >>> get_provider_offline_timeout("claude")
    300
    >>> get_provider_offline_timeout("codex")
    1800
    """
    cfg = get_provider_config(provider_type)
    return cfg["offline"]["timeout_seconds"]


def get_provider_evidence_config(provider_type: str | None) -> dict[str, Any]:
    """获取 provider 的 evidence 维度配置。"""
    cfg = get_provider_config(provider_type)
    return cfg["evidence"]


def get_provider_state_config(provider_type: str | None) -> dict[str, Any]:
    """获取 provider 的 state 维度配置。"""
    cfg = get_provider_config(provider_type)
    return cfg["state"]


def get_provider_startup_config(provider_type: str | None) -> dict[str, Any]:
    """获取 provider 的 startup 维度配置。"""
    cfg = get_provider_config(provider_type)
    return cfg["startup"]


def list_known_providers() -> list[str]:
    """返回所有已注册的 provider 类型列表。"""
    return list(_PROVIDER_CONFIGS.keys())

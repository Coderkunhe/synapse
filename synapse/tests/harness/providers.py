"""Provider config 工厂函数。

P13-B6: 以纯 dict 形式定义 Provider 配置（D-P13-007）。
B6+ 实现 `worker_providers` 表后，这些 dict 将替换为 DB 读取。

每个 Provider config 覆盖 B4 定义的五维契约：
- heartbeat: 心跳方法 + 间隔 + 超时
- offline:   离线判定超时 + 恢复策略
- evidence:  证据格式 + 大小限制 + 支持的文件类型
- state:     状态主数据源 + 缓存策略
- startup:   启动触发器 + 健康检查
"""

from __future__ import annotations

from typing import Any


def claude_code_provider_config() -> dict[str, Any]:
    """Claude Code 标准 Provider 配置。

    特征: daemon heartbeat (55s interval), file-based state,
          structured evidence, SessionStart hook trigger.
    """
    return {
        "type": "claude_code",
        "version": "1.0.0",
        "heartbeat": {
            "method": "daemon",
            "interval_seconds": 55,
            "max_skew_seconds": 10,
            "timeout_seconds": 300,
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
            "file_path": ".claude/_task-current.md",
            "refresh_on_startup": True,
            "cache_ttl_seconds": 60,
        },
        "startup": {
            "trigger": "hook",
            "health_check": True,
        },
    }


def codex_cli_provider_config() -> dict[str, Any]:
    """Codex CLI 标准 Provider 配置。

    特征: cron heartbeat (60s interval, 更大抖动容忍),
          API-only state, free_text evidence, prompt trigger.
    """
    return {
        "type": "codex_cli",
        "version": "0.146.0",
        "heartbeat": {
            "method": "cron",
            "interval_seconds": 60,
            "max_skew_seconds": 30,
            "timeout_seconds": 1800,
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
            "file_path": None,
            "refresh_on_startup": False,
            "cache_ttl_seconds": 0,
        },
        "startup": {
            "trigger": "prompt",
            "health_check": False,
        },
    }


def custom_provider_config(**overrides: Any) -> dict[str, Any]:
    """创建自定义 Provider 配置，用于边界测试。

    用法:
        # 测试极短超时
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 10},
            offline={"timeout_seconds": 10},
        )
        # 测试零超时（永不断开语义）
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 0},
            offline={"timeout_seconds": 0},
        )
    """
    base = claude_code_provider_config()
    for section, values in overrides.items():
        if section in base and isinstance(base[section], dict):
            base[section].update(values)
    return base

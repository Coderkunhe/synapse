"""P13-B7: Provider 配置测试 — config 解析 + 验证 + 边界用例。

测试覆盖:
  - 五维契约结构完整性（heartbeat/offline/evidence/state/startup）
  - 超时计算逻辑（Claude 300s vs Codex 1800s）
  - custom_provider_config() 覆盖 + 边界（零超时、负数、非 dict、未知 section）
  - Provider 差异矩阵（method/format/source/trigger 差异）
  - 边界用例（None 值、大超时值、skew 验证）

这些是 L2 纯数据测试 — 无 DB 依赖，验证 harness/providers.py 工厂函数。
"""

from __future__ import annotations

import pytest

from tests.harness.providers import (
    claude_code_provider_config,
    codex_cli_provider_config,
    custom_provider_config,
)


# ── 结构完整性 ──────────────────────────────────────────────────


class TestProviderConfigStructure:
    """五维契约结构完整性 — 每个 Provider 必须覆盖 B4 定义的全部五维。"""

    def test_claude_config_has_all_five_dimensions(self):
        cfg = claude_code_provider_config()
        assert cfg["type"] == "claude_code"
        assert cfg["version"] == "1.0.0"
        assert "heartbeat" in cfg, "Missing heartbeat dimension"
        assert "offline" in cfg, "Missing offline dimension"
        assert "evidence" in cfg, "Missing evidence dimension"
        assert "state" in cfg, "Missing state dimension"
        assert "startup" in cfg, "Missing startup dimension"

    def test_codex_config_has_all_five_dimensions(self):
        cfg = codex_cli_provider_config()
        assert cfg["type"] == "codex_cli"
        assert cfg["version"] == "0.146.0"
        assert "heartbeat" in cfg
        assert "offline" in cfg
        assert "evidence" in cfg
        assert "state" in cfg
        assert "startup" in cfg

    @pytest.mark.parametrize("dimension", [
        "heartbeat", "offline", "evidence", "state", "startup",
    ])
    def test_claude_dimension_is_non_empty_dict(self, dimension: str):
        cfg = claude_code_provider_config()
        section = cfg[dimension]
        assert isinstance(section, dict), f"{dimension} should be dict"
        assert len(section) > 0, f"{dimension} should not be empty"

    @pytest.mark.parametrize("dimension", [
        "heartbeat", "offline", "evidence", "state", "startup",
    ])
    def test_codex_dimension_is_non_empty_dict(self, dimension: str):
        cfg = codex_cli_provider_config()
        section = cfg[dimension]
        assert isinstance(section, dict), f"{dimension} should be dict"
        assert len(section) > 0, f"{dimension} should not be empty"


# ── Heartbeat 维度验证 ──────────────────────────────────────────


class TestHeartbeatDimension:
    """heartbeat 维度字段完整性 + 值语义。"""

    def test_claude_heartbeat_fields(self):
        hb = claude_code_provider_config()["heartbeat"]
        assert hb["method"] == "daemon"
        assert hb["interval_seconds"] == 55
        assert hb["max_skew_seconds"] == 10
        assert hb["timeout_seconds"] == 300

    def test_codex_heartbeat_fields(self):
        hb = codex_cli_provider_config()["heartbeat"]
        assert hb["method"] == "cron"
        assert hb["interval_seconds"] == 60
        assert hb["max_skew_seconds"] == 30
        assert hb["timeout_seconds"] == 1800

    def test_claude_timeout_is_300_seconds(self):
        """核心差异: Claude daemon 300s 短超时。"""
        assert claude_code_provider_config()["heartbeat"]["timeout_seconds"] == 300

    def test_codex_timeout_is_1800_seconds(self):
        """核心差异: Codex cron 1800s 长超时。"""
        assert codex_cli_provider_config()["heartbeat"]["timeout_seconds"] == 1800

    def test_codex_timeout_larger_than_claude(self):
        """Provider 差异回归守卫: Codex 超时必须 > Claude 超时。"""
        claude_to = claude_code_provider_config()["heartbeat"]["timeout_seconds"]
        codex_to = codex_cli_provider_config()["heartbeat"]["timeout_seconds"]
        assert codex_to > claude_to, (
            f"Codex timeout ({codex_to}s) must exceed Claude timeout ({claude_to}s)"
        )

    def test_codex_skew_larger_than_claude(self):
        """Codex cron 模式容忍更大的心跳抖动。"""
        claude_skew = claude_code_provider_config()["heartbeat"]["max_skew_seconds"]
        codex_skew = codex_cli_provider_config()["heartbeat"]["max_skew_seconds"]
        assert codex_skew > claude_skew, (
            f"Codex skew ({codex_skew}s) must exceed Claude skew ({claude_skew}s)"
        )


# ── Offline 维度验证 ────────────────────────────────────────────


class TestOfflineDimension:
    """offline 维度: 离线判定 + 恢复策略。"""

    def test_claude_offline_fields(self):
        off = claude_code_provider_config()["offline"]
        assert off["timeout_seconds"] == 300
        assert off["recovery"] == "daemon_auto_restart"

    def test_codex_offline_fields(self):
        off = codex_cli_provider_config()["offline"]
        assert off["timeout_seconds"] == 1800
        assert off["recovery"] == "cron_window"

    def test_recovery_strategies_differ(self):
        """不同 provider 类型的恢复策略应不同。"""
        claude_rec = claude_code_provider_config()["offline"]["recovery"]
        codex_rec = codex_cli_provider_config()["offline"]["recovery"]
        assert claude_rec != codex_rec


# ── Evidence 维度验证 ───────────────────────────────────────────


class TestEvidenceDimension:
    """evidence 维度: 证据格式 + 文件支持。"""

    def test_claude_evidence_fields(self):
        ev = claude_code_provider_config()["evidence"]
        assert ev["format"] == "structured"
        assert ev["max_size_bytes"] == 65536
        assert ev["supports_files"] is True
        assert ev["supports_diff"] is True
        assert ev["supports_screenshot"] is True

    def test_codex_evidence_fields(self):
        ev = codex_cli_provider_config()["evidence"]
        assert ev["format"] == "free_text"
        assert ev["max_size_bytes"] == 65536
        assert ev["supports_files"] is False
        assert ev["supports_diff"] is False
        assert ev["supports_screenshot"] is False

    def test_evidence_format_differs(self):
        """structured vs free_text — 两种不同的证据格式。"""
        claude_fmt = claude_code_provider_config()["evidence"]["format"]
        codex_fmt = codex_cli_provider_config()["evidence"]["format"]
        assert claude_fmt != codex_fmt


# ── State 维度验证 ──────────────────────────────────────────────


class TestStateDimension:
    """state 维度: 状态主数据源 + 缓存。"""

    def test_claude_state_fields(self):
        st = claude_code_provider_config()["state"]
        assert st["primary_source"] == "file"
        assert st["file_path"] == ".claude/_task-current.md"
        assert st["refresh_on_startup"] is True
        assert st["cache_ttl_seconds"] == 60

    def test_codex_state_fields(self):
        st = codex_cli_provider_config()["state"]
        assert st["primary_source"] == "api"
        assert st["file_path"] is None
        assert st["refresh_on_startup"] is False
        assert st["cache_ttl_seconds"] == 0

    def test_state_source_differs(self):
        """file vs api — 两种不同的状态数据源。"""
        claude_src = claude_code_provider_config()["state"]["primary_source"]
        codex_src = codex_cli_provider_config()["state"]["primary_source"]
        assert claude_src != codex_src


# ── Startup 维度验证 ────────────────────────────────────────────


class TestStartupDimension:
    """startup 维度: 启动触发器 + 健康检查。"""

    def test_claude_startup_fields(self):
        su = claude_code_provider_config()["startup"]
        assert su["trigger"] == "hook"
        assert su["health_check"] is True

    def test_codex_startup_fields(self):
        su = codex_cli_provider_config()["startup"]
        assert su["trigger"] == "prompt"
        assert su["health_check"] is False

    def test_startup_trigger_differs(self):
        """hook vs prompt — 不同的启动机制。"""
        claude_trig = claude_code_provider_config()["startup"]["trigger"]
        codex_trig = codex_cli_provider_config()["startup"]["trigger"]
        assert claude_trig != codex_trig


# ── custom_provider_config() 覆盖 ────────────────────────────────


class TestCustomProviderConfig:
    """custom_provider_config() — 覆盖 + 边界行为。"""

    def test_override_single_section(self):
        """覆盖 heartbeat timeout_seconds。"""
        cfg = custom_provider_config(heartbeat={"timeout_seconds": 60})
        assert cfg["heartbeat"]["timeout_seconds"] == 60
        # 其他字段保持不变
        assert cfg["heartbeat"]["method"] == "daemon"
        assert cfg["heartbeat"]["interval_seconds"] == 55

    def test_override_multiple_sections(self):
        """同时覆盖 heartbeat 和 offline。"""
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 120},
            offline={"timeout_seconds": 120},
        )
        assert cfg["heartbeat"]["timeout_seconds"] == 120
        assert cfg["offline"]["timeout_seconds"] == 120
        # 未覆盖部分保持原值
        assert cfg["evidence"]["format"] == "structured"
        assert cfg["state"]["primary_source"] == "file"

    def test_override_partial_section_preserves_other_keys(self):
        """仅覆盖 section 中的一个 key，其余 key 保持原值。"""
        cfg = custom_provider_config(heartbeat={"timeout_seconds": 999})
        assert cfg["heartbeat"]["timeout_seconds"] == 999
        assert cfg["heartbeat"]["method"] == "daemon"
        assert cfg["heartbeat"]["interval_seconds"] == 55
        assert cfg["heartbeat"]["max_skew_seconds"] == 10

    def test_override_with_zero_timeout(self):
        """零超时语义: 永不断开。"""
        cfg = custom_provider_config(
            heartbeat={"timeout_seconds": 0},
            offline={"timeout_seconds": 0},
        )
        assert cfg["heartbeat"]["timeout_seconds"] == 0
        assert cfg["offline"]["timeout_seconds"] == 0

    def test_override_with_negative_timeout(self):
        """负数超时 — 允许通过（语义由调用方解释）。"""
        cfg = custom_provider_config(heartbeat={"timeout_seconds": -1})
        assert cfg["heartbeat"]["timeout_seconds"] == -1

    def test_override_with_large_timeout(self):
        """极大超时值 — 允许通过（如 7 天 = 604800s）。"""
        cfg = custom_provider_config(heartbeat={"timeout_seconds": 604800})
        assert cfg["heartbeat"]["timeout_seconds"] == 604800

    def test_override_unknown_section_is_noop(self):
        """未知 section 不应报错，也不影响结果。"""
        cfg = custom_provider_config(unknown_section={"foo": "bar"})
        # 结果应与 base claude config 一致
        base = claude_code_provider_config()
        assert cfg["type"] == base["type"]
        assert cfg["heartbeat"] == base["heartbeat"]
        assert "unknown_section" not in cfg

    def test_override_non_dict_value_raises_typeerror(self):
        """非 dict 覆盖值应抛出 TypeError。"""
        with pytest.raises(TypeError, match="expects a dict"):
            custom_provider_config(heartbeat="not_a_dict")

    def test_override_non_dict_value_error_message_includes_section_name(self):
        """TypeError 消息应包含违规 section 名称以便调试。"""
        with pytest.raises(TypeError, match="heartbeat"):
            custom_provider_config(heartbeat=123)

    def test_override_non_dict_value_error_message_includes_type_name(self):
        """TypeError 消息应包含实际类型名。"""
        with pytest.raises(TypeError, match="int"):
            custom_provider_config(heartbeat=42)

    def test_override_with_none_value_in_section(self):
        """section 内 key 设为 None — 允许通过。"""
        cfg = custom_provider_config(state={"file_path": None})
        assert cfg["state"]["file_path"] is None

    def test_override_empty_dict_is_noop(self):
        """空 dict 覆盖不改变任何值。"""
        cfg = custom_provider_config(heartbeat={})
        base = claude_code_provider_config()
        assert cfg["heartbeat"] == base["heartbeat"]

    def test_override_all_five_dimensions(self):
        """一次性覆盖全部五维。"""
        cfg = custom_provider_config(
            heartbeat={"method": "custom_method"},
            offline={"recovery": "manual"},
            evidence={"format": "binary"},
            state={"primary_source": "memory"},
            startup={"trigger": "api_call"},
        )
        assert cfg["heartbeat"]["method"] == "custom_method"
        assert cfg["offline"]["recovery"] == "manual"
        assert cfg["evidence"]["format"] == "binary"
        assert cfg["state"]["primary_source"] == "memory"
        assert cfg["startup"]["trigger"] == "api_call"


# ── Provider 差异回归守卫 ───────────────────────────────────────


class TestProviderDifferentiation:
    """确保两个 Provider config 在所有关键维度上可区分。"""

    def test_types_differ(self):
        assert claude_code_provider_config()["type"] != codex_cli_provider_config()["type"]

    def test_versions_differ(self):
        assert claude_code_provider_config()["version"] != codex_cli_provider_config()["version"]

    def test_heartbeat_methods_differ(self):
        hb_c = claude_code_provider_config()["heartbeat"]["method"]
        hb_x = codex_cli_provider_config()["heartbeat"]["method"]
        assert hb_c != hb_x, f"Heartbeat methods should differ: {hb_c} vs {hb_x}"

    def test_timeout_seconds_differ(self):
        """回归守卫: 若两个 timeout 相同，说明配置定义有误。"""
        to_c = claude_code_provider_config()["heartbeat"]["timeout_seconds"]
        to_x = codex_cli_provider_config()["heartbeat"]["timeout_seconds"]
        assert to_c != to_x, (
            f"Timeouts must differ: Claude={to_c}s, Codex={to_x}s"
        )

    def test_offline_recovery_differs(self):
        rec_c = claude_code_provider_config()["offline"]["recovery"]
        rec_x = codex_cli_provider_config()["offline"]["recovery"]
        assert rec_c != rec_x

    def test_evidence_formats_differ(self):
        fmt_c = claude_code_provider_config()["evidence"]["format"]
        fmt_x = codex_cli_provider_config()["evidence"]["format"]
        assert fmt_c != fmt_x

    def test_state_sources_differ(self):
        src_c = claude_code_provider_config()["state"]["primary_source"]
        src_x = codex_cli_provider_config()["state"]["primary_source"]
        assert src_c != src_x

    def test_startup_triggers_differ(self):
        trig_c = claude_code_provider_config()["startup"]["trigger"]
        trig_x = codex_cli_provider_config()["startup"]["trigger"]
        assert trig_c != trig_x

    def test_codex_has_no_file_support(self):
        """Codex 不应支持文件证据（free_text only）。"""
        ev = codex_cli_provider_config()["evidence"]
        assert not ev["supports_files"]
        assert not ev["supports_diff"]
        assert not ev["supports_screenshot"]

    def test_claude_has_full_evidence_support(self):
        """Claude 应支持全部证据类型。"""
        ev = claude_code_provider_config()["evidence"]
        assert ev["supports_files"]
        assert ev["supports_diff"]
        assert ev["supports_screenshot"]


# ── 幂等性 ──────────────────────────────────────────────────────


class TestProviderConfigIdempotency:
    """每次调用应返回独立的 dict — 修改不互相影响。"""

    def test_claude_config_is_independent_copy(self):
        cfg1 = claude_code_provider_config()
        cfg2 = claude_code_provider_config()
        cfg1["heartbeat"]["timeout_seconds"] = 99999
        assert cfg2["heartbeat"]["timeout_seconds"] == 300, (
            "Modifying one config must not affect another"
        )

    def test_codex_config_is_independent_copy(self):
        cfg1 = codex_cli_provider_config()
        cfg2 = codex_cli_provider_config()
        cfg1["evidence"]["format"] = "modified"
        assert cfg2["evidence"]["format"] == "free_text"

    def test_custom_does_not_mutate_original(self):
        """custom_provider_config 不应修改 base config。"""
        original = claude_code_provider_config()
        original_hb = dict(original["heartbeat"])
        _custom = custom_provider_config(heartbeat={"timeout_seconds": 999})
        assert original["heartbeat"] == original_hb, (
            "custom_provider_config should not mutate the base config"
        )


# ── max_skew 合理性 ─────────────────────────────────────────────


class TestMaxSkewValidation:
    """max_skew 必须小于 interval_seconds（否则心跳窗口无意义）。"""

    def test_claude_skew_less_than_interval(self):
        hb = claude_code_provider_config()["heartbeat"]
        assert hb["max_skew_seconds"] < hb["interval_seconds"], (
            f"max_skew ({hb['max_skew_seconds']}s) must be < "
            f"interval ({hb['interval_seconds']}s)"
        )

    def test_codex_skew_less_than_interval(self):
        hb = codex_cli_provider_config()["heartbeat"]
        assert hb["max_skew_seconds"] < hb["interval_seconds"], (
            f"max_skew ({hb['max_skew_seconds']}s) must be < "
            f"interval ({hb['interval_seconds']}s)"
        )

    def test_custom_skew_exceeding_interval_passes_through(self):
        """custom_provider_config 不校验逻辑关系 — 由调用方负责。"""
        cfg = custom_provider_config(heartbeat={
            "interval_seconds": 10,
            "max_skew_seconds": 999,
        })
        assert cfg["heartbeat"]["max_skew_seconds"] == 999

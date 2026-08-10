"""P14-B2: pitfall_service 单元测试。

覆盖：
- get_next_pfl_id() 正确分配 ID
- create_pitfall() 创建格式正确的条目
- pitfall_exists() 检测已存在的 PFL
- 重复 PFL ID 检测

注意：create 测试使用临时文件，不污染真实的 pitfalls.md。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import src.services.pitfall_service as ps


# ── Fixture: temp pitfalls.md ─────────────────────────────────────────────


@pytest.fixture
def temp_pitfalls_file():
    """创建临时 pitfalls.md 供 create 测试使用，不污染真实文件。"""
    content = """# Synapse 技术踩坑注册表

> 当前登记：1 项（1 PFL + 0 AP）

---

## 未闭环条目

### PFL-001 — Existing test entry ✅ 已修复

**踩坑日期**：2026-01-01（Test）· **状态**：✅ 已修复 · **严重度**：🟢

**现象**：Pre-existing test entry.

---
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="pitfalls_test_", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp_path = f.name

    with mock.patch.object(ps, "_PITFALLS_PATH", Path(tmp_path)):
        yield Path(tmp_path)

    # Cleanup
    Path(tmp_path).unlink(missing_ok=True)


# ── Tests ──────────────────────────────────────────────────────────────────


class TestGetNextPflId:
    """get_next_pfl_id() — 只读，使用真实文件。"""

    def test_returns_valid_format(self):
        """返回的 PFL ID 格式正确（PFL-NNN）。"""
        pfl_id = ps.get_next_pfl_id()
        assert re.match(r"^PFL-\d{3}$", pfl_id), f"Invalid format: {pfl_id}"

    def test_returns_three_digit_number(self):
        """PFL ID 数字部分为三位零填充。"""
        pfl_id = ps.get_next_pfl_id()
        num = int(pfl_id.split("-")[1])
        assert 100 <= num <= 999, f"Number out of range: {num}"

    def test_returns_consistent_without_create(self):
        """连续调用返回相同结果（因为没有 create 改变文件）。"""
        id1 = ps.get_next_pfl_id()
        id2 = ps.get_next_pfl_id()
        assert id1 == id2, f"Expected same ID without create: {id1} vs {id2}"

    def test_returns_greater_than_last_real(self):
        """返回的 ID 应大于当前真实文件中的最大 PFL 编号。"""
        pfl_id = ps.get_next_pfl_id()
        # 当前文件中有 PFL-143 等条目，下一个应 > 143
        num = int(pfl_id.split("-")[1])
        assert num > 143, f"Expected > 143, got {num}"


class TestPitfallExists:
    """pitfall_exists() — 只读，使用真实文件。"""

    def test_existing_pfl_returns_true(self):
        """已存在的 PFL 返回 True。"""
        assert ps.pitfall_exists("PFL-143") is True

    def test_nonexistent_pfl_returns_false(self):
        """不存在的 PFL 返回 False。"""
        assert ps.pitfall_exists("PFL-999") is False


class TestCreatePitfall:
    """create_pitfall() — 使用临时文件。"""

    def test_creates_entry_and_returns_id(self, temp_pitfalls_file):
        """创建条目返回正确的 PFL ID。"""
        pfl_id = ps.create_pitfall(
            title="Test pitfall from unit test",
            description="This is a test entry created by automated tests.",
            severity="🟡",
            cause="Testing the create_pitfall function",
            fix_direction="Remove this entry after test verification",
            discovery_source="Unit test",
        )
        assert re.match(r"^PFL-\d{3}$", pfl_id)
        assert ps.pitfall_exists(pfl_id)

    def test_next_id_sees_created_entry(self, temp_pitfalls_file):
        """创建后 get_next_pfl_id 返回更大的值。"""
        pfl_id = ps.create_pitfall(
            title="ID increment test",
            description="Testing ID increment",
            severity="🟢",
            discovery_source="Unit test",
        )
        next_id = ps.get_next_pfl_id()
        created_num = int(pfl_id.split("-")[1])
        next_num = int(next_id.split("-")[1])
        # 创建了一个新条目后，next 应该更大
        # 注意：如果 PFL-001 存在，创建后可能得到 PFL-002，next 是 PFL-003
        assert next_num > created_num, f"Expected next > created: {next_num} vs {created_num}"

    def test_entry_appears_in_file(self, temp_pitfalls_file):
        """创建的条目确实出现在临时文件中。"""
        pfl_id = ps.create_pitfall(
            title="File presence test",
            description="Verifying entry appears in pitfalls.md",
            severity="🟢",
            discovery_source="Unit test",
        )
        content = temp_pitfalls_file.read_text(encoding="utf-8")
        assert f"### {pfl_id}" in content
        assert "File presence test" in content

    def test_entry_has_all_required_fields(self, temp_pitfalls_file):
        """创建的条目包含所有必要字段。"""
        pfl_id = ps.create_pitfall(
            title="Required fields test",
            description="Checking all markdown fields are present",
            severity="🔴",
            cause="Root cause analysis",
            fix_direction="Fix direction text",
            discovery_source="Unit test",
        )
        content = temp_pitfalls_file.read_text(encoding="utf-8")
        idx = content.find(f"### {pfl_id}")
        assert idx >= 0
        # 提取到下一个 PFL 条目
        end_idx = content.find("\n### PFL-", idx + 1)
        if end_idx < 0:
            end_idx = len(content)
        entry = content[idx:end_idx]
        assert "**踩坑日期**" in entry
        assert "**状态**" in entry
        assert "**严重度**" in entry
        assert "**现象**" in entry
        assert "**根因**" in entry
        assert "**修复方向**" in entry

    def test_create_without_optional_fields(self, temp_pitfalls_file):
        """optional 字段（cause, fix_direction）为空时也能创建。"""
        pfl_id = ps.create_pitfall(
            title="Minimal entry without cause",
            description="No cause or fix direction",
            severity="🟢",
            discovery_source="Unit test",
        )
        content = temp_pitfalls_file.read_text(encoding="utf-8")
        idx = content.find(f"### {pfl_id}")
        assert idx >= 0
        end_idx = content.find("\n### PFL-", idx + 1)
        if end_idx < 0:
            end_idx = content.find("\n---", idx + 1)
        if end_idx < 0:
            end_idx = len(content)
        entry = content[idx:end_idx]
        assert "**根因**" not in entry
        assert "**修复方向**" not in entry

    def test_duplicate_id_raises_error(self, temp_pitfalls_file):
        """创建重复 PFL ID 抛出 ValueError。"""
        pfl_id = ps.create_pitfall(
            title="Dedup test - first create",
            description="First entry for dedup test",
            severity="🟢",
            discovery_source="Unit test",
        )
        with pytest.raises(ValueError, match=f"{pfl_id} already exists"):
            ps.create_pitfall(
                pfl_id=pfl_id,
                title="Dedup test - should fail",
                description="Duplicate entry",
                severity="🟢",
                discovery_source="Unit test",
            )

    def test_invalid_pfl_id_format_raises_error(self, temp_pitfalls_file):
        """无效的 PFL ID 格式抛出 ValueError。"""
        with pytest.raises(ValueError, match="Invalid PFL ID format"):
            ps.create_pitfall(
                pfl_id="BAD-FORMAT",
                title="Bad format test",
                description="Should fail validation",
                severity="🟢",
                discovery_source="Unit test",
            )

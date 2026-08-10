"""Pitfall 程序化创建服务（P14-B2 G2 自动 PFL 登记）。

提供程序化的 PFL ID 分配和条目创建功能，
使 escalation detector 和 error report 端点能自动创建 PFL 条目。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# pitfalls.md 路径相对于 synapse/ 目录
_PITFALLS_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "pitfalls.md"
_OVERRIDE_PATH: Path | None = None


def _get_pitfalls_path() -> Path:
    """返回当前 pitfalls.md 路径（支持测试覆盖）。"""
    return _OVERRIDE_PATH or _PITFALLS_PATH


def set_pitfalls_path_for_test(path: Path) -> None:
    """测试专用：覆盖 pitfalls.md 路径。"""
    global _OVERRIDE_PATH
    _OVERRIDE_PATH = path


def reset_pitfalls_path_for_test() -> None:
    """测试专用：恢复默认路径。"""
    global _OVERRIDE_PATH
    _OVERRIDE_PATH = None


def get_next_pfl_id() -> str:
    """解析 pitfalls.md，返回下一个可用的 PFL ID。

    扫描所有 ``PFL-NNN`` 引用，取最大值 +1。
    返回格式：``PFL-XXX``（三位零填充，如 ``PFL-155``）。

    Raises:
        FileNotFoundError: pitfalls.md 不存在。
    """
    if not _get_pitfalls_path().exists():
        raise FileNotFoundError(f"pitfalls.md not found at {_get_pitfalls_path()}")

    content = _get_pitfalls_path().read_text(encoding="utf-8")
    ids = re.findall(r"PFL-(\d+)", content)
    if not ids:
        return "PFL-155"  # 从当前最大 154 之后的第一个
    max_num = max(int(n) for n in ids)
    return f"PFL-{max_num + 1:03d}"


def create_pitfall(
    title: str,
    description: str,
    *,
    severity: str = "🔴",
    cause: str | None = None,
    fix_direction: str | None = None,
    pfl_id: str | None = None,
    discovery_source: str = "P14-B2 自动登记",
) -> str:
    """创建一条 PFL 条目并追加到 pitfalls.md 的「未闭环条目」节。

    在 ``## 未闭环条目`` 标题后，第一条已有 PFL 条目之前插入新条目。

    Args:
        title: PFL 标题（不含 PFL-XXX 前缀）。
        description: 现象描述（对应 **现象** 字段）。
        severity: 严重度 emoji（``🔴`` / ``🟡`` / ``🟢``）。
        cause: 根因分析（可选，对应 **根因** 字段）。
        fix_direction: 修复方向（可选，单行文本）。
        pfl_id: 显式指定 PFL ID（可选）。默认自动分配下一个 ID。
        discovery_source: 发现来源标注（如 ``P14-B2 自动登记``）。

    Returns:
        创建的 PFL ID（如 ``PFL-155``）。

    Raises:
        FileNotFoundError: pitfalls.md 不存在。
        ValueError: PFL ID 已存在。
    """
    if not _get_pitfalls_path().exists():
        raise FileNotFoundError(f"pitfalls.md not found at {_get_pitfalls_path()}")

    # ── 分配 PFL ID ──
    if pfl_id is None:
        pfl_id = get_next_pfl_id()

    _validate_pfl_id_format(pfl_id)

    # 检查重复
    content = _get_pitfalls_path().read_text(encoding="utf-8")
    if _pfl_exists_in_content(content, pfl_id):
        raise ValueError(f"{pfl_id} already exists in pitfalls.md")

    # ── 构建条目 ──
    today = date.today().isoformat()
    entry = _build_entry(
        pfl_id=pfl_id,
        title=title,
        description=description,
        severity=severity,
        cause=cause,
        fix_direction=fix_direction,
        date_str=today,
        source=discovery_source,
    )

    # ── 插入到「未闭环条目」节 ──
    new_content = _insert_after_unclosed_header(content, entry)

    _get_pitfalls_path().write_text(new_content, encoding="utf-8")

    # ── 更新 header 计数 ──
    _update_header_count()

    logger.info("Created %s: %s", pfl_id, title)
    return pfl_id


def pitfall_exists(pfl_id: str) -> bool:
    """检查 PFL ID 是否已存在于 pitfalls.md 中。"""
    if not _get_pitfalls_path().exists():
        return False
    content = _get_pitfalls_path().read_text(encoding="utf-8")
    return _pfl_exists_in_content(content, pfl_id)


# ── Internal helpers ──────────────────────────────────────────────────────


def _validate_pfl_id_format(pfl_id: str) -> None:
    if not re.match(r"^PFL-\d{3}$", pfl_id):
        raise ValueError(f"Invalid PFL ID format: {pfl_id} (expected PFL-NNN)")


def _pfl_exists_in_content(content: str, pfl_id: str) -> bool:
    return bool(re.search(rf"^### {re.escape(pfl_id)}\s", content, re.MULTILINE))


def _build_entry(
    *,
    pfl_id: str,
    title: str,
    description: str,
    severity: str,
    cause: str | None,
    fix_direction: str | None,
    date_str: str,
    source: str,
) -> str:
    """构建单条 PFL markdown 条目。"""
    status = "🔴 待修复"

    lines = [
        "",
        f"### {pfl_id} — {title} {status}",
        "",
        f"**踩坑日期**：{date_str}（{source}）· **状态**：{status} · **严重度**：{severity}",
        "",
        f"**现象**：{description}",
    ]

    if cause:
        lines.append("")
        lines.append(f"**根因**：{cause}")

    if fix_direction:
        lines.append("")
        lines.append("**修复方向**：")
        lines.append(f"1. {fix_direction}")

    lines.append("")
    lines.append("---")

    return "\n".join(lines)


def _insert_after_unclosed_header(content: str, entry: str) -> str:
    """在 ``## 未闭环条目`` 标题后、第一条已有条目之前插入新条目。

    如果该节下已有条目，插入在标题行后第一条 ``### `` 之前（保持倒序/最新在前）。
    如果该节为空，追加到节尾（下一个 ``## `` 标题或文件末尾）。
    """
    header_pattern = r"^## 未闭环条目\s*$"

    # 找到 header 行号
    lines = content.split("\n")
    header_idx = None
    for i, line in enumerate(lines):
        if re.match(header_pattern, line):
            header_idx = i
            break

    if header_idx is None:
        # 如果不存在「未闭环条目」节，追加到文件末尾
        logger.warning(
            "No '## 未闭环条目' section found in pitfalls.md — appending to end of file"
        )
        return content.rstrip("\n") + "\n" + entry + "\n"

    # 找到 header 后的第一个非空行（跳过空白行）
    insert_idx = header_idx + 1
    while insert_idx < len(lines) and lines[insert_idx].strip() == "":
        insert_idx += 1

    # 如果下一个非空行是其他节标题（## ...），在中间插入
    # 如果下一个是 ### PFL-xxx，在它之前插入（最新在前）
    # 否则在 header 后插入

    # 插入新条目
    new_lines = lines[:insert_idx] + [entry] + lines[insert_idx:]
    return "\n".join(new_lines)


def _update_header_count() -> None:
    """更新 pitfalls.md 头部的登记计数（``当前登记：N 项``）。

    仅做 best-effort——解析失败不阻断主流程。
    """
    try:
        content = _get_pitfalls_path().read_text(encoding="utf-8")
    except Exception:
        return

    # 统计 PFL 条目数
    pfl_count = len(re.findall(r"^### PFL-\d+", content, re.MULTILINE))
    # 统计 AP 条目数
    ap_count = len(re.findall(r"^### AP-", content, re.MULTILINE))
    total = pfl_count + ap_count

    # 统计状态
    fixed = len(re.findall(r"✅", content.split("## 未闭环条目")[0] if "## 未闭环条目" in content else ""))
    # 简化：直接替换行
    new_content = re.sub(
        r"^> 当前登记：\d+ 项.*$",
        f"> 当前登记：{total} 项（{pfl_count} PFL + {ap_count} AP）",
        content,
        flags=re.MULTILINE,
    )
    if new_content != content:
        try:
            _get_pitfalls_path().write_text(new_content, encoding="utf-8")
        except Exception:
            pass  # best-effort

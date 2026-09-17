#!/usr/bin/env python3
"""P100-B166: reqlog 旧 Phase 归档迁移。

把 docs/requirements-log.md 里「已闭环但从未迁档」的批次条目 verbatim 迁入
docs/archive/requirements-log-archive.md，并把误置在「考古补登 — B124」块里的
P100-B128~B151（近期治理批，非考古）搬回活跃区。

背景矛盾（B109/B127 声称「P9+P10+P11 已归档」但主文件仍滞留）：
  - 旧债区（1367-5176）含 P3/P4/P5/P6/P8/P100 + P9/P10/P11 残片 + 「考古补登」混装块
  - 标题级对比：主 198 标题 vs archive 291 标题，真重复仅 16 个 → 主因是「该迁没迁」，非「去重」

边界锚点（heading 文本 · 唯一性断言）:
  OLD_START   = 首个 `## `（活跃区结束、旧债区开始）
  RELOC_START = P100-B128（误置块的起点）
  RELOC_END   = P13-B11（误置块里「迁 archive」部分的起点）
  INSERT_AT   = P100-B124（活跃区内 B128-151 的插入点，紧跟 B127 之后）

切分结果:
  archive_part_A = lines[OLD_START : RELOC_START]   # L5 报告 + P9/P10/P11 残片 + 旧 Phase + 考古补登 B17-B98
  relocate_block = lines[RELOC_START : RELOC_END]   # P100-B128~B151 + 中间 L5 报告 → 搬回活跃区
  archive_part_B = lines[RELOC_END : EOF]           # P13-B11/12 + P14-B7-13 + P16-B0-3

用法:
  python3 tools/p100-b166-reqlog-archive.py --dry-run   # 只打印计划与断言，不落盘
  python3 tools/p100-b166-reqlog-archive.py --apply     # 落盘
"""
import sys

MAIN = "docs/requirements-log.md"
ARCHIVE = "docs/archive/requirements-log-archive.md"

OLD_START = "## 🔀 L5 P100-B47→B50 拉通报告"
RELOC_START = "### P100-B128: L5 遗留治理"
RELOC_END = "### P13-B11: C13 Hook 诊断"
INSERT_AT = "### 2026-08-09 — P100-B124: Reqlog 孤儿归档"


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def find(lines, substr, label):
    idxs = [i for i, ln in enumerate(lines) if ln.rstrip("\n").startswith(substr)]
    assert len(idxs) == 1, f"锚点「{label}」匹配到 {len(idxs)} 处（期望 1）: {substr!r}"
    return idxs[0]


def main():
    dry = "--apply" not in sys.argv
    mode = "DRY-RUN" if dry else "APPLY"

    main_lines = read_lines(MAIN)
    archive_lines = read_lines(ARCHIVE)

    old_start = find(main_lines, OLD_START, "OLD_START")
    reloc_start = find(main_lines, RELOC_START, "RELOC_START")
    reloc_end = find(main_lines, RELOC_END, "RELOC_END")
    insert_at = find(main_lines, INSERT_AT, "INSERT_AT")

    # 顺序断言（锚点必须按 活跃区 < 旧债区 < 误置块 < 补登块 排列）
    assert insert_at < old_start < reloc_start < reloc_end, (
        f"锚点顺序异常: insert={insert_at} old={old_start} reloc_start={reloc_start} reloc_end={reloc_end}"
    )

    active_head = main_lines[:old_start]          # header + 活跃区（含 B127）
    archive_part_a = main_lines[old_start:reloc_start]
    relocate_block = main_lines[reloc_start:reloc_end]
    archive_part_b = main_lines[reloc_end:]

    # 块首尾断言（防止锚点错位导致内容丢失）
    assert relocate_block[0].rstrip("\n").startswith(RELOC_START), "relocate 块首行不是 P100-B128"
    assert archive_part_b[0].rstrip("\n").startswith(RELOC_END), "archive_part_b 首行不是 P13-B11"
    assert archive_part_a[0].rstrip("\n").startswith(OLD_START), "archive_part_a 首行不是 L5 B47→B50"
    # archive_part_a 末条目应为考古补登 P100-B98（而非误吞 B128）
    assert any(ln.rstrip("\n").startswith("### P100-B98") for ln in archive_part_a[-12:]), \
        "archive_part_a 末尾 12 行内找不到 P100-B98 标题"
    assert not any(ln.rstrip("\n").startswith("### P100-B128") for ln in archive_part_a), \
        "archive_part_a 误吞了 P100-B128（relocate 块应从这里开始）"

    # 新主文件 = 活跃区（插入点前）+ relocate 块 + 活跃区（插入点后）
    new_main = active_head[:insert_at] + relocate_block + active_head[insert_at:]

    # 新 archive = 原 archive + 新 section header + part A + part B
    section_header = [
        "\n",
        "---\n",
        "\n",
        "## P100-B166 归档：旧 Phase 全量迁档（P3/P4/P5/P6/P8/P100 + P9/P10/P11 残片 + P13-P16 补登残片）\n",
        "\n",
        "> 2026-09-18 · 解决 B109「P11 已归档」与主文件滞留的矛盾 —— 把主 reqlog 里已闭环但从未迁档的批次条目 verbatim 迁入本文档。\n",
        "> 迁移脚本：tools/p100-b166-reqlog-archive.py（边界断言 · 0 内容丢失）\n",
        "\n",
    ]
    new_archive = archive_lines + section_header + archive_part_a + archive_part_b

    # 内容守恒断言（总行数守恒：主文件减去的 == archive 增的，relocate 只在主文件内部搬家）
    delta_main = len(main_lines) - len(new_main)
    delta_archive = len(new_archive) - len(archive_lines)
    assert delta_main == len(archive_part_a) + len(archive_part_b), "主文件删减行数 ≠ 迁出块行数"
    assert delta_archive == len(section_header) + len(archive_part_a) + len(archive_part_b), "archive 增行数不符"

    print(f"=== P100-B166 reqlog 归档迁移 [{mode}] ===")
    print(f"锚点定位: 活跃区末={old_start+1}  旧债区起={old_start+1}  relocate[{reloc_start+1}:{reloc_end}]  insert@={insert_at+1}")
    print(f"  旧债区总行数      : {len(main_lines) - old_start}")
    print(f"    └ archive_part_a: {len(archive_part_a)} 行（L5+P9/P10/P11 残片+旧 Phase+考古补登 B17-B98）")
    print(f"    └ relocate_block: {len(relocate_block)} 行（P100-B128~B151 + L5 报告 → 搬回活跃区）")
    print(f"    └ archive_part_b: {len(archive_part_b)} 行（P13-B11/12 + P14-B7-13 + P16-B0-3）")
    print(f"主 reqlog: {len(main_lines)} → {len(new_main)} 行（-{delta_main}）")
    print(f"archive  : {len(archive_lines)} → {len(new_archive)} 行（+{delta_archive}）")
    print(f"守恒断言  : 主文件删 {delta_main} == 迁出块 {len(archive_part_a)+len(archive_part_b)}  ✅")

    # 抽查：relocate 块里应只含 P100 与 L5，不含 P13/P14/P16
    stray = [ln.rstrip() for ln in relocate_block
             if ln.lstrip().startswith("###") and not (
                 ln.lstrip().startswith("### P100-B") or "L5 拉通" in ln)]
    if stray:
        print(f"⚠️  relocate 块混入非 P100/L5 标题 {len(stray)} 条:")
        for s in stray[:10]:
            print(f"    {s}")
    else:
        print(f"relocate 纯度  : 全部 P100-B / L5 标题 ✅（无 P13/P14/P16 混入）")

    if dry:
        print("\n[dry-run] 未落盘。用 --apply 执行。")
        return

    with open(MAIN, "w", encoding="utf-8") as f:
        f.writelines(new_main)
    with open(ARCHIVE, "w", encoding="utf-8") as f:
        f.writelines(new_archive)
    print("\n✅ 已落盘。")


if __name__ == "__main__":
    main()

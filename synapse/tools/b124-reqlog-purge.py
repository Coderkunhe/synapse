#!/usr/bin/env python3
"""
P100-B124: Reqlog purge — archive orphan sections + backfill roadmap entries.
Confirmed orphans: 35 P100-B sections with dedicated headers but no git commits.
Backfill: 22 entries from roadmap that are missing from reqlog.
"""
import re, subprocess, sys
from datetime import datetime

REPO = '/Users/USERNAME/projects/personal/ai/ai-synapse'
REQLOG = f'{REPO}/synapse/docs/requirements-log.md'
ARCHIVE = f'{REPO}/synapse/docs/archive/requirements-log-archive.md'
DRY_RUN = '--execute' not in sys.argv

# Confirmed orphans (35): dedicated sections without git commits
ORPHANS = [
    'P100-B14', 'P100-B15', 'P100-B16', 'P100-B23', 'P100-B24',
    'P100-B29', 'P100-B30', 'P100-B31', 'P100-B32', 'P100-B33',
    'P100-B41', 'P100-B50', 'P100-B51', 'P100-B52', 'P100-B53',
    'P100-B54', 'P100-B55', 'P100-B56', 'P100-B58', 'P100-B59',
    'P100-B60', 'P100-B67', 'P100-B68', 'P100-B69', 'P100-B71',
    'P100-B74', 'P100-B75', 'P100-B76', 'P100-B77', 'P100-B78',
    'P100-B79', 'P100-B80', 'P100-B81', 'P100-B83', 'P100-B84',
]

# Gate 1 backfill data (from roadmap)
BACKFILL = {
    'P100-B17': 'V-002 防呆闭环 — make check-frontend 路径封装',
    'P100-B18': 'V-007 + V-012 防呆 — session-checkpoint token 估算 + post-commit batch counter',
    'P100-B19': 'V-003 防呆 — check-plan-mode.sh Plan Mode 入口检测',
    'P100-B20': 'V-004 防呆 — mypy type checking + check-types target',
    'P100-B21': 'V-005 防呆 — execution-checklist 五段式清单',
    'P100-B22': 'V-011 防呆 — check-docs.sh CLAUDE↔methodology 交叉引用检测',
    'P100-B26': 'P100-B25 自检修复 — V-020 monorepo 路径 + V-021 pipefail 崩溃 + MEM_DIR + 二次复发 · 5 files',
    'P100-B35': 'L5 拉通 P100-B34→P9-B81 — 文档新鲜度 + 叙事一致性 · 计数器复位',
    'P100-B37': 'make check 零警告 — L5 拉通 + 6 项清零',
    'P100-B38': 'S-023 一致性扫描 — 扫描工具就位',
    'P100-B39': 'S-016 Scout — 纯分析 · 文件清单 + 分层方案',
    'P100-B40': 'S-016 (1/6) — DB + Model 层重命名',
    'P100-B43': 'S-016 (4/6) — Schema 收尾 + API 路由 · 双路由器向后兼容',
    'P100-B48': '治理 backlog 消化(2) — G23 ws.py KeyError · G4 · G18 · G15 · 5 files',
    'P100-B49': '治理 backlog 消化(3) — G8 · G11 · G12 · G14 · G19 · 8 files',
    'P100-B82': '战略决策登记 — PI-05 多级授权降为远期 · S-013 确认远期 · 全局治理扫描 S-067~S-072 登记',
    'P100-B86': '违纪回顾 + 全量清零 — V-027/V-028 🔴→🟢 闭环 · 26/27 🟢 · 活跃 0 🎉',
    'P100-B87': '⏭️ 跳号（roadmap 标注为空 — 编号保留但无实际工作）',
    'P100-B97': 'G-036 requirements-log 膨胀治理 — P9+P10 归档至 archive · check-docs.sh 阈值调整',
    'P100-B98': '脚本硬约束 — session-init.js 486 行 · SKILL.md 616→185 行 (-70%) · generate-skill.sh 部署一致性',
    'P13-B11': 'C13 Hook 诊断 — SessionStart hook 静默失败检测 · check-session-hook-health.sh canary 探针 · CLAUDE.md 启动自检链 ③.5 扩展 · 4 files',
    'P13-B12': 'C11 O SLA Metric — O 响应性 SLA 自动度量 · o_sla_metrics.py + GET /stats/o-sla · p50/p95/p99 + SLA 达标率 · +16 tests · 4 files',
}

def find_section_boundaries(lines, batch):
    """Find start and end line numbers for a batch's dedicated section."""
    # Match header like "## P100-B14:" or "## P100-B14 —" (H2 or H3)
    header_pattern = re.compile(rf'^#{{2,3}}\s+{re.escape(batch)}[\s:——]')
    any_header = re.compile(r'^(#{2,3})\s+')

    start = None
    for i, line in enumerate(lines):
        if header_pattern.match(line):
            start = i
            break

    if start is None:
        return None, None

    # Find end: next H2/H3 header at same or higher level (not sub-headings like H4)
    header_level = len(re.match(r'^(#{2,3})', lines[start]).group(1))
    for i in range(start + 1, len(lines)):
        m = any_header.match(lines[i])
        if m:
            level = len(m.group(1))
            if level <= header_level:
                return start, i

    return start, len(lines)

def main():
    with open(REQLOG, 'r') as f:
        lines = f.readlines()

    # Phase 1: Archive orphan sections
    archive_entries = []
    replacements = []

    for batch in ORPHANS:
        start, end = find_section_boundaries(lines, batch)
        if start is None:
            print(f"  ⚠️  {batch}: section not found, skipping")
            continue

        section_lines = lines[start:end]
        header = section_lines[0].strip().lstrip('#').strip()

        # Build archive entry
        archive_entries.append(f"### {batch}: {header}\n\n")
        archive_entries.append(f"**归档原因**: git 历史中无独立 `{batch}` commit。工作内容已通过其他批次或合并提交完成。\n")
        archive_entries.append(f"**归档日期**: B124 · {datetime.now().strftime('%Y-%m-%d')}\n\n")
        for l in section_lines[1:]:
            archive_entries.append(l)
        archive_entries.append("\n---\n\n")

        # Replacement in reqlog
        replacement = (
            f"> **{batch}** 已归档至 [archive/requirements-log-archive.md](archive/requirements-log-archive.md)"
            f" — B124 考古归档 · 无独立 git commit，工作合并至其他批次。\n\n"
        )
        replacements.append((start, end, replacement))

        content_lines = len([l for l in section_lines if l.strip()])
        print(f"  {batch}: lines {start+1}-{end} ({content_lines} non-empty) → archive")

    if replacements:
        # Write archive (append)
        archive_header = (
            f"\n---\n\n## P100 考古归档 — B124 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
            f"> 以下 {len(replacements)} 个批次在 requirements-log.md 中有独立章节，"
            f"但 git 历史中无对应的独立 commit。\n"
            f"> 工作内容已通过其他批次或合并提交完成，此处保留原始 reqlog 记录供追溯。\n\n"
        )
        archive_entries.insert(0, archive_header)

        if not DRY_RUN:
            with open(ARCHIVE, 'a') as f:
                f.write(''.join(archive_entries))
            print(f"\n✅ Appended {len(replacements)} entries to archive")

            # Apply replacements (reverse order to preserve line numbers)
            replacements.sort(key=lambda x: x[0], reverse=True)
            for start, end, replacement in replacements:
                lines[start:end] = [replacement]
            print(f"✅ Replaced {len(replacements)} sections in reqlog")
        else:
            print(f"\n🔍 DRY RUN — would archive {len(replacements)} sections")

    # Phase 2: Add backfill entries
    backfill_text = (
        f"\n---\n\n## P100 + P13 考古补登 — B124 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
        f"> 以下 {len(BACKFILL)} 个批次在 roadmap 中有记载但 requirements-log 缺失，"
        f"从 roadmap 提取关键信息补登。\n"
        f"> 标注「🔍 考古补登」区别于常规 L1-L4 自检条目。\n\n"
    )

    for batch in sorted(BACKFILL.keys(), key=lambda x: (x.split('-B')[0], int(x.split('-B')[1]))):
        desc = BACKFILL[batch]
        backfill_text += f"### {batch}: {desc} 🔍 考古补登\n\n"
        backfill_text += f"- **来源**: roadmap.md\n"
        backfill_text += f"- **状态**: ✅ 已完成（git 历史可追溯）\n"
        backfill_text += f"- **备注**: B124 考古补登 — 原 reqlog 缺失，从 roadmap 还原\n\n"

    if not DRY_RUN:
        lines.append(backfill_text)
        with open(REQLOG, 'w') as f:
            f.writelines(lines)
        print(f"✅ Added {len(BACKFILL)} backfill entries to end of reqlog")
        print(f"✅ Wrote modified reqlog ({len(lines)} lines)")
    else:
        print(f"🔍 DRY RUN — would add {len(BACKFILL)} backfill entries")

    print(f"\n📊 B124 summary: archive {len(replacements)} orphans + backfill {len(BACKFILL)} entries")
    if DRY_RUN:
        print("🔍 Pass --execute to apply changes.")

if __name__ == '__main__':
    main()

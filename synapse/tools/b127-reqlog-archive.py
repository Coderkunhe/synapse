#!/usr/bin/env python3
"""P100-B127: Archive P11+P12 sections from requirements-log.md + compact empty lines.

1. Parse requirements-log.md into sections (### delimited)
2. Extract P11-B* and P12-B* sections → append to archive
3. Remove from active file
4. Compact excessive empty lines (3+ consecutive → 2)
5. Report statistics
"""

import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
REQLOG = PROJECT_DIR / "docs" / "requirements-log.md"
ARCHIVE = PROJECT_DIR / "docs" / "archive" / "requirements-log-archive.md"

# ── Parse sections ──────────────────────────────────────────

def parse_sections(text: str) -> list[dict]:
    """Split text into blocks: each ### header + its body (until next ### or ---)."""
    # Find all ### headers
    header_pattern = re.compile(r"^### .*$", re.MULTILINE)
    sep_pattern = re.compile(r"^---\s*$", re.MULTILINE)

    # Find all section boundaries
    boundaries = []
    for m in header_pattern.finditer(text):
        boundaries.append(("###", m.start(), m.group()))
    for m in sep_pattern.finditer(text):
        boundaries.append(("---", m.start(), m.group()))

    boundaries.sort(key=lambda x: x[1])

    sections = []
    for i, (kind, pos, header) in enumerate(boundaries):
        if kind != "###":
            continue
        # Find end: next boundary or EOF
        end = len(text)
        for j in range(i + 1, len(boundaries)):
            end = boundaries[j][1]
            break
        body = text[pos:end]
        sections.append({
            "header": header.strip(),
            "start": pos,
            "end": end,
            "body": body,
            "is_p11": bool(re.search(r'P11-B\d+', header)),
            "is_p12": bool(re.search(r'P12-B\d+', header)),
            "batch_id": extract_batch_id(header),
        })

    return sections


def extract_batch_id(header: str) -> str | None:
    m = re.search(r'(P1[12]-B\d+)', header)
    return m.group(1) if m else None


# ── Main ─────────────────────────────────────────────────────

def main():
    text = REQLOG.read_text(encoding="utf-8")
    original_lines = text.count("\n")

    sections = parse_sections(text)
    p11_sections = [s for s in sections if s["is_p11"]]
    p12_sections = [s for s in sections if s["is_p12"]]
    to_archive = p11_sections + p12_sections

    if not to_archive:
        print("No P11 or P12 sections found. Nothing to do.")
        return

    # ── Detect duplicates ──
    seen_ids = {}
    duplicates = []
    for s in to_archive:
        bid = s["batch_id"]
        if bid and bid in seen_ids:
            duplicates.append((bid, seen_ids[bid], s))
        elif bid:
            seen_ids[bid] = s

    # ── Archive: append to archive file ──
    archive_header = f"\n\n---\n\n## P11 + P12 全量归档（P100-B127 · 2026-08-09）\n\n"
    archive_header += f"> P11: {len(p11_sections)} 条 · P12: {len(p12_sections)} 条 · "
    archive_header += f"共 {len(to_archive)} 条\n"
    archive_header += f"> 归档原因：P11 (B137 ✅) + P12 (B52 ✅) 均已全量闭环\n"
    if duplicates:
        archive_header += f"> ⚠️ 重复条目 {len(duplicates)} 对（B124 补登与原始条目共存）— 两版均保留供审计\n"

    archive_body = archive_header
    total_archived_chars = 0
    for s in to_archive:
        archive_body += "\n" + s["body"].rstrip() + "\n"
        total_archived_chars += len(s["body"])

    # Read existing archive
    existing_archive = ARCHIVE.read_text(encoding="utf-8") if ARCHIVE.exists() else ""
    ARCHIVE.write_text(existing_archive + archive_body, encoding="utf-8")

    # ── Remove from active file ──
    # Process in reverse order to preserve positions
    removed_chars = 0
    result = text
    for s in sorted(to_archive, key=lambda x: x["start"], reverse=True):
        result = result[:s["start"]] + result[s["end"]:]
        removed_chars += (s["end"] - s["start"])

    # ── Compact empty lines (3+ → 2) ──
    result = re.sub(r'\n{4,}', '\n\n\n', result)

    # ── Update header ──
    import datetime
    today = datetime.date.today().isoformat()
    result = re.sub(
        r'> 最后更新：.*$',
        f'> 最后更新：{today}（P100-B127 🔜 · P11+P12 reqlog 归档 · counter=1）',
        result,
        count=1,
        flags=re.MULTILINE,
    )

    new_lines = result.count("\n")
    REQLOG.write_text(result, encoding="utf-8")

    # ── Report ──
    print(f"═══ P100-B127 Reqlog 归档报告 ═══")
    print(f"")
    print(f"📦 归档条目:")
    print(f"   P11: {len(p11_sections)} 条")
    print(f"   P12: {len(p12_sections)} 条")
    print(f"   合计: {len(to_archive)} 条")
    if duplicates:
        print(f"   ⚠️  重复条目: {len(duplicates)} 对")
        for bid, s1, s2 in duplicates:
            print(f"      {bid}: 行 {text[:s1['start']].count(chr(10))+1} + 行 {text[:s2['start']].count(chr(10))+1}")
    print(f"")
    print(f"📏 文件大小:")
    print(f"   归档前: {original_lines:,} 行")
    print(f"   归档后: {new_lines:,} 行")
    print(f"   减少: {original_lines - new_lines:,} 行 ({(original_lines - new_lines) * 100 // original_lines}%)")
    print(f"   归档内容: {total_archived_chars:,} 字符")
    print(f"")
    print(f"📁 归档目标: docs/archive/requirements-log-archive.md")
    print(f"   (追加 {len(archive_body.split(chr(10)))} 行)")


if __name__ == "__main__":
    main()

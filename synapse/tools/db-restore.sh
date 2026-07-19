#!/usr/bin/env bash
# ── Synapse Database Restore ────────────────────────────────
# 用法:
#   bash tools/db-restore.sh             列出所有可用备份
#   bash tools/db-restore.sh <filename>  从指定备份恢复
#   bash tools/db-restore.sh latest      从最新备份恢复
#
# 恢复前会自动备份当前数据库（防止误操作二次伤害）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${PROJECT_DIR}/data/synapse.db"
BACKUP_DIR="${PROJECT_DIR}/data/backups"

# ── 列出备份 ──────────────────────────────────────────────

list_backups() {
    echo "📂 可用备份: ${BACKUP_DIR}"
    echo ""
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -1 "$BACKUP_DIR"/*.db 2>/dev/null)" ]; then
        echo "  (无备份文件)"
        exit 0
    fi
    printf "  %-45s %10s  %s\n" "文件名" "大小" "时间"
    printf "  %-45s %10s  %s\n" "──────" "────" "────"
    ls -1t "$BACKUP_DIR"/*.db | while read -r f; do
        NAME=$(basename "$f")
        SIZE=$(ls -lh "$f" | awk '{print $5}')
        MTIME=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$f" 2>/dev/null || stat -c "%y" "$f" 2>/dev/null | cut -d'.' -f1)
        printf "  %-45s %10s  %s\n" "$NAME" "$SIZE" "$MTIME"
    done
}

# ── 无参数 → 列出备份 ─────────────────────────────────────

if [ $# -eq 0 ]; then
    list_backups
    exit 0
fi

# ── 解析目标备份 ──────────────────────────────────────────

if [ "$1" = "latest" ]; then
    TARGET=$(ls -1t "$BACKUP_DIR"/*.db 2>/dev/null | head -1)
    if [ -z "$TARGET" ]; then
        echo "❌ 无可用备份"
        exit 1
    fi
else
    TARGET="${BACKUP_DIR}/$1"
    if [ ! -f "$TARGET" ]; then
        echo "❌ 备份文件不存在: $1"
        echo ""
        list_backups
        exit 1
    fi
fi

# ── 确认 ──────────────────────────────────────────────────

echo "⚠️  即将恢复数据库:"
echo "   当前: ${DB_PATH}"
echo "   来源: $(basename "$TARGET")"
echo ""
echo "   当前数据库将被覆盖。恢复前会自动备份当前状态。"
echo ""
read -rp "   确认恢复? (输入 yes 继续): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "❌ 已取消"
    exit 0
fi

# ── 备份当前库（安全网）───────────────────────────────────

if [ -f "$DB_PATH" ]; then
    bash "$SCRIPT_DIR/db-backup.sh" "before-restore-$(date +%Y%m%d-%H%M%S)"
fi

# ── 执行恢复 ──────────────────────────────────────────────

cp "$TARGET" "$DB_PATH"
echo "✅ 数据库已恢复: $(basename "$TARGET")"

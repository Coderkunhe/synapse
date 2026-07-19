#!/usr/bin/env bash
# ── Synapse Database Backup ──────────────────────────────
# 用法: bash tools/db-backup.sh [label]
#   无参数   → 自动生成带时间戳的备份
#   带 label → 备份文件名附加标签（如 "before-migration"）
#
# 备份位置: data/backups/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${PROJECT_DIR}/data/synapse.db"
BACKUP_DIR="${PROJECT_DIR}/data/backups"

# ── 前置检查 ────────────────────────────────────────────

if [ ! -f "$DB_PATH" ]; then
    echo "❌ 数据库文件不存在: $DB_PATH"
    echo "   提示: 运行 make db-init 初始化数据库"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── 生成备份文件名 ──────────────────────────────────────

TIMESTAMP="$(date +%Y-%m-%d-%H%M%S)"
if [ $# -gt 0 ] && [ -n "$1" ]; then
    LABEL="-$1"
else
    LABEL=""
fi
BACKUP_NAME="synapse-${TIMESTAMP}${LABEL}.db"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

# ── 执行备份 ─────────────────────────────────────────────

cp "$DB_PATH" "$BACKUP_PATH"

# 文件大小（人类可读）
SIZE=$(ls -lh "$BACKUP_PATH" | awk '{print $5}')

echo "✅ 备份完成: ${BACKUP_NAME} (${SIZE})"

# ── 清理旧备份（保留最近 20 个）─────────────────────────

BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/*.db 2>/dev/null | wc -l | tr -d ' ')
if [ "$BACKUP_COUNT" -gt 20 ]; then
    TO_DELETE=$((BACKUP_COUNT - 20))
    echo "🗑️  清理 ${TO_DELETE} 个旧备份…"
    ls -1t "$BACKUP_DIR"/*.db | tail -n "$TO_DELETE" | xargs rm -f
fi

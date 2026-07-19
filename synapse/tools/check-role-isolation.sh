#!/usr/bin/env bash
# Synapse 角色隔离观测门禁 — ADR-006 观测协议 S1-S3/S7 机械检测
# 用法: bash tools/check-role-isolation.sh
# 接入: make check-role-isolation（警告级，不阻断）
# 来源: P11-B2 — ADR-006 角色隔离 · 观测 + 服务端（L2/L3）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ERRORS=0
WARNINGS=0

red()   { echo -e "\033[31m$1\033[0m"; }
green() { echo -e "\033[32m$1\033[0m"; }
yellow(){ echo -e "\033[33m$1\033[0m"; }

echo "=== Synapse 角色隔离观测门禁（ADR-006 S1-S3/S7）==="
echo ""

# ═══════════════════════════════════════════════════════════════════
# Layer A: 模板围栏合规静态扫描
# ═══════════════════════════════════════════════════════════════════

echo "--- Layer A: 模板围栏合规 ---"

TEMPLATES_DIR="$PROJECT_DIR/docs/templates"
ROLE_TEMPLATES=("role-orchestrator.md" "role-builder.md" "role-steward.md")

for tpl in "${ROLE_TEMPLATES[@]}"; do
    path="$TEMPLATES_DIR/$tpl"

    if [[ ! -f "$path" ]]; then
        red "  ❌ $tpl 不存在（$label 模板缺失）"
        ERRORS=$((ERRORS + 1))
        continue
    fi

    issues=0

    # A1: 能力边界 / 负面清单
    if ! grep -qE '(能力边界|负面清单|不在你的职责范围内)' "$path"; then
        yellow "  ⚠️  $tpl: 缺少「能力边界」/ 负面清单声明"
        issues=$((issues + 1))
    fi

    # A2: 人类越界拒绝
    if ! grep -q '即使人类' "$path"; then
        yellow "  ⚠️  $tpl: 缺少「即使人类明确要求」越界拒绝文本"
        issues=$((issues + 1))
    fi

    # A3: 角色不可变声明
    if ! grep -q '角色不可变' "$path"; then
        yellow "  ⚠️  $tpl: 缺少「角色不可变」声明"
        issues=$((issues + 1))
    fi

    if [[ $issues -eq 0 ]]; then
        green "  ✅ $tpl — 围栏合规"
    else
        WARNINGS=$((WARNINGS + issues))
    fi
done

echo ""

# ═══════════════════════════════════════════════════════════════════
# Layer A2: VALID_ROLES ↔ 模板文件 一致性
# ═══════════════════════════════════════════════════════════════════

echo "--- Layer A2: VALID_ROLES ↔ 模板一致性 ---"

# Check that each role in VALID_ROLES has a role-{role}.md template
VALID_ROLES_LINE=$(grep -A10 'VALID_ROLES.*frozenset' "$PROJECT_DIR/src/services/template_service.py" 2>/dev/null || true)

if [[ -z "$VALID_ROLES_LINE" ]]; then
    yellow "  ⚠️  无法解析 VALID_ROLES（template_service.py 中未找到定义）"
    WARNINGS=$((WARNINGS + 1))
else
    # Extract role names from VALID_ROLES
    for role in orchestrator builder steward; do
        role_tpl="$TEMPLATES_DIR/role-${role}.md"
        if echo "$VALID_ROLES_LINE" | grep -qi "$role"; then
            if [[ -f "$role_tpl" ]]; then
                green "  ✅ role-${role}.md — VALID_ROLES 有对应模板"
            else
                red "  ❌ VALID_ROLES 包含「${role}」但 role-${role}.md 不存在"
                ERRORS=$((ERRORS + 1))
            fi
        fi
    done
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
# Layer B: EventStore 跨角色访问检测（S1-S3, S7）
# ═══════════════════════════════════════════════════════════════════

echo "--- Layer B: EventStore 跨角色访问检测 ---"

DB_PATH="$PROJECT_DIR/data/synapse.db"

if [[ ! -f "$DB_PATH" ]]; then
    yellow "  ⚠️  数据库文件不存在（$DB_PATH）— 跳过 EventStore 扫描"
    yellow "  💡 提示: 启动应用并触发一些请求后，EventStore 数据将可用"
    WARNINGS=$((WARNINGS + 1))
else
    # Check if sqlite3 is available
    if ! command -v sqlite3 &>/dev/null; then
        yellow "  ⚠️  sqlite3 不可用 — 跳过 EventStore 扫描"
        WARNINGS=$((WARNINGS + 1))
    else
        # Query authorization_request.created events
        AUTH_EVENTS=$(sqlite3 "$DB_PATH" \
            "SELECT COUNT(*) FROM events WHERE event_type = 'authorization_request.created';" 2>/dev/null || echo "0")

        if [[ "$AUTH_EVENTS" == "0" ]]; then
            green "  ✅ EventStore: 零 authorization_request.created 事件（无跨角色访问）"
        else
            # S1-S3, S7 classification
            yellow "  📊 EventStore 发现 $AUTH_EVENTS 条 authorization_request.created 事件"

            # S1: Builder → O endpoints
            S1_COUNT=$(sqlite3 "$DB_PATH" \
                "SELECT COUNT(*) FROM events WHERE event_type = 'authorization_request.created' AND json_extract(payload, '$.request_type') = 'api_auth' AND (json_extract(payload, '$.operation') LIKE '%task.create%' OR json_extract(payload, '$.operation') LIKE '%task.assign%' OR json_extract(payload, '$.operation') LIKE '%verification.verify%');" 2>/dev/null || echo "0")
            yellow "    S1 (Builder→O): $S1_COUNT 次"

            # S2: O → B endpoints
            S2_COUNT=$(sqlite3 "$DB_PATH" \
                "SELECT COUNT(*) FROM events WHERE event_type = 'authorization_request.created' AND json_extract(payload, '$.request_type') = 'api_auth' AND (json_extract(payload, '$.operation') LIKE '%task.claim%' OR json_extract(payload, '$.operation') LIKE '%task.submit%');" 2>/dev/null || echo "0")
            yellow "    S2 (O→Builder): $S2_COUNT 次"

            # S3: Mixed role patterns (same worker)
            S3_COUNT=$(sqlite3 "$DB_PATH" \
                "SELECT COUNT(DISTINCT actor_id) FROM (SELECT actor_id FROM events WHERE event_type = 'authorization_request.created' GROUP BY actor_id HAVING COUNT(DISTINCT CASE WHEN json_extract(payload, '$.operation') LIKE '%task.create%' OR json_extract(payload, '$.operation') LIKE '%task.assign%' THEN 'o' WHEN json_extract(payload, '$.operation') LIKE '%task.claim%' OR json_extract(payload, '$.operation') LIKE '%task.submit%' THEN 'b' END) > 1);" 2>/dev/null || echo "0")
            yellow "    S3 (角色模糊): $S3_COUNT 个 Worker"

            # S7: Steward → O/B endpoints
            S7_COUNT=$(sqlite3 "$DB_PATH" \
                "SELECT COUNT(*) FROM events WHERE event_type = 'authorization_request.created' AND json_extract(payload, '$.request_type') = 'api_auth' AND json_extract(payload, '$.actor_role') = 'steward';" 2>/dev/null || echo "0")
            yellow "    S7 (Steward→O/B): $S7_COUNT 次"

            # Classification per ADR-006 判定矩阵
            TOTAL_S1_S2=$((S1_COUNT + S2_COUNT))
            if [[ $TOTAL_S1_S2 -eq 0 && $S3_COUNT -eq 0 ]]; then
                green "  🟢 零串戏 — 无跨角色访问"
            elif [[ $TOTAL_S1_S2 -le 2 && $S3_COUNT -eq 0 ]]; then
                yellow "  🟡 轻微串戏 — S1+S2 ≤ 2, S3 = 0（记录，不阻断）"
            else
                red "  🔴 严重串戏 — S1+S2 > 2 或 S3 > 0（需分析根因）"
            fi
        fi
    fi
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════

echo "--- 角色隔离观测门禁结果 ---"
if [[ $ERRORS -gt 0 ]]; then
    red "  ❌ $ERRORS 个错误"
fi
if [[ $WARNINGS -gt 0 ]]; then
    yellow "  ⚠️  $WARNINGS 个警告"
fi
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
    green "  ✅ 全部通过"
fi

# Warning-level only — never block commit
exit 0

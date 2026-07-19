#!/usr/bin/env bash
# Synapse API 契约检查 — OpenAPI schema 快照对比
# 用法: bash tools/check-contracts.sh
# 来源: P5-B17（master-backlog S-001）
#
# 行为:
#   首次运行（无基线）→ 提示生成基线，exit 0
#   有基线且无变更 → exit 0
#   有基线 + breaking change → 详细报告差异，exit 1
#   有基线 + 非 breaking 变更 → 告警但 exit 0，提示更新基线
#
# Breaking change 定义:
#   1. 路径删除（removed paths）
#   2. Response schema 字段删除（removed properties）
#   3. Required 字段新增（added required params）
#   4. 参数类型变更（type changes）

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BASELINE="$PROJECT_DIR/docs/contracts/openapi-baseline.json"
CONTRACTS_DIR="$PROJECT_DIR/docs/contracts"
ERRORS=0
WARNINGS=0

red()    { echo -e "\033[31m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
yellow() { echo -e "\033[33m$1\033[0m"; }

echo "=== API 契约检查（OpenAPI schema 快照对比）==="
echo ""

# ── 生成当前 OpenAPI schema ──────────────────────────────

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

CURRENT="$TMPDIR/current-openapi.json"

cd "$PROJECT_DIR"
if ! PYTHONPATH="$PROJECT_DIR" .venv/bin/python -c "
from src.main import app
import json
schema = app.openapi()
# Normalize: strip descriptions (they change without breaking contracts)
def strip_descriptions(obj, path=()):
    if isinstance(obj, dict):
        return {k: strip_descriptions(v, path + (k,)) for k, v in obj.items() if k not in ('description', 'title', 'summary', 'operationId')}
    elif isinstance(obj, list):
        return [strip_descriptions(v, path) for v in obj]
    return obj
print(json.dumps(strip_descriptions(schema), indent=2, sort_keys=True))
" > "$CURRENT" 2>/dev/null; then
    red "❌ 无法生成 OpenAPI schema — 请检查 FastAPI app 是否可正常启动"
    exit 1
fi

# ── 首次运行：无基线 ────────────────────────────────────

if [ ! -f "$BASELINE" ]; then
    yellow "📋 首次运行 — 未找到契约基线文件"
    yellow "   基线路径: docs/contracts/openapi-baseline.json"
    echo ""
    yellow "💡 运行以下命令生成基线:"
    yellow "   make contracts-baseline"
    echo ""
    green "✅ 首次运行不阻断（基线尚未建立）"
    exit 0
fi

# ── 对比 ─────────────────────────────────────────────────

echo "--- 路径变更 ---"

# Extract paths as sorted lists for comparison
CURRENT_PATHS=$(PYTHONPATH="$PROJECT_DIR" .venv/bin/python -c "
import json
with open('$CURRENT') as f:
    schema = json.load(f)
paths = sorted(schema.get('paths', {}).keys())
print('\n'.join(paths))
")

BASELINE_PATHS=$(PYTHONPATH="$PROJECT_DIR" .venv/bin/python -c "
import json
with open('$BASELINE') as f:
    schema = json.load(f)
paths = sorted(schema.get('paths', {}).keys())
print('\n'.join(paths))
")

# Removed paths (breaking)
REMOVED=$(comm -23 <(echo "$BASELINE_PATHS") <(echo "$CURRENT_PATHS"))
if [ -n "$REMOVED" ]; then
    while IFS= read -r path; do
        [ -z "$path" ] && continue
        red "  ❌ BREAKING: 路径删除 — $path"
        ERRORS=$((ERRORS + 1))
    done <<< "$REMOVED"
fi

# Added paths (non-breaking)
ADDED=$(comm -13 <(echo "$BASELINE_PATHS") <(echo "$CURRENT_PATHS"))
if [ -n "$ADDED" ]; then
    while IFS= read -r path; do
        [ -z "$path" ] && continue
        yellow "  ℹ️  新增端点 — $path"
        WARNINGS=$((WARNINGS + 1))
    done <<< "$ADDED"
fi

if [ -z "$REMOVED" ] && [ -z "$ADDED" ]; then
    green "  ✅ 端点路径无变更"
fi
echo ""

# ── Response schema 字段变更 ──────────────────────────────

echo "--- Response schema 字段变更 ---"

# Compare schemas per path + method
SCHEMA_DIFF=$(PYTHONPATH="$PROJECT_DIR" .venv/bin/python -c "
import json, sys

with open('$CURRENT') as f:
    current = json.load(f)
with open('$BASELINE') as f:
    baseline = json.load(f)

errors = []
warnings = []

current_paths = current.get('paths', {})
baseline_paths = baseline.get('paths', {})

for path in sorted(set(baseline_paths.keys()) & set(current_paths.keys())):
    for method in sorted(set(baseline_paths[path].keys()) & set(current_paths[path].keys())):
        base_op = baseline_paths[path][method]
        curr_op = current_paths[path][method]

        # Compare response schemas
        base_resp = base_op.get('responses', {})
        curr_resp = curr_op.get('responses', {})

        for status in sorted(set(base_resp.keys()) & set(curr_resp.keys())):
            base_schema = base_resp[status].get('content', {}).get('application/json', {}).get('schema', {})
            curr_schema = curr_resp[status].get('content', {}).get('application/json', {}).get('schema', {})

            if not base_schema or not curr_schema:
                continue

            # Compare properties
            base_props = set(base_schema.get('properties', {}).keys())
            curr_props = set(curr_schema.get('properties', {}).keys())

            removed = base_props - curr_props
            added = curr_props - base_props

            for prop in sorted(removed):
                errors.append(f'{path} [{method}] {status}: 字段删除 — {prop}')

            for prop in sorted(added):
                warnings.append(f'{path} [{method}] {status}: 新增字段 — {prop}')

            # Compare required fields
            base_req = set(base_schema.get('required', []))
            curr_req = set(curr_schema.get('required', []))

            new_required = curr_req - base_req
            for prop in sorted(new_required):
                errors.append(f'{path} [{method}] {status}: 字段变为 required — {prop}')

            # Compare property types
            for prop in sorted(base_props & curr_props):
                base_type = base_schema['properties'][prop].get('type')
                curr_type = curr_schema['properties'][prop].get('type')
                if base_type and curr_type and base_type != curr_type:
                    errors.append(f'{path} [{method}] {status}: 类型变更 — {prop} ({base_type} → {curr_type})')

for e in errors:
    print(f'ERROR:{e}')
for w in warnings:
    print(f'WARN:{w}')
" 2>/dev/null)

if [ -n "$SCHEMA_DIFF" ]; then
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        if [[ "$line" == ERROR:* ]]; then
            red "  ❌ BREAKING: ${line#ERROR:}"
            ERRORS=$((ERRORS + 1))
        elif [[ "$line" == WARN:* ]]; then
            yellow "  ⚠️  ${line#WARN:}"
            WARNINGS=$((WARNINGS + 1))
        fi
    done <<< "$SCHEMA_DIFF"
fi

if [ -z "$SCHEMA_DIFF" ]; then
    green "  ✅ Response schema 无变更"
fi
echo ""

# ── 总结 ─────────────────────────────────────────────────

echo "========================================="
if [ "$ERRORS" -gt 0 ]; then
    red "💀 $ERRORS 个 breaking change — 请确认变更是否为有意为之"
    echo ""
    red "   如果是有意变更，请更新基线: make contracts-baseline"
    echo ""
    exit 1
elif [ "$WARNINGS" -gt 0 ]; then
    yellow "⚠️  $WARNINGS 个非 breaking 变更（新增端点/字段）"
    echo ""
    yellow "   建议更新基线: make contracts-baseline"
    echo ""
    green "✅ 无 breaking change — 门禁通过"
    exit 0
else
    green "✅ 契约无变更 — 门禁通过"
    exit 0
fi

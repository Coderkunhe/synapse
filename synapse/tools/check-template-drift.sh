#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# P100-B105: Template drift detection
#
# Compares server-side template SHA256 fingerprints against source
# files to detect stale deployments. Wired into `make check`.
#
# Exit: 0 = all templates current · 1 = drift detected · 2 = error
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SYNAPSE_PROJECT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

failures=0
warnings=0

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 模板 drift 检测"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Compute template versions ────────────────────────────────

cd "$PROJECT_DIR"

VERSIONS_JSON=$(python3 -c "
import json, sys
try:
    from src.services.template_service import compute_template_versions
    versions = compute_template_versions()
    print(json.dumps(versions))
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(2)
" 2>&1) || {
    echo -e "${RED}❌ 无法计算模板版本指纹${NC}"
    echo "$VERSIONS_JSON"
    exit 2
}

# ── 2. Validate version format ──────────────────────────────────

VERSION=$(echo "$VERSIONS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])")
FILES_JSON=$(echo "$VERSIONS_JSON" | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['files']))")
UPDATED_AT=$(echo "$VERSIONS_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['updated_at'])")

# Check combined version format: "sha256:<64 hex chars>"
if [[ "$VERSION" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo -e "  ${GREEN}✅${NC} 合并版本: ${VERSION:0:18}..."
else
    echo -e "  ${RED}❌${NC} 合并版本格式异常: $VERSION"
    ((failures++))
fi

echo "  更新时间: $UPDATED_AT"

# ── 3. Verify all template .md files have hash entries ────────────

echo ""
echo "  Per-file hashes:"
declare -a missing_files=()

for md_file in "$PROJECT_DIR/docs/templates"/*.md; do
    fname=$(basename "$md_file")
    file_hash=$(echo "$FILES_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('$fname', ''))" 2>/dev/null || true)
    if [[ -z "$file_hash" ]]; then
        echo -e "    ${RED}❌${NC} $fname — 缺失 hash 条目"
        missing_files+=("$fname")
        ((failures++))
    elif [[ "$file_hash" =~ ^sha256:[a-f0-9]{64}$ ]]; then
        echo -e "    ${GREEN}✅${NC} $fname — ${file_hash:0:18}..."
    else
        echo -e "    ${RED}❌${NC} $fname — hash 格式异常: $file_hash"
        ((failures++))
    fi
done

# Check for subdirectory files (synapse-client/)
if [[ -d "$PROJECT_DIR/docs/templates/synapse-client" ]]; then
    echo ""
    echo "  synapse-client/ 文件 (不在版本管理中):"
    echo -e "    ${YELLOW}⚠️${NC}  ️synapse-client/ 下的 .js/.md 文件不在 compute_template_versions() 扫描范围内（仅扫描 .md）"
    echo "       这些文件在 generate-skill.sh 时通过 --check-version 对比部署版本。"
fi

# ── 4. Check for orphan .md files NOT in templates/ ──────────────

if [[ ${#missing_files[@]} -gt 0 ]]; then
    echo ""
    echo -e "  ${RED}缺失 hash 的文件: ${missing_files[*]}${NC}"
fi

# ── 5. Optional: Check worker deployments ────────────────────────

WORKER_DIRS=$(ls -d "$PROJECT_DIR/../ai-synapse-worker-"* 2>/dev/null || true)
if [[ -n "$WORKER_DIRS" ]]; then
    echo ""
    echo "  Worker 部署版本对比:"
    for worker_dir in $WORKER_DIRS; do
        worker_name=$(basename "$worker_dir")
        version_file="$worker_dir/.claude/synapse-version.json"
        if [[ -f "$version_file" ]]; then
            deployed_version=$(python3 -c "import json; print(json.load(open('$version_file')).get('version',''))" 2>/dev/null || echo "")
            if [[ "$deployed_version" == "$VERSION" ]]; then
                echo -e "    ${GREEN}✅${NC} $worker_name — 最新"
            else
                echo -e "    ${YELLOW}⚠️${NC}  $worker_name — 已过期 (部署: ${deployed_version:0:18}... → 模板: ${VERSION:0:18}...)"
                ((warnings++))
            fi
        else
            echo -e "    ${YELLOW}⚠️${NC}  $worker_name — 无 synapse-version.json（运行 generate-skill.sh --upgrade 生成）"
            ((warnings++))
        fi
    done
fi

# ── Result ─────────────────────────────────────────────────────

echo ""
if [[ $failures -gt 0 ]]; then
    echo -e "${RED}❌ $failures failure(s) detected${NC}"
    exit 1
elif [[ $warnings -gt 0 ]]; then
    echo -e "${YELLOW}⚠️  $warnings warning(s) — 建议运行 generate-skill.sh --upgrade${NC}"
    exit 0
else
    echo -e "${GREEN}✅ 模板 drift 检测通过${NC}"
    exit 0
fi

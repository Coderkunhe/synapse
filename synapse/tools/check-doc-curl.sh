#!/usr/bin/env bash
# S-024(b) · doc curl 块 subprocess E2E 机械门禁
#
# 扫描 onboarding.md 中所有 curl 代码块：
#   1. 结构校验（默认）— URL 模式·HTTP 方法·Auth header·JSON body 语法
#   2. Live 模式（SYNAPSE_BASE_URL 设置时）— subprocess 真跑 assert 2xx
#
# 集成：
#   - make check-doc-curl（独立 target）
#   - make check（聚合管道 · 警告级，首部署不阻断）
#
# 用法：
#   bash tools/check-doc-curl.sh [--onboarding <path>]
#   SYNAPSE_BASE_URL=http://localhost:8000 bash tools/check-doc-curl.sh  # live 模式
#
# 退出码：0 = 通过/警告 · 1 = 结构错误（阻断）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

yellow() { echo -e "\033[33m$1\033[0m"; }
green()  { echo -e "\033[32m$1\033[0m"; }
red()    { echo -e "\033[31m$1\033[0m"; }
bold()   { echo -e "\033[1m$1\033[0m"; }

# ── 参数解析 ──────────────────────────────────────────────────

ONBOARDING="${ONBOARDING:-$PROJECT_DIR/docs/onboarding.md}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --onboarding) ONBOARDING="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# CHECK_ONBOARDING 可从外部环境注入（gate test 用）
if [ -z "${CHECK_ONBOARDING:-}" ]; then
    export CHECK_ONBOARDING="$ONBOARDING"
fi

if [ ! -f "$CHECK_ONBOARDING" ]; then
    yellow "  ⚠️  $CHECK_ONBOARDING 不存在，跳过 doc-curl 检测"
    exit 0
fi

LIVE_MODE="false"
if [ -n "${SYNAPSE_BASE_URL:-}" ]; then
    LIVE_MODE="true"
fi

echo ""
bold "=== doc-curl 门禁 (S-024b) ==="
echo ""

# ── 核心解析 + 校验（Python inline — 处理多行 curl + JSON 验证）──

# bash 5.x set -e 在 command substitution 非零退出时杀脚本，需要临时关闭
set +e
OUTPUT=$(python3 << 'PYEOF'
import json
import re
import subprocess
import sys
import os

onboarding_path = os.environ.get("CHECK_ONBOARDING", "")
if not onboarding_path:
    print("  ⚠️  CHECK_ONBOARDING 未设置")
    sys.exit(1)

with open(onboarding_path) as f:
    content = f.read()

# ── 提取 bash 代码块 ──────────────────────────────────────────
blocks = re.findall(r'```bash\n(.*?)```', content, re.DOTALL)

# ── 已知 Synapse API 端点模式（用于 URL 校验）─────────────────
KNOWN_PATTERNS = [
    # Agent 生命周期
    (r'^POST /v1/teams/tea_[a-zA-Z0-9]+/agents$', 'POST'),
    (r'^POST /v1/agents/ag_[a-zA-Z0-9]+/handshake$', 'POST'),
    (r'^POST /v1/agents/ag_[a-zA-Z0-9]+/heartbeat$', 'POST'),
    (r'^GET /v1/agents/ag_[a-zA-Z0-9]+$', 'GET'),
    (r'^DELETE /v1/agents/ag_[a-zA-Z0-9]+$', 'DELETE'),
    (r'^GET /v1/agents/ag_[a-zA-Z0-9]+/protocol\?project_id=', 'GET'),
    # Task 核心
    (r'^GET /v1/projects/prj_[a-zA-Z0-9]+/tasks$', 'GET'),
    (r'^GET /v1/projects/prj_[a-zA-Z0-9]+/tasks/available$', 'GET'),
    (r'^GET /v1/tasks/tsk_[a-zA-Z0-9]+$', 'GET'),
    (r'^POST /v1/projects/prj_[a-zA-Z0-9]+/tasks$', 'POST'),
    (r'^PATCH /v1/tasks/tsk_[a-zA-Z0-9]+$', 'PATCH'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/ready\?expected_version=', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/claim\?expected_version=', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/submit$', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/blocker$', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/assign$', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/cancel\?expected_version=', 'POST'),
    (r'^POST /v1/tasks/tsk_[a-zA-Z0-9]+/terminate$', 'POST'),
    # Batch / Project / Verification
    (r'^POST /v1/teams/tea_[a-zA-Z0-9]+/projects$', 'POST'),
    (r'^GET /v1/teams/tea_[a-zA-Z0-9]+/projects$', 'GET'),
    (r'^POST /v1/batches/bat_[a-zA-Z0-9]+/claim$', 'POST'),
    (r'^GET /v1/tasks/tsk_[a-zA-Z0-9]+/verifications$', 'GET'),
    (r'^POST /v1/verifications/vrf_[a-zA-Z0-9]+/verify$', 'POST'),
]

VALID_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'}

# ── 辅助函数 ──────────────────────────────────────────────────

def extract_curl_commands(block: str) -> list[dict]:
    """Extract individual curl commands from a bash block, handling line continuations
    and multi-line bodies (JSON spanning multiple lines without backslash)."""
    lines = block.split('\n')

    # Phase 1: Join backslash continuations into single lines
    joined_lines = []
    current = ''
    for line in lines:
        stripped = line.rstrip()
        if stripped.endswith('\\'):
            current += stripped[:-1] + ' '
        else:
            current += stripped
            if current.strip():
                joined_lines.append(current.strip())
            current = ''
    if current.strip():
        joined_lines.append(current.strip())

    # Phase 2: Group multi-line curl commands
    # A curl command starts with 'curl ' and continues until the next 'curl ' line
    # or blank line. Body lines (inside -d '...') are part of the same command.
    curl_groups = []
    current_group = []
    for line in joined_lines:
        if re.match(r'^curl\s', line):
            if current_group:
                curl_groups.append(' '.join(current_group))
            current_group = [line]
        elif current_group:
            # This line is a continuation (body, header on its own line, etc.)
            current_group.append(line)
        # else: not in a curl command, skip (comments, etc.)
    if current_group:
        curl_groups.append(' '.join(current_group))

    commands = [parse_curl(g) for g in curl_groups]
    return commands


def parse_curl(cmd: str) -> dict:
    """Parse a single curl command into its components."""
    result = {
        'raw': cmd,
        'method': 'GET',  # default
        'url': '',
        'headers': [],
        'has_auth': False,
        'has_content_type': False,
        'body': None,
        'body_str': '',
        'errors': [],
    }

    # Extract method: -X POST / --request POST
    m = re.search(r'(?:-X|--request)\s+(\S+)', cmd)
    if m:
        result['method'] = m.group(1).upper()

    # Extract URL (first http/https token after curl)
    m = re.search(r"""curl\s+(?:-[a-zA-Z-]+\s+\S+\s+)*['"]?(https?://[^'"\s]+)['"]?""", cmd)
    if m:
        result['url'] = m.group(1)
        # Strip trailing backslash artifacts
        result['url'] = result['url'].rstrip('\\')

    # If URL not found via regex, try simpler approach
    if not result['url']:
        m = re.search(r"""https?://[^\s'"\\]+""", cmd)
        if m:
            result['url'] = m.group(0)

    # Extract headers
    for h in re.finditer(r"""(?:-H|--header)\s+['"]([^'"]+)['"]""", cmd):
        header_val = h.group(1)
        result['headers'].append(header_val)
        if header_val.lower().startswith('authorization:'):
            if 'bearer' in header_val.lower():
                result['has_auth'] = True
        if header_val.lower().startswith('content-type:'):
            result['has_content_type'] = True

    # Extract body
    body_match = re.search(r"""(?:-d|--data(?:-raw)?)\s+'(.*?)(?:'|$)""", cmd)
    if not body_match:
        body_match = re.search(r'(?:-d|--data(?:-raw)?)\s+"(.*?)(?:"|$)', cmd)
    if not body_match:
        body_match = re.search(r'(?:-d|--data(?:-raw)?)\s+(\{.*?\})(?:\s|$)', cmd)
    if body_match:
        result['body_str'] = body_match.group(1)
        try:
            result['body'] = json.loads(result['body_str'])
        except json.JSONDecodeError as e:
            result['errors'].append(f"JSON body 语法错误: {e}")

    return result


def validate_curl(cmd: dict, block_idx: int) -> list[str]:
    """Validate a parsed curl command. Returns list of error messages."""
    errors = list(cmd['errors'])

    # 1. Method validation
    if cmd['method'] not in VALID_METHODS:
        errors.append(f"无效 HTTP 方法: {cmd['method']}")

    # 2. URL validation
    url = cmd['url']
    if not url:
        errors.append("缺少 URL")
    elif not url.startswith('http://localhost:8000/v1/'):
        errors.append(f"URL 应为 http://localhost:8000/v1/... 格式，实际: {url}")
    else:
        # Extract path from URL for pattern matching
        path = url.replace('http://localhost:8000', '')
        # Remove query params for base path matching
        base_path = path.split('?')[0] if '?' in path else path

        # Build method+path key for matching
        method_path = f"{cmd['method']} {base_path}"

        # Check against known patterns
        matched = False
        for pattern, expected_method in KNOWN_PATTERNS:
            if re.match(pattern, method_path):
                matched = True
                if cmd['method'] != expected_method:
                    errors.append(f"HTTP 方法与端点不匹配: {cmd['method']} (期望 {expected_method})")
                break

        if not matched:
            # Don't error on unknown patterns — doc may have new endpoints
            # But flag if the path doesn't start with /v1/
            if not path.startswith('/v1/'):
                errors.append(f"API 路径应以 /v1/ 开头: {path}")

    # 3. Auth header required for all Synapse endpoints
    if not cmd['has_auth']:
        errors.append("缺少 Authorization: Bearer 认证头")

    # 4. Content-Type required for methods with body
    if cmd['method'] in ('POST', 'PUT', 'PATCH') and cmd['body_str']:
        if not cmd['has_content_type']:
            errors.append("POST/PUT/PATCH 含 body 时需 Content-Type: application/json")

    return errors


# ── 主逻辑 ────────────────────────────────────────────────────

all_errors = []
total_curls = 0
block_num = 0

for i, block in enumerate(blocks):
    # Determine approximate line number in source doc
    block_start = content[:content.index(block)].count('\n') + 1 if block in content else 0

    curls = extract_curl_commands(block)
    if not curls:
        continue  # skip blocks with no curl (env exports, generate-skill, etc.)

    block_num += 1
    for j, curl in enumerate(curls):
        total_curls += 1
        errors = validate_curl(curl, block_num)

        method = curl['method']
        url_short = curl['url'].replace('http://localhost:8000', '') if curl['url'] else '(no url)'
        if len(url_short) > 70:
            url_short = url_short[:67] + '...'

        if errors:
            all_errors.append({
                'block': block_num,
                'line_approx': block_start,
                'method': method,
                'url': url_short,
                'errors': errors,
            })
            print(f"  ❌ Block {block_num} · {method} {url_short}")
            for e in errors:
                print(f"     → {e}")
        else:
            print(f"  ✅ Block {block_num} · {method} {url_short}")


# ── 汇总 ──────────────────────────────────────────────────────
print("")
if all_errors:
    print(f"  🔴 {len(all_errors)}/{total_curls} 条 curl 命令存在结构问题")
    print("")
    print("  💡 修复方向：")
    print("     1. 确认 URL 匹配 API 端点表（onboarding.md §5）")
    print("     2. 确认 Authorization: Bearer 头存在")
    print("     3. 确认 POST/PATCH 含 Content-Type: application/json")
    print("     4. 检查 -d body 为合法 JSON（可用 python3 -m json.tool 验证）")
    sys.exit(1)
else:
    print(f"  ✅ 全部 {total_curls} 条 curl 命令结构校验通过")
    sys.exit(0)
PYEOF
)

STRUCT_EXIT=$?
set -e

# Echo the Python output (captured by command substitution)
echo "$OUTPUT"

# ── Live 模式（可选）──────────────────────────────────────────

if [ "$LIVE_MODE" = "true" ] && [ $STRUCT_EXIT -eq 0 ]; then
    echo ""
    bold "─── Live 模式 · subprocess 真跑 ───"
    echo ""

    LIVE_FAIL=0
    LIVE_TOTAL=0
    LIVE_PASS=0

    # 重新提取所有 curl 并逐条运行
    while IFS= read -r curl_cmd; do
        [ -z "$curl_cmd" ] && continue
        LIVE_TOTAL=$((LIVE_TOTAL + 1))

        # 替换 localhost:8000 → SYNAPSE_BASE_URL
        adapted=$(echo "$curl_cmd" | sed "s|http://localhost:8000|${SYNAPSE_BASE_URL}|g")

        # 运行 curl，捕获 HTTP 状态码
        HTTP_CODE=$(eval "$adapted -s -o /dev/null -w '%{http_code}'" 2>&1) || true

        # 截取 URL 用于显示
        URL_SHORT=$(echo "$adapted" | grep -oE "${SYNAPSE_BASE_URL}[^ ]*" | head -1 | sed 's|'"${SYNAPSE_BASE_URL}"'||')
        [ -z "$URL_SHORT" ] && URL_SHORT="(parse error)"
        [ ${#URL_SHORT} -gt 60 ] && URL_SHORT="${URL_SHORT:0:57}..."

        if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" -ge 200 ] 2>/dev/null && [ "$HTTP_CODE" -lt 300 ] 2>/dev/null; then
            green "  ✅ HTTP $HTTP_CODE · $URL_SHORT"
            LIVE_PASS=$((LIVE_PASS + 1))
        else
            red "  ❌ HTTP ${HTTP_CODE:-???} · $URL_SHORT"
            LIVE_FAIL=$((LIVE_FAIL + 1))
        fi
    done < <(python3 -c "
import re, sys
with open('$CHECK_ONBOARDING') as f:
    content = f.read()
blocks = re.findall(r'\`\`\`bash\n(.*?)\`\`\`', content, re.DOTALL)
for block in blocks:
    lines = block.split('\n')
    joined = []
    current = ''
    for line in lines:
        s = line.rstrip()
        if s.endswith('\\\\'):
            current += s[:-1] + ' '
        else:
            current += s
            if current.strip(): joined.append(current.strip())
            current = ''
    if current.strip(): joined.append(current.strip())
    for line in joined:
        if re.match(r'^curl\s', line):
            print(line)
")

    echo ""
    if [ "$LIVE_FAIL" -eq 0 ]; then
        green "  ✅ Live 模式: $LIVE_PASS/$LIVE_TOTAL 通过 ($SYNAPSE_BASE_URL)"
    else
        yellow "  ⚠️  Live 模式: $LIVE_PASS/$LIVE_TOTAL 通过 · $LIVE_FAIL 失败 ($SYNAPSE_BASE_URL)"
        echo "  💡 Live 失败可能是占位 ID/凭证不匹配（onboarding.md 使用示例 ID）"
    fi
fi

# ── 最终退出 ──────────────────────────────────────────────────

echo ""
if [ $STRUCT_EXIT -ne 0 ]; then
    red "❌ doc-curl 结构校验未通过"
    exit 1
else
    green "✅ doc-curl 检测完成"
    exit 0
fi

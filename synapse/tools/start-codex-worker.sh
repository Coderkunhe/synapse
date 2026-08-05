#!/usr/bin/env bash
# start-codex-worker.sh — Codex Worker 一键启动（P12-B13）
#
# 封装 `codex exec` + boot prompt 注入，消除手动粘贴。
# Codex CLI 没有 SessionStart hook → 此脚本等效 HK-1。
#
# Usage:
#   # 从项目根目录启动（默认在 ../synapse-codex-builder）：
#   bash tools/start-codex-worker.sh
#
#   # 指定 Codex Worker 目录：
#   bash tools/start-codex-worker.sh --project-dir /path/to/synapse-codex-builder
#
#   # 传递额外 codex 配置：
#   bash tools/start-codex-worker.sh -c 'model="opus"' --enable some-feature
#
#   # 试运行（只打印将要执行的 prompt，不实际启动）：
#   bash tools/start-codex-worker.sh --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Codex Worker 目录：从 synapse/ 向上两级到 ai/，再进入 synapse-codex-builder
DEFAULT_WORKER_DIR="$PROJECT_ROOT/../../synapse-codex-builder"

# ── Color helpers ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── Parse args ──
WORKER_DIR="$DEFAULT_WORKER_DIR"
DRY_RUN=false
CODEX_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-dir)
            WORKER_DIR="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -c|--config|--enable|--disable)
            CODEX_ARGS+=("$1" "$2")
            shift 2
            ;;
        *)
            CODEX_ARGS+=("$1")
            shift
            ;;
    esac
done

# ── Pre-flight checks ──
if [[ ! -d "$WORKER_DIR" ]]; then
    echo -e "${RED}ERROR: Codex Worker 目录不存在: $WORKER_DIR${NC}"
    echo -e "${YELLOW}提示: 先运行 bootstrap-worker.sh --target codex 初始化${NC}"
    exit 1
fi

BOOT_PROMPT="$WORKER_DIR/_boot-prompt.md"
if [[ ! -f "$BOOT_PROMPT" ]]; then
    echo -e "${RED}ERROR: _boot-prompt.md 不存在: $BOOT_PROMPT${NC}"
    echo -e "${YELLOW}提示: bootstrap-worker.sh 应已生成此文件${NC}"
    exit 1
fi

# 检查 codex CLI 可用
if ! command -v codex &>/dev/null; then
    echo -e "${RED}ERROR: codex CLI 未安装或不在 PATH 中${NC}"
    echo -e "${YELLOW}安装: brew install codex${NC}"
    exit 1
fi

CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
echo -e "${CYAN}=== Synapse Codex Worker Launcher ===${NC}"
echo -e "  Worker dir : ${GREEN}$WORKER_DIR${NC}"
echo -e "  Boot prompt: ${GREEN}$BOOT_PROMPT${NC}"
echo -e "  Codex      : ${GREEN}$CODEX_VERSION${NC}"
echo -e "  Dry run    : ${YELLOW}$DRY_RUN${NC}"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}── 以下是将要注入 codex exec 的 boot prompt ──${NC}"
    echo ""
    cat "$BOOT_PROMPT"
    echo ""
    echo -e "${YELLOW}── 实际启动命令（去掉 --dry-run 执行）──${NC}"
    echo "  cd $WORKER_DIR && codex exec ${CODEX_ARGS[*]} - < _boot-prompt.md"
    exit 0
fi

# ── 构建 prompt：boot prompt 已包含「读 SKILL.md → 设 CronCreate → 工作循环」完整指令 ──
# SKILL.md 不在此嵌入——Codex 可从文件系统读取（boot prompt 中已指明路径）

# ── 启动 Codex ──
echo -e "${GREEN}启动 Codex Worker...${NC}"
echo -e "${CYAN}提示: 按 Ctrl+C 退出 · Worker 启动后可最小化窗口${NC}"
echo ""

cd "$WORKER_DIR"

# 使用 stdin 传入 boot prompt（codex exec `-` 从 stdin 读取初始 prompt）
codex exec "${CODEX_ARGS[@]}" - < "$BOOT_PROMPT"

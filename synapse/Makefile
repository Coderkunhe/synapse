.PHONY: help check check-all check-docs check-batch-numbers check-lessons check-comments check-tests check-types check-line-count check-contracts check-violations check-schema-audit check-discussions check-plan-mode check-fresh-eyes check-gate-tests check-doc-curl check-db-consistency check-agent-worker-consistency check-issue-numbers check-hooks check-frontend setup hooks db-init db-sync contracts-baseline

# ─── Synapse Makefile ──────────────────────────────────────
# 精简版 — 只包含本项目适用的 target。
# 来源: P5-B12，从 GlassCortex 制度审计 P0 前三项派生。
#
# 用法: make help

.DEFAULT_GOAL := help

# ── 入口 ──────────────────────────────────────────────────

help: ## 显示所有可用 target
	@echo "Synapse Makefile"
	@echo ""
	@echo "  门禁:"
	@echo "    make check               完整门禁（docs + batch + lessons + comments + tests）"
	@echo "    make check-all           全栈门禁（check + 前端 lint + 前端 typecheck）"
	@echo "    make check-docs          文档门禁"
	@echo "    make check-batch-numbers Batch 编号连续性检查"
	@echo "    make check-lessons       经验编号连续性检查（LRN 防呆）"
	@echo "    make check-comments      代码注释质量扫描"
	@echo "    make check-line-count    文件行数上限检查（>800 行拦截）"
	@echo "    make check-contracts     API 契约快照对比（breaking change 检测）"
	@echo "    make check-violations   违纪门禁（复发检测 + 防呆统计 + 回顾逾期阻断）"
	@echo "    make check-shared-modules  共享模块治理（消费者统计 + Risk Assessment 覆盖）"
	@echo "    make check-phase         Phase 治理门禁（Phase 声明+编号+规模+隔离）"
	@echo "    make check-schema-audit Schema Audit 继承一致性检查"
	@echo "    make check-discussions 讨论→登记管道（孤儿 D-ID 检测，警告级）"
	@echo "    make check-plan-mode   Plan Mode 入口检测（V-003 防呆，警告级）"
	@echo "    make check-fresh-eyes  Fresh-eyes 契约层复审门禁（G-007，警告级）"
	@echo "    make check-gate-tests  防呆有效性验证（V-020/V-021/G-007 gate tests）"
	@echo "    make check-doc-curl    onboarding.md curl 块结构校验（S-024b，首部署警告级）"
	@echo "    make check-agent-worker-consistency  Agent→Worker 术语一致性扫描（S-023，警告级）"
	@echo "    make check-issue-numbers  议题编号自洽校验（G26，警告级）"
	@echo "    make check-db-consistency  DB ↔ docs 一致性检查（警告级）"
	@echo "    make check-role-isolation  角色隔离观测门禁（ADR-006 S1-S3/S7，警告级）"
	@echo "    make check-hooks         Git hooks 完整性检测（V-028 防呆 — 新 clone 后必检）"
	@echo "    make check-quality-gate  质量三板斧机械门禁（GAP-2 — 代码变更需自检文件）"
	@echo "    make check-checkpoint-freshness  Checkpoint 新鲜度门禁（GAP-3 — 今日更新检查）"
	@echo "    make check-batch-sequence  批次顺序机械校验（GAP-4 — track 指针一致性）"
	@echo "    make check-tests         测试门禁（pytest）"
	@echo "    make check-types         Python 类型检查（mypy — V-004 防呆）"
	@echo "    make check-frontend      前端门禁（oxlint + tsc typecheck）"
	@echo ""
	@echo "  基础设施:"
	@echo "    make setup       首次初始化（venv + deps + db + hooks）"
	@echo "    make hooks       安装 git hooks"
	@echo "    make db-init     初始化数据库（alembic upgrade head）"
	@echo "    make db-sync     从 DB 导出 Batch 状态到 docs/batch-status.md"
	@echo ""

check: check-hooks check-docs check-batch-numbers check-lessons check-comments check-line-count check-contracts check-phase check-violations check-shared-modules check-schema-audit check-discussions check-plan-mode check-fresh-eyes check-gate-tests check-doc-curl check-db-consistency check-agent-worker-consistency check-issue-numbers check-role-isolation check-batch-sequence check-quality-gate check-checkpoint-freshness check-types check-tests ## 完整门禁
	@echo ""
	@echo "✅ 门禁全部通过"

check-all: check check-line-count check-frontend ## 全栈门禁（Python + 前端）
	@echo ""
	@echo "✅ 全栈门禁全部通过"

check-docs: ## 文档门禁（新鲜度 + 测试骨架 + 计划清理 + L5 间隔）
	@bash tools/check-docs.sh

check-batch-numbers: ## Batch 编号连续性检查
	@bash tools/check-batch-numbers.sh

check-lessons: ## 经验编号连续性检查（LRN 防呆）
	@bash tools/check-lessons.sh

check-comments: ## 代码注释质量扫描
	@bash tools/check-comments.sh

check-tests: ## 运行 pytest
	@pytest -v --tb=short 2>&1 || { echo "❌ 测试未通过"; exit 1; }
	@echo "✅ 测试通过"

check-types: ## Python 类型检查（mypy — V-004 防呆，首部署警告级）
	@echo "--- Python mypy 类型检查 ---"
	@MYPY_OUT=$$(python3 -m mypy --config-file mypy.ini src/ 2>&1); EXIT=$$?; \
	echo "$$MYPY_OUT"; \
	ERRORS=$$(echo "$$MYPY_OUT" | grep -cE '^src/.*error:' || true); \
	if [ $$EXIT -ne 0 ]; then \
		echo ""; \
		printf "  ┌──────────────────────────────────────────────────────────────┐\n"; \
		printf "  │  ⚠️  mypy 发现 %s 个类型错误（基线: ~51，首部署警告级）          │\n" "$$ERRORS"; \
		printf "  ├──────────────────────────────────────────────────────────────┤\n"; \
		printf "  │  V-004 防呆已上线 — 当前为警告模式，不阻断 commit               │\n"; \
		printf "  │  目标: 逐步修复基线错误 → 归零后升级为阻断 (exit 1)            │\n"; \
		printf "  │  Action: 每次 Batch 修复若干 → 错误数只降不增                   │\n"; \
		printf "  └──────────────────────────────────────────────────────────────┘\n"; \
		echo ""; \
	fi
	@echo "✅ check-types 完成"

check-line-count: ## 文件行数上限检查（>800 行拦截）
	@bash tools/check-line-count.sh

check-contracts: ## API 契约快照对比（breaking change 检测）
	@bash tools/check-contracts.sh

check-phase: ## Phase 治理门禁（Phase 声明+编号+规模+隔离）
	@bash tools/check-phase.sh

check-violations: ## 违纪门禁（复发检测 + 防呆统计 + 回顾逾期阻断）
	@bash tools/check-violations.sh

check-shared-modules: ## 共享模块治理（消费者统计 + Risk Assessment 覆盖扫描）
	@echo "=== L2f Shared Module Governance ==="
	@PYTHONPATH=. python3 tools/check_shared_modules.py
	@echo "✅ check-shared-modules 完成"

check-schema-audit: ## Schema Audit 继承一致性检查（所有 Response 类必须继承 AuditFields）
	@PYTHONPATH=. python3 tools/check-schema-audit.py

check-discussions: ## 讨论→登记管道（孤儿 D-ID 检测，警告级，不阻断）
	@bash tools/check-discussions.sh

check-plan-mode: ## Plan Mode 入口检测（V-003 防呆，警告级，首部署不阻断）
	@bash tools/check-plan-mode.sh

check-fresh-eyes: ## Fresh-eyes 契约层复审门禁（G-007，警告级，首部署不阻断）
	@bash tools/check-fresh-eyes.sh

check-gate-tests: ## 防呆有效性验证 — 为 V-020/V-021/G-007 gate scripts 各写 trigger test（P100-B27）
	@echo "--- Gate Tests (V-020/V-021/G-007) ---"
	@python3 -m pytest tests/gates/ -v --tb=short 2>&1 || { echo "❌ Gate tests 未通过"; exit 1; }
	@echo "✅ Gate tests 通过"

check-doc-curl: ## onboarding.md curl 块结构校验（S-024b，首部署警告级）
	@echo "--- Doc Curl 校验 (S-024b) ---"
	@bash tools/check-doc-curl.sh 2>&1 || { echo "⚠️  Doc curl 校验发现问题（首部署警告级，不阻断）"; exit 0; }
	@echo "✅ Doc Curl 校验通过"

check-agent-worker-consistency: ## Agent→Worker 术语一致性扫描（S-023，警告级）
	@bash tools/check-agent-worker-consistency.sh

check-issue-numbers: ## 议题编号自洽校验（G26 · CLAUDE.md ↔ tracks ↔ master-backlog 三方对齐，警告级）
	@bash tools/check-issue-numbers.sh

check-db-consistency: ## DB ↔ docs 一致性检查（警告级）
	@echo "--- DB ↔ docs 一致性 ---"
	@if [ ! -f "data/synapse.db" ]; then \
		echo "⏭️  DB 不存在，跳过一致性检查（运行 make db-init 初始化）"; \
	else \
		PYTHONPATH=. python3 tools/seed-synapse-project.py --check 2>&1; EXIT=$$?; \
		if [ $$EXIT -eq 1 ]; then \
			echo ""; \
			echo "⚠️  DB ↔ docs 不一致 — 运行 make db-sync 同步"; \
		elif [ $$EXIT -eq 2 ]; then \
			echo "⚠️  一致性检查无法执行（项目未创建或文档缺失）— 运行 make db-sync 生成"; \
		fi; \
	fi
	@echo "✅ check-db-consistency 完成"

check-role-isolation: ## 角色隔离观测门禁（ADR-006 S1-S3/S7，警告级，不阻断）
	@bash tools/check-role-isolation.sh

check-hooks: ## Git hooks 完整性检测（V-028 防呆 — 新 clone/迁库后首次 make check 即可发现）
	@bash tools/check-hooks.sh

check-quality-gate: ## 质量三板斧机械门禁（GAP-2 · G-030 — 代码变更需自检文件）
	@bash tools/check-quality-gate.sh

check-checkpoint-freshness: ## Checkpoint 新鲜度门禁（GAP-3 · G-031 — memory/active 今日更新检查）
	@bash tools/check-checkpoint-freshness.sh

check-batch-sequence: ## 批次顺序机械校验（GAP-4 · G-032 — 验证 track 文件指针一致性 · commit-msg hook 做完整校验）
	@bash tools/check-batch-sequence.sh --track-only

contracts-baseline: ## 生成/更新 API 契约基线快照
	@PYTHONPATH=. .venv/bin/python tools/_gen_contracts_baseline.py

check-frontend: ## 前端门禁（oxlint + tsc typecheck）
	@echo "--- 前端 lint ---"
	@cd frontend && npm run lint 2>&1 || { echo "❌ 前端 lint 未通过"; exit 1; }
	@echo "✅ 前端 lint 通过"
	@echo "--- 前端 typecheck ---"
	@cd frontend && npx tsc -b 2>&1 || { echo "❌ 前端 typecheck 未通过"; exit 1; }
	@echo "✅ 前端 typecheck 通过"

# ── 基础设施 ──────────────────────────────────────────────

setup: hooks db-init ## 首次初始化
	@if [ ! -d ".venv" ]; then \
		python3 -m venv .venv && \
		.venv/bin/pip install -r requirements.txt && \
		echo "✅ venv 创建完成"; \
	else \
		echo "⏭️  .venv 已存在，跳过"; \
	fi

hooks: ## 安装 git hooks（pre-commit + commit-msg + post-commit）
	@if [ ! -f "../.git/hooks/pre-commit" ]; then \
		ln -sf ../../synapse/tools/pre-commit ../.git/hooks/pre-commit && \
		echo "✅ pre-commit hook 已安装"; \
	else \
		echo "⏭️  pre-commit hook 已存在，跳过"; \
	fi
	@if [ ! -f "../.git/hooks/commit-msg" ]; then \
		cp tools/check-commit-prefix.sh ../.git/hooks/commit-msg && \
		chmod +x ../.git/hooks/commit-msg && \
		echo "✅ commit-msg hook 已安装"; \
	else \
		echo "⏭️  commit-msg hook 已存在，跳过"; \
	fi
	@if [ ! -f "../.git/hooks/post-commit" ]; then \
		cp tools/post-commit.sh ../.git/hooks/post-commit && \
		chmod +x ../.git/hooks/post-commit && \
		echo "✅ post-commit hook 已安装"; \
	else \
		echo "⏭️  post-commit hook 已存在，跳过"; \
	fi

db-init: ## 初始化数据库
	@if [ ! -f "data/synapse.db" ]; then \
		.venv/bin/alembic upgrade head && \
		echo "✅ 数据库已初始化"; \
	else \
		echo "⏭️  数据库已存在，跳过"; \
	fi

db-sync: ## 从 DB 导出 Batch 状态到 docs/batch-status.md
	@PYTHONPATH=. python3 tools/seed-synapse-project.py --sync

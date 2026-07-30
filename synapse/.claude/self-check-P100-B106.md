# P100-B106 Self-Check — 测试/生产一致性 + 门禁内容诚实度升级

## 编码前 Scout（三问）

- [x] **数据流拉通**：FK PRAGMA 需在 engine 创建后为每个连接启用；func.now → _utcnow 需从 base.py 导入；DateTime(timezone=True) 仅改 TimestampMixin（其他 DateTime 列留后批）；quality-gate 升级从 WARNING→ERROR；l5-reset 新增第 4 关需在 SCRIPT_DIR 定义后执行；CI workflow 在 repo root .github/ 下；Makefile check-db-migration 需绕过 JWT_SECRET 校验
- [x] **同类参照**：FK PRAGMA 模式参照 SQLAlchemy 官方 docs（event.listens_for + sync_engine.connect）；_utcnow 已存在于 base.py（由 TimestampMixin 使用）；DateTime(timezone=True) 已有 Worker.last_heartbeat_at 先例；quality-gate 复用现有 grep 模式；l5-reset 复用 3 关框架；CI 参照 GitHub Actions 标准 Python workflow
- [x] **用户一句话**：SQLite FK 启用后测试爆出 648→37 失败——全部是 FK 约束暴露的既有数据完整性 bug（Event.team_id="" 等），B106 修核心路径（auth+seed），其余→B107

## 编码后自检（四问）

- [x] **乐观路径**：test_auth_email 22/22 全绿 · 全量 611/648 passed · FK PRAGMA 正确拦截违规操作 · quality-gate 脚本语法验证通过 · CI workflow 结构完整
- [x] **边界状态**：37 failing tests 均为 Event.team_id="" FK 违规或测试 fixture 假 ID——非本次变更引入的回归，是 FK PRAGMA 暴露的既有 bug。auth_service flush 修复消除 refresh_token FK 时序问题。conftest Worker.user_id=None 修复消除 seed fixture FK 违规。
- [x] **对比同类**：所有变更遵循项目现有模式——FK PRAGMA 用标准 SQLAlchemy event listener；时间源统一用已有 _utcnow()；quality-gate 升级保持与现有门禁风格一致；CI workflow 用标准 GitHub Actions 双矩阵
- [x] **变更清单口播**：9 files changed (+ 1 new CI workflow) — src/db.py, src/models/event.py, src/models/token_usage.py, src/models/base.py, src/services/auth_service.py, tests/conftest.py, tools/check-quality-gate.sh, tools/l5-reset.sh, Makefile, .github/workflows/ci.yml (new)

> B107 交棒：Event.team_id 改为 nullable + 系统事件 team_id=None + test fixture 假 ID 修复 + 目标 648/648 零回归

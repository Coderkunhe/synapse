# D4 Dogfood — B36 Codex 混搭执行状态

> God's-eye 在会话中逐步更新。

## 阶段

| Phase | 状态 | 备注 |
|:---|:--:|:---|
| A: God's-eye 环境就位 | ✅ | Phase 0: 清理旧目录+plist · 3 独立 git clone · 3 Worker 注册 · Skill 生成 |
| B: O 创建 Task 链 | ✅ | 3 Task 创建 + promote + assign · 依赖链正确 |
| C: BA + BB 自主循环 | ✅ | BA 完成 T1+T3 · BB 2x submit 但 evidence 格式不匹配 |
| D: 验收 | ⚠️ | T1✅ T3✅ T2❌(2x rejected) |

## 终态

| Task | Worker | 客户端 | 结果 |
|:---|:---|:---|:---|
| Task 1 后端 API | BA | Claude Code | ✅ completed |
| Task 2 前端可视化 | BB | Codex CLI | ❌ 2x rejected (evidence 格式) |
| Task 3 集成验证 | P11 旧 Worker | Claude Code | ✅ completed (污染) |

## B36 发现 (13 PFLs)

| PFL | 发现 | 严重度 |
|:---|:---|:--:|
| PFL-131 | SessionStart hook 未生成 _task-current.md | 🔴 |
| PFL-132 | Codex CLI 5min 内 offline · 无 daemon | 🟡 |
| PFL-133 | God's-eye 违规干预 | 🔴 |
| PFL-134 | Codex offline → Task 分配落空 | 🔴 |
| PFL-135 | _task-current.md 缺失对 Claude/Codex 不对称影响 | 🔴 |
| PFL-136 | 授权审批管道阻塞 Builder | 🔴 |
| PFL-137 | 审批 UI 全量展示过期请求 | 🟡 |
| PFL-138 | Phase 0.5 role=member 而非 builder | 🔴 |
| PFL-139 | ProjectRoleAssign 无 role 校验 | 🔴 |
| PFL-140 | 授权过期用 alert 而非模态窗 | 🟡 |
| PFL-141 | Codex CLI 需人工 prompt 才启动 | 🔴 |
| PFL-142 | 旧 P11 Worker 越界污染 B36 | 🔴 |
| PFL-143 | Codex evidence 未落库 · JSON 格式不匹配 | 🔴 |

---

## B48 Dogfood — PFL-151 SPoF 三层防御

> 暗号: `p12-b48-dogfood` · 2026-08-08 · plan: `docs/plans/p12-b48-dogfood.md`

### 就位状态

| 组件 | 状态 | 详情 |
|:---|:--:|:---|
| Server | 🟢 | port 8001, all reapers running, verify_escalated=0 |
| B46+B47 commit | ✅ | `c272744` — notify + escalate, 15 files, +622/-14 |
| Tests | ✅ | 719/719 pass, 10/10 B46+B47 tests pass |
| Dogfood gate | ✅ | `dogfood-active` activated |
| O Worker | 🟢 | `ag_019fe05e8cde755c` · orchestrator · active · hb=08:12 |
| BA Worker | 🟢 | `ag_019fe05e8dc27d64` · builder · active · hb=08:12 |
| BB Worker | ⬜ | optional Codex — skipped for B48 simplicity |
| Project | 🟢 | `prj_019fe05f3f2d7a4a` · B48 Dogfood v2 |

### SPoF 探针

| 探针 | 目标 | 状态 |
|:--:|------|:--:|
| 1 | L1 notify — Builder → O WS push | ⬜ |
| 2 | L2 escalate — Server → @Human + WS | ⬜ |
| 3 | L3 self-health — O CronCreate provider-aware | ⬜ |
| 4 | End-to-end cascade — O dead → defense fires | ⬜ |

### V-Criteria

| # | 标准 | 状态 |
|:--:|------|:--:|
| V1 | notify 返回 200 + notified_orchestrator_ids 非空 | ⬜ |
| V2 | conversation 出现 @Orchestrator 消息 | ⬜ |
| V3 | O 收到 notify 后恢复验收 | ⬜ |
| V4 | task.escalated 事件可见 | ⬜ |
| V5 | conversation 出现 @Human escalation 消息 | ⬜ |
| V6 | health verify_escalated > 0 | ⬜ |
| V7 | escalation cooldown 生效 | ⬜ |
| V8 | O heartbeat 在 300s 窗口内 | ⬜ |
| V9 | offline_detected 计数器正常 | ⬜ |
| V10 | 心跳 monitor 区分 Claude/Codex 超时 | ⬜ |
| V11 | 三层中至少两层被验证 | ⬜ |
| V12 | Task 不永久卡死在 in_verification | ⬜ |
| V13 | 零 God's-eye src/ 变更 | ⬜ |

### 发现

| PFL | 发现 | 严重度 |
|:---|:---|:--:|

(待狗粮执行后填充)

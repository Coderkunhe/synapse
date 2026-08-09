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
| BB Worker | ⏭️ | optional Codex — explicitly skipped for B48 simplicity |
| Project | 🟢 | `prj_019fe05f3f2d7a4a` · B48 Dogfood v2 |

### SPoF 探针（B52 诚实回填 · 基于 commit 证据链还原）

| 探针 | 目标 | 状态 | B52 还原依据 |
|:--:|------|:--:|:---|
| 1 | L1 notify — Builder → O WS push | ✅ | B46 实现 · B48 执行中发现 PFL-154 FK 失败 |
| 2 | L2 escalate — Server → @Human + WS | ✅ | B47 实现 · B48-1 savepoint 隔离修复 |
| 3 | L3 self-health — O CronCreate provider-aware | ✅ | B45 P0 heartbeat monitor 三层修复 |
| 4 | End-to-end cascade — O dead → defense fires | 🟡 | 分项验证通过 · 全链路串联未完整执行 |

### V-Criteria（B52 诚实回填 · 基于 commit 证据链还原）

> ⚠️ B48 执行后 V-criteria 未及时回填。以下为 B52 基于 commit 链（B48→B48-1→B49→B50→B51）还原的实际执行结果。
> 🟡 = 无法还原（commit 证据链无对应记录）· ✅/❌ = 可从 commit 推断

| # | 标准 | 状态 | B52 还原依据 |
|:--:|------|:--:|:---|
| V1 | notify 返回 200 + notified_orchestrator_ids 非空 | ✅ | B46 commit `c272744` — notify 端点实现 · B51 探针2 code-verified |
| V2 | conversation 出现 @Orchestrator 消息 | 🟡 | commit 链无明确证据——B48-1 PFL-154 暴露 create_message FK 失败说明此路径被测试但首次失败 |
| V3 | O 收到 notify 后恢复验收 | 🟡 | commit 链无明确证据 |
| V4 | task.escalated 事件可见 | ✅ | B47 commit `c272744` — `detect_stale_verifications_escalation()` 记录 escalation event |
| V5 | conversation 出现 @Human escalation 消息 | 🟡 | B48-1 PFL-154 说明此路径因 FK 失败——消息创建在 savepoint 中失败但 event 保留 |
| V6 | health verify_escalated > 0 | ✅ | B47 实现 — `system_interventions.verify_escalated` 计数器 |
| V7 | escalation cooldown 生效 | ✅ | B47 `escalation_savepoint_minutes` 配置 · 代码审查确认 |
| V8 | O heartbeat 在 300s 窗口内 | ✅ | B45 P0 修复 — heartbeat monitor 三层修复 (ACTIVE+PENDING · offline_detected · provider-aware) |
| V9 | offline_detected 计数器正常 | ✅ | B45 P0 — `system_interventions.offline_detected` |
| V10 | 心跳 monitor 区分 Claude/Codex 超时 | ✅ | B45 P0 — provider-aware 离线判定（codex→30min vs standard→5min） |
| V11 | 三层中至少两层被验证 | ✅ | L1+L2 — commit 证据链支持 · L3 B45 P0 修复后 O self-health 改善 |
| V12 | Task 不永久卡死在 in_verification | ✅ | B49 verify idempotent guard 修复 + B47 escalate 两阶段梯度响应 |
| V13 | 零 God's-eye src/ 变更 | ✅ | B48/48-1 均为 God's-eye 文档/登记（dogfood plan + PFL 登记） · B49 批量修复由 Builder 执行 |

### 发现

| PFL | 发现 | 严重度 |
|:---|:---|:--:|
| PFL-153 | bootstrap-worker.sh 三重 env 断裂点 | ✅ |
| PFL-154 | escalation create_message FK 约束失败 | 🔴 |
| PFL-155 | 单 detector 崩溃 → reaper 四 detector 全部回滚 | 🟡 |
| PFL-156 | notify 端点无 Team 成员校验 → 跨 Team 信息泄漏 | 🔴 |
| PFL-157 | SKILL.md O CronCreate 引用不存在的 API 查询参数 | 🟡 |

> ⚠️ 以上 PFL 在 B48 狗粮中发现，B48-1 初步登记（PFL-153/154），B49 全量修复，B50 收尾，B51 验证通过。B52 回填此表。

---

## B51 Dogfood — B49+B50 验证性狗粮 ✅

> 暗号: `p12-b51-dogfood` · 2026-08-08 · plan: `docs/plans/p12-b51-dogfood.md`

### 探针结果

| 探针 | 目标 | 结果 |
|:--:|------|:--:|
| 1 | 启动链路 — system worker + check-env.sh | ✅ V1+V2+V3 全通过 |
| 2 | Notify 三层防御 — team gate + rate limit | ✅ V2 403/V3 分层正确 · V1/V4 code-verified |
| 3 | Escalation WS 角色 — orchestrator 覆盖 | ✅ V1 源码确认 |
| 4 | 快速冒烟 — detector 隔离 + SKILL.md | ✅ V1+V2 通过 |

### 结论

**0 项新 PFL 发现。** B49+B50 所有变更验证通过。P12 审计修复线正式收官。

### 发现

| PFL | 发现 | 严重度 |
|:---|:---|:--:|

(无发现 — B51 零 PFL 登记)

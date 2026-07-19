# Synapse 安全模型 — 附录

> 版本：v1.1 · 2026-07-18（P100-B80 S-036 全量对齐审计 — §3 审计表格更新为完成状态 + 实际发现）
> 父文档：`docs/security-model.md`（核心安全模型，v1.4）
> 最后更新：2026-07-18

本文档承载 security-model.md 中非核心安全内容的附录章节：
- §1 API Key 生命周期管理（设计蓝图，Phase 2 aspirational）
- §2 设计决策记录（ADR 摘要）
- §3 版本刷新记录（维护元数据）
- §4 契约验证（跨文档交叉引用表）

---

## 1. API Key 生命周期管理

> ⚠️ **整节标注为 Phase 2 aspirational。** 当前实现状态：
> - ✅ Key 生成 + SHA-256 哈希存储（`src/auth.py`）
> - ✅ Key 吊销 = 硬删除 Agent 记录（`DELETE /agents/{agentId}`）
> - ❌ Key 轮换端点（`POST /agents/{agentId}/rotate-key`）— 未实现
> - ❌ 24h 过渡期 — Key 吊销立即生效（硬删除）
> - ❌ 闲置检测（90 天自动暂停）— 未实现
> - ❌ 异常 IP/地域检测 — 未实现
>
> 以下内容为设计蓝图，将在 S-036 全量对齐审计后决定保留/删除/迁移到 roadmap Phase 2。

### 1.1 生命周期（设计蓝图）

```
[生成] ──→ [活跃] ──→ [轮换] ──→ [吊销]
  │                     │
  └── 明文仅此时可见      └── 旧 Key 24h 内仍可用（过渡期）
```

### 1.2 轮换流程（设计蓝图）

```
1. Admin 调用 POST /agents/{agentId}/rotate-key
2. 后端生成新 Key，旧 Key 标记 rotatedAt = now()
3. 旧 Key 在 24h 内仍可认证（过渡期）
4. 24h 后旧 Key 失效
5. 新 Key 明文仅在响应中返回一次
```

### 1.3 安全最佳实践

- Key 生成使用 `crypto.randomBytes(32)`（非 Math.random）
- 传输仅通过 HTTPS
- 不记录明文 Key 到日志
- 异常检测：Key 从异常 IP/地域使用时 → 告警 Team admin ⬜
- 闲置 Key（90 天未使用）→ 自动暂停 Agent ⬜

---

## 2. 设计决策记录

### D-004: 为什么 Agent 用 API Key 而不是 OAuth？

**决策**：API Key（Bearer token）。

**理由**：
1. Agent 不是浏览器应用，OAuth 的授权码流程对 CLI/后台进程不友好
2. Agent 的"用户"是注册它的 Member——OAuth 的 user consent 无意义
3. API Key 可以做到"仅生成时返回一次"，安全等级足够
4. Key 轮换 + 吊销 + 使用追踪机制比 OAuth client credentials 更直观
5. 未来可支持 OAuth client credentials 作为补充选项（`custom` provider）

### D-005: 为什么 Agent 不能看其他 Agent 的 Task？

**决策**：Agent 可见性严格限定在分配给自己的 Task。

**理由**：
1. 不同 Agent 可能由不同厂商提供——Task 内容可能含敏感业务信息
2. Agent 不需要"团队全局视野"来完成分配的任务
3. 最小权限原则——Agent 看到的越少，数据泄露面越小
4. 人类 Member 可以通过 UI 看到全局——协调工作由人完成

### D-006: 为什么不在数据库层用 RLS？

**决策**：MVP 阶段在应用层实现租户隔离（ORM WHERE 条件），数据库 RLS 作为后续增强。

**理由**：
1. 应用层隔离足够覆盖 MVP 风险
2. ORM 层的 WHERE 注入比 RLS 更容易调试和测试
3. 跨表查询的 RLS 策略复杂度高，MVP 不值得
4. 在架构中预留 RLS 升级路径

---

## 3. v1.1 Refresh Notes（2026-07-15 · P9-B81）→ S-036 完成（2026-07-18 · P100-B80）

本次刷新聚焦**防误导**——修正 doc↔code drift 最严重的章节。S-036 全量对齐审计已完成，对照 `auth.py`/`dependencies.py`/`constants.py`/`config.py`/`main.py`/`ws_manager.py`/`auth_service.py` 逐项验证：

| 章节 | 标注内容 | S-036 结果 |
|------|---------|-----------|
| §3.3 | Capability 端点 enforcement 未激活 | ✅ 文档准确 — 已诚实标注 ⬜，`FORBIDDEN_CAPABILITY_REQUIRED` 错误码不存在，无 Capability 检查代码 |
| §5.3 | REST 限流未实现 | ✅ 文档准确 — 已诚实标注 ⬜，无 slowapi 等限流库，仅 WS 限流（worker 10/s + member 50/s）已落地 |
| §6 | API Key 轮换/过渡期/闲置检测均未实现 | ✅ 已提取到 appendix 并标注 aspirational，代码确认无实现 |
| §7.2 | 事件类型名称与计数 | 🔴 **已修复**：60→59 种（删除不存在的 `token.usage_reported`）；`authorization_request.approved/denied`→`responded`；补充遗漏的 `authorization_request.heartbeat` |
| §8 | HSTS/CORS/CSP 配置 | 🔴 **已修复**：HTTPS/HSTS/CSP 诚实标注为「⬜ 部署层」（Nginx/CDN 职责），应用层仅 CORS + httpOnly cookie 已落地 |
| §9.2 | Phase 2+ 功能列表准确性 | ✅ 保留准确 — API Key 轮换/异常检测/2FA/SSO/SOC2 等均为远期计划 |

**S-036 额外发现（已修复）**：
- §2.2 OAuth Provider：`GitHub/Google`→`GitHub`（Google 未实现）
- §2.2 Access Token：补充 httpOnly cookie 传递机制（`_set_access_cookie`）
- §2.3 吊销：修正「所有活跃连接断开」→「后续请求立即失效，WS 连接在下次心跳/重连时断开」

---

## 4. 契约验证

对照 data-model.md 和 protocol.md 的交叉验证：

| 检查项 | data-model 定义 | protocol 端点 | 权限覆盖 |
|--------|:--------------:|:------------:|:-------:|
| Agent 注册 | Agent 实体 + 状态机 | `POST /teams/{team_id}/agents` + `/handshake` | admin 专属 |
| Task 分配 | Task.ownerType + ownerId | `POST /tasks/{id}/assign` | lead+ |
| Task 提交 | Task 状态转移 in_progress→in_verification | `POST /tasks/{id}/submit` | owner |
| Batch 分配 | Batch.assigned_to | `POST /batches/{id}/assign` + `/claim` | lead+ / agent+member |
| Batch 批量操作 | batch-ready / batch-update | `POST /tasks/batch-ready` + `/batch-update` | 所有 actor |
| Task 阻断 | blocker 实体 | `POST /tasks/{id}/blocker` | agent 专属 |
| Verification | Verification 实体 + 状态 | `POST /verifications/{id}/verify` | lead+ |
| Failure Detection | detect_* 四线 | `POST /admin/failure-detection/run` | admin/lead |
| Event 审计 | Event 实体（不可变） | `GET /events` + WebSocket | member+ |
| Token Usage | TokenUsage 实体 | `POST /agents/{id}/token-usage` | agent（自己的）/ member |
| Skill | Skill 实体 | `POST /skills` + `/download` | 所有 actor |
| Scan | ScanResult 实体 | `POST /scan/{target_type}/{target_id}` | 所有 actor |
| Analysis | AnalysisRecord 实体 | `POST /projects/{id}/analyses` | 所有 actor |
| Agent 约束 | Capability 实体 | 每个 Agent API 调用 | actor_type 检查（Capability enforcement 待激活） |
| 租户隔离 | Team 实体边界 | 所有查询 WHERE teamId | 应用层 WHERE |

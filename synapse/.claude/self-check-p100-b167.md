# P100-B167 自检 — 授权列表过期修复（前端删 isExpired 残留 + 后端 respond 过期硬门禁）

> 批号: P100-B167 · 性质: 治理批（Builder 直接改 src/ + frontend/ · 无 dogfood 模式）· 日期: 2026-09-27
> 根因: 过期审批请求仍显示批准/拒绝按钮 —— 两层：① 前端 Approvals.tsx 的 isExpired 是 P12-B39 加后端 include_expired=false 过滤前的死代码，且顶层 AuthRequestModal 引用嵌套在 Approvals 内的 isExpired（作用域不可达 → 点开历史条目 ReferenceError）② 后端 respond_to_request 只查 status != pending 不查 expires_at（30s reaper 窗口内已过期仍 pending 可被 stale 客户端批准）。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 授权请求生命周期：create 写 expires_at = now + ttl → list_auth_requests(status=pending) 默认 include_expired=false 过滤 expires_at > now → _auth_expiry_reaper 每 30s 把 pending+expired 翻 expired → respond_to_request 审批。缺口在 respond 端：只守卫 status 不守卫 expires_at，前端 Pending tab 的 isExpired 死代码反而在 30s 窗口内"半保护"（置灰按钮），删掉后必须由后端硬门禁兜底。
- [x] **同类参照** — expire_stale_requests 用 `AuthorizationRequest.expires_at < now` 做过期判定（SQL 层）；heartbeat/report_execution 用 `record.status != pending/approved` 做状态守卫抛 InvalidStateTransition；InvalidStateTransition 签名固定 (entity_type, entity_id, from_status, to_status) 无 message kwarg → 过期用 ConflictError(code=AUTHORIZATION_REQUEST_EXPIRED) 更语义化（与 create 的 TOO_MANY_PENDING_REQUESTS 同款）。B137 记 SQLite 返回 naive datetime → 比较前 replace(tzinfo=utc) 归一。
- [x] **用户一句话** — 用户在 Web UI 审批列表里点开一个已过期（但 reaper 还没翻状态）的请求，批准被后端明确拒绝（409 AUTHORIZATION_REQUEST_EXPIRED），而不是静默成功或前端崩溃；历史条目 modal 能正常打开不再 ReferenceError。

## 编码后自检（四问）

- [x] **乐观路径** — pending 未过期请求 → respond_to_request 正常批准/拒绝（test_approve_pending_request / test_deny_pending_request 不回归）；前端 Pending tab 不再渲染 Expired 标签、按钮正常可点。
- [x] **边界状态** — 已过期仍 pending（expires_at 过去 · status 仍 pending）→ raise ConflictError AUTHORIZATION_REQUEST_EXPIRED（新测试 test_cannot_respond_expired_pending_request）；已 reaper 翻 expired 的 → 仍走原 InvalidStateTransition；SQLite naive / PG aware 两路时区归一守卫；expires_at 非空（model nullable=False）。
- [x] **对比同类** — 复用 expire_stale_requests 的 `expires_at < now` 判定 + replace(tzinfo=utc) 归一（B137 先例）；ConflictError 与 create 的流控错误同款；前端删死代码对齐 P12-B39 后端过滤后的现状，不新造逻辑。
- [x] **变更清单口播** — 3 代码文件 ≤8 上限：authorization_service.py(+硬门禁) · Approvals.tsx(-isExpired 死代码+modal 死引用+import) · test_authorization_service.py(+1) · 1013 tests（1012 基线 + 1 新增，零回归）· 前端 tsc 0 新增错误。

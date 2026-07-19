# P8 Protocol Contract — Creator ↔ Worker 消息契约

**版本**: 1.0.0
**状态**: P8 前置步骤（B1 前完成）
**日期**: 2026-07-05
**定位**: Creator 和 Worker 之间所有通信的契约定义。P8 B1→B7 的每个端点必须引用本文中的对应消息定义。

---

## 一、协议消息总表

| # | 消息 | 方向 | 触发场景 | Payload |
|:--:|------|:--:|------|------|
| 1 | `claim` | Worker → System | Worker 认领 Task 或 Batch | `{worker_id, batch_id?, task_id?, message_id}` |
| 2 | `claim_ack` | System → Worker | 系统确认认领成功 | `{task_id, lease_expires_at, batch_context?}` |
| 3 | `submit` | Worker → System | Worker 提交 Task 产出 | `{task_id, worker_id, output, evidence[], message_id}` |
| 4 | `verify` | Creator → System | Creator 验收判定 | `{task_id, verdict, criterion_results[], notes?, message_id}` |
| 5 | `reject` | Creator → System | Creator 驳回 Task | `{task_id, criterion_id, expected, actual, delta?, suggestion?, message_id}` |
| 6 | `blocker_report` | Worker → System | Worker 遇到阻塞 | `{task_id, worker_id, blocker_type, description, suggested_fix?, message_id}` |
| 7 | `heartbeat` | Worker → System | Worker 周期性存活信号 | `{worker_id, active_task_id?, progress_summary?, message_id}` |
| 8 | `pause` | Creator → System | Creator 暂停 Task | `{task_id, reason, message_id}` |
| 9 | `terminate` | Creator → System | Creator 终止 Task（永久） | `{task_id, reason, cascade_deps?, message_id}` |

---

## 二、消息详细定义

### 2.1 claim — Worker 认领

```
方向: Worker → System
源状态: Task.READY
目标状态: Task.IN_PROGRESS
并发控制: version 乐观锁（UPDATE WHERE version=? → affected_rows=0 → 409 Conflict）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `worker_id` | UUID | ✅ | 认领的 Worker ID |
| `batch_id` | UUID | ❌ | 批量认领整个 Batch |
| `task_id` | UUID | ❌ | 认领单个 Task（与 batch_id 二选一） |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- `batch_id` 提供时：原子认领该 Batch 下所有 READY Task
- `task_id` 提供时：只认领该 Task
- 两者都提供时：以 `task_id` 为准，`batch_id` 仅用于 context 记录
- 两者都不提供 → 400 Bad Request
- 认领成功 → 设置 `owner_id=worker_id`, `claimed_at=NOW()`, `lease_expires_at=NOW()+T_lease`, Task → IN_PROGRESS
- 认领冲突（version 不匹配或 status≠READY）→ 409 Conflict

---

### 2.2 claim_ack — 认领确认

```
方向: System → Worker
触发: claim 成功处理后
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 被认领的 Task ID |
| `lease_expires_at` | ISO8601 | ✅ | Lease 过期时间 |
| `batch_context` | object | ❌ | 如果 Batch 认领，返回 Batch 内所有 Task ID 列表 |

---

### 2.3 submit — Worker 提交

```
方向: Worker → System
源状态: Task.IN_PROGRESS
目标状态: Task.IN_VERIFICATION（触发验证流程）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 提交的 Task ID |
| `worker_id` | UUID | ✅ | 提交的 Worker ID |
| `output` | any | ✅ | Task 产出（结构取决于 Task 类型） |
| `evidence` | array | ✅ | 证据列表（文件引用、截图、日志片段等） |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- 校验 Worker 是否是 Task 的当前 owner → 不是则 403
- 校验 Task 状态为 IN_PROGRESS → 不是则 409 state_conflict
- 提交成功 → Task → IN_VERIFICATION，自动创建 Verification 记录
- Worker 的 `last_progress_at` 更新

---

### 2.4 verify — Creator 验收

```
方向: Creator → System
源状态: Task.IN_VERIFICATION
目标状态: Task.COMPLETED（全部 PASSED）或 Task.IN_PROGRESS（有 REJECTED）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 验收的 Task ID |
| `verdict` | enum | ✅ | `PASSED` 或 `REJECTED` |
| `criterion_results` | array | ✅ | 逐条验收结果 |
| `criterion_results[].criterion_id` | UUID | ✅ | 验收条款 ID |
| `criterion_results[].passed` | bool | ✅ | 该条款是否通过 |
| `criterion_results[].actual` | string | ❌ | 实际产出描述 |
| `criterion_results[].notes` | string | ❌ | 备注 |
| `notes` | string | ❌ | 整体备注 |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- 校验 Task 状态为 IN_VERIFICATION → 不是则 409 state_conflict
- 多 Verification 聚合：全部 `criterion_results[].passed == true` 才算 Task PASSED
- PASSED → Task → COMPLETED, 所有 Verification 记录标记 resolved
- REJECTED → Task → IN_PROGRESS, redo_count += 1, Worker 的重做队列追加
- 驳回必须绑定到具体 criterion_id

---

### 2.5 reject — Creator 驳回

```
方向: Creator → System
源状态: Task.IN_VERIFICATION
目标状态: Task.IN_PROGRESS（Worker 重做）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 驳回的 Task ID |
| `criterion_id` | UUID | ✅ | 被驳回的具体验收条款 |
| `expected` | string | ✅ | 期望的标准 |
| `actual` | string | ✅ | 实际收到的产出 |
| `delta` | string | ❌ | 差距描述 |
| `suggestion` | string | ❌ | 改进建议（给 Worker 的引导） |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- 同 verify(REJECTED)，但携带更丰富的驳回上下文
- `suggestion` 字段给 Worker 指出重做方向

---

### 2.6 blocker_report — Worker 阻塞报告

```
方向: Worker → System
源状态: Task.IN_PROGRESS
目标状态: Task.READY（回池，不惩罚 Worker）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 被阻塞的 Task ID |
| `worker_id` | UUID | ✅ | 报告的 Worker ID |
| `blocker_type` | enum | ✅ | `DEPENDENCY_MISSING` / `SPEC_UNCLEAR` / `RESOURCE_UNAVAILABLE` / `OTHER` |
| `description` | string | ✅ | 阻塞描述 |
| `suggested_fix` | string | ❌ | Worker 建议的解决方案 |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- Task → READY（回池），不增加 redo_count
- Worker 的 active_task_id 释放
- 不算 Worker 失败（D-P7-017）

---

### 2.7 heartbeat — Worker 心跳

```
方向: Worker → System
触发: 周期性（建议间隔 ≤ T_hb/3 ≈ 20s）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `worker_id` | UUID | ✅ | Worker ID |
| `active_task_id` | UUID | ❌ | 当前正在执行的 Task |
| `progress_summary` | string | ❌ | 进度简述 |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- 更新 Worker 的 `last_heartbeat_at`
- 如果 `active_task_id` 提供且与上次不同 → 更新 `last_progress_at`
- 不改变任何 Task 状态

---

### 2.8 pause — Creator 暂停

```
方向: Creator → System
源状态: Task.IN_PROGRESS
目标状态: Task.PAUSED
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 暂停的 Task ID |
| `reason` | string | ✅ | 暂停原因 |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- Task → PAUSED
- PAUSED 不消耗 lease，不阻塞 Worker 队列
- Worker 下一次 heartbeat 时发现 Task 被 PAUSED → 停止计算

---

### 2.9 terminate — Creator 终止

```
方向: Creator → System
源状态: READY / IN_PROGRESS / PAUSED
目标状态: Task.CANCELLED（终端态，不可逆转）
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:--:|------|
| `task_id` | UUID | ✅ | 终止的 Task ID |
| `reason` | string | ✅ | 终止原因 |
| `cascade_deps` | bool | ❌ | 是否级联终止依赖此 Task 的其他 Task（远期） |
| `message_id` | UUID | ✅ | 幂等去重 key |

**行为**:
- Task → CANCELLED（永久终端）
- 如果 Task 有 Worker → 释放 Worker 的 active_task_id
- CANCELLED 不同于 REJECTED——Task 永远不会被完成
- 可触达路径：READY → CANCELLED / IN_PROGRESS → CANCELLED / PAUSED → CANCELLED

---

## 三、协议约定（强制）

### 3.1 幂等性

- 每条消息必须携带 `message_id`（UUID）
- 系统用 `message_id` 去重：同一 `message_id` 重复发送不产生副作用
- 去重窗口 ≥ 24h（覆盖合理的重试周期）
- 已处理的消息返回 `200 OK` + 原始处理结果（不是 409）

### 3.2 状态校验

- 消息只在 Task 处于合法源状态时被接受
- 非法状态变迁 → 返回 `409 Conflict` + `state_conflict` error_code
- 响应格式：
  ```json
  {
    "error_code": "state_conflict",
    "message": "Task {{task_id}} is in {{current_state}}, expected {{expected_state}}",
    "conflict_detail": {
      "task_id": "...",
      "current_state": "...",
      "expected_state": "...",
      "attempted_operation": "claim|submit|verify|..."
    }
  }
  ```

### 3.3 Event 记录

- 每条消息被成功处理后，必须在**同一 DB 事务**中写入 EventStore
- 协议消息和 Event 是 **1:1 映射**（协议消息 ≠ Event，但一一对应）:
  - `claim` → `task.claimed`
  - `submit` → `task.submitted`
  - `verify(PASSED)` → `task.completed`
  - `verify(REJECTED)` → `task.rejected`
  - `reject` → `task.rejected`
  - `blocker_report` → `task.blocker_reported`
  - `heartbeat` → 不写 Event（心跳太频繁，只更新 Worker 字段）
  - `pause` → `task.paused`
  - `terminate` → `task.cancelled`
- 唯一例外：`heartbeat` 不写 Event（高频操作，避免 EventStore 膨胀）

### 3.4 错误格式

所有错误返回统一格式：

```json
{
  "error_code": "<string>",
  "message": "<human-readable>",
  "conflict_detail": {}  // 可选，仅 state_conflict 时携带
}
```

| error_code | HTTP Status | 场景 |
|------|:--:|------|
| `state_conflict` | 409 | 状态不匹配 |
| `claim_conflict` | 409 | 并发认领冲突（乐观锁失败） |
| `not_owner` | 403 | Worker 不是 Task 的 owner |
| `not_found` | 404 | Task/Worker 不存在 |
| `invalid_message` | 400 | 消息格式/字段非法 |
| `duplicate_message` | 200 | 幂等：已处理过的 message_id |

---

## 四、与 P8 Batch 的映射

| Batch | 实现的协议消息 | 关键端点 |
|:--:|------|------|
| B1 | (状态机基础——不直接暴露协议消息) | Task 状态变迁内部逻辑 |
| B2 | `heartbeat` | `POST /workers/{id}/heartbeat` |
| B3 | `claim`, `claim_ack`, `submit` | `POST /tasks/{id}/claim`, `POST /tasks/{id}/submit` |
| B4a | `verify`, `reject` | `POST /tasks/{id}/verify` |
| B4b | `verify`（批量） | `POST /verifications/batch` |
| B5 | `blocker_report` + 超时检测 | `POST /tasks/{id}/blocker` |
| B7 | `pause`, `terminate` | `POST /tasks/{id}/pause`, `POST /tasks/{id}/terminate` |

---

## 五、版本策略

- P8 内可**追加**新消息类型，不可**修改**已有消息的语义
- 字段可**追加**（新增可选字段），不可**删除**或**改变类型**
- B8 E2E 验证时对照本契约逐条检查实现一致性

---

## 关联

- [[synapse-p7-d5-decision]] — D5 P8 Batch Plan（本契约的来源）
- [[synapse-p7-d3-decision]] — D3 Skill-as-Protocol（协议哲学来源）
- [[synapse-p8-design-principles]] — P8 设计原则

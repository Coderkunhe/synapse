# ADR-002: Event Sourcing for the Event Ledger

- **Status**: Accepted
- **Date**: 2026-07-04
- **Deciders**: P5-B17
- **Replaces**: D-010 (architecture.md)

## Context

Synapse 的核心价值主张是"过程记忆积累"——历史数据 append-only，作为 Layer 2 增值 Agent 的原材料（architecture.md §2）。这意味着 Event 流的完整性直接决定 Synapse 的上限。

在实现过程中，有两个关键设计选择：

1. Event 写入应放在哪里——service 层还是 router 层？
2. Event 应如何与业务事务关联——独立写入还是同事务？

## Decision

1. **Event 写入在 service 层执行**（不在 router 层）。每个 service 函数在完成业务状态变更后，调用 `event_store.record()` 写入 Event。Router 只负责提交包含业务变更 + Event 的完整事务。

2. **Event 与业务操作共享同一数据库事务**。`event_store.record()` 使用 caller 传入的 `AsyncSession`，不创建独立事务。Router 的一次 `db.commit()` 同时持久化业务变更和 Event——要么都成功，要么都回滚。

3. **Event 不可变**。`EventStore.record()` 只做 INSERT，没有 UPDATE/DELETE 方法。一旦写入，任何人（包括 admin）都不能修改或删除 Event 记录。

4. **EventStore 是模块级单例**。`event_store = EventStore()` 在模块加载时创建，service 函数直接 `import` 使用。不做构造函数注入——EventStore 是无状态的写通道，不需要 mock。

## Consequences

### Positive

- **原子性保证**：不可能出现"任务状态变成了 completed 但 Event 没记录"的情况——共享事务确保两者同生共死
- **审计完整性**：Event 表是从数据库层面保证的完整审计日志，不需要应用层协调
- **Layer 2 数据质量**：Event 流的完整性和一致性直接保证了下游增值 Agent 的输出质量

### Negative

- Event 写入失败会导致整个业务操作回滚——Event 是硬依赖，不是软依赖
- EventStore 单例使得单元测试中无法替换 Event 实现（当前不需要——测试数据库就是 SQLite，Event 表自然可写）
- 高频操作（如 heartbeat）如果记录 Event 会产生大量行——当前 heartbeat 不记录 Event，由调用方决定

### Evolution

当需要以下能力时，此决策需要重新审视：

- Event 流需要推送到外部消息队列（Kafka/NATS）→ 考虑 outbox pattern
- 需要跨服务 Event 消费 → 考虑在 EventStore 中增加 webhook 回调
- Event 表行数影响查询性能 → 考虑分区表或归档策略

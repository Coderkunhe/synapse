# ADR-001: Layered Architecture (Router → Service → Model)

- **Status**: Accepted
- **Date**: 2026-07-04
- **Deciders**: P5-B17
- **Replaces**: D-008 (data-model.md), D-010 (architecture.md)

## Context

Synapse 是一个 API-first 协调平台。早期开发中，tasks 和 agents 两个域通过 service 层封装业务逻辑，但 batches、projects、teams 三个域的 CRUD 操作直接在路由处理器中操作 SQLAlchemy ORM 对象。这导致两个问题：

1. **一致性风险**：直接在 router 中创建 ORM 对象意味着没有状态机门禁、没有事件记录——绕过了 Synapse 的两大核心机制
2. **可测试性下降**：路由中内联的业务逻辑只能用 HTTP E2E 测试覆盖，无法做快速的单元测试

## Decision

采用三层架构，每层有明确定义的职责：

```
Router  →  编排层（不写业务逻辑）
Service →  业务层（不操作 HTTP）
Model  →  数据层（不包含业务规则，除状态机定义外）
```

### Router 层职责（五件事）

1. 解析/校验输入 — Pydantic schema 自动完成
2. 提取认证上下文 — `ActorInfo` via `Depends(get_current_actor)`
3. 调用 service 函数 — 传入已校验的参数
4. 格式化响应 — `ResponseModel.model_validate(service_to_response(result))`
5. 提交事务 — `await db.commit()`

### Service 层职责（四件事）

1. 业务逻辑 — 状态机转换、权限判断、跨实体约束
2. 状态机门禁 — `_validate_transition()` 在每次状态变更前执行
3. 事件记录 — 每次状态变更调用 `event_store.record()`
4. JSON 序列化 — `safe_dumps`/`safe_loads` 处理 JSONB 字段

### 红线

- Router **不得**直接创建/修改/删除 ORM 对象
- Router **不得**内联构建 SQLAlchemy 查询（游标分页等）
- Service **不得**调用 `db.commit()` — 事务所有权归 Router
- Service **不得**访问 HTTP 层对象（Request、Response）

## Consequences

### Positive

- 业务逻辑可脱离 HTTP 测试：service 函数接受 `AsyncSession`，可直接在单元测试中验证
- 所有状态变更自动记录 Event：不可能出现"改了数据库但没写 Event"的漏洞
- 新增域时只需复制 pattern：router → service → model，不需要重新发明

### Negative

- 简单 CRUD（如 Team 更新名字）也需要经过 service 层，增加一层间接调用
- 现有三个 router（batches/projects/teams）需要重构以遵循此规则

### Known Tech Debt

| Router | 违规 | 严重程度 |
|--------|------|:---:|
| `batches.py` | 直接在 router 中创建 Batch ORM 对象（无 service） | 🟡 |
| `projects.py` | 直接在 router 中创建/更新/归档 Project ORM 对象 | 🟡 |
| `teams.py` | 直接在 router 中更新 Team、创建/删除 Member | 🟡 |
| `events.py` | 内联游标分页查询（未提取到 service） | 🟢 |

这些将在后续 Batch 中逐一修复，按优先级：batches → projects → teams → events。

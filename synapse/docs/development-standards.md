# Synapse 开发规范

> 版本：v1.0 · 2026-07-05
> 来源：P6 深度扫描 — 数据库全量审计 + 代码库扫描
> 原则：**本文档是强制门禁，不是建议。新代码违反 → make check 拦截。**

---

## 1. 数据库规范

### 1.1 基线字段 — AuditMixin

**所有业务表**（除 `event` 等不可变日志表）必须继承 `AuditMixin`，包含以下字段：

```python
class AuditMixin(TimestampMixin):
    """基线审计字段 — 所有业务表强制继承。

    继承链：Base → TimestampMixin → AuditMixin
    TimestampMixin 提供: created_at, updated_at
    AuditMixin 新增以下:
    """

    is_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True,
        comment="软删除/禁用标记"
    )
    create_user_id: Mapped[str] = mapped_column(
        String(40), nullable=False,
        comment="创建人 ID (member_id 或 agent_id)"
    )
    last_update_user_id: Mapped[str | None] = mapped_column(
        String(40), nullable=True,
        comment="最后更新人 ID"
    )
    remark: Mapped[str | None] = mapped_column(
        String(2000), nullable=True,
        comment="备注"
    )
    version_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="乐观锁版本号"
    )
```

### 1.2 表分类与字段适用规则

| 表类型 | 示例 | 继承 | is_disabled | version_no | create_user_id |
|---|---|---|---|---|---|
| 业务实体 | team, project, batch, task, agent, skill, member | AuditMixin | ✅ | ✅ | ✅ |
| 分析/扫描记录 | analysis_record, scan_result | AuditMixin | ✅ | ✅ | ✅ |
| 不可变事件 | event | 仅 Base | ❌ | ❌ | 仅 create_user_id |
| 关联/从属 | verification, capability | AuditMixin | ❌（继承父实体状态） | ✅ | ✅ |
| 系统/认证 | refresh_token | AuditMixin | ❌（用 revoked_at 替代） | ❌ | ✅ |
| 工具快照 | continuity_snapshot | AuditMixin | ✅ | ❌（不可变快照） | ✅ |

### 1.3 表命名规范

- **表名**：小写 + 下划线，单数形式（`task`，非 `tasks`）
- **列名**：小写 + 下划线（`project_id`，非 `projectId`）
- **Python 保留字冲突**：加下划线后缀（`metadata_`，非 `metadata`）
- **外键**：`{target_table}_id` 格式
- **布尔列**：`is_{adjective}` 前缀（`is_disabled`，非 `disabled`）
- **时间列**：`{action}_at` 后缀（`created_at`、`completed_at`、`revoked_at`）

### 1.4 Migration 规范

- **所有 migration 通过 Alembic 管理**，禁止手写 DDL
- 新增字段必须有默认值（或 nullable=True），确保存量数据兼容
- 不可逆 migration（如删列）需在 PR 描述中标注 `IRREVERSIBLE`

---

## 2. 后端规范

### 2.1 API 设计

- **路径前缀**：`/v1/{resource}`，RESTful 风格
- **方法语义**：
  - `GET /v1/{resource}` — 列表（支持 `?status=&type=&limit=&offset=`）
  - `GET /v1/{resource}/{id}` — 详情
  - `POST /v1/{resource}` — 创建
  - `PATCH /v1/{resource}/{id}` — 部分更新
  - `DELETE /v1/{resource}/{id}` — 删除/归档（软删除，设 `is_disabled=true`）
- **URL 参数**：小写 + 下划线（`target_type`，非 `targetType`）
- **认证**：Bearer token，Header `Authorization: Bearer <token>`
- **分页**：`limit`(default=50, max=200) + `offset`(default=0)，返回 `{items, total, limit, offset}`
- **多租户**：所有端点通过 JWT `team_id` claim 确定租户边界

### 2.2 乐观锁

所有可写业务表使用 `version_no` 实现乐观锁：

```
PATCH /v1/tasks/{id}?expected_version=3

版本匹配 → 更新成功，version_no += 1
版本不匹配 → 409 Conflict
  {
    "code": "VERSION_CONFLICT",
    "detail": "Expected version 3 but current version is 5",
    "current_version": 5
  }
```

### 2.3 分层架构

```
api/routers/   — 路由层：参数校验 + 认证 + 调用 service，不含业务逻辑
services/      — 服务层：业务逻辑 + 事务管理 + 事件发布
models/        — 数据模型：ORM 映射 + 关系定义
schemas/       — Pydantic schema：请求/响应验证
constants.py   — 枚举常量：StrEnum，不在代码中散落魔法字符串
```

- **Router 不写业务逻辑**：router 函数 ≤ 30 行，只做编排
- **Service 不接触 HTTP**：service 不 import `Request`/`Response`/`HTTPException`
- **一个 Service 只负责一个聚合根**

### 2.4 错误处理

统一错误响应格式：

```json
{
  "code": "RESOURCE_NOT_FOUND",
  "detail": "Task tk_xxx not found",
  "context": {"task_id": "tk_xxx"}
}
```

- 业务错误用 `SynapseError(code, detail, status_code, context)`
- Router 层 catch `SynapseError` → HTTP 响应
- 不直接用 `HTTPException`

### 2.5 SQLAlchemy 规范

- **查询**：使用 2.0 style（`select(Model).where(...)`）而非 `query()`
- **异步**：所有 DB 操作用 `AsyncSession`
- **Greenlet**：`default`/`onupdate` 用 Python callable 而非 SQL `func.now()`，避免 MissingGreenlet

---

## 3. 前端规范

### 3.1 i18n — 强制执行

- **所有用户可见文本必须通过 `t('key')` 渲染**，禁止硬编码任何语言的字符串
- 包括：标题、标签、placeholder、按钮文字、错误提示、tooltip、下拉选项值、状态徽章
- 例外：代码/ID/URL/日期格式字符串可硬编码，但显示文本必须翻译
- 新增翻译 key 后必须在 `en` 和 `zh` 两处同时添加

### 3.2 组件规范

- **表单**：描述/长文本字段必须用 `<textarea>`，禁止 `<input type="text">`
- **Placeholder**：所有 `<input>`/`<textarea>` 的 `placeholder` 必须用 `t()`
- **下拉选项**：选项显示文本用 `t()`，选项值（发往 API）用英文常量
- **日期格式化**：`formatDate()` 接受 `lang` 参数，中文界面用 `zh-CN` locale

### 3.3 WebSocket

- `useWebSocket` hook 的 `topics` 参数不得使用内联 `[]` 字面量（每次渲染新引用导致重连）
- 使用 `useMemo(() => [...], [])` 或组件外常量
- 最大重连次数 ≤ 5，超过后停止自动重连

### 3.4 路由

- 每个 Route path 在 `NAV_ITEMS` 中有对应项（除非是详情页如 `/tasks/:id`）
- 必须有 `path="*"` 的 404 catch-all 路由
- `ProtectedRoute` 在 `isLoading` 时渲染 spinner，不返回 `null`

---

## 4. 文档规范

### 4.1 双写过渡期

**当前阶段**：关键数据一式两份
- **数据库**：权威数据源（通过 Synapse API 写入）
- **文档**：`docs/` 目录下的 markdown（手动同步，作为备份）

**目标阶段**：数据库为唯一权威源
- 文档内容从数据库拉取生成（`make sync-docs` 或脚本导出）
- `docs/` 中的 markdown 成为"导出产物"而非"手写源"

### 4.2 必须维护的文档

| 文档 | 触发更新条件 |
|---|---|
| `master-backlog.md` | 每次新增/scoped 待办项 |
| `roadmap.md` | 每次 Phase/Batch 状态变更 |
| `development-standards.md` | 规范变更 |
| `CLAUDE.md` | 项目结构/工具链/铁律变更 |
| `docs/plans/` | 每个新 Batch 开始前 |

---

## 5. 门禁检查（make check）

新增检查项：

| 检查 | 工具 | 阻断级别 |
|---|---|---|
| `check-db-audit` | 扫描所有 Model，确认 AuditMixin 继承 | 硬阻断 |
| `check-i18n` | 扫描 TSX 中未走 `t()` 的硬编码英文文本 | 硬阻断 |
| `check-placeholder` | 扫描 `<input>`/`<textarea>` 中硬编码 `placeholder=` | 硬阻断 |
| `check-version-no` | 扫描 POST/PATCH 端点是否支持 `expected_version` | 软告警 |

---

## 6. 种子心态（Seed Mindset）

> 本文档不是终点，是起点。

### 6.1 为什么是"种子"

每个项目的开发规范都有两种写法：

**石碑模式**：一次性刻好，后来的人只能读，不能改。结果——三个月后规范与代码已经脱节，新人看着石碑怀疑人生。

**种子模式**：把规范当成一颗种子。种下去的是核心原则（§1-5），但它会在实践中生长——每次踩坑，每次 code review 发现新模式，每次新成员带来新视角，都是种子在吸收养分。

### 6.2 种子的生长规则

1. **核心原则不可变，实践指南可生长**：§1-5 的核心门禁（AuditMixin、i18n、分层架构）是种子里的基因，不会变。§6 以下的实践指南、踩坑记录、模式推荐是枝叶，随着项目成熟不断生长。

2. **谁发现，谁播种**：任何人在开发中发现一个可复用的模式或一个可避免的坑，直接 PR 到本文档。不需要"等下次规划会议"——规范文档的维护成本远低于错误的重复成本。

3. **生长痕迹要可见**：每次对规范的修改都要在变更记录中留下清晰痕迹（日期 + 内容 + 触发原因），让后来的人能理解"为什么当时这样改"。

4. **修剪是生长的一部分**：过时的规范要及时标记 `[DEPRECATED]`，不要直接删除。被废弃的规范本身也是一种知识——它告诉你"这条路走过，不通"。

### 6.3 种子的土壤 — 团队文化

规范文档写得再好，没有团队文化做土壤，种子长不出来。

- **规范不是束缚，是护栏**：规范帮你避免已知的坑，不是限制你的创造力。
- **质疑规范是健康的表现**：如果你觉得某条规范不合理，提出来讨论。规范是为人服务的，不是反过来。
- **代码 review 的第一参照物**：review 时，如果有分歧，先翻本文档——它是最低共识，不是最高标准。

### 6.4 种子的未来

随着项目演进，本文档的生长方向：

| 阶段 | 内容 | 触发条件 |
|---|---|---|
| 现在（种子） | 核心门禁 + 分层规范 | P6 深度扫描完成 |
| 近期（幼苗） | 踩坑记录 + FAQ | 积累 5+ 个实际踩坑案例 |
| 中期（小树） | 性能基线 + 安全规范 | 生产部署前 |
| 远期（大树） | 架构决策记录(ADR) 索引 + 模式目录 | 3+ 子系统稳定后 |

**最重要的原则**：如果你读完这份规范，发现有一个地方不清楚、不准确、或者跟实际代码对不上——**不要忍，现在就改**。种子需要每一个人的浇灌。

---

## 7. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-07-05 | v1.0 | 初始版本 — 数据库 AuditMixin 基线 + 后端分层 + 前端 i18n/WebSocket/路由规范 |

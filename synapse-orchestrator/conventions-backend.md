# 后端编码约定 — Synapse

> 本文档定义本项目后端开发的具体命令和约定。L2b 层——按技术栈加载。
> 角色职责和操作方法论见 [role-builder.md](role-builder.md)。

## 技术栈

| 层面 | 选型 | 版本 |
|------|------|------|
| 语言 | Python | 3.12 |
| 框架 | FastAPI | latest |
| ORM | SQLAlchemy | 2.0+ (async) |
| 数据库 | SQLite (开发) / PostgreSQL (生产) | — |
| 迁移 | Alembic | latest |
| 测试 | pytest + pytest-asyncio | 8.x |
| 类型检查 | mypy | 1.10+ |
| 认证 | python-jose (JWT) + bcrypt | — |

## 目录结构

```
src/
├── main.py            ← App factory + lifespan
├── config.py          ← pydantic-settings
├── db.py              ← SQLAlchemy async engine
├── dependencies.py    ← FastAPI Depends
├── auth.py            ← JWT + API Key
├── exceptions.py      ← 结构化错误
├── api/
│   ├── router.py      ← 主路由聚合
│   └── routers/       ← 按领域分路由文件
├── models/            ← SQLAlchemy ORM（~27 实体）
├── schemas/           ← Pydantic request/response
├── services/          ← 业务逻辑层
└── utils/             ← ID 生成器 + JSON 工具

tests/                 ← 根级测试目录
├── conftest.py        ← 共享 fixtures
└── test_*.py          ← 按领域分测试文件
```

## 开发命令

| 操作 | 命令 | 说明 |
|------|------|------|
| 安装依赖 | `pip install -r requirements.txt` | 建议在 venv 中执行 |
| 数据库迁移 | `alembic upgrade head` | 应用所有未执行 migration |
| 创建迁移 | `alembic revision --autogenerate -m "描述"` | 自动检测 model 变更 |
| 运行测试 | `pytest -v --tb=short` | `asyncio_mode=auto`，自动检测 async 测试 |
| 类型检查 | `python3 -m mypy --config-file mypy.ini src/` | 当前 ~51 预存错误，警告模式 |
| 启动服务 | `uvicorn src.main:create_app --factory --reload` | 开发模式热重载 |

**全量门禁**：`make check`（21 步管道：doc 门禁 + 类型检查 + 测试 + 契约检查 + 治理检查）。

## 数据库约定

### ORM 模型

- 所有表继承 `Base`（SQLAlchemy declarative base）
- 所有 Response schema 继承 `AuditFields`（`created_at` / `updated_at`）
- ID 使用 UUID7（`uuid6.uuid7()`），在 model 层生成
- 关系用 `relationship()` + 显式 `ForeignKey`

### Migration

```
alembic revision --autogenerate -m "add_xxx_table"
# → 检查生成的 migration 文件
# → alembic upgrade head
# → alembic downgrade -1  ← 必须验证 downgrade 可用
# → alembic upgrade head
```

**关键约束**：每个 migration 必须有可用的 `downgrade()` 路径。Steward 审查会将缺少 downgrade 的 migration 标为 P0。

### 兼容约束

项目需同时支持 SQLite（开发）和 PostgreSQL（生产）：
- ❌ 不用 `Enum` 类型 → 用 `String` + Pydantic enum 校验
- ❌ 不用 `JSONB` → 用 `JSON` / `Text`
- ❌ 不用 `SERIAL` / `AUTOINCREMENT` → 用 UUID7
- ❌ 不用数据库专属函数（`NOW()` 除外）

## API 约定

| 约定 | 示例 |
|------|------|
| RESTful 名词复数 | `GET /projects/{id}/tasks`，`POST /tasks` |
| 嵌套资源 | `/projects/{pid}/tasks/{tid}` |
| 错误响应统一格式 | `ErrorResponse` schema（`detail: str` + `code: str`） |
| 分页 | `CursorPage`（`cursor: str` + `limit: int`） |
| 认证头 | `Authorization: Bearer <token>` 或 `X-API-Key: <key>` |

### Router 模式

```python
from fastapi import APIRouter, Depends
from src.dependencies import get_current_actor
from src.schemas.tasks import TaskResponse

router = APIRouter(prefix="/projects/{project_id}/tasks", tags=["tasks"])

@router.get("/", response_model=list[TaskResponse])
async def list_tasks(project_id: str, actor = Depends(get_current_actor)):
    ...
```

## Import 规范

```python
# 1. 标准库
from datetime import datetime

# 2. 第三方
from fastapi import APIRouter, Depends
from sqlalchemy import select

# 3. 项目内部（绝对导入，从 src/ 开始）
from src.db import get_session
from src.models.task import Task
from src.schemas.tasks import TaskResponse
```

## 验证门禁

| 检查项 | 命令 | 阻塞级 |
|--------|------|:---:|
| 测试 | `pytest -v --tb=short` | ✅ 阻塞 |
| 类型检查 | `python3 -m mypy src/` | ⚠️ 警告（~51 预存错误，不阻塞） |
| 全量门禁 | `make check` | ✅ 阻塞 |
| 全栈门禁 | `make check-all` | ✅ 阻塞（含前端） |

## 关键约束

- **无 Python formatter**。本项目未配置 ruff/black/isort。代码风格靠人工一致 + code review。
- **mypy 警告模式**。`disallow_untyped_defs = False`——不强制类型注解。预存 ~51 个 mypy 错误，提交前确认**不新增**即可。
- **依赖升级纪律**。`pip install` 或 `requirements.txt` 变更后 → 立即 `make check` 全量门禁重跑。
- **测试数据库**。pytest 使用内存 SQLite（`aiosqlite`），测试间数据隔离。

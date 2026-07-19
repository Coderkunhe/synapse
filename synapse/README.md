# Synapse

> 人机混合团队分布式协调平台
> 最后更新：2026-07-04

**不存代码，只协调工作。** Synapse 是软件开发过程的 single source of truth——需求、任务拆分、实现、验证，每一步谁在干、干到哪了，都在这里同步。团队成员可以是人，也可以是 agent（Claude、Codex 等）。

## 与 GlassCortex 的关系

Synapse 和 [GlassCortex](../glassmind/) 是两个独立项目。Synapse 通过"偷看" GlassCortex 的开发流程经验来提炼可复用的协调方法论，但绝不修改其代码。

## 项目状态

🟢 **Phase 2 MVP 完成**（2026-07-04）— 29 端点全量实现 · 22 E2E tests · FastAPI + React 前后端就绪 · Docker 本地部署可用。

## 文档结构

| 文档 | 说明 |
|------|------|
| [CLAUDE.md](CLAUDE.md) | AI 会话入口（铁律 + 指针） |
| [PRD](docs/prd.md) | 产品需求文档 |
| [数据模型](docs/data-model.md) | 核心实体定义 |
| [协调协议](docs/protocol.md) | 人机混合协作协议 |
| [架构设计](docs/architecture.md) | 系统架构 + 技术选型 |
| [安全模型](docs/security-model.md) | 多租户权限 |
| [MVP 边界](docs/mvp-boundary.md) | MVP 精确边界定义 |
| [路线图](docs/roadmap.md) | 开发路线图 |
| [需求日志](docs/requirements-log.md) | 每批交付记录 |
| [方法论](docs/methodology.md) | 开发工作流 |
| [经验](docs/lessons-learned.md) | 可迁移通用经验 |
| [踩坑](docs/pitfalls.md) | 技术踩坑注册表 |
| [协作规范](CONTRIBUTING.md) | 开发协作规范 |

## 协作方式

见 [CONTRIBUTING.md](CONTRIBUTING.md)

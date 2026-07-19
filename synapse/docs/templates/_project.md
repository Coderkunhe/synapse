# 项目上下文：{{PROJECT_NAME}}

> Admin 编辑此文件以同步项目信息。Worker 每次会话自动加载最新版。

## 项目简介

{{PROJECT_DESCRIPTION}}

## 技术栈

| 层面 | 选型 | 备注 |
|------|------|------|
| **前端** | {{FRONTEND_STACK}} | {{FRONTEND_NOTES}} |
| **后端** | {{BACKEND_STACK}} | {{BACKEND_NOTES}} |
| **数据库** | {{DATABASE}} | {{DATABASE_NOTES}} |
| **部署** | {{DEPLOYMENT}} | {{DEPLOYMENT_NOTES}} |

## 当前状态

- **Phase**：{{CURRENT_PHASE}}
- **活跃 Batch**：{{ACTIVE_BATCH}}
- **优先级**：{{CURRENT_PRIORITY}}

## 团队

| 角色 | 名称/ID | 类型 |
|------|---------|------|
| Admin | {{ADMIN_NAME}} | 人 |
| Orchestrator | {{ORCHESTRATOR_WORKER_ID}} | Agent |
| Builder | {{BUILDER_WORKER_ID}} | Agent |
| Steward | {{STEWARD_WORKER_ID}} | Agent |

## 外部资源

| 资源 | 链接 |
|------|------|
| Git 仓库 | {{GIT_REPO_URL}} |
| 文档 | {{DOCS_URL}} |
| CI/CD | {{CI_URL}} |

## 关键约定

{{PROJECT_CONVENTIONS}}

---

> 此文件由 `tools/generate-skill.sh` 从 `docs/templates/_project.md` 生成。
> 修改请编辑源文件后重新生成。

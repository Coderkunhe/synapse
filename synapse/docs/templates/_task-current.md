# 当前任务

> ⚠️ **一期手动填写模板**（D-P11-010 决策 — P11-B6 落地）。
>
> Task 级变量（TASK_ID / TASK_TITLE / TASK_PRIORITY / TASK_EFFORT / TASK_VERIFICATIONS / TASK_CONTEXT）无法在 Project 层面自动解析——它们属于具体的 Task assignment。
>
> **一期使用时**，Admin 根据实际分配的 Task 填写以下占位符。`--from-api` 模式会自动将此文件替换为含详细填写指引的模板。
>
> **二期**：`POST /agents/{id}/handshake` 响应中 Synapse 自动返回当前 Task 信息，`generate-skill.sh` 自动填充此文件。

---

## 当前活跃 Task

| 字段 | 值 |
|------|-----|
| Task ID | `{{TASK_ID}}` |
| 标题 | `{{TASK_TITLE}}` |
| 优先级 | `{{TASK_PRIORITY}}` |
| 预估 effort | `{{TASK_EFFORT}}` |

## Verification 条件（合同）

> 列出此 Task 的 Verification 条件——每条必须是机器可判定的。
>
> 示例：
> - `pytest tests/test_xxx.py -v` 全部通过
> - `make check` 零新增告警
> - `cd frontend && npm run build` 通过

{{TASK_VERIFICATIONS}}

## 关联上下文

> 填写与当前 Task 相关的额外上下文（关联 PR、设计文档、依赖的 Task 等）。

{{TASK_CONTEXT}}

---

> 💡 此文件由 `tools/generate-skill.sh` 从 `docs/templates/_task-current.md` 生成。
> 修改请编辑源文件后重新生成。

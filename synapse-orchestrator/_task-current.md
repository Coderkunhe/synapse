# 当前任务

> ⚠️ 此文件为手动填写模板。Task 级变量（TASK_ID / TASK_TITLE / TASK_PRIORITY / TASK_EFFORT / TASK_VERIFICATIONS / TASK_CONTEXT）无法在 Project 层面解析——它们属于具体的 Task assignment。
>
> 一期使用时，Admin 根据实际分配的 Task 填写以下字段。二期将由 Synapse handshake API 自动返回当前 Task。

---

## 当前活跃 Task

| 字段 | 值 |
|------|-----|
| Task ID | `请填写 Task ID（如 task_xxx）` |
| 标题 | `请填写 Task 标题` |
| 优先级 | `请填写（high / medium / low）` |
| 预估 effort | `请填写（如 2h / 1d）` |

## Verification 条件（合同）

请列出此 Task 的 Verification 条件——每条必须是机器可判定的。

示例：
- `pytest tests/test_xxx.py -v` 全部通过
- `make check` 零新增告警
- `cd frontend && npm run build` 通过

## 关联上下文

请填写与当前 Task 相关的额外上下文（关联 PR、设计文档、依赖的 Task 等）。

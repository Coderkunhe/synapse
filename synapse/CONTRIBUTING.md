# 协作规范

> 最后更新：2026-07-03

## 开发流程

Synapse 采用 [八步链路](docs/methodology.md) 工作流：

```
Pre-flight → Plan → 拆分 → TDD → 五层自检 → 文档闭环 → 推送 → 清理
```

每批变更必须通过五层自检（L1-L5），未通过不进下一批。

## AI 会话协作

- 从 `synapse/` 目录启动的 Claude 会话自动读取 `CLAUDE.md`
- 跨会话记忆由 `/memory/` 目录维护
- glassmind 目录对本项目只读，详见 CLAUDE.md 铁律

## 提交规范

- 格式：`<type>(<scope>): <description>`
- Type: `feat` / `fix` / `docs` / `refactor` / `test` / `chore`
- 每批 ≤8 文件变更

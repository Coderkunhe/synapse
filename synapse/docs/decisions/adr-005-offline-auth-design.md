# ADR-005: 离线/内网部署 Auth 兼容设计

- **Status**: Draft（设计预留，实现裁剪）
- **Date**: 2026-07-17
- **Deciders**: P10-B14 讨论

## Context

Synapse 是分布式协调平台，部署场景包括：

| 部署场景 | 网络条件 | Auth 依赖 |
|----------|----------|-----------|
| SaaS / 公网 | 完全联网 | SMTP + GitHub OAuth |
| 企业内网 | 可出站但无公网 DNS | 可能内网 SMTP · 无 OAuth |
| 完全气隙 | 零外部连接 | 无 SMTP · 无 OAuth |

P10 议题 2 当前实现仅覆盖公网场景。离线/气隙场景需要显式设计。

## Decision

**设计预留，实现裁剪**。

- P10-B15 落地 SMTP 邮件发送（公网场景的生产就绪）
- 离线兼容相关的 `DEPLOYMENT_MODE`、bootstrap 通道、admin reset、OAuth 降级 **不在 P10 实现**
- 以下设计文档作为远期实现的 spec，确保当前架构不堵死远期路径

### 远期：`DEPLOYMENT_MODE`

```
DEPLOYMENT_MODE = "online"   # 默认 · 完整公网能力
                | "airgap"   # 气隙 · 零外部依赖
```

当 `DEPLOYMENT_MODE=airgap` 时：
- OAuth 端点返回 `FEATURE_UNAVAILABLE`
- Password Reset 不依赖 SMTP，改为 admin 通道
- 自注册策略由 `AIRGAP_SELF_REGISTRATION` 控制

### 远期：Bootstrap 三通道

气隙环境首次部署时数据库为空，需要第一条管理员账号的创建通道：

**通道 A — 环境变量自动播种**（容器化/K8s 部署）：
```
INITIAL_ADMIN_EMAIL=admin@internal
INITIAL_ADMIN_PASSWORD=changeme123
```
→ lifespan startup 检测 user 表空 → 自动创建 admin。

**通道 B — CLI 工具**（传统运维）：
```
$ python tools/create-admin.py --email admin@internal
→ 生成随机密码 → 打印到终端
```

**通道 C — 开放注册 + 邮箱匹配提权**（小团队信任网络）：
```
AIRGAP_SELF_REGISTRATION=true
AIRGAP_ADMIN_EMAILS=admin@internal
```
→ 注册邮箱匹配列表 → 自动赋予 admin 角色。

### 近期预留点

P10-B15 实现时确保以下点不被堵死：

1. `SMTP_HOST` 为空时 → email_service 优雅降级（log warning，不抛异常）—— 这为远期 airgap 模式做准备，目前只是防御性代码
2. `forgot-password` 端点保留「无 SMTP 时返回 token 到 API」的行为（当前已有 debug 模式），远期 admin reset 通道可复用
3. OAuth 端点已有 `GITHUB_CLIENT_ID` 为空时的降级路径，不再扩展

## Consequences

- ✅ P10 议题 2 按时完成（SMTP 邮件发送上线）
- ✅ 离线兼容设计已文档化，远期实现有据可依
- ⬜ 离线兼容的完整实现待独立 Phase 或 P10 后期批次
- ⬜ Bootstrap 通道在首次气隙部署前必须落地至少一条

## Related

- P10 Plan: `memory/synapse-session-2026-07-17-p10-planning.md` — P10 8 议题全貌
- D-P10-012: 离线/内网部署兼容讨论（session checkpoint）
- P10-B15: Email 基础设施（SMTP + 邮件模板 + 发送服务）

# P100-B137 自检 — 时区序列化修复（VDD 先红后绿）

> 批号: P100-B137 · 性质: 首个触 src/ 的 P100 治理批 · 日期: 2026-08-14
> 根因: AuthorizationRequest 的 expires_at/last_heartbeat_at/responded_at 是 naive DateTime，
> SQLite 无原生时区类型 → round-trip 剥离 tzinfo → Pydantic 序列化无偏移 → 前端 new Date() 早 8h 误判过期。

## 编码前 Scout（三问）

- [x] **数据流拉通** — create_authorization_request 写入 aware datetime(now=datetime.now(timezone.utc)) → SQLite naive 列剥离 tzinfo → `_to_response` 用 model_validate(from_attributes) 读 ORM → Pydantic 序列化无偏移 → Approvals.tsx:41 new Date() 按 GMT+8 误判过期禁用批准按钮；修复点在 schema 序列化层。
- [x] **同类参照** — TimestampMixin(base.py:36-40) 已用 DateTime(timezone=True) 但 SQLite 下同为 no-op；refresh_token/password_reset_token 的读侧用 `replace(tzinfo=utc)` 补偿(auth_service.py:519/714)；worker.py:62-63 已用 timezone=True。结论：序列化补 UTC 是既有 idiom。
- [x] **用户一句话** — 用户在 Web UI 审批弹窗里，批准按钮不再因为时区误判而提前 8 小时被禁用，expires_at 返回 ISO 带 Z 后缀。

## 编码后自检（四问）

- [x] **乐观路径** — 创建请求 → 独立 session 重读(naive) → model_validate → field_validator 补 UTC → expires_at.tzinfo 非 None → model_dump(mode=json) 输出 `2026-08-14T06:00:00Z`；test_expires_at_serializes_with_timezone 已覆盖。
- [x] **边界状态** — responded_at 未审批时为 None，field_validator `v is not None` 守卫跳过 None；已 aware(PG) 时 tzinfo 非 None 直接透传不双重补偿；全量 941 tests 零回归。
- [x] **对比同类** — field_validator 补 UTC 对齐 auth_service 的 replace(tzinfo=utc) idiom；timezone=True 对齐 TimestampMixin 约定；新增测试复用 test_authorization_service.py 既有 db_session/test_project/test_worker fixtures。
- [x] **变更清单口播** — 5 代码文件（3 model + 1 schema + 1 test）≤8 上限：authorization_request.py(3 列 timezone=True) · refresh_token.py · password_reset_token.py · schemas/authorization_request.py(field_validator) · tests/test_authorization_service.py(+2 tests)。

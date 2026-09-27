# P100-B168 自检 — report_execution InvalidStateTransition 传参修复

> 批号: P100-B168 · 性质: 治理批（Builder 直接改 src · 无 dogfood 模式）· 日期: 2026-09-27
> 根因: `report_execution` 非 approved 分支的 `InvalidStateTransition` 调用传了签名外 kwarg（request_id/message · 缺 entity_type/entity_id）→ 命中即 TypeError（500 而非干净 400）· 此前 report_execution 零测试覆盖 → 漏网。

## 编码前 Scout（三问）

- [x] **数据流拉通** — capability 执行结果上报：worker 执行后 POST /authorization-requests/{id}/report → report_execution 校验 request_type=capability_exec → status=approved → 拥有者 → 写 outcome。非 approved 分支抛 InvalidStateTransition 本应给 400，但参数名抄错 → Python __init__ 报 TypeError → FastAPI 转 500。
- [x] **同类参照** — 全仓 8 处 InvalidStateTransition 调用：worker_state_machine/task_state_machine/task_core 用位置参数，protection_service/verification_service/respond_to_request/heartbeat 用关键字 entity_type/entity_id，仅 report_execution 抄错为 request_id/message。签名固定 (entity_type, entity_id, from_status, to_status)。
- [x] **用户一句话** — Worker 对未批准请求上报执行结果时，API 返回干净的 400 INVALID_STATUS_TRANSITION，而不是 500 Internal Server Error 让客户端误判服务端故障。

## 编码后自检（四问）

- [x] **乐观路径** — capability_exec + approved + 拥有者 → report_execution 正常写 outcome（现有逻辑不动 · 无回归）。
- [x] **边界状态** — capability_exec + pending → InvalidStateTransition（新测试钉住）；capability_exec + approved + 非拥有者 → ForbiddenError（原有分支不回归）；非 capability_exec → ForbiddenError（原有分支不回归）。
- [x] **对比同类** — 对齐 respond_to_request/heartbeat 的关键字风格 entity_type="AuthorizationRequest" + entity_id=request_id；标准错误消息（丢失自定义中文 message，但格式统一）。
- [x] **变更清单口播** — 2 代码文件 ≤8 上限：authorization_service.py(1 处传参) · test_authorization_service.py(+1) · 1014 tests（1013 基线 + 1 新增，零回归）。

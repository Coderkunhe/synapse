# P100-B171 自检 — WS 鉴权迁 cookie 根修

> 批号: P100-B171 · 性质: 治理批（Builder 直接改 src+frontend · 无 dogfood 模式）· 日期: 2026-09-28
> 根因: P100-B58 把 JWT localStorage→httpOnly cookie 只迁了 HTTP 层，漏了 WS 层。前端把哨兵 `'cookie'` 当 token 拼进 `ws://…/v1/ws?token=cookie`，后端 ws.py 只认 `?token=` 真 JWT → close 4001 → 前端红点「未连接」常驻。

## 编码前 Scout（三问）

- [x] **数据流拉通** — 浏览器登录后 access_token 存 httpOnly cookie（path=/v1 · SameSite=lax）→ WS 握手是 GET 升级请求，同 site（localhost:5173→localhost:8000）自动带 Cookie → 后端 `ws.cookies.get('access_token')` 取回 → `_verify_ws_token` 走 JWT 分支（无 DB 往返）。前端 `useWebSocket` 只拿 AuthContext 的 `'cookie'` 哨兵做 auth gate，不拼 `?token=`。
- [x] **同类参照** — HTTP 层 `dependencies.get_current_actor`（:47）已用 `request.cookies.get(settings.access_token_cookie_name) or bearer` 做 cookie 优先，WS 层缺失对称逻辑 → 照抄该读法。API Key 路径（`?token=sk-syn-`）保留给 Worker。
- [x] **用户一句话** — 登录后 Dashboard 左上角 WSStatus 变绿点，不再常驻「未连接」；`/health` `ws_connections≥1`。

## 编码后自检（四问）

- [x] **乐观路径** — 登录后 cookie 存在 → WS 握手自动带 cookie → 后端 cookie 回退命中 → `connected` + 绿点。
- [x] **边界状态** — 无 cookie + 无 query → close 4001（新 guard 防 `None.startswith` TypeError）；`?token=` query 仍走原路径（回归测试钉住）；cookie 过期 → `_verify_ws_token` 返 None → close 4001（不变）。
- [x] **对比同类** — 后端对称 `dependencies.py:47` 的 cookie 读法；`token: Query(None)` 可选签名对齐 FastAPI 惯例。
- [x] **变更清单口播** — 2 代码文件 ≤8 上限：ws.py（1 处签名 + 1 处 cookie 回退 + 1 处缺 token guard）· ws.ts（1 处去 `?token=`）· +1 test（3 例）· 1017 tests（1014 基线 + 3 新增 · 零回归）。

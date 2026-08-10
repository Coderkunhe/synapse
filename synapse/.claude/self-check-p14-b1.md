# P14-B1 编码前 Scout + 编码后自检

## 编码前 Scout（三问）

- [x] **数据流拉通** — stale reaper (`_stale_task_reaper`) 在 main.py line 130-132 从 settings 读取 `escalation_minutes` + `escalation_cooldown`，line 185-189 传给 `detect_stale_verifications_escalation()`。line 138-143 的 startup log 已记录 interval/stale/reassign/verify_timeout 四个参数但漏了 escalation。本次仅给 log 语句补两个已有局部变量，无新数据流、无新 API 调用、无权限变更。

- [x] **同类参照** — 参照 heartbeat_monitor (`_worker_heartbeat_monitor`) line 339-343 的 startup log 格式: `"Worker heartbeat monitor started: interval=%ds, standard_timeout=%ds, codex_timeout=%ds"` — key=value 逗号分隔。本次追加 `escalation=%dmin, escalation_cooldown=%dmin` 保持完全一致的格式风格。stale reaper 与 heartbeat_monitor 同为 main.py 中的后台 coroutine，风格对齐。

- [x] **用户一句话** — P13-B10 发现 stale reaper 启动日志不记录 escalation 配置。运维通过 `grep "Stale task reaper started"` 看日志时能一眼确认 escalation 是否已启用、触发阈值和冷却时间，无需翻 config.py 或查环境变量。这是一个"让运维一眼看懂配置"的微小改进。

## 编码后自检（四问）

- [x] **乐观路径** — Server 启动后 stale reaper 首次扫描即输出包含全部 6 个参数（interval, stale, reassign, verify_timeout, escalation, escalation_cooldown）的 startup log。escalation_minutes 默认值 10，escalation_cooldown_minutes 默认值 30，即使未显式配置也有值可输出。log 输出格式与 heartbeat_monitor startup log 完全一致，运维可用同一套 grep 规则。

- [x] **边界状态** — escalation 参数在 config.py line 126-127 有硬编码默认值（10min/30min），不存在 None 或空值场景。settings 对象在 coroutine 启动时已初始化，`settings.verification_escalation_minutes` 不会抛出 AttributeError。log 语句在 try 块内（line 133），任何意外异常会被外层 catch 捕获并 log 为 warning，不会导致 coroutine 崩溃。

- [x] **对比同类** — 与 heartbeat_monitor 的 startup log（line 339-343）逐项对比：均使用 `key=value` 格式、逗号分隔、同一 `_logger.info()` 调用、同一缩进级别。stale reaper 的 log 原本就用 `%ds`/`%dmin` 后缀标明单位，新增参数保持 `%dmin` 后缀。无风格漂移，无命名不一致。

- [x] **变更清单口播** — 变更文件：`src/main.py` 仅 line 139-143 的 `_logger.info()` 调用追加两个已有局部变量到格式化字符串。1 file，1 logical line，零接口变更，零新增依赖。897 tests 零回归（pytest -x -q 实际验证通过）。Staged 总文件 8 个，其中 7 个为文档/工具/checkpoint，唯一代码文件为此变更。

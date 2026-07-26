# Verification & Evidence 可信模型

> Synapse 自动验收的可靠性设计。最后更新：2026-07-26（P11 D-P11-B69-2 架构对齐产出）。

## 问题本质

Synapse 不存代码、不执行构建——自动验收只能基于 Builder 提交的文本证据判断"是否符合验收条件"。两个核心挑战：

1. **验收条件的可判定性**：Orchestrator 写的条件太模糊（"代码写好了"），自动验收形同虚设
2. **证据的可信度**：Builder 可能提供不实证据，Orchestrator 无法独立复现执行结果

平台不能替代项目内部的专业判断，但可以通过结构性约束确保自动验收的下限。

---

## 1. 验收条件质量保障（四层模型）

### L1 — 结构性硬门禁（B70 实现）

Task 进入 READY 状态前，服务端校验所有 Verification 条件：

**可判定性检查**（每条 Verification 必须包含以下至少一种）：
- 数字指标：`"test suite 12/12 passed"`, `"覆盖率 ≥ 80%"`
- 文件路径：`"文件 output/report.pdf 存在"`
- 命令输出：`"grep -r 'TODO' src/ 返回空"`
- API 状态码：`"POST /login 返回 200"`

反例（拒绝 ready）：
- ❌ `"代码写好了"`
- ❌ `"功能正常"`
- ❌ `"没有 bug"`

**最少数量**（按 effort 而非文件数，通用场景兼容）：

| Effort | 最少 Verification |
|:---|:---:|
| XS | ≥1 |
| S | ≥2 |
| M+ | ≥3 |
| 关键路径/安全相关 | ≥3（须含安全/边界检查） |

**证据类型必填**：每条 Verification 必须声明 `expected_evidence_type`（见 §2）。

### L2 — 领域无关通用模板（B70 实现）

| 活动类型 | Verification 模板 | 适用场景 |
|---------|-------------------|---------|
| **产物交付** | `"{产物路径} 存在 + {格式检查} 通过"` | 设计稿、文档、海报、报告 |
| **数据变更** | `"{操作} 返回 {预期状态码} + {字段} 非空/符合预期"` | API、数据库、配置文件 |
| **流程执行** | `"{流程名} {N/N} 步全部完成 + 无错误日志"` | 部署、迁移、批量处理 |
| **决策/分析** | `"输出含 {必需结论要素} + 数据源引用 ≥ {N} 处"` | 调研报告、竞品分析、技术选型 |
| **创作/生成** | `"{输出物} 通过 {检查工具/审查标准} + 符合 {规范}"` | 文案、翻译、代码生成 |

模板和领域无关——"设计海报"和"实现 API"都能套"产物交付"。

### L3 — 质量评分引擎（B71 实现）

Task ready 前自动评分：

```
Verification 质量评分（0-100）:
  ├─ 可判定性 (40%): 每条是否含可测量指标
  ├─ 覆盖度 (30%): 是否覆盖了 Task 描述的所有输出维度
  ├─ 边界条件 (20%): 是否包含失败/异常场景的判定
  └─ 冗余度 (10%): 是否有两条在判定同一件事

< 40 分 → 硬阻断，不允许 ready
40-60 分 → 警告 ⚠️，允许 ready 但标注
> 60 分 → 通过
```

### L4 — 争议学习（远期）

从验收打回记录中学习措辞歧义：
- 模式：`Verification 条件 '{条件}' 被 Builder 理解为 A，Orchestrator 判定为 B`
- 回馈：下次 Orchestrator 写类似条件时，平台提示"该措辞历史上引起过 N 次争议，建议改为..."

---

## 2. 证据可信度模型

### 证据等级

```
L0 自述型      "我完成了"                               ← 零约束，不应用于自动验收
L1 指标型      "pytest: 23/23 passed, coverage 82%"      ← 可交叉验证但可伪造
L2 产物型      "SHA256: abc123, 文件: output/report.pdf"  ← 伪造需实际生成文件
L3 外部验证型   CI 结果、Git commit hash、第三方服务回调    ← 最难伪造
```

### expected_evidence_type 枚举

| 类型 | 含义 | Builder 必须提供 | 适用场景 |
|:---|------|------|------|
| `command_output` | 命令执行输出 | 命令文本 + 完整输出 | 测试、lint、脚本 |
| `artifact_hash` | 产物文件 | 文件路径 + SHA256 + 大小 | 设计稿、文档、构建产物 |
| `api_response` | API 响应 | 状态码 + 响应体关键字段 | API 端点、数据变更 |
| `external_ref` | 外部系统引用 | 外部链接/ID（如 Git commit, CI run ID） | 部署、CI、代码提交 |
| `self_report` | 自我声明 | 文字描述 | **仅限**主观判断类条件（如"文案风格符合品牌调性"） |

### Orchestrator 验收协议

```
1. 类型匹配检查
   条件要求 command_output，Builder 只贴了 self_report → 直接打回
   不等看内容，类型不匹配就拒绝

2. 内容一致性检查
   类型匹配 → 对照 Verification 条件逐条判定

3. 交叉验证（多 Task 间）
   Task A 声称 "POST /login 返回 200"
   Task B 声称 "前端调用 /login 成功"
   → Orchestrator 交叉对比：一致 → 可信度上升；矛盾 → 标记异常

4. 抽查威慑
   每 N 个 Task 随机抽 1 个 → 要求 Builder 提供 L3 级证据
   Builder 不知道哪次会被抽 → 每次都得真的干活
```

---

## 3. 产出交付（output_access）

### 问题

Synapse 不存代码、不执行构建。Task 完成了，客户在**哪里**拿到实际产出？

产出现在依赖 Builder 在评论区手动贴链接，没有结构化交付入口。这是客户体验的最后一公里——验收通过但客户拿不到结果 = 平台对客户无价值。

### output_access 约定（B70 实现）

Builder 提交 evidence 时**必须**包含 `output_access` 字段：

| type | value 格式 | 适用场景 |
|:---|------|------|
| `git_branch` | `"{repo_url}@{branch_name}"` | 代码实现（客户 clone/查看分支） |
| `file_url` | `"{可访问的文件 URL}"` | 设计稿、PDF、图片（客户可直接打开） |
| `web_link` | `"{可访问的网页 URL}"` | 部署预览、在线文档、CI 结果 |
| `inline` | `"{纯文本内容}"` | 文案、分析报告、短文本（客户在 UI 直接阅读） |

**门禁**：
- 无 `output_access` → Orchestrator 拒收，打回要求补充
- `output_access.type` 不在枚举中 → 打回

**客户侧**：Web UI Task 完成卡片显示产出链接，客户一键可达。

---

## 4. 诚实边界

平台无论如何挡不住 Builder 精心伪造一套完整的假证据。这是所有协作系统的共同前提——人类团队同理。

Synapse 的定位是：

> "自动验收通过验证证据与条件的**一致性**来判定完成，而非独立复现执行结果。平台提供证据类型约束、交叉验证和抽查机制来提高可信度。对于需要独立验证的关键任务，建议配置 L3 外部验证型验收条件（如 CI 集成、第三方服务回调）。"

机制让诚实比欺骗更容易，剩下的靠信任积累。

---

## 相关文档

- `docs/templates/role-orchestrator.md` — Orchestrator 验收规程（含证据类型对比 + 交叉验证 + output_access 检查）
- `docs/templates/role-builder.md` — Builder 证据提交规范（含 output_access 必填）
- `docs/templates/_protocol.md` — 证据类型约定 + output_access 规范
- `memory/active/p11.md` — P11 当前状态 + B70 执行范围

# 前端编码约定 — Synapse

> 本文档定义本项目前端开发的具体命令和约定。L2b 层——按技术栈加载。
> 角色职责和操作方法论见 [role-builder.md](role-builder.md)。

## 技术栈

| 层面 | 选型 | 版本 |
|------|------|------|
| 构建 | Vite | 8.x |
| UI | React | 19.x |
| 类型 | TypeScript | 6.x |
| Lint | oxlint | latest |
| 路由 | React Router DOM | 7.x |
| 图标 | lucide-react | latest |

## 目录结构

```
frontend/src/
├── api/            ← API client（client.ts, ws.ts）+ hooks
├── components/     ← 共享 UI 组件
├── contexts/       ← React contexts（AuthContext 等）
├── i18n/           ← 国际化翻译文件
├── pages/          ← 路由级页面组件
├── styles/         ← 全局 CSS
├── utils/          ← 工具函数
├── App.tsx         ← App 根组件 + 路由定义
└── main.tsx        ← 入口（BrowserRouter + createRoot）
```

## 开发命令

| 操作 | 命令 | 工作目录 |
|------|------|:---:|
| 安装依赖 | `npm install` | `frontend/` |
| 启动开发服务器 | `npm run dev` | `frontend/` |
| Lint 检查 | `npm run lint` | `frontend/` |
| 类型检查 + 构建 | `npm run build` | `frontend/` |

**`npm run build` = `tsc -b && vite build`**。先跑 TypeScript 项目引用类型检查，再 Vite 打包。

## TypeScript 约定

- `verbatimModuleSyntax: true` → `import type` 与 `import` 明确分离
- `erasableSyntaxOnly: true` → 不用 `enum`，用 `const` objects 或 union types
- `noUnusedLocals: true` / `noUnusedParameters: true` → 未使用的变量/参数是 error
- `skipLibCheck: true` → 不检查 `.d.ts` 文件
- import 不加 `.tsx` / `.ts` 扩展名（bundler 模块解析自动处理）

## Import 顺序

```typescript
// 1. React 核心
import { useState, useEffect } from 'react'

// 2. 第三方库
import { useNavigate } from 'react-router-dom'

// 3. 共享组件
import { Button } from '../components/Button'

// 4. Contexts
import { useAuth } from '../contexts/AuthContext'

// 5. API / utils
import { apiClient } from '../api/client'
```

## Oxlint 规则

配置文件：`frontend/.oxlintrc.json`

| 规则 | 级别 | 说明 |
|------|:---:|------|
| `react/rules-of-hooks` | error | Hook 必须在组件顶层调用 |
| `react/only-export-components` | warn | 组件文件只导出组件 |

插件：`react` + `typescript` + `oxc`。无 ESLint——oxlint 是唯一的 lint 工具。

## 验证门禁

| 检查项 | 命令 | 阻塞级 |
|--------|------|:---:|
| Oxlint | `cd frontend && npm run lint` | ✅ 阻塞 |
| TypeScript 类型检查 + 构建 | `cd frontend && npm run build` | ✅ 阻塞 |
| 手工浏览器验证 | `npm run dev` → 打开 `localhost:5173` → 走通变更路径 | — |

`make check-frontend` 一键跑完 lint + build。

## 关键约束

- **无前端测试框架**。本项目未配置 vitest/jest/Playwright。前端验证靠 `npm run build` 通过 + 手工浏览器检查。
- **无 CSS 框架**。样式写在 `frontend/src/styles/global.css`。无 Tailwind / styled-components。
- **XSS 防护**：使用 `dompurify` 对用户输入做清理。
- **i18n**：翻译文件在 `frontend/src/i18n/translations.ts`，支持中英文。

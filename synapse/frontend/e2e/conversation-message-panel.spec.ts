import { test, expect } from '@playwright/test'
import {
  loginAsHunter,
  accessCookie,
  seedProjectAndTasks,
  type HunterAuth,
  type SeededProject,
} from './helpers'

// 共享消息正文，串行模式下 test 2 复用 test 1 种下的消息做 resolve/reopen。
const MSG_BODY = 'hello from e2e message panel'

let hunter: HunterAuth
let p: SeededProject

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  p = await seedProjectAndTasks(request, hunter.teamId, `e2e-msgpanel-${stamp}`, [
    { title: 'MsgTask' },
  ])
})

test('发送→渲染→持久：UI composer 发消息 · 断言渲染 + reload 后仍在', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskId = p.taskIds['MsgTask']
  await page.goto(`/tasks/${taskId}`)

  await page.getByTestId('message-input').fill(MSG_BODY)
  await page.getByTestId('message-send').click()

  await expect(page.getByTestId('message-item').filter({ hasText: MSG_BODY })).toBeVisible({ timeout: 15_000 })

  // 持久化：reload 后消息仍在（列表从 GET .../messages 拉取，非内存态）
  await page.reload()
  await expect(page.getByTestId('message-item').filter({ hasText: MSG_BODY })).toBeVisible({ timeout: 15_000 })

  await context.close()
})

test('resolve/reopen：标记已解决 → data-resolved=true + 徽章 → 重新打开', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskId = p.taskIds['MsgTask']
  await page.goto(`/tasks/${taskId}`)

  const item = page.getByTestId('message-item').filter({ hasText: MSG_BODY })
  await expect(item).toBeVisible({ timeout: 15_000 })

  // resolve
  await item.getByTestId('message-toggle-resolve').click()
  await expect(item).toHaveAttribute('data-resolved', 'true')
  await expect(item.getByText('Resolved', { exact: true })).toBeVisible()

  // reopen
  await item.getByTestId('message-toggle-resolve').click()
  await expect(item).toHaveAttribute('data-resolved', 'false')

  await context.close()
})

test('@mention 往返：composer 发含 @worker:<name> 的 body → 正常创建并渲染', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskId = p.taskIds['MsgTask']
  await page.goto(`/tasks/${taskId}`)

  // mention 解析在 create 路径内联执行（parse_mentions → resolve_mentions），
  // 未匹配的 worker 静默跳过、不阻断创建 —— 断言 @ 文本完整渲染即可证 create 路径不 500。
  const body = '@worker:somebody please review this'
  await page.getByTestId('message-input').fill(body)
  await page.getByTestId('message-send').click()

  await expect(page.getByTestId('message-item').filter({ hasText: body })).toBeVisible({ timeout: 15_000 })

  await context.close()
})

test.afterAll(async ({ request }) => {
  try {
    await loginAsHunter(request)
  } catch {
    // Best-effort — residue is namespaced and handled by cleanup-dogfood-residue.py.
  }
})

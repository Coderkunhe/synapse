import { test, expect } from '@playwright/test'
import {
  API_BASE,
  loginAsHunter,
  accessCookie,
  seedProjectAndTasks,
  cancelSeededTasks,
  type HunterAuth,
  type SeededProject,
} from './helpers'

// 共享消息正文，串行模式下 test 2 复用 test 1 种下的消息做 resolve/reopen。
const MSG_BODY = 'hello from e2e message panel'

let hunter: HunterAuth
let p: SeededProject
let clickWorker: { id: string; name: string } | null = null

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  p = await seedProjectAndTasks(request, hunter.teamId, `e2e-msgpanel-${stamp}`, [
    { title: 'MsgTask' },
  ])

  // 注册 + 握手一个 active worker，供 @mention 点击跳转用例使用（DG-2 可复现，
  // 不依赖 dev DB 预置 worker）。register → pending，handshake(api_key) → active。
  const regRes = await request.post(`${API_BASE}/v1/teams/${hunter.teamId}/workers`, {
    headers: { Authorization: `Bearer ${hunter.accessToken}` },
    data: { name: `e2e-click-${stamp}` },
  })
  if (regRes.ok()) {
    const reg = await regRes.json()
    const hsRes = await request.post(`${API_BASE}/v1/workers/${reg.worker.id}/handshake`, {
      headers: { Authorization: `Bearer ${reg.api_key}` },
      data: {},
    })
    if (hsRes.ok()) clickWorker = { id: reg.worker.id, name: reg.worker.name }
  }
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

  // @mention 高亮渲染：@worker:somebody token 应包在 .mentionHighlight span 里
  await expect(page.getByTestId('mention-highlight').filter({ hasText: '@worker:somebody' })).toBeVisible()

  await context.close()
})

test('@mention 点击跳转：@worker:<真实名> 渲染成链接 → 点击跳 WorkerDetail', async ({ browser }) => {
  test.skip(!clickWorker, 'worker registration failed — skip click-through')

  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskId = p.taskIds['MsgTask']
  await page.goto(`/tasks/${taskId}`)

  // 发含真实 active worker 名的 @mention（后跟空格 → name 精确命中，无尾随标点）
  const body = `@worker:${clickWorker.name} please look`
  await page.getByTestId('message-input').fill(body)
  await page.getByTestId('message-send').click()

  const mention = page.getByTestId('mention-highlight').filter({ hasText: `@worker:${clickWorker.name}` })
  await expect(mention).toBeVisible({ timeout: 15_000 })
  // 命中 worker → 渲染成 <a>，href 指向 /workers/<id>
  await expect(mention).toHaveAttribute('href', `/workers/${clickWorker.id}`)

  // 点击跳转 WorkerDetail（URL 落到 /workers/<id>）
  await mention.click()
  await expect(page).toHaveURL(new RegExp(`/workers/${clickWorker.id}`))

  await context.close()
})

test('threading：回复 → data-in-reply-to 非空 + 回复标识渲染', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskId = p.taskIds['MsgTask']
  await page.goto(`/tasks/${taskId}`)

  // 发父消息
  const parentBody = 'threading parent message'
  await page.getByTestId('message-input').fill(parentBody)
  await page.getByTestId('message-send').click()
  const parent = page.getByTestId('message-item').filter({ hasText: parentBody })
  await expect(parent).toBeVisible({ timeout: 15_000 })

  // 点回复 → banner 出现
  await parent.getByTestId('message-reply').click()
  await expect(page.getByTestId('message-reply-banner')).toBeVisible()

  // 发回复
  const replyBody = 'threading reply message'
  await page.getByTestId('message-input').fill(replyBody)
  await page.getByTestId('message-send').click()
  const reply = page.getByTestId('message-item').filter({ hasText: replyBody })
  await expect(reply).toBeVisible({ timeout: 15_000 })

  // 断言回复带 in_reply_to_id（非空）→ threading 已接线
  await expect(reply).toHaveAttribute('data-in-reply-to', /^.+$/)
  // 回复标识（↩ by <sender>）渲染
  await expect(reply.getByText(/↩/)).toBeVisible()

  await context.close()
})

test('mention 三态：等待 → 思考中 → 已回复 ✓', async ({ browser, request }) => {
  const stamp = Date.now().toString(36)

  // 独立 project + 一个停在 backlog 的任务（避免 ready 队列抢占 mention 唤醒：
  // 有 ready 任务时 state-router 落 claim 而非 respond_to_mention）。
  const projRes = await request.post(`${API_BASE}/v1/teams/${hunter.teamId}/projects`, {
    headers: { Authorization: `Bearer ${hunter.accessToken}` },
    data: { name: `e2e-mention-proj-${stamp}`, slug: `e2e-mention-proj-${stamp}` },
  })
  if (!projRes.ok()) throw new Error(`create mention project failed: ${projRes.status()}`)
  const proj = await projRes.json()
  const taskRes = await request.post(`${API_BASE}/v1/projects/${proj.id}/tasks`, {
    headers: { Authorization: `Bearer ${hunter.accessToken}` },
    data: { title: 'mention carrier', description: 'e2e', verifications: [{ type: 'manual', description: 'e2e mention three-state check' }] },
  })
  if (!taskRes.ok()) throw new Error(`create mention task failed: ${taskRes.status()}`)
  const task = await taskRes.json()

  // 注册 + 握手 + 赋 builder 角色
  const regRes = await request.post(`${API_BASE}/v1/teams/${hunter.teamId}/workers`, {
    headers: { Authorization: `Bearer ${hunter.accessToken}` },
    data: { name: `e2e-mention-${stamp}` },
  })
  if (!regRes.ok()) throw new Error(`register worker failed: ${regRes.status()}`)
  const reg = await regRes.json()
  await request.post(`${API_BASE}/v1/workers/${reg.worker.id}/handshake`, {
    headers: { Authorization: `Bearer ${reg.api_key}` },
    data: {},
  })
  const roleRes = await request.post(`${API_BASE}/v1/admin/projects/${proj.id}/roles`, {
    headers: { Authorization: `Bearer ${hunter.accessToken}` },
    data: { worker_id: reg.worker.id, role: 'builder' },
  })
  if (!roleRes.ok()) throw new Error(`assign role failed: ${roleRes.status()}`)

  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()
  await page.goto(`/tasks/${task.id}`)

  // ① 发 @mention → 等待响应
  const body = `@worker:${reg.worker.name} please review`
  await page.getByTestId('message-input').fill(body)
  await page.getByTestId('message-send').click()
  const item = page.getByTestId('message-item').filter({ hasText: body })
  await expect(item).toBeVisible({ timeout: 15_000 })
  await expect(item.getByTestId('mention-state')).toHaveAttribute('data-mention-state', 'waiting')

  // 给 WS 一个订阅窗口（消息走 REST 直刷，WS 订阅在 mount 后异步完成）
  await page.waitForTimeout(500)

  // ② 触发 worker 心跳 → respond_to_mention → 思考中（WS 广播到 team）
  const hbRes = await request.post(`${API_BASE}/v1/workers/${reg.worker.id}/heartbeat`, {
    headers: { Authorization: `Bearer ${reg.api_key}` },
    data: { project_id: proj.id },
  })
  if (!hbRes.ok()) throw new Error(`heartbeat failed: ${hbRes.status()} ${await hbRes.text()}`)
  await expect(item.getByTestId('mention-state')).toHaveAttribute('data-mention-state', 'thinking', { timeout: 15_000 })

  // ③ 回复 → 已回复 ✓
  await item.getByTestId('message-reply').click()
  const replyBody = 'e2e mention reply'
  await page.getByTestId('message-input').fill(replyBody)
  await page.getByTestId('message-send').click()
  await expect(page.getByTestId('message-item').filter({ hasText: replyBody })).toBeVisible({ timeout: 15_000 })
  await expect(item.getByTestId('mention-state')).toHaveAttribute('data-mention-state', 'replied')

  await context.close()
})

// Best-effort cleanup: cancel the seeded MsgTask so the run leaves no owner=None
// `ready` residue in the shared dev DB (PFL-275). Also remove the registered
// click-through worker (DG-3 善后). NOTE: the worker delete FK-fails until
// PFL-276 (mention 关联表缺 ON DELETE CASCADE) is fixed — best-effort, residue
// is namespaced (`e2e-click-<stamp>`).
test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p)
  if (clickWorker) {
    await request.delete(`${API_BASE}/v1/workers/${clickWorker.id}`, {
      headers: { Authorization: `Bearer ${hunter.accessToken}` },
    })
  }
})

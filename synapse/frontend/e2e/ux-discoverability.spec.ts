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

let hunter: HunterAuth
let p1: SeededProject
let p1Name: string

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  // One claimable (ready + no owner) task drives the discoverability deep link.
  p1Name = `E2E Smoke e2e-ux-${stamp}`
  p1 = await seedProjectAndTasks(request, hunter.teamId, `e2e-ux-${stamp}`, [
    { title: 'UX-A' },
  ])
})

test('#1 Dashboard「可认领 N」→ 深链 /tasks?filter=unclaimed', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')

  const projectCard = page.locator(`[data-project-id="${p1.projectId}"]`)
  await expect(projectCard).toBeVisible()

  // `ready` chip is now the claimable deep link. `data-status` stays for e2e.
  const claimable = projectCard.locator('[data-status="ready"]')
  await expect(claimable).toBeVisible()
  await expect(claimable).toHaveAttribute('data-count', '1')

  await claimable.click()

  await expect(page).toHaveURL(/tasks\?project=.*&filter=unclaimed/)
  await expect(page.getByTestId('filter-tab-unclaimed')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('filter-tab-unclaimed')).toHaveAttribute('data-active', 'true')
  // viewTab 仍为 active——?filter 不撞 ?tab=history。
  await expect(page.getByTestId('filter-tab-all')).toHaveAttribute('data-active', 'false')

  await context.close()
})

test('#2 项目详情 tasks tab 渲染任务 board', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto(`/projects/${p1.projectId}`)

  const tasksTab = page.getByTestId('tab-tasks')
  await expect(tasksTab).toBeVisible()
  await tasksTab.click()

  // TaskColumn 的 TaskCard 有 role="link" + aria-label=标题。
  await expect(page.getByRole('link', { name: 'UX-A' })).toBeVisible({ timeout: 15_000 })

  await context.close()
})

test('#3 nav 标签文案自解释（态势 / My Tasks）', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')

  const nav = page.locator('nav')
  await expect(nav.getByText('Situation')).toBeVisible()
  await expect(nav.getByText('My Tasks')).toBeVisible()

  await context.close()
})

test('#4 live 绿点标签在 dashboard/workbench 页头可见', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')
  await expect(page.getByTestId('dashboard-live-label')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dashboard-live-label')).toHaveText('Live')

  await page.goto('/workbench')
  await expect(page.getByTestId('workbench-live-label')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('workbench-live-label')).toHaveText('Live')

  await context.close()
})

test('#5 侧边导航 Teams 入口可见 + 跳转 /teams', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')

  const teamsNav = page.locator('nav').getByText('Teams')
  await expect(teamsNav).toBeVisible({ timeout: 15_000 })
  await teamsNav.click()

  await expect(page).toHaveURL(/\/teams$/)

  await context.close()
})

test('#6 历史任务首载默认折叠，点击批次头才展开', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  // Seed via the authenticated browser context (`page.request` shares its
  // cookies) — the test-scoped `request` fixture has no login cookie.
  const stamp = Date.now().toString(36)
  const p2 = await seedProjectAndTasks(page.request, hunter.teamId, `e2e-uxhist-${stamp}`, [
    { title: 'UX-History' },
  ])
  const taskId = p2.taskIds['UX-History']

  // Cancel the seeded task so it shows up in the history view (completed/cancelled).
  const taskRes = await page.request.get(`${API_BASE}/v1/tasks/${taskId}`)
  const task = await taskRes.json()
  const cancelRes = await page.request.post(`${API_BASE}/v1/tasks/${taskId}/cancel`, {
    data: { expected_version: task.version_no },
  })
  expect(cancelRes.ok()).toBeTruthy()

  // Tasks deep link resolves `project` by *name* (not id) — P17-B34.
  const projectName = `E2E Smoke e2e-uxhist-${stamp}`
  await page.goto(`/tasks?project=${encodeURIComponent(projectName)}&tab=history`)

  // Batch group header is visible (null-batch → "No batch"), but its task rows
  // stay collapsed until the group header is clicked.
  const groupHeader = page.getByText('No batch')
  await expect(groupHeader).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('1 history')).toBeVisible()
  await expect(page.getByRole('link', { name: 'UX-History' })).toHaveCount(0)

  await groupHeader.click()
  await expect(page.getByRole('link', { name: 'UX-History' })).toBeVisible()

  await context.close()
})

test('#7 My Tasks tab 无 worker 下拉即显示本人已认领任务', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  // Claim UX-A as the logged-in human (browser context cookie carries the
  // identity). The mine tab must resolve "me" from /me/tasks — not from the
  // worker filter dropdown.
  const taskA = p1.taskIds['UX-A']
  const claimRes = await page.request.post(`${API_BASE}/v1/tasks/${taskA}/claim`, {
    data: { expected_version: p1.versions[taskA] },
  })
  expect(claimRes.ok()).toBeTruthy()

  // Deep-link into the mine tab WITHOUT selecting any worker in the dropdown.
  await page.goto(`/tasks?project=${encodeURIComponent(p1Name)}&filter=mine`)

  await expect(page.getByTestId('filter-tab-mine')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('filter-tab-mine')).toHaveAttribute('data-active', 'true')

  // The claimed task appears on the board even though the worker filter is empty.
  await expect(page.getByRole('link', { name: 'UX-A' })).toBeVisible({ timeout: 15_000 })

  await context.close()
})

test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p1)
})

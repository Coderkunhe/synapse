import { test, expect } from '@playwright/test'
import {
  loginAsHunter,
  accessCookie,
  seedProjectAndTasks,
  cancelSeededTasks,
  type HunterAuth,
  type SeededProject,
} from './helpers'

let hunter: HunterAuth
let p1: SeededProject

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  // One claimable (ready + no owner) task drives the discoverability deep link.
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

test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p1)
})

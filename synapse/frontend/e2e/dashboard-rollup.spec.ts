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

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  // Single claimable task (no deps) — its status transitions drive the
  // team rollup's real-time refresh (P17-B28).
  p1 = await seedProjectAndTasks(request, hunter.teamId, `e2e-rollup-${stamp}`, [
    { title: 'A' },
  ])
})

test('#1 项目名钻取 → overview 态势 tab（DAG 渲染）', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')

  const taskA = p1.taskIds['A']
  const projectCard = page.locator(`[data-project-id="${p1.projectId}"]`)
  await expect(projectCard).toBeVisible()

  // B27 钻取：点项目名 Link → /projects/:id?tab=overview（团队态势 → 项目态势）。
  // 项目卡内唯一 <a> 即项目名链接（Dashboard.tsx projectNameLink）。
  await projectCard.locator('a').click()
  await expect(page).toHaveURL(new RegExp(`/projects/${p1.projectId}\\?tab=overview`))

  // overview tab 由 ?tab=overview 直接激活（ProjectDetail 初始化 activeTab）→
  // 态势 DAG 渲染，证明钻取真正落地了态势视图，而非只改了 URL。
  await expect(page.getByTestId(`dag-node-${taskA}`)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId(`dag-node-${taskA}`)).toHaveAttribute('data-status', 'ready')

  await context.close()
})

test('#2 团队 rollup live 绿点 + claim 实时变色', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/dashboard')

  // Live dot green → WS connected. P100-B178 (PFL-273): WS onopen can exceed
  // the 15s default under full-suite load — allow 30s.
  await expect(page.getByTestId('dashboard-live-dot')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dashboard-live-dot')).toHaveAttribute('title', 'connected', {
    timeout: 30_000,
  })

  const taskA = p1.taskIds['A']
  const projectCard = page.locator(`[data-project-id="${p1.projectId}"]`)

  // Initial: A is `ready` → project card shows a `ready` chip with count 1.
  await expect(projectCard).toBeVisible()
  await expect(projectCard.locator('[data-status="ready"]')).toHaveAttribute('data-count', '1')

  // Claim A → team rollup refetches (300ms debounce) → chip flips ready→in_progress.
  const claimRes = await page.request.post(`${API_BASE}/v1/tasks/${taskA}/claim`, {
    data: { expected_version: p1.versions[taskA] },
  })
  expect(claimRes.ok()).toBeTruthy()

  await expect(projectCard.locator('[data-status="in_progress"]')).toHaveAttribute(
    'data-count',
    '1',
    { timeout: 10_000 },
  )
  await expect(projectCard.locator('[data-status="ready"]')).toHaveCount(0)

  await context.close()
})

// Best-effort cleanup: cancel the seeded task so the e2e run leaves no
// owner=None `ready` residue in the shared dev DB (PFL-275). The e2e-rollup-*
// project itself is left for review / cleanup-dogfood-residue.py.
test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p1)
})

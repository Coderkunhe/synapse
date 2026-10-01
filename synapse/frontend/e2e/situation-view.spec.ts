import { test, expect } from '@playwright/test'
import {
  API_BASE,
  loginAsHunter,
  accessCookie,
  seedProjectAndTasks,
  type HunterAuth,
  type SeededProject,
} from './helpers'

let hunter: HunterAuth
let p1: SeededProject
let p2: SeededProject

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  // P1: 3-task dependency chain A → B → C (A is the root — claimable).
  p1 = await seedProjectAndTasks(request, hunter.teamId, `e2e-smoke-${stamp}`, [
    { title: 'A' },
    { title: 'B', dependsOn: ['A'] },
    { title: 'C', dependsOn: ['B'] },
  ])
  // P2: isolated project — used to prove cross-project event isolation.
  p2 = await seedProjectAndTasks(request, hunter.teamId, `e2e-smoke-iso-${stamp}`, [
    { title: 'X' },
  ])
})

test('#2 态势 live 绿点 + DAG 渲染', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto(`/projects/${p1.projectId}`)
  await page.getByTestId('tab-overview').click()

  // live dot green → WS connected
  await expect(page.getByTestId('live-dot')).toBeVisible({ timeout: 15_000 })
  // P100-B178 (PFL-273): WS onopen can exceed the 15s default expect timeout
  // under full-suite load (timing contention, not a product bug) — allow 30s.
  await expect(page.getByTestId('live-dot')).toHaveAttribute('title', 'connected', {
    timeout: 30_000,
  })

  // DAG node for task A renders and is `ready`
  const taskA = p1.taskIds['A']
  await expect(page.getByTestId(`dag-node-${taskA}`)).toBeVisible()
  await expect(page.getByTestId(`dag-node-${taskA}`)).toHaveAttribute('data-status', 'ready')

  await context.close()
})

test('#3 claim → DAG 实时变色 + 事件流 prepend + 项目隔离', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto(`/projects/${p1.projectId}`)
  await page.getByTestId('tab-overview').click()
  await expect(page.getByTestId('live-dot')).toBeVisible({ timeout: 15_000 })

  const taskA = p1.taskIds['A']

  // Claim A (root task, no dependencies) — same cookie via page.request.
  const claimRes = await page.request.post(`${API_BASE}/v1/tasks/${taskA}/claim`, {
    data: { expected_version: p1.versions[taskA] },
  })
  expect(claimRes.ok()).toBeTruthy()

  // DAG node turns in_progress WITHOUT a manual refresh (300ms debounce + poll).
  await expect(page.getByTestId(`dag-node-${taskA}`)).toHaveAttribute(
    'data-status',
    'in_progress',
    { timeout: 10_000 },
  )

  // Event stream prepends task.claimed for A at the top.
  const firstRow = page.locator('[data-event-type]').first()
  await expect(firstRow).toHaveAttribute('data-event-type', 'task.claimed', { timeout: 10_000 })
  await expect(firstRow).toHaveAttribute('data-target-id', taskA)

  // Isolation: claim P2's task X → P1's event stream must NOT show X.
  const taskX = p2.taskIds['X']
  const claimX = await page.request.post(`${API_BASE}/v1/tasks/${taskX}/claim`, {
    data: { expected_version: p2.versions[taskX] },
  })
  expect(claimX.ok()).toBeTruthy()
  await page.waitForTimeout(1_000)
  await expect(page.locator(`[data-target-id="${taskX}"]`)).toHaveCount(0)
  // A's claim event stays on top — X did not displace it.
  await expect(page.locator('[data-event-type]').first()).toHaveAttribute('data-target-id', taskA)

  await context.close()
})

// Best-effort cleanup: cancel the claimed smoke tasks. The e2e-smoke-* projects
// themselves are left for review / cleanup-dogfood-residue.py. The `request`
// context is already authenticated from beforeAll's login (its cookie jar), so
// no second login is needed here (P100-B178 · PFL-273 — avoids a 429th login).
test.afterAll(async ({ request }) => {
  try {
    for (const [project, key] of [[p1, 'A'], [p2, 'X']] as const) {
      const taskId = project.taskIds[key]
      const taskRes = await request.get(`${API_BASE}/v1/tasks/${taskId}`)
      if (!taskRes.ok()) continue
      const task = await taskRes.json()
      await request.post(`${API_BASE}/v1/tasks/${taskId}/cancel`, {
        data: { expected_version: task.version_no },
      })
    }
  } catch {
    // Best-effort only — residue is namespaced and handled by cleanup-dogfood-residue.py.
  }
})

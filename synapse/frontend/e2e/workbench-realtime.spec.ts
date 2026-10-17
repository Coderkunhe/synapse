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
  // Single claimable task (no deps). It starts unowned (owner=None), so it is
  // NOT "mine" — claiming it flips ownership to Hunter and drives the
  // workbench's real-time appearance (P17-B30).
  p1 = await seedProjectAndTasks(request, hunter.teamId, `e2e-workbench-${stamp}`, [
    { title: 'A' },
  ])
})

test('#1 工作台 live 绿点 + claim 实时出现', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  await page.goto('/workbench')

  // Live dot green → WS connected. P100-B178 (PFL-273): WS onopen can exceed
  // the 15s default under full-suite load — allow 30s.
  await expect(page.getByTestId('workbench-live-dot')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('workbench-live-dot')).toHaveAttribute('title', 'connected', {
    timeout: 30_000,
  })

  const taskA = p1.taskIds['A']
  const card = page.locator(`[data-task-id="${taskA}"]`)

  // Before claim: A is `ready` + unowned → not in "my tasks".
  await expect(card).toHaveCount(0)

  // Claim A → ownership flips to Hunter → WS `task.claimed` → 300ms debounced
  // refetch → the card appears as `in_progress` without a page reload.
  const claimRes = await page.request.post(`${API_BASE}/v1/tasks/${taskA}/claim`, {
    data: { expected_version: p1.versions[taskA] },
  })
  expect(claimRes.ok()).toBeTruthy()

  await expect(card).toBeVisible({ timeout: 10_000 })
  await expect(card.locator('[data-status="in_progress"]')).toHaveCount(1)

  await context.close()
})

// Best-effort cleanup: cancel the seeded task so the e2e run leaves no
// owner=None `ready` residue in the shared dev DB (PFL-275).
test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p1)
})

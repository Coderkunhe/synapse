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
let p: SeededProject

test.describe.configure({ mode: 'serial' })

test.beforeAll(async ({ request }) => {
  hunter = await loginAsHunter(request)
  const stamp = Date.now().toString(36)
  // Chain DepNode-A ← DepNode-B ← DepNode-C (C depends on B depends on A).
  p = await seedProjectAndTasks(request, hunter.teamId, `e2e-daggraph-${stamp}`, [
    { title: 'DepNode-A' },
    { title: 'DepNode-B', dependsOn: ['DepNode-A'] },
    { title: 'DepNode-C', dependsOn: ['DepNode-B'] },
  ])
})

test('TaskDetail DAG 渲染传递闭包 · 零 N+1（单次 dependency-graph）', async ({ browser }) => {
  const context = await browser.newContext()
  await context.addCookies([accessCookie(hunter.accessToken)])
  const page = await context.newPage()

  const taskC = p.taskIds['DepNode-C']

  // Count bare task-detail requests (GET /v1/tasks/{id}) and dependency-graph calls.
  const taskDetailPaths: string[] = []
  let dependencyGraphCalls = 0
  page.on('request', (req) => {
    const u = new URL(req.url())
    if (u.hostname !== 'localhost' || u.port !== '8000') return
    if (u.pathname.includes('dependency-graph')) dependencyGraphCalls += 1
    const m = u.pathname.match(/^\/v1\/tasks\/([^/]+)$/)
    if (m) taskDetailPaths.push(u.pathname)
  })

  await page.goto(`/tasks/${taskC}`)

  // DAG renders the transitive closure: DepNode-A (layer 2) is NOT in C's direct
  // depends_on list, so it only appears if the BFS walked two levels.
  await expect(page.getByRole('heading', { name: /Dependency Graph/i })).toBeVisible()
  await expect(page.locator('svg text', { hasText: 'DepNode-A' })).toBeVisible({ timeout: 15_000 })

  // No N+1: every bare /v1/tasks/{id} request targets C itself — the dependency
  // tasks (DepNode-A / DepNode-B) are never fetched individually. (TaskDetail
  // legitimately fetches its own detail more than once on mount.)
  expect(taskDetailPaths.every((p) => p === `/v1/tasks/${taskC}`)).toBe(true)

  // And the graph came from the project-scoped endpoint (React dev StrictMode +
  // TaskDetail re-render can legitimately re-run the effect, hence `>= 1`).
  expect(dependencyGraphCalls).toBeGreaterThanOrEqual(1)

  await context.close()
})

// Best-effort cleanup: cancel the seeded DepNode chain so the run leaves no
// owner=None `ready` residue in the shared dev DB (PFL-275).
test.afterAll(async ({ request }) => {
  await cancelSeededTasks(request, hunter.accessToken, p)
})

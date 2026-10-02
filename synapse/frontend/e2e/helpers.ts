import type { APIRequestContext } from '@playwright/test'

/** Backend base URL. Full URLs are used (not `use.baseURL`) so the browser's
 * fetch (CORS, credentials include) and the request context hit :8000 directly. */
export const API_BASE = 'http://localhost:8000'

export interface HunterAuth {
  accessToken: string
  teamId: string
}

export async function loginAsHunter(request: APIRequestContext): Promise<HunterAuth> {
  const email = process.env.SYNAPSE_HUNTER_EMAIL || 'dev@example.com'
  const password = process.env.SYNAPSE_HUNTER_PASSWORD || '__REDACTED_PASSWORD__'
  const res = await request.post(`${API_BASE}/v1/auth/login`, {
    data: { email, password },
  })
  if (!res.ok()) {
    throw new Error(`Hunter login failed: ${res.status()} ${await res.text()}`)
  }
  const body = await res.json()
  return { accessToken: body.access_token, teamId: body.team_id }
}

/** Build the httpOnly access_token cookie to inject into a browser context.
 * Mirrors the backend's `_set_access_cookie` (auth.py:80) — host `localhost`,
 * httpOnly, samesite lax. Path defaults to `/` (superset of `/v1`, still sent
 * to the WS handshake at /v1/ws). */
export function accessCookie(accessToken: string) {
  return {
    name: 'access_token',
    value: accessToken,
    url: 'http://localhost:8000',
    httpOnly: true,
    sameSite: 'Lax' as const,
  }
}

export interface SeedTask {
  title: string
  dependsOn?: string[]
}

export interface SeededProject {
  projectId: string
  taskIds: Record<string, string>
  versions: Record<string, number>
}

/** Seed a namespaced project + tasks, then ready each task. Returns the project
 * id, title→taskId, and taskId→current version (post-ready). */
export async function seedProjectAndTasks(
  request: APIRequestContext,
  teamId: string,
  slug: string,
  tasks: SeedTask[],
): Promise<SeededProject> {
  const projRes = await request.post(`${API_BASE}/v1/teams/${teamId}/projects`, {
    data: { name: `E2E Smoke ${slug}`, slug },
  })
  if (!projRes.ok()) {
    throw new Error(`create project failed: ${projRes.status()} ${await projRes.text()}`)
  }
  const project = await projRes.json()
  const projectId: string = project.id

  const taskIds: Record<string, string> = {}
  const versions: Record<string, number> = {}

  for (const t of tasks) {
    const taskRes = await request.post(`${API_BASE}/v1/projects/${projectId}/tasks`, {
      data: {
        title: t.title,
        description: `E2E smoke task: ${t.title}`,
        verifications: [{ type: 'manual', description: 'E2E smoke verification' }],
        ...(t.dependsOn && t.dependsOn.length > 0
          ? { depends_on: t.dependsOn.map(id => ({ task_id: taskIds[id], type: 'sequential' })) }
          : {}),
      },
    })
    if (!taskRes.ok()) {
      throw new Error(`create task "${t.title}" failed: ${taskRes.status()} ${await taskRes.text()}`)
    }
    const task = await taskRes.json()
    taskIds[t.title] = task.id

    const readyRes = await request.post(`${API_BASE}/v1/tasks/${task.id}/ready`, {
      data: { expected_version: task.version_no },
    })
    if (!readyRes.ok()) {
      throw new Error(`ready task "${t.title}" failed: ${readyRes.status()} ${await readyRes.text()}`)
    }
    const readyTask = await readyRes.json()
    versions[task.id] = readyTask.version_no
  }

  return { projectId, taskIds, versions }
}

/** Best-effort cancel every task in a seeded project, so an e2e run leaves no
 * owner=None `ready` residue in the shared dev DB (PFL-275). Generalizes the
 * situation-view afterAll — cancels ALL tasks, not just the claimable roots,
 * because dependent tasks (B/C/etc.) are left `ready` otherwise.
 *
 * Authenticates via `Authorization: Bearer` rather than the cookie jar: the
 * Playwright `request` fixture is isolated per hook, so the login cookie set in
 * `beforeAll` is NOT carried into `afterAll` (a GET there returns 401). Each
 * task's current version is re-read via GET (a claim in a prior test may have
 * bumped it past the seeded snapshot in `SeededProject.versions`). */
export async function cancelSeededTasks(
  request: APIRequestContext,
  accessToken: string,
  project: SeededProject,
): Promise<void> {
  const auth = { Authorization: `Bearer ${accessToken}` }
  try {
    for (const taskId of Object.values(project.taskIds)) {
      const taskRes = await request.get(`${API_BASE}/v1/tasks/${taskId}`, { headers: auth })
      if (!taskRes.ok()) continue
      const task = await taskRes.json()
      await request.post(`${API_BASE}/v1/tasks/${taskId}/cancel`, {
        headers: auth,
        data: { expected_version: task.version_no },
      })
    }
  } catch {
    // Best-effort only — residue is namespaced and handled by cleanup-dogfood-residue.py.
  }
}

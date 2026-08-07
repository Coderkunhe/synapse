export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ── Feature flags (S-015 极简模式) ──────────────────────────────────────────

export interface Features {
  project_count: number
  batch_size: number
  teams: boolean
}

export async function fetchFeatures(): Promise<Features> {
  const res = await fetch(`${API_BASE}/v1/features`)
  if (!res.ok) throw new Error(`Failed to fetch features: ${res.status}`)
  return res.json()
}

// ── Request helpers ──────────────────────────────────────────────────────────

interface RequestOptions {
  token?: string
}

async function request<T>(path: string, options: RequestInit & RequestOptions = {}): Promise<T> {
  const { token, ...fetchOptions } = options
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers as Record<string, string>),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...fetchOptions,
    headers,
    credentials: 'include',
  })
  if (!res.ok) {
    // 401 on /v1/auth/me means "not logged in yet" — caller handles it
    // 401 on any other endpoint means session expired → redirect to login
    if (res.status === 401 && path !== '/v1/auth/me') {
      window.location.href = '/login'
      throw new ApiError(401, { detail: 'Session expired — redirecting to login' })
    }
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

export class ApiError extends Error {
  status: number
  code: string | null
  body: unknown
  constructor(status: number, body: unknown) {
    const bodyObj = body as Record<string, unknown> | undefined
    // Server returns {error: {code: "...", message: "..."}} (SynapseError format)
    // or {detail: "..."} (FastAPI default)
    const msg =
      (bodyObj?.error as Record<string, unknown> | undefined)?.message ||
      (bodyObj?.detail as string) ||
      `HTTP ${status}`
    super(String(msg))
    this.status = status
    this.code =
      ((bodyObj?.error as Record<string, unknown> | undefined)?.code as string) ||
      null
    this.body = body
  }
}

// ── Projects ──────────────────────────────────────────────

export interface ProjectSummary {
  id: string
  team_id: string
  name: string
  slug: string
  description: string | null
  status: string
  default_branch: string | null
  git_repo_url: string | null
  api_docs_url: string | null
  frontend_test_url: string | null
  use_phase_mode: boolean
  current_phase: string | null
  organization: string | null
  metadata: Record<string, unknown> | null
  is_protected: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
}

export function fetchProjects(
  teamId: string,
  token: string,
  params?: { cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: ProjectSummary[]; next_cursor: string | null; total: number }>(
    `/v1/teams/${teamId}/projects${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function fetchProject(projectId: string, token: string) {
  return request<ProjectSummary>(`/v1/projects/${projectId}`, { token })
}

export function createProject(
  teamId: string,
  body: {
    name: string
    slug: string
    description?: string
    default_branch?: string
    git_repo_url?: string
    api_docs_url?: string
    frontend_test_url?: string
    use_phase_mode?: boolean
    current_phase?: string
    organization?: string
    metadata?: Record<string, unknown>
  },
  token: string,
) {
  return request<ProjectSummary>(`/v1/teams/${teamId}/projects`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

export function updateProject(
  projectId: string,
  body: {
    name?: string
    description?: string
    default_branch?: string
    git_repo_url?: string
    api_docs_url?: string
    frontend_test_url?: string
    use_phase_mode?: boolean
    current_phase?: string
    organization?: string
    metadata?: Record<string, unknown>
  },
  token: string,
) {
  return request<ProjectSummary>(`/v1/projects/${projectId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(body),
  })
}

export function archiveProject(projectId: string, token: string) {
  return request<ProjectSummary>(`/v1/projects/${projectId}/archive`, {
    method: 'POST',
    token,
  })
}

export function toggleProjectProtection(projectId: string, isProtected: boolean, token: string) {
  return request<ProjectSummary>(`/v1/projects/${projectId}/protection`, {
    method: 'PATCH',
    token,
    body: JSON.stringify({ is_protected: isProtected }),
  })
}

export function deleteProject(projectId: string, token: string) {
  return request<void>(`/v1/projects/${projectId}`, {
    method: 'DELETE',
    token,
  })
}

/** Resolve a project by name — find existing or auto-create (P9-B1). */
export function resolveProject(name: string, token: string) {
  return request<ProjectSummary>(
    `/v1/projects/resolve?name=${encodeURIComponent(name)}`,
    { method: 'POST', token },
  )
}

// ── Project Roles ──────────────────────────────────────────

export interface ProjectRoleEntry {
  worker_id: string
  worker_name: string
  role: string
}

/** List all worker-role assignments in a project (team admin only). */
export function fetchProjectRoles(projectId: string, token: string) {
  return request<{ project_id: string; roles: ProjectRoleEntry[] }>(
    `/v1/admin/projects/${projectId}/roles`,
    { token },
  )
}

/** Get the current actor's role in a project (P12-B18: for frontend permission checks). */
export function fetchMyProjectRole(projectId: string, token: string) {
  return request<{ role: string | null; is_super_admin: boolean }>(
    `/v1/projects/${projectId}/my-role`,
    { token },
  )
}

/** Assign (or update) a worker's role in a project (team admin only). */
export function assignProjectRole(projectId: string, workerId: string, role: string, token: string) {
  return request<ProjectRoleEntry>(
    `/v1/admin/projects/${projectId}/roles`,
    { method: 'POST', token, body: JSON.stringify({ worker_id: workerId, role }) },
  )
}

/** Revoke a worker's role in a project (team admin only). */
export function revokeProjectRole(projectId: string, workerId: string, token: string) {
  return request<void>(
    `/v1/admin/projects/${projectId}/roles/${workerId}`,
    { method: 'DELETE', token },
  )
}

// ── Batches ────────────────────────────────────────────────

export interface BatchSummary {
  id: string
  project_id: string
  name: string
  description: string | null
  status: string
  order: number | null
  phase: string | null
  batch_number: number | null
  assigned_to: string | null
  created_at: string
  updated_at: string
  completed_at: string | null
}

export function fetchBatches(
  projectId: string,
  token: string,
  params?: { cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: BatchSummary[]; next_cursor: string | null; total: number }>(
    `/v1/projects/${projectId}/batches${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function fetchBatch(batchId: string, token: string) {
  return request<BatchSummary>(`/v1/batches/${batchId}`, { token })
}

export function createBatch(
  projectId: string,
  body: {
    name: string
    description?: string
    order?: number
    phase?: string
    batch_number?: number
  },
  token: string,
) {
  return request<BatchSummary>(`/v1/projects/${projectId}/batches`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

// ── Dashboard ─────────────────────────────────────────────

export interface TeamStats {
  team_id: string
  worker_count: number
  active_task_count: number
  project_count: number
  today_event_count: number
  total_tokens: number
  total_token_requests: number
  week_tokens: number
}

export function fetchTeamStats(teamId: string, token: string) {
  return request<TeamStats>(`/v1/dashboard/teams/${teamId}/stats`, { token })
}

// ── Dashboard: Project Breakdown ─────────────────────────────────────

export interface ProjectBreakdown {
  project_id: string
  project_name: string
  total_tasks: number
  completed_tasks: number
  by_status: {
    backlog: number
    ready: number
    in_progress: number
    in_verification: number
    completed: number
    cancelled: number
  }
}

export interface ProjectsBreakdownResponse {
  team_id: string
  projects: ProjectBreakdown[]
}

export function fetchProjectsBreakdown(teamId: string, token: string) {
  return request<ProjectsBreakdownResponse>(`/v1/dashboard/teams/${teamId}/projects-breakdown`, { token })
}

// ── Tasks ─────────────────────────────────────────────────

export interface TaskSummary {
  id: string
  title: string
  status: string
  priority: string
  owner_type: string | null
  owner_id: string | null
  version_no: number
  batch_id: string | null
  tags: string[] | null
  depends_on: Array<{ task_id: string; type?: string }> | null
  deadline_at: string | null
  is_overdue: boolean
  completed_at: string | null
  created_at: string
}

export interface TaskDetail {
  id: string
  project_id: string
  title: string
  description: string | null
  status: string
  priority: string
  owner_type: string | null
  owner_id: string | null
  parent_task_id: string | null
  batch_id: string | null
  estimated_effort: string | null
  tags: string[] | null
  depends_on: Array<{ task_id: string; type?: string }> | null
  metadata: Record<string, unknown> | null
  version_no: number
  deadline_at: string | null
  is_overdue: boolean
  completed_at: string | null
  created_at: string
  updated_at: string
}

export type TaskStatus = 'backlog' | 'ready' | 'in_progress' | 'in_verification' | 'completed' | 'cancelled' | 'rejected'

export function fetchTasks(projectId: string, token: string, opts?: {
  ownerId?: string
  batchId?: string
  search?: string
  status?: string
  cursor?: string
  limit?: number
}) {
  const params = new URLSearchParams({ limit: String(opts?.limit ?? 100) })
  if (opts?.ownerId) params.set('owner_id', opts.ownerId)
  if (opts?.batchId) params.set('batch_id', opts.batchId)
  if (opts?.search) params.set('search', opts.search)
  if (opts?.status) params.set('status', opts.status)
  if (opts?.cursor) params.set('cursor', opts.cursor)
  return request<{ items: TaskSummary[]; total: number; next_cursor: string | null }>(
    `/v1/projects/${projectId}/tasks?${params}`,
    { token },
  )
}

export function fetchTask(taskId: string, token: string) {
  return request<TaskDetail>(`/v1/tasks/${taskId}`, { token })
}

export function createTask(
  projectId: string,
  body: {
    title: string
    description: string
    priority?: string
    parent_task_id?: string
    batch_id?: string
    estimated_effort?: string
    tags?: string[]
    metadata?: Record<string, unknown>
    deadline_at?: string
    depends_on?: Array<{
      task_id: string
      type: string
    }>
    verifications?: Array<{
      type: string
      description: string
      criteria?: Record<string, unknown>
    }>
  },
  token: string,
) {
  return request<TaskDetail>(`/v1/projects/${projectId}/tasks`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

export function claimTask(taskId: string, expectedVersion: number, token: string) {
  return request<TaskDetail>(`/v1/tasks/${taskId}/claim?expected_version=${expectedVersion}`, {
    method: 'POST',
    token,
  })
}

export function updateTask(
  taskId: string,
  body: {
    title?: string
    description?: string
    priority?: string
    estimated_effort?: string
    tags?: string[]
    deadline_at?: string
    expected_version: number
  },
  token: string,
) {
  return request<TaskDetail>(`/v1/tasks/${taskId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(body),
  })
}

export function cancelTask(taskId: string, expectedVersion: number, token: string) {
  return request<TaskDetail>(`/v1/tasks/${taskId}/cancel?expected_version=${expectedVersion}`, {
    method: 'POST',
    token,
  })
}

export function readyTask(taskId: string, expectedVersion: number, token: string) {
  return request<TaskDetail>(`/v1/tasks/${taskId}/ready?expected_version=${expectedVersion}`, {
    method: 'POST',
    token,
  })
}

export function submitTask(
  taskId: string,
  body: { summary: string; evidence?: Record<string, unknown>; expected_version: number },
  token: string,
) {
  return request<TaskDetail>(`/v1/tasks/${taskId}/submit`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

// ── Batch operations (P9-B72, S-033) ──────────────────────────

export interface BatchOperationError {
  task_id: string
  error: string
}

export interface BatchOperationResponse {
  updated_count: number
  failed_count: number
  task_ids: string[]
  errors: BatchOperationError[]
  claimed_count?: number  // assign-batch endpoint uses claimed_count instead of updated_count
}

export function batchReadyTasks(taskIds: string[], token: string) {
  return request<BatchOperationResponse>('/v1/tasks/batch-ready', {
    method: 'POST',
    token,
    body: JSON.stringify({ task_ids: taskIds }),
  })
}

export function batchUpdateTasks(
  taskIds: string[],
  updates: { priority?: string; estimated_effort?: string; tags?: string[]; deadline_at?: string },
  token: string,
) {
  return request<BatchOperationResponse>('/v1/tasks/batch-update', {
    method: 'POST',
    token,
    body: JSON.stringify({ task_ids: taskIds, ...updates }),
  })
}

export function assignBatchTasks(
  taskIds: string[],
  ownerType: 'member' | 'worker',
  ownerId: string,
  token: string,
) {
  return request<BatchOperationResponse>('/v1/tasks/assign-batch', {
    method: 'POST',
    token,
    body: JSON.stringify({ task_ids: taskIds, owner_type: ownerType, owner_id: ownerId }),
  })
}

// ── Verifications ──────────────────────────────────────────

export interface VerificationResponse {
  id: string
  task_id: string
  type: string
  description: string
  criteria: Record<string, unknown> | null
  status: string
  verified_by: string | null
  verified_at: string | null
  evidence: Record<string, unknown> | null
  rejection_reason: string | null
  review_flag: boolean
  auto_approved: boolean
}

export function fetchVerifications(taskId: string, token: string) {
  return request<VerificationResponse[]>(`/v1/tasks/${taskId}/verifications`, { token })
}

export function verifyVerification(
  verificationId: string,
  body: {
    status: string
    comment?: string
    evidence?: Record<string, unknown>
    rejection_reason?: string
    expected_task_version: number
  },
  token: string,
) {
  return request<VerificationResponse>(`/v1/verifications/${verificationId}/verify`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

// ── Workers ────────────────────────────────────────────────

export interface WorkerSummary {
  id: string
  name: string
  provider: string
  provider_model: string | null
  status: string
  is_disabled: boolean
  metadata: Record<string, unknown> | null
  batch_size: number
  active_task_count: number
  completed_task_count: number
  active_batches: number
}

export interface WorkerDetail extends WorkerSummary {
  team_id: string
  system_prompt: string | null
  batch_size: number
  created_at: string
  updated_at: string
}

export interface WorkerCreatePayload {
  name: string
  provider?: string
  provider_model?: string | null
  system_prompt?: string | null
  metadata?: Record<string, unknown> | null
  batch_size?: number
}

export interface WorkerCreateResponse {
  worker: WorkerDetail
  api_key: string
}

export function fetchWorkers(teamId: string, token: string, params?: { status?: string }) {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  const qs = searchParams.toString()
  return request<{ items: WorkerSummary[]; total: number }>(
    `/v1/teams/${teamId}/workers${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function createWorker(teamId: string, body: WorkerCreatePayload, token: string) {
  return request<WorkerCreateResponse>(`/v1/teams/${teamId}/workers`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

export function fetchWorker(workerId: string, token: string) {
  return request<WorkerDetail>(`/v1/workers/${workerId}`, { token })
}

export function suspendWorker(workerId: string, token: string) {
  return request<WorkerDetail>(`/v1/workers/${workerId}/suspend`, {
    method: 'POST',
    token,
  })
}

export function resumeWorker(workerId: string, token: string) {
  return request<WorkerDetail>(`/v1/workers/${workerId}/resume`, {
    method: 'POST',
    token,
  })
}

export function deleteWorker(workerId: string, token: string) {
  return request<void>(`/v1/workers/${workerId}`, {
    method: 'DELETE',
    token,
  })
}

export function workerHandshake(workerId: string, token: string, body: {
  workerVersion: string
  capabilities: Array<{ name: string; description: string }>
  supportedEvents: string[]
  preferredChannel: string
}) {
  return request<WorkerDetail>(`/v1/workers/${workerId}/handshake`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

// ── Token Usage ───────────────────────────────────────────

export interface TokenUsageResponse {
  id: string
  worker_id: string
  task_id: string | null
  project_id: string | null
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost: string | null
  request_id: string | null
  recorded_at: string
  metadata: Record<string, unknown> | null
  // AuditFields
  is_disabled: boolean
  create_user_id: string
  last_update_user_id: string | null
  remark: string | null
  version_no: number
  created_at: string
  updated_at: string
}

export function fetchTokenUsage(
  workerId: string,
  token: string,
  params?: { cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: TokenUsageResponse[]; next_cursor: string | null; total: number }>(
    `/v1/workers/${workerId}/token-usage${qs ? `?${qs}` : ''}`,
    { token },
  )
}

// ── Token Usage Stats (B54) ──────────────────────────────

export interface TokenUsageDaily {
  date: string
  tokens: number
  requests: number
}

export interface TokenUsageStats {
  worker_id: string
  total_tokens: number
  total_requests: number
  model_count: number
  providers: Record<string, number>
  models: Record<string, number>
  daily: TokenUsageDaily[]
}

export function fetchTokenUsageStats(workerId: string, token: string) {
  return request<TokenUsageStats>(`/v1/workers/${workerId}/token-usage/stats`, { token })
}

/** Download rendered SKILL.md as a Blob (for file download — not JSON). */
export async function downloadSkillBlob(
  workerId: string,
  projectId: string,
  token: string,
): Promise<Blob> {
  const res = await fetch(
    `${API_BASE}/v1/workers/${workerId}/skill/download?project_id=${encodeURIComponent(projectId)}`,
    {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    },
  )
  if (!res.ok) {
    if (res.status === 401) {
      window.location.href = '/login'
      throw new ApiError(401, { detail: 'Session expired — redirecting to login' })
    }
    throw new ApiError(res.status, { detail: res.statusText })
  }
  return res.blob()
}

// ── Auth ──────────────────────────────────────────────────

export interface AuthStatusResponse {
  authenticated: boolean
  member_id: string | null
  team_id: string | null
  role: string | null
  display_name: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: string
  member_id: string
  team_id: string
  role: string
  display_name: string
  expires_in: number
}

export function fetchAuthMe(token?: string) {
  return request<AuthStatusResponse>('/v1/auth/me', { token })
}

/** Refresh the access token using the httpOnly refresh_token cookie. */
export function refreshAccessToken() {
  return request<TokenResponse>('/v1/auth/refresh', {
    method: 'POST',
    credentials: 'include',
  })
}

/** Dev-mode auto-login — returns a token for the default admin user. */
export function fetchDevToken() {
  return request<TokenResponse>('/v1/auth/dev-token')
}

/** Logout — revoke refresh token (cookie-based). */
export function logoutRequest() {
  return request<void>('/v1/auth/logout', { method: 'POST', credentials: 'include' })
}

/** Email/Password login — backend sets httpOnly cookie on success. */
export function loginWithEmail(email: string, password: string) {
  return request<TokenResponse>('/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  })
}

/** Email/Password registration — backend sets httpOnly cookie on success. */
export function registerUser(email: string, password: string, displayName: string) {
  return request<TokenResponse>('/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({
      email: email.trim().toLowerCase(),
      password,
      display_name: displayName.trim(),
    }),
  })
}

/** Password Reset — request a reset link for the given email. */
export function forgotPassword(email: string) {
  return request<{ message: string; reset_token?: string }>(
    '/v1/auth/forgot-password',
    {
      method: 'POST',
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    },
  )
}

/** Password Reset — complete the reset with a token and new password. */
export function resetPassword(token: string, newPassword: string) {
  return request<{ message: string }>('/v1/auth/reset-password', {
    method: 'POST',
    body: JSON.stringify({ token, new_password: newPassword }),
  })
}

// ── Docs ──────────────────────────────────────────────────

export interface DocItem {
  filename: string
  exists: boolean
}

export interface DocGroup {
  key: string
  labelKey: string
  items: DocItem[]
}

export interface DocContent {
  filename: string
  content: string
  content_type: 'markdown' | 'html'
}

export function fetchDocList(token: string) {
  return request<{ groups: DocGroup[] }>('/v1/docs', { token })
}

export function fetchDocContent(filename: string, token: string) {
  return request<DocContent>(
    `/v1/docs/${encodeURIComponent(filename)}?format=html`,
    { token },
  )
}

// ── Events ────────────────────────────────────────────────

export interface EventSummary {
  id: string
  event_type: string
  actor_type: string
  actor_id: string
  target_type: string
  target_id: string
  payload: Record<string, unknown>
  created_at: string
}

// ── Analyses ──────────────────────────────────────────────

export interface AnalysisSummary {
  id: string
  project_id: string
  actor_type: string
  actor_id: string
  analysis_type: string
  title: string
  content: string
  source_batch_id: string | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export function fetchAnalyses(
  projectId: string,
  token: string,
  params?: { analysis_type?: string; cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.analysis_type) searchParams.set('analysis_type', params.analysis_type)
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: AnalysisSummary[]; next_cursor: string | null; total: number }>(
    `/v1/projects/${projectId}/analyses${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function createAnalysis(
  projectId: string,
  body: {
    analysis_type: string
    title: string
    content: string
    source_batch_id?: string
    metadata?: Record<string, unknown>
  },
  token: string,
) {
  return request<AnalysisSummary>(`/v1/projects/${projectId}/analyses`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

export function fetchTeamEvents(teamId: string, token: string) {
  return request<{ items: EventSummary[] }>(
    `/v1/teams/${teamId}/events?limit=20`,
    { token },
  )
}

// ── Compliance Scans ───────────────────────────────────────

export interface ScanVerdict {
  rule_id: string
  status: string
  detail: string
}

export interface ScanSummary {
  pass: number
  fail: number
  warn: number
}

export interface ScanDetail {
  id: string
  target_type: string
  target_id: string
  actor_type: string
  actor_id: string
  rules_checked: ScanVerdict[]
  summary: ScanSummary
  created_at: string
  updated_at: string
}

export function fetchScans(
  teamId: string,
  token: string,
  params?: { target_type?: string; cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.target_type) searchParams.set('target_type', params.target_type)
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: ScanDetail[]; next_cursor: string | null; total: number }>(
    `/v1/teams/${teamId}/scans${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function fetchScan(scanId: string, token: string) {
  return request<ScanDetail>(`/v1/scans/${scanId}`, { token })
}

export function executeScan(targetType: string, targetId: string, token: string) {
  return request<ScanDetail>(`/v1/scans/${targetType}/${targetId}`, {
    method: 'POST',
    token,
  })
}

// ── Skills ──────────────────────────────────────────────────

export interface SkillSummary {
  id: string
  team_id: string
  name: string
  version: string
  status: string
  template_md: string
  protocol_spec: Record<string, unknown> | null
  scan_rule_ids: string[] | null
  metadata: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export function fetchSkills(
  teamId: string,
  token: string,
  params?: { status?: string; cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: SkillSummary[]; next_cursor: string | null; total: number }>(
    `/v1/teams/${teamId}/skills${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function fetchSkill(skillId: string, token: string) {
  return request<SkillSummary>(`/v1/skills/${skillId}`, { token })
}

export function createSkill(
  teamId: string,
  body: {
    name: string
    version?: string
    template_md: string
    protocol_spec?: Record<string, unknown>
    scan_rule_ids?: string[]
    metadata?: Record<string, unknown>
  },
  token: string,
) {
  return request<SkillSummary>(`/v1/teams/${teamId}/skills`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

// ── Teams ──────────────────────────────────────────────────

export interface TeamResponse {
  id: string
  name: string
  slug: string
  description: string | null
  avatar_url: string | null
  is_disabled: boolean
  create_user_id: string
  last_update_user_id: string | null
  remark: string | null
  version_no: number
  created_at: string
  updated_at: string
}

export function fetchTeam(teamId: string, token: string) {
  return request<TeamResponse>(`/v1/teams/${teamId}`, { token })
}

export function updateTeam(
  teamId: string,
  body: { name?: string; description?: string; avatar_url?: string },
  token: string,
) {
  return request<TeamResponse>(`/v1/teams/${teamId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(body),
  })
}

// ── Members ──────────────────────────────────────────────────

export interface MemberResponse {
  id: string
  team_id: string
  user_id: string
  display_name: string
  role: string
  joined_at: string
  last_active_at: string | null
  is_disabled: boolean
  create_user_id: string
  last_update_user_id: string | null
  remark: string | null
  version_no: number
  created_at: string
  updated_at: string
}

export function fetchMembers(
  teamId: string,
  token: string,
  params?: { cursor?: string; limit?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  const qs = searchParams.toString()
  return request<{ items: MemberResponse[]; next_cursor: string | null; total: number }>(
    `/v1/teams/${teamId}/members${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function inviteMember(
  teamId: string,
  body: { user_id: string; display_name: string; role?: string },
  token: string,
) {
  return request<MemberResponse>(`/v1/teams/${teamId}/members`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  })
}

export function removeMember(teamId: string, memberId: string, token: string) {
  return request<void>(`/v1/teams/${teamId}/members/${memberId}`, {
    method: 'DELETE',
    token,
  })
}

export function updateSkill(
  skillId: string,
  body: {
    name?: string
    version?: string
    status?: string
    template_md?: string
    protocol_spec?: Record<string, unknown>
    scan_rule_ids?: string[]
    metadata?: Record<string, unknown>
  },
  token: string,
) {
  return request<SkillSummary>(`/v1/skills/${skillId}`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(body),
  })
}

// ── WebPush / Push Notifications (P10-B45) ────────────────────────

export interface PushSubscriptionPayload {
  endpoint: string
  keys: { p256dh: string; auth: string }
  device_info?: string
}

export interface PushSubscriptionResponse {
  id: string
  user_id: string
  endpoint: string
  device_info: string | null
  is_disabled: boolean
  created_at: string
  updated_at: string
}

export interface VapidPublicKeyInfo {
  vapid_public_key: string
  vapid_claims_email: string
}

export function fetchVapidPublicKey() {
  return request<VapidPublicKeyInfo>('/v1/webpush/vapid-public-key')
}

export function subscribePush(body: PushSubscriptionPayload) {
  return request<PushSubscriptionResponse>('/v1/webpush/subscribe', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function unsubscribePush(endpoint: string) {
  return request<void>('/v1/webpush/subscribe', {
    method: 'DELETE',
    body: JSON.stringify({ endpoint }),
  })
}

export function fetchPushSubscriptions() {
  return request<PushSubscriptionResponse[]>('/v1/webpush/subscriptions')
}

// ── Authorization Requests (P10-B23) ──────────────────────────

export interface AuthRequestSummary {
  id: string
  project_id: string
  worker_id: string
  worker_name: string | null
  request_type: string
  operation: string | null
  target_resource_type: string | null
  target_resource_id: string | null
  target_resource_name: string | null
  prompt_type: string | null
  prompt_message: string | null
  prompt_choices: string[] | null
  status: string
  responded_by_worker_id: string | null
  responded_by_worker_name: string | null
  responded_at: string | null
  response_note: string | null
  response_data: string | null
  expires_at: string
  last_heartbeat_at: string
  created_at: string
  updated_at: string
  // capability_exec 字段组（P11-B49 前端适配）
  capability_id: string | null
  outcome: string | null
  exit_code: number | null
  duration_ms: number | null
}

export function fetchAuthRequests(
  projectId: string,
  token: string,
  params?: { status?: string; limit?: number; offset?: number },
) {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.set('status', params.status)
  if (params?.limit) searchParams.set('limit', String(params.limit))
  if (params?.offset) searchParams.set('offset', String(params.offset))
  const qs = searchParams.toString()
  return request<AuthRequestSummary[]>(
    `/v1/projects/${projectId}/authorization-requests${qs ? `?${qs}` : ''}`,
    { token },
  )
}

export function respondToAuthRequest(
  requestId: string,
  body: { status: string; response_note?: string; response_data?: string },
  token: string,
) {
  return request<AuthRequestSummary>(`/v1/authorization-requests/${requestId}/respond`, {
    method: 'PATCH',
    token,
    body: JSON.stringify(body),
  })
}

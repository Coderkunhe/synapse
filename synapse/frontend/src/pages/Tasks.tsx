import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Lock, ClipboardList, X, Search, Check, Loader2, Clock } from 'lucide-react'
import TaskColumn from '../components/TaskColumn'
import HistoryList from '../components/HistoryList'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import BatchSelect from '../components/BatchSelect'
import { fetchTasks, fetchBatches, fetchWorkers, createTask, cancelTask, resolveProject, readyTask, claimTask, batchReadyTasks, batchUpdateTasks, assignBatchTasks, ApiError } from '../api/client'
import type { TaskSummary, WorkerSummary } from '../api/client'
import type { TaskDetail } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useFeatures } from '../contexts/FeaturesContext'
import { useI18n } from '../contexts/I18nContext'
import styles from './Tasks.module.css'

const PRIORITIES = ['p0', 'p1', 'p2', 'p3']
const EFFORTS = ['xs', 's', 'm', 'l', 'xl']
const VERIFY_TYPES = ['manual', 'automated', 'check_list']

interface VerificationInput {
  type: string
  description: string
}

interface DependsOnInput {
  task_id: string
  type: 'sequential' | 'artifact'
}

export default function Tasks() {
  const { t } = useI18n()
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<{ message: string; status?: number } | null>(null)
  const [projectId, setProjectId] = useState<string | null>(null)
  const [projectName, setProjectName] = useState('')
  const [resolving, setResolving] = useState(false)
  const { token, teamId } = useAuth()
  const { isMinimalBatch } = useFeatures()
  const [searchParams, setSearchParams] = useSearchParams()

  const STATUS_COLUMNS = [
    { status: 'backlog', label: t('tasks.columns.backlog') },
    { status: 'ready', label: t('tasks.columns.ready') },
    { status: 'in_progress', label: t('tasks.columns.inProgress') },
    { status: 'in_verification', label: t('tasks.columns.inVerification') },
  ]

  // ── Auto-resolve project ────────────────────────────────

  const doResolve = useCallback(async (name: string) => {
    if (!token) return null
    setResolving(true)
    try {
      const proj = await resolveProject(name, token)
      localStorage.setItem('synapse_project_id', proj.id)
      localStorage.setItem('synapse_project_name', name)
      setProjectId(proj.id)
      setProjectName(name)
      return proj.id
    } catch (err) {
      console.error('Failed to resolve project', err)
      setError({ message: t('tasks.resolveProjectError') })
      return null
    } finally {
      setResolving(false)
    }
  }, [token])

  useEffect(() => {
    if (!token || !teamId) return
    // P17-B34: ?project=<name> deep-link wins over localStorage restore.
    const projectParam = searchParams.get('project')
    if (projectParam) {
      doResolve(projectParam)
      return
    }
    const savedId = localStorage.getItem('synapse_project_id')
    if (savedId) {
      setProjectId(savedId)
      // Restore project name too (saved by doResolve)
      const savedName = localStorage.getItem('synapse_project_name') || ''
      setProjectName(savedName)
      return
    }
    // No saved project — auto-create "Default"
    doResolve('Default')
  }, [token, teamId, doResolve, searchParams])

  // ── Filter state (P9-B18) ──────────────────────────────
  const [filterSearch, setFilterSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [filterWorkerId, setFilterWorkerId] = useState('')
  const [filterBatchId, setFilterBatchId] = useState('')
  const [workers, setWorkers] = useState<WorkerSummary[]>([])

  // ── Tab state (P9-B36) — URL-addressable via ?filter (P17-B34) ──
  const filterParam = searchParams.get('filter')
  const activeTab: 'all' | 'mine' | 'unclaimed' =
    filterParam === 'mine' || filterParam === 'unclaimed' || filterParam === 'all'
      ? filterParam
      : 'all'

  const setActiveTab = (tab: 'all' | 'mine' | 'unclaimed') => {
    const params = new URLSearchParams(searchParams)
    if (tab === 'all') params.delete('filter')
    else params.set('filter', tab)
    setSearchParams(params, { replace: true })
  }

  // ── View tab: active board vs history (P9-B47) ──────────
  const viewTab = (searchParams.get('tab') === 'history' ? 'history' : 'active') as 'active' | 'history'
  const historyBatchId = searchParams.get('batch') || undefined

  const setViewTab = (tab: 'active' | 'history', batchId?: string) => {
    const params = new URLSearchParams(searchParams)
    if (tab === 'history') {
      params.set('tab', 'history')
      if (batchId) params.set('batch', batchId)
    } else {
      params.delete('tab')
      params.delete('batch')
    }
    setSearchParams(params, { replace: true })
  }

  // ── Debounce keyword input (300ms) ────────────────────
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(filterSearch), 300)
    return () => clearTimeout(timer)
  }, [filterSearch])

  // ── Fetch agents for worker filter dropdown ────────────
  useEffect(() => {
    if (!token || !teamId) return
    fetchWorkers(teamId, token)
      .then(res => setWorkers(res.items))
      .catch((err) => { console.error('Failed to fetch workers for filter', err) /* Non-critical: worker filter dropdown enrichment */ })
  }, [token, teamId])

  // ── Filter-aware task fetch ───────────────────────────
  // Server-side filtering per tab (P17-B38): unclaimed/mine are pushed to the
  // API so pagination no longer truncates before the client filters.
  const filterOpts =
    activeTab === 'unclaimed'
      ? { unclaimed: true as const, search: debouncedSearch || undefined }
      : activeTab === 'mine'
        ? { mine: true as const }
        : {
            ownerId: filterWorkerId || undefined,
            batchId: filterBatchId || undefined,
            search: debouncedSearch || undefined,
          }

  // ── Fetch tasks when project is resolved ────────────────

  useEffect(() => {
    if (!token || !projectId) return
    setLoading(true)
    setError(null)
    fetchTasks(projectId, token, filterOpts)
      .then(res => { setTasks(res.items); setNextCursor(res.next_cursor) })
      .catch(err => {
        const status = err instanceof ApiError ? err.status : undefined
        // 404 likely means stale project_id in localStorage — clear and re-resolve
        if (status === 404) {
          localStorage.removeItem('synapse_project_id')
          localStorage.removeItem('synapse_project_name')
          setProjectId(null)
          setProjectName('')
          // Auto-resolve "Default" as fallback
          doResolve('Default')
          return
        }
        setError({ message: err.message, status })
      })
      .finally(() => setLoading(false))
  }, [projectId, token, doResolve, filterWorkerId, filterBatchId, debouncedSearch, activeTab])

  // ── Build worker name map ─────────────────────────────────
  const workerNames = useMemo(() => {
    const map = new Map<string, string>()
    workers.forEach(w => map.set(w.id, w.name))
    return map
  }, [workers])

  // ── Fetch batches for name map ──────────────────────────

  useEffect(() => {
    if (!token || !projectId) return
    fetchBatches(projectId, token)
      .then(res => {
        const map = new Map<string, string>()
        res.items.forEach(b => map.set(b.id, b.name))
        setBatchNames(map)
      })
      .catch((err) => { console.error('Failed to fetch batch names', err) /* Non-critical: batch name enrichment for task list */ })
  }, [projectId, token])

  // ── Create form state ───────────────────────────────────

  const [showCreate, setShowCreate] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newPriority, setNewPriority] = useState('p2')
  const [newBatchId, setNewBatchId] = useState('')
  const [newEffort, setNewEffort] = useState('')
  const [newTags, setNewTags] = useState('')
  const [newDeadline, setNewDeadline] = useState('')
  const [newVerifications, setNewVerifications] = useState<VerificationInput[]>([
    { type: 'manual', description: '' },
  ])
  const [newDeps, setNewDeps] = useState<DependsOnInput[]>([])
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [createdTask, setCreatedTask] = useState<TaskDetail | null>(null)
  const [quickActionError, setQuickActionError] = useState<string | null>(null)
  const [newDeadlinePreset, setNewDeadlinePreset] = useState<string | null>(null)
  const deadlineInputRef = useRef<HTMLInputElement>(null)

  // ── Tag autocomplete: extract unique tags from loaded tasks ──
  const allTags = useMemo(
    () => [...new Set(tasks.flatMap(t => t.tags || []))].sort(),
    [tasks],
  )

  // ── Dependency search state ─────────────────────────────
  const [depSearchIdx, setDepSearchIdx] = useState<number | null>(null)
  const [depSearchQuery, setDepSearchQuery] = useState('')
  const [depSearchResults, setDepSearchResults] = useState<TaskSummary[]>([])
  const [depSearchLoading, setDepSearchLoading] = useState(false)
  const depSearchRef = useRef<HTMLDivElement>(null)

  // Debounced dependency search
  useEffect(() => {
    if (!depSearchQuery.trim() || !token || !projectId) {
      setDepSearchResults([])
      return
    }
    const timer = setTimeout(async () => {
      setDepSearchLoading(true)
      try {
        const res = await fetchTasks(projectId, token, { search: depSearchQuery })
        setDepSearchResults(res.items)
      } catch (err) {
        console.error('Dependency search failed', err)
        setQuickActionError(t('tasks.depSearchError'))
        setDepSearchResults([])
      } finally {
        setDepSearchLoading(false)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [depSearchQuery, token, projectId])

  const closeDepSearch = () => {
    setDepSearchIdx(null)
    setDepSearchQuery('')
    setDepSearchResults([])
  }

  // ── Deadline presets ────────────────────────────────────
  const DEADLINE_PRESETS: Array<{ key: string; hours: number }> = [
    { key: '1h', hours: 1 },
    { key: '2h', hours: 2 },
    { key: '6h', hours: 6 },
    { key: '1d', hours: 24 },
    { key: '3d', hours: 72 },
  ]

  const applyDeadlinePreset = (key: string, hours: number) => {
    const d = new Date(Date.now() + hours * 3600 * 1000)
    setNewDeadline(d.toISOString().slice(0, 16))
    setNewDeadlinePreset(key)
  }

  const handleDeadlineChange = (value: string) => {
    setNewDeadline(value)
    setNewDeadlinePreset(null) // manual edit → clear preset highlight
  }

  const focusCustomDeadline = () => {
    setNewDeadlinePreset('custom')
    deadlineInputRef.current?.focus()
  }

  // ── Batch name map + hover state ───────────────────────
  const [batchNames, setBatchNames] = useState<Map<string, string>>(new Map())
  const [hoveredBatchId, setHoveredBatchId] = useState<string | null>(null)

  // ── Batch selection state ──────────────────────────────
  const [batchMode, setBatchMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [cancelling, setCancelling] = useState(false)
  const [batchResult, setBatchResult] = useState<string | null>(null)
  const [batchProcessing, setBatchProcessing] = useState(false)
  const [showAssignTarget, setShowAssignTarget] = useState(false)
  const [assignTargetId, setAssignTargetId] = useState('')

  const addVerification = () => {
    setNewVerifications([...newVerifications, { type: 'manual', description: '' }])
  }

  const removeVerification = (idx: number) => {
    setNewVerifications(newVerifications.filter((_, i) => i !== idx))
  }

  const updateVerification = (idx: number, field: keyof VerificationInput, value: string) => {
    const updated = [...newVerifications]
    updated[idx] = { ...updated[idx], [field]: value }
    setNewVerifications(updated)
  }

  const startDepSearch = (idx: number) => {
    setDepSearchIdx(idx)
    setDepSearchQuery('')
    setDepSearchResults([])
  }

  const selectDepTask = (task: TaskSummary) => {
    if (depSearchIdx === null) return
    updateDep(depSearchIdx, 'task_id', task.id)
    setDepSearchIdx(null)
    setDepSearchQuery('')
    setDepSearchResults([])
  }

  const addDep = () => {
    setNewDeps([...newDeps, { task_id: '', type: 'sequential' }])
  }

  const removeDep = (idx: number) => {
    setNewDeps(newDeps.filter((_, i) => i !== idx))
  }

  const updateDep = (idx: number, field: keyof DependsOnInput, value: string) => {
    const updated = [...newDeps]
    updated[idx] = { ...updated[idx], [field]: value }
    setNewDeps(updated)
  }

  const resetForm = () => {
    setNewTitle('')
    setNewDescription('')
    setNewPriority('p2')
    setNewBatchId('')
    setNewEffort('')
    setNewTags('')
    setNewDeadline('')
    setNewDeadlinePreset(null)
    setNewVerifications([{ type: 'manual', description: '' }])
    setNewDeps([])
    setDepSearchIdx(null)
    setDepSearchQuery('')
    setDepSearchResults([])
    setCreateError(null)
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !projectId) return

    // P9-B69: description 改为 required，提交前校验
    if (!newDescription.trim()) {
      const errorKey = 'errors.DESCRIPTION_REQUIRED'
      const translated = t(errorKey)
      setCreateError(translated !== errorKey ? translated : 'Task description is required')
      return
    }

    setCreating(true)
    setCreateError(null)
    try {
      const task = await createTask(
        projectId,
        {
          title: newTitle.trim(),
          description: newDescription.trim(),
          priority: newPriority,
          batch_id: newBatchId.trim() || undefined,
          estimated_effort: newEffort || undefined,
          tags: newTags.trim()
            ? newTags.split(',').map(tg => tg.trim()).filter(Boolean)
            : undefined,
          deadline_at: newDeadline || undefined,
          depends_on: newDeps.length
            ? newDeps.filter(d => d.task_id.trim())
            : undefined,
          // P9-B69: verifications 改为可选
          verifications: newVerifications
            .filter(v => v.description.trim())
            .map(v => ({ type: v.type, description: v.description.trim() })),
        },
        token,
      )
      resetForm()
      setShowCreate(false)
      setCreatedTask(task)
      // Reload the board (preserve active filters)
      fetchTasks(projectId, token, filterOpts)
        .then(res => { setTasks(res.items); setNextCursor(res.next_cursor) })
        .catch(err => setError({
          message: err.message,
          status: err instanceof ApiError ? err.status : undefined,
        }))
    } catch (err: unknown) {
      if (err instanceof ApiError && err.code) {
        const errorKey = `errors.${err.code}`
        const translated = t(errorKey)
        setCreateError(
          translated !== errorKey
            ? `${translated} (${err.code})`
            : err.message,
        )
      } else {
        setCreateError(err instanceof Error ? err.message : 'Create failed')
      }
    } finally {
      setCreating(false)
    }
  }

  // ── Batch handlers ────────────────────────────────────

  const handleToggleBatchMode = () => {
    if (batchMode) {
      setBatchMode(false)
      setSelectedIds(new Set())
      setBatchResult(null)
    } else {
      setBatchMode(true)
    }
  }

  const handleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleCancelSelected = async () => {
    if (!token || selectedIds.size === 0) return
    setCancelling(true)
    setBatchResult(null)
    let ok = 0
    let fail = 0

    // Find the full task objects for selected IDs (need version for optimistic lock)
    const selectedTasks = tasks.filter(t => selectedIds.has(t.id))
    const terminalStatuses = new Set(['completed', 'cancelled'])

    for (const t of selectedTasks) {
      if (terminalStatuses.has(t.status)) {
        fail++ // can't cancel terminal tasks
        continue
      }
      try {
        await cancelTask(t.id, t.version_no, token)
        ok++
      } catch (err) {
        console.error('Failed to cancel task', t.id, err) /* User-visible feedback via fail counter in batchResult */
        fail++
      }
    }

    setCancelling(false)
    setBatchResult(t('tasks.batchCancelResult', { ok, fail }))
    setSelectedIds(new Set())

    // Reload tasks
    if (projectId) {
      try {
        const res = await fetchTasks(projectId, token, filterOpts)
        setTasks(res.items)
        setNextCursor(res.next_cursor)
      } catch (err) { console.error('Failed to refresh tasks after batch operation', err) /* Non-critical: UI refresh after batch op already showed result */ }
    }
  }

  // ── Batch operation handlers (P9-B72, S-033) ──────────────

  const reloadTasksAfterBatch = async () => {
    if (!projectId || !token) return
    try {
      const res = await fetchTasks(projectId, token, filterOpts)
      setTasks(res.items)
      setNextCursor(res.next_cursor)
    } catch { /* ignore */ }
  }

  const handleLoadMore = async () => {
    if (!projectId || !token || !nextCursor) return
    setLoadingMore(true)
    try {
      const res = await fetchTasks(projectId, token, { ...filterOpts, cursor: nextCursor })
      setTasks(prev => [...prev, ...res.items])
      setNextCursor(res.next_cursor)
    } catch { /* ignore */ }
    finally { setLoadingMore(false) }
  }


  const handleBatchReady = async () => {
    if (!token || selectedIds.size === 0) return
    setBatchProcessing(true)
    setBatchResult(null)
    try {
      const res = await batchReadyTasks([...selectedIds], token)
      setBatchResult(t('tasks.batchReadyResult', { ok: res.updated_count, fail: res.failed_count }))
      setSelectedIds(new Set())
    } catch {
      setBatchResult(t('tasks.batchReadyError'))
    }
    setBatchProcessing(false)
    await reloadTasksAfterBatch()
  }

  const handleBatchPriority = async (priority: string) => {
    if (!token || selectedIds.size === 0) return
    setBatchProcessing(true)
    setBatchResult(null)
    try {
      const res = await batchUpdateTasks([...selectedIds], { priority }, token)
      setBatchResult(t('tasks.batchUpdateResult', { ok: res.updated_count, fail: res.failed_count }))
      setSelectedIds(new Set())
    } catch (err) {
      console.error('Batch priority update failed', err) /* User-visible feedback via batchResult error message below */
      setBatchResult(t('tasks.batchUpdateError'))
    }
    setBatchProcessing(false)
    await reloadTasksAfterBatch()
  }

  const handleBatchAssign = async () => {
    if (!token || selectedIds.size === 0 || !assignTargetId) return
    setBatchProcessing(true)
    setBatchResult(null)
    try {
      const res = await assignBatchTasks([...selectedIds], 'worker', assignTargetId, token)
      // assign-batch returns claimed_count, not updated_count
      setBatchResult(t('tasks.batchAssignResult', { count: res.claimed_count ?? res.updated_count ?? 0 }))
      setSelectedIds(new Set())
      setShowAssignTarget(false)
      setAssignTargetId('')
    } catch (err) {
      console.error('Batch assign failed', err) /* User-visible feedback via batchResult error message below */
      setBatchResult(t('tasks.batchAssignError'))
    }
    setBatchProcessing(false)
    await reloadTasksAfterBatch()
  }

  const handleClearFilters = () => {
    setFilterSearch('')
    setDebouncedSearch('')
    setFilterWorkerId('')
    setFilterBatchId('')
    setActiveTab('all')
  }

  // ── Quick action error helper (P9-B38) ─────────────────────
  const quickActionErrorMsg = (err: unknown): string => {
    if (err instanceof ApiError && err.code) {
      const errorKey = `errors.${err.code}`
      const translated = t(errorKey)
      return translated !== errorKey ? translated : err.message
    }
    return err instanceof Error ? err.message : 'Action failed'
  }

  // ── Quick action handlers (P9-B37) ───────────────────────
  const handlePromote = async (taskId: string, version: number) => {
    if (!token || !projectId) return
    setQuickActionError(null)
    try {
      await readyTask(taskId, version, token)
      const res = await fetchTasks(projectId, token, filterOpts)
      setTasks(res.items)
      setNextCursor(res.next_cursor)
    } catch (err: unknown) {
      setQuickActionError(quickActionErrorMsg(err))
      setTimeout(() => setQuickActionError(null), 5000)
    }
  }

  const handleClaim = async (taskId: string, version: number) => {
    if (!token || !projectId) return
    setQuickActionError(null)
    try {
      await claimTask(taskId, version, token)
      const res = await fetchTasks(projectId, token, filterOpts)
      setTasks(res.items)
      setNextCursor(res.next_cursor)
    } catch (err: unknown) {
      setQuickActionError(quickActionErrorMsg(err))
      setTimeout(() => setQuickActionError(null), 5000)
    }
  }

  // ── Worker filter (all tab owner scoping · P17-B37) ──
  const handleWorkerFilterChange = (workerId: string) => {
    setFilterWorkerId(workerId)
  }

  // ── Tab-filtered task list (server-side · P17-B38) ────────
  // The board fetch already scopes by activeTab (unclaimed/mine), so no
  // client-side truncation filter is needed here.
  const displayTasks = tasks

  // ── Server-side badge counts (P17-B38) ────────────────────
  const [unclaimedCount, setUnclaimedCount] = useState(0)
  const [historyCount, setHistoryCount] = useState(0)

  useEffect(() => {
    if (!token || !projectId) return
    let cancelled = false
    Promise.all([
      fetchTasks(projectId, token, { unclaimed: true, limit: 1 }).then(r => r.total),
      fetchTasks(projectId, token, { status: 'completed,cancelled', limit: 1 }).then(r => r.total),
    ])
      .then(([unclaimedTotal, historyTotal]) => {
        if (cancelled) return
        setUnclaimedCount(unclaimedTotal)
        setHistoryCount(historyTotal)
      })
      .catch(() => { /* badge counts are non-critical */ })
    return () => { cancelled = true }
  }, [projectId, token, tasks])

  // ── Render guards ───────────────────────────────────────

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  if (error) {
    return (
      <EmptyState
        icon={ClipboardList}
        title={error.status === 404 ? t('tasks.notFound') : t('common.error')}
        description={error.message}
      />
    )
  }

  // ── Project name input handler ──────────────────────────

  const handleProjectBlur = () => {
    const trimmed = projectName.trim()
    if (!trimmed || !token) return
    doResolve(trimmed)
  }

  const handleProjectKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const trimmed = projectName.trim()
      if (trimmed && token) doResolve(trimmed)
    }
  }

  // ── Render ──────────────────────────────────────────────

  return (
    <div>
      {/* Click-outside overlay for dep search dropdown — React synthetic event, not document.addEventListener */}
      {depSearchIdx !== null && (
        <div
          onMouseDown={closeDepSearch}
          style={{ position: 'fixed', inset: 0, zIndex: 998 }}
          aria-hidden="true"
        />
      )}
      <PageHeader title={t('tasks.heading')}>
        <input
          type="text"
          className={styles.projectNameInput}
          value={projectName}
          onChange={e => setProjectName(e.target.value)}
          onBlur={handleProjectBlur}
          onKeyDown={handleProjectKeyDown}
          placeholder="Project name (optional)"
          disabled={resolving}
        />
      </PageHeader>

      {resolving || loading ? (
        <p className={styles.loading}>{t('common.loading')}</p>
      ) : (
        <>
          {/* ── Create form ─────────────────────────────── */}
          <div className={styles.createForm}>
            <div className={styles.formTitle}>
              {showCreate ? t('tasks.createTask') : (
                <button
                  type="button"
                  className={styles.submitBtn}
                  onClick={() => { setShowCreate(true); setCreateError(null); setCreatedTask(null) }}
                >
                  + {t('tasks.createTask')}
                </button>
              )}
            </div>
            {showCreate && (
              <form onSubmit={handleCreate}>
                {/* Title + Priority */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 2 }}>
                    <label htmlFor="task-create-title">{t('tasks.title')}</label>
                    <input
                      type="text"
                      id="task-create-title"
                      value={newTitle}
                      onChange={e => setNewTitle(e.target.value)}
                      placeholder={t('tasks.titlePlaceholder')}
                      style={{ width: '100%' }}
                      required
                    />
                  </div>
                  <div className={styles.formField} style={{ width: '100px' }}>
                    <label htmlFor="task-create-priority">{t('tasks.priority')}</label>
                    <select id="task-create-priority" value={newPriority} onChange={e => setNewPriority(e.target.value)}>
                      {PRIORITIES.map(p => (
                        <option key={p} value={p}>{t(`tasks.priorities.${p}`)}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Description */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="task-create-description">{t('tasks.description')}</label>
                    <textarea
                      id="task-create-description"
                      value={newDescription}
                      onChange={e => setNewDescription(e.target.value)}
                      placeholder={t('tasks.descPlaceholder')}
                      style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                    />
                  </div>
                </div>

                {/* Batch + Effort + Deadline */}
                <div className={styles.formRow}>
                  {!isMinimalBatch && (
                  <div className={styles.formField}>
                    <label htmlFor="task-create-batchId">{t('tasks.batchId')}</label>
                    <BatchSelect
                      id="task-create-batchId"
                      projectId={projectId || ''}
                      value={newBatchId}
                      onChange={setNewBatchId}
                    />
                  </div>
                  )}
                  <div className={styles.formField} style={{ width: '90px' }}>
                    <label htmlFor="task-create-effort">{t('tasks.effort')}</label>
                    <select id="task-create-effort" value={newEffort} onChange={e => setNewEffort(e.target.value)}>
                      <option value="">{t('common.none')}</option>
                      {EFFORTS.map(e => (
                        <option key={e} value={e}>{t(`tasks.efforts.${e}`)}</option>
                      ))}
                    </select>
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="task-create-deadline">{t('tasks.deadline')}</label>
                    <div className={styles.deadlineChips}>
                      {DEADLINE_PRESETS.map(p => (
                        <button
                          key={p.key}
                          type="button"
                          className={`${styles.deadlineChip} ${newDeadlinePreset === p.key ? styles.deadlineChipActive : ''}`}
                          onClick={() => applyDeadlinePreset(p.key, p.hours)}
                        >
                          {t(`tasks.deadlinePresets.${p.key}`)}
                        </button>
                      ))}
                      <button
                        type="button"
                        className={`${styles.deadlineChip} ${newDeadlinePreset === 'custom' ? styles.deadlineChipActive : ''}`}
                        onClick={focusCustomDeadline}
                      >
                        {t('tasks.deadlinePresets.custom')}
                      </button>
                    </div>
                    <input
                      type="datetime-local"
                      id="task-create-deadline"
                      value={newDeadline}
                      onChange={e => handleDeadlineChange(e.target.value)}
                      ref={deadlineInputRef}
                      style={{ width: '200px' }}
                    />
                  </div>
                </div>

                {/* Tags */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="task-create-tags">{t('tasks.tags')}</label>
                    <input
                      type="text"
                      id="task-create-tags"
                      value={newTags}
                      onChange={e => setNewTags(e.target.value)}
                      placeholder={t('tasks.tagsPlaceholder')}
                      list="tag-suggestions"
                      autoComplete="off"
                      style={{ width: '100%' }}
                    />
                    <datalist id="tag-suggestions">
                      {allTags.map(tag => (
                        <option key={tag} value={tag} />
                      ))}
                    </datalist>
                  </div>
                </div>

                {/* Dependencies */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <div className={styles.verifyHeader}>
                      <span className={styles.label}>{t('tasks.dependsOn')}</span>
                      <button
                        type="button"
                        className={styles.smallBtn}
                        onClick={addDep}
                      >
                        {t('tasks.addDep')}
                      </button>
                    </div>
                    {newDeps.map((d, idx) => (
                      <div key={idx} className={styles.verifyRow}>
                        <div className={styles.depSearchWrapper} ref={depSearchIdx === idx ? depSearchRef : undefined} onMouseDown={depSearchIdx === idx ? (e) => e.stopPropagation() : undefined}>
                          <div className={styles.depSearchInputRow}>
                            <Search size={12} className={styles.depSearchIcon} />
                            <input
                              type="text"
                              value={depSearchIdx === idx ? depSearchQuery : d.task_id}
                              onChange={e => {
                                if (depSearchIdx === idx) {
                                  setDepSearchQuery(e.target.value)
                                } else {
                                  updateDep(idx, 'task_id', e.target.value)
                                }
                              }}
                              onFocus={() => startDepSearch(idx)}
                              placeholder={t('tasks.depSearchPlaceholder')}
                              className={styles.depSearchInput}
                              autoComplete="off"
                            />
                            {depSearchIdx === idx && depSearchLoading && (
                              <Loader2 size={12} className={styles.depSearchSpinner} />
                            )}
                          </div>
                          {depSearchIdx === idx && depSearchResults.length > 0 && (
                            <div className={styles.depSearchDropdown}>
                              {depSearchResults.map(task => (
                                <button
                                  key={task.id}
                                  type="button"
                                  className={styles.depSearchItem}
                                  onClick={() => selectDepTask(task)}
                                >
                                  <span className={styles.depSearchItemId}>{task.id.slice(0, 8)}</span>
                                  <span className={styles.depSearchItemTitle}>{task.title}</span>
                                  <span className={`gm-intent-pill intent-${task.status}`}>{task.status}</span>
                                </button>
                              ))}
                            </div>
                          )}
                          {depSearchIdx === idx && depSearchQuery.trim() && !depSearchLoading && depSearchResults.length === 0 && (
                            <div className={styles.depSearchDropdown}>
                              <div className={styles.depSearchEmpty}>{t('tasks.depSearchNoResults')}</div>
                            </div>
                          )}
                        </div>
                        <select
                          value={d.type}
                          onChange={e => updateDep(idx, 'type', e.target.value)}
                          style={{ width: '110px' }}
                        >
                          <option value="sequential">{t('tasks.depTypes.sequential')}</option>
                          <option value="artifact">{t('tasks.depTypes.artifact')}</option>
                        </select>
                        <button
                          type="button"
                          className={styles.removeBtn}
                          onClick={() => {
                            if (depSearchIdx === idx) {
                              setDepSearchIdx(null)
                              setDepSearchQuery('')
                              setDepSearchResults([])
                            }
                            removeDep(idx)
                          }}
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Verifications */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <div className={styles.verifyHeader}>
                      <span className={styles.label}>{t('tasks.verifications')}</span>
                      <button
                        type="button"
                        className={styles.smallBtn}
                        onClick={addVerification}
                      >
                        {t('tasks.addVerification')}
                      </button>
                    </div>
                    {newVerifications.map((v, idx) => (
                      <div key={idx} className={styles.verifyRow}>
                        <select
                          value={v.type}
                          onChange={e => updateVerification(idx, 'type', e.target.value)}
                          style={{ width: '120px' }}
                        >
                          {VERIFY_TYPES.map(vt => (
                            <option key={vt} value={vt}>{t(`tasks.verifyTypes.${vt}`)}</option>
                          ))}
                        </select>
                        <input
                          type="text"
                          value={v.description}
                          onChange={e => updateVerification(idx, 'description', e.target.value)}
                          placeholder={t('tasks.verifyPlaceholder')}
                          style={{ flex: 1 }}
                        />
                        {newVerifications.length > 1 && (
                          <button
                            type="button"
                            className={styles.removeBtn}
                            onClick={() => removeVerification(idx)}
                          >
                            <X size={14} />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                {createError && <p className={styles.error}>{createError}</p>}

                <div className={styles.formRow}>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={creating || !newTitle.trim()}
                  >
                    {creating ? t('tasks.creating') : t('tasks.createBtn')}
                  </button>
                  <button
                    type="button"
                    className={styles.filterChip}
                    onClick={() => { setShowCreate(false); resetForm() }}
                  >
                    {t('common.cancel')}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* ── Post-creation guidance ──────────────────── */}
          {createdTask && (
            <div className={styles.successBanner}>
              <span className={styles.successIcon}><Check size={16} /></span>
              <span className={styles.successText}>
                {t('tasks.createSuccess')} — <strong>{createdTask.title}</strong>
              </span>
              {createdTask.status === 'backlog' && (
                <button
                  type="button"
                  className={styles.successLink}
                  onClick={() => handlePromote(createdTask.id, createdTask.version_no)}
                >
                  {t('tasks.moveToReady')}
                </button>
              )}
              <button
                type="button"
                className={styles.successLink}
                onClick={() => { setCreatedTask(null); setShowCreate(true) }}
              >
                {t('tasks.continueCreate')}
              </button>
              <Link to={`/tasks/${createdTask.id}`} className={styles.successLink}>
                {t('tasks.viewDetail')}
              </Link>
              <button
                type="button"
                className={styles.successClose}
                onClick={() => setCreatedTask(null)}
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* ── View tabs: Active Board / History (P9-B47) ── */}
          <div className={styles.viewTabBar}>
            <button
              type="button"
              className={`${styles.viewTab} ${viewTab === 'active' ? styles.viewTabActive : ''}`}
              onClick={() => setViewTab('active')}
            >
              {t('tasks.tabs.active')}
            </button>
            <button
              type="button"
              className={`${styles.viewTab} ${viewTab === 'history' ? styles.viewTabActive : ''}`}
              onClick={() => setViewTab('history')}
            >
              {t('tasks.tabs.history')}
              {historyCount > 0 && <span className={styles.tabBadge}>{historyCount}</span>}
            </button>
          </div>

          {/* ── Active Board ───────────────────────────── */}
          {viewTab === 'active' && (
          <>
          {/* ── Batch Actions ──────────────────────────── */}
          <div className={styles.batchBar}>
            <button
              className={`${styles.filterChip} ${batchMode ? styles.filterChipActive : ''}`}
              onClick={handleToggleBatchMode}
            >
              {batchMode ? t('tasks.done') : t('tasks.batchActions')}
            </button>
            {batchMode && (
              <>
                <span className={styles.batchInfo}>
                  {selectedIds.size > 0
                    ? t('tasks.selected', { count: selectedIds.size })
                    : t('tasks.selectHint')}
                </span>
                {selectedIds.size > 0 && (
                  <>
                    <button
                      className={styles.smallPrimaryBtn}
                      onClick={handleBatchReady}
                      disabled={batchProcessing}
                      title={t('tasks.batchReadyTooltip')}
                    >
                      {batchProcessing ? '…' : t('tasks.batchReady')}
                    </button>
                    <select
                      className={styles.batchActionSelect}
                      value=""
                      onChange={e => { if (e.target.value) handleBatchPriority(e.target.value) }}
                      disabled={batchProcessing}
                      title={t('tasks.batchChangePriority')}
                    >
                      <option value="">{t('tasks.batchChangePriority')}</option>
                      {PRIORITIES.map(p => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                    {!showAssignTarget ? (
                      <button
                        className={styles.smallPrimaryBtn}
                        onClick={() => setShowAssignTarget(true)}
                        disabled={batchProcessing}
                      >
                        {t('tasks.batchAssign')}
                      </button>
                    ) : (
                      <span className={styles.assignTargetGroup}>
                        <select
                          className={styles.batchActionSelect}
                          value={assignTargetId}
                          onChange={e => setAssignTargetId(e.target.value)}
                        >
                          <option value="">{t('tasks.assignWorkerPlaceholder')}</option>
                          {workers.filter(a => a.status === 'active').map(a => (
                            <option key={a.id} value={a.id}>{a.name} (worker)</option>
                          ))}
                        </select>
                        <button
                          className={styles.smallPrimaryBtn}
                          onClick={handleBatchAssign}
                          disabled={batchProcessing || !assignTargetId}
                        >
                          {t('common.confirm')}
                        </button>
                        <button
                          className={styles.smallDangerBtn}
                          onClick={() => { setShowAssignTarget(false); setAssignTargetId(''); }}
                        >
                          ✕
                        </button>
                      </span>
                    )}
                    <button
                      className={styles.smallDangerBtn}
                      onClick={handleCancelSelected}
                      disabled={cancelling || batchProcessing}
                    >
                      {cancelling ? t('tasks.cancelling') : t('tasks.cancelSelected')}
                    </button>
                  </>
                )}
                {batchResult && <span className={styles.batchInfo}>{batchResult}</span>}
              </>
            )}
          </div>

          {/* ── Filter toolbar (P9-B18) ─────────────────── */}
          {!resolving && !loading && !error && (
            <div className={styles.filterBar}>
              <Search size={14} className={styles.filterIcon} />
              <input
                type="search"
                className={styles.filterSearch}
                value={filterSearch}
                onChange={e => setFilterSearch(e.target.value)}
                placeholder={t('tasks.filter.searchPlaceholder')}
              />
              <select
                value={filterWorkerId}
                onChange={e => handleWorkerFilterChange(e.target.value)}
              >
                <option value="">{t('tasks.filter.workerAll')}</option>
                {workers.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
              {!isMinimalBatch && (
              <BatchSelect
                projectId={projectId || ''}
                value={filterBatchId}
                onChange={setFilterBatchId}
                placeholder={t('tasks.filter.batchAll')}
              />
              )}
              {!isMinimalBatch && (
                <Link
                  to={projectId ? `/batches?project_id=${projectId}` : '/batches'}
                  className={styles.filterLink}
                >
                  {t('nav.batches')} →
                </Link>
              )}
              {(filterSearch || filterWorkerId || filterBatchId) && (
                <button
                  type="button"
                  className={styles.filterChip}
                  onClick={handleClearFilters}
                >
                  <X size={12} style={{ marginRight: 4 }} />
                  {t('tasks.filter.clear')}
                </button>
              )}
            </div>
          )}

          {/* ── Quick action error (P9-B37) ──────────────── */}
          {quickActionError && (
            <div className={styles.quickActionError}>
              <span>{quickActionError}</span>
              <button type="button" onClick={() => setQuickActionError(null)}>
                <X size={14} />
              </button>
            </div>
          )}

          {/* ── Tab bar (P9-B36) ────────────────────────── */}
          <div className={styles.tabBar}>
            <button
              type="button"
              className={`${styles.tab} ${activeTab === 'all' ? styles.tabActive : ''}`}
              data-testid="filter-tab-all"
              data-active={activeTab === 'all' ? 'true' : 'false'}
              onClick={() => setActiveTab('all')}
            >
              {t('tasks.tabs.all')}
            </button>
            <button
              type="button"
              className={`${styles.tab} ${activeTab === 'mine' ? styles.tabActive : ''}`}
              data-testid="filter-tab-mine"
              data-active={activeTab === 'mine' ? 'true' : 'false'}
              onClick={() => setActiveTab('mine')}
            >
              {t('tasks.tabs.mine')}
            </button>
            <button
              type="button"
              className={`${styles.tab} ${activeTab === 'unclaimed' ? styles.tabActive : ''}`}
              data-testid="filter-tab-unclaimed"
              data-active={activeTab === 'unclaimed' ? 'true' : 'false'}
              onClick={() => setActiveTab('unclaimed')}
            >
              {t('tasks.tabs.unclaimed')}
              {unclaimedCount > 0 && (
                <span className={styles.tabBadge}>{unclaimedCount}</span>
              )}
            </button>
          </div>

          {/* ── Board ──────────────────────────────────── */}
          {displayTasks.length === 0 && activeTab === 'all' && !filterSearch && !filterWorkerId && !filterBatchId ? (
            <EmptyState
              icon={ClipboardList}
              title={t('tasks.emptyBoardTitle')}
              description={t('tasks.emptyBoardHint')}
            >
              <button
                type="button"
                className={styles.submitBtn}
                onClick={() => { setShowCreate(true); setCreateError(null); setCreatedTask(null) }}
                style={{ marginTop: 16 }}
              >
                + {t('tasks.createTask')}
              </button>
            </EmptyState>
          ) : displayTasks.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title={
                activeTab === 'mine'
                  ? t('tasks.mineEmpty')
                  : activeTab === 'unclaimed'
                    ? t('tasks.unclaimedEmpty')
                    : t('tasks.emptyBoardTitle')
              }
              description=""
            >
              {activeTab === 'unclaimed' && (
                <button
                  type="button"
                  className={styles.submitBtn}
                  onClick={() => setActiveTab('all')}
                  style={{ marginTop: 16 }}
                >
                  {t('tasks.tabs.all')}
                </button>
              )}
            </EmptyState>
          ) : (
            <div className={styles.board}>
              {STATUS_COLUMNS.map(({ status, label }) => (
                <TaskColumn
                  key={status}
                  label={label}
                  tasks={displayTasks.filter(tk => tk.status === status)}
                  selectable={batchMode}
                  selectedIds={selectedIds}
                  onSelect={handleSelect}
                  batchNames={batchNames}
                  workerNames={workerNames}
                  hoveredBatchId={hoveredBatchId}
                  onBatchHover={setHoveredBatchId}
                  currentWorkerId={filterWorkerId || undefined}
                  onPromote={handlePromote}
                  onClaim={handleClaim}
                />
              ))}
            </div>
          )}
          {/* ── Load More ─────────────────────────────── */}
          {nextCursor && (
            <div className={styles.loadMoreBar}>
              <button
                type="button"
                className={styles.loadMoreBtn}
                onClick={handleLoadMore}
                disabled={loadingMore}
              >
                {loadingMore ? t('common.loading') : t('tasks.loadMore')}
              </button>
            </div>
          )}
          {/* ── View history cross-link ────────────────── */}
          {displayTasks.some(t => t.status === 'completed' || t.status === 'cancelled') && (
            <div className={styles.viewHistoryBar}>
              <button
                type="button"
                className={styles.viewHistoryLink}
                onClick={() => setViewTab('history')}
              >
                <Clock size={14} />
                {t('tasks.history.viewInBoard')}
              </button>
            </div>
          )}
        </>
      )}
      {/* ── History View (P9-B47) ──────────────────────── */}
      {viewTab === 'history' && projectId && token && (
        <HistoryList
          projectId={projectId}
          token={token}
          initialBatchId={historyBatchId}
          onBackToBoard={() => setViewTab('active')}
        />
      )}
    </>
  )}
</div>
  )
}

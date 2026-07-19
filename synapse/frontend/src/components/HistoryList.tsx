import { useState, useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Search, ChevronDown, ChevronRight, ChevronLeft, ChevronsUpDown, ClipboardList } from 'lucide-react'
import { fetchTasks, fetchBatches, ApiError } from '../api/client'
import type { TaskSummary } from '../api/client'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import styles from './HistoryList.module.css'

const HISTORY_STATUSES = new Set(['completed', 'cancelled'])

interface HistoryListProps {
  projectId: string
  token: string
  initialBatchId?: string
  onBackToBoard?: () => void
}

interface BatchGroup {
  batchId: string | null
  batchName: string
  tasks: TaskSummary[]
}

export default function HistoryList({ projectId, token, initialBatchId, onBackToBoard }: HistoryListProps) {
  const { t, lang } = useI18n()
  const [allTasks, setAllTasks] = useState<TaskSummary[]>([])
  const [batchNames, setBatchNames] = useState<Map<string, string>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // ── Filters ───────────────────────────────────────────────
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [expandedGroups, setExpandedGroups] = useState<Set<string | null>>(new Set())
  const [expandAll, setExpandFlag] = useState(false)

  // ── Debounce keyword ──────────────────────────────────────
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  // ── Fetch data ────────────────────────────────────────────
  useEffect(() => {
    if (!token || !projectId) return
    setLoading(true)
    setError(null)

    // Fetch tasks (all statuses — we filter client-side) and batches in parallel
    Promise.all([
      fetchTasks(projectId, token),
      fetchBatches(projectId, token).catch(() => ({ items: [] as Array<{ id: string; name: string }> })),
    ])
      .then(([taskRes, batchRes]) => {
        const historyTasks = taskRes.items.filter(t => HISTORY_STATUSES.has(t.status))
        setAllTasks(historyTasks)
        const map = new Map<string, string>()
        batchRes.items.forEach((b: { id: string; name: string }) => map.set(b.id, b.name))
        setBatchNames(map)
      })
      .catch(err => {
        setError(err instanceof ApiError ? err.message : t('tasks.history.loadError'))
      })
      .finally(() => setLoading(false))
  }, [projectId, token])

  // ── Auto-expand on first load ────────────────────────────
  const [hasInitialExpanded, setHasInitialExpanded] = useState(false)
  useEffect(() => {
    if (allTasks.length === 0 || hasInitialExpanded) return
    setHasInitialExpanded(true)
    if (initialBatchId) {
      // Expand only the linked batch group
      setExpandedGroups(new Set([initialBatchId]))
    } else {
      // Expand all groups so the user sees data immediately
      const allIds = new Set<string | null>()
      allTasks.forEach(t => allIds.add(t.batch_id))
      setExpandedGroups(allIds)
    }
  }, [allTasks, initialBatchId, hasInitialExpanded])

  // ── Client-side filter + group ───────────────────────────
  const groups = useMemo(() => {
    let filtered = allTasks

    // Keyword search
    if (debouncedSearch.trim()) {
      const q = debouncedSearch.toLowerCase()
      filtered = filtered.filter(
        t => t.title.toLowerCase().includes(q) || t.id.toLowerCase().includes(q),
      )
    }

    // Group by batch_id
    const groupMap = new Map<string | null, TaskSummary[]>()
    filtered.forEach(t => {
      const bid = t.batch_id
      if (!groupMap.has(bid)) groupMap.set(bid, [])
      groupMap.get(bid)!.push(t)
    })

    // Sort groups: null-batch first, then by recency (we use batch name as proxy)
    const result: BatchGroup[] = []
    const nullGroup = groupMap.get(null)
    if (nullGroup) {
      result.push({ batchId: null, batchName: t('tasks.history.noBatch'), tasks: nullGroup })
      groupMap.delete(null)
    }

    // Sort by batch name descending (names like "P9-B46" sort lexicographically as proxy for time)
    const sortedEntries = [...groupMap.entries()].sort((a, b) => {
      const nameA = batchNames.get(a[0] || '') || a[0] || ''
      const nameB = batchNames.get(b[0] || '') || b[0] || ''
      return nameB.localeCompare(nameA) // descending
    })

    sortedEntries.forEach(([bid, tasks]) => {
      const name = batchNames.get(bid || '') || bid || ''
      // Sort tasks within group: completed first, then by created_at desc
      tasks.sort((a, b) => {
        if (a.status === 'completed' && b.status !== 'completed') return -1
        if (b.status === 'completed' && a.status !== 'completed') return 1
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      })
      result.push({ batchId: bid, batchName: name, tasks })
    })

    return result
  }, [allTasks, debouncedSearch, batchNames, t])

  // ── Toggle group expand ──────────────────────────────────
  const toggleGroup = (batchId: string | null) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(batchId)) {
        next.delete(batchId)
      } else {
        next.add(batchId)
      }
      return next
    })
  }

  const handleExpandAll = () => {
    if (expandAll) {
      setExpandedGroups(new Set())
      setExpandFlag(false)
    } else {
      setExpandedGroups(new Set(groups.map(g => g.batchId)))
      setExpandFlag(true)
    }
  }

  // ── Render ────────────────────────────────────────────────
  if (loading) {
    return <p className={styles.loading}>{t('common.loading')}</p>
  }

  if (error) {
    return <p className={styles.error}>{error}</p>
  }

  const totalCount = allTasks.length
  const filteredCount = groups.reduce((sum, g) => sum + g.tasks.length, 0)

  return (
    <div className={styles.container}>
      {/* ── Header bar ─────────────────────────────────── */}
      <div className={styles.headerBar}>
        {onBackToBoard && (
          <button type="button" className={styles.backLink} onClick={onBackToBoard}>
            <ChevronLeft size={14} />
            {t('tasks.history.backToBoard')}
          </button>
        )}
        <span className={styles.totalCount}>
          {t('tasks.history.totalCount', { count: totalCount })}
        </span>
      </div>

      {/* ── Filter bar ─────────────────────────────────── */}
      <div className={styles.filterBar}>
        <Search size={14} className={styles.filterIcon} />
        <input
          type="search"
          className={styles.filterSearch}
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder={t('tasks.filter.searchPlaceholder')}
        />
        {search && (
          <button
            type="button"
            className={styles.filterClear}
            onClick={() => { setSearch(''); setDebouncedSearch('') }}
          >
            {t('tasks.filter.clear')}
          </button>
        )}
        {groups.length > 0 && (
          <button
            type="button"
            className={styles.expandToggle}
            onClick={handleExpandAll}
          >
            {expandAll ? <ChevronsUpDown size={14} /> : <ChevronsUpDown size={14} />}
            {expandAll ? t('tasks.history.collapseAll') : t('tasks.history.expandAll')}
          </button>
        )}
      </div>

      {/* ── Empty state ────────────────────────────────── */}
      {groups.length === 0 && (
        <div className={styles.empty}>
          <ClipboardList size={32} className={styles.emptyIcon} />
          <p className={styles.emptyTitle}>{t('tasks.history.emptyTitle')}</p>
          <p className={styles.emptyHint}>
            {allTasks.length === 0
              ? t('tasks.history.emptyHint')
              : t('tasks.history.filteredEmpty')}
          </p>
        </div>
      )}

      {/* ── Batch groups ───────────────────────────────── */}
      {groups.map(group => {
        const isExpanded = expandedGroups.has(group.batchId)
        const count = group.tasks.length

        return (
          <div key={group.batchId ?? '__no_batch__'} className={styles.group}>
            {/* Group header */}
            <button
              type="button"
              className={styles.groupHeader}
              onClick={() => toggleGroup(group.batchId)}
            >
              <span className={styles.groupChevron}>
                {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </span>
              <span className={styles.groupName}>
                {group.batchId ? (
                  <Link
                    to={`/batches/${group.batchId}`}
                    className={styles.groupBatchLink}
                    onClick={e => e.stopPropagation()}
                  >
                    {group.batchName}
                  </Link>
                ) : (
                  group.batchName
                )}
              </span>
              <span className={styles.groupCount}>
                {t('tasks.history.groupCount', { count })}
              </span>
            </button>

            {/* Task rows */}
            {isExpanded && (
              <div className={styles.groupBody}>
                {group.tasks.map(task => (
                  <Link
                    key={task.id}
                    to={`/tasks/${task.id}`}
                    className={styles.taskRow}
                  >
                    <span className={`gm-intent-pill intent-${task.status}`}>
                      {t(`tasks.columns.${task.status}`)}
                    </span>
                    <span className={styles.taskTitle}>{task.title}</span>
                    <span className={styles.taskMeta}>
                      <span className={styles.taskId}>{task.id.slice(0, 8)}</span>
                      {task.owner_id && (
                        <span className={styles.taskOwner}>
                          {task.owner_id.slice(0, 8)}
                        </span>
                      )}
                      <span className={styles.taskDate}>
                        {task.status === 'completed'
                          ? formatDate(task.completed_at ?? task.created_at, lang)
                          : formatDate(task.created_at, lang)}
                      </span>
                    </span>
                    <ChevronRight size={14} className={styles.taskChevron} />
                  </Link>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* ── Footer count ────────────────────────────────── */}
      {filteredCount !== totalCount && (
        <p className={styles.filterNote}>
          {t('tasks.history.filterNote', { filtered: filteredCount, total: totalCount })}
        </p>
      )}
    </div>
  )
}

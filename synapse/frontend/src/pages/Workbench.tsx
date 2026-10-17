import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Lock } from 'lucide-react'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import { fetchMyTasks } from '../api/client'
import { useWebSocket, TASK_EVENT_TYPES } from '../api/ws'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import type { WorkbenchTask } from '../api/client'
import styles from './Workbench.module.css'

/** 状态 → 颜色 + i18n label（与 Dashboard STATUS_CONFIG 对齐，rejected 兜底）。 */
const STATUS_CONFIG: Record<string, { color: string; labelKey: string }> = {
  backlog: { color: '#94a3b8', labelKey: 'task.columns.backlog' },
  ready: { color: '#60a5fa', labelKey: 'task.columns.ready' },
  in_progress: { color: '#f59e0b', labelKey: 'task.columns.inProgress' },
  in_verification: { color: '#a78bfa', labelKey: 'task.columns.inVerification' },
  completed: { color: '#4ade80', labelKey: 'task.columns.completed' },
  cancelled: { color: '#f87171', labelKey: 'task.columns.cancelled' },
  rejected: { color: '#f87171', labelKey: 'task.columns.cancelled' },
}

export default function Workbench() {
  const { t, lang } = useI18n()
  const { token, logout } = useAuth()
  const [tasks, setTasks] = useState<WorkbenchTask[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) {
      setLoading(false)
      setError(t('auth.setTokenHint'))
      return
    }
    fetchMyTasks(token)
      .then(res => setTasks(res.tasks))
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [token, t])

  // ── P17-B30: my-tasks WS real-time ───────────────────────────────
  const { status, lastEvent } = useWebSocket(token, TASK_EVENT_TYPES, logout)
  const refreshRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Any task.* event reshapes "my tasks" (claim flips ownership → a task appears
  // or leaves). 300ms debounce aggregates a burst into a single fetch.
  useEffect(() => {
    if (!lastEvent) return
    if (!TASK_EVENT_TYPES.includes(lastEvent.event_type)) return

    if (refreshRef.current) clearTimeout(refreshRef.current)
    refreshRef.current = setTimeout(() => {
      if (!token) return
      fetchMyTasks(token)
        .then(res => setTasks(res.tasks))
        .catch(() => { /* keep last known list — non-critical refresh */ })
    }, 300)
  }, [lastEvent, token])

  // Clear the pending refresh on unmount
  useEffect(() => {
    return () => {
      if (refreshRef.current) clearTimeout(refreshRef.current)
    }
  }, [])

  if (error) {
    return <EmptyState icon={Lock} title={t('workbench.heading')} description={error} />
  }

  return (
    <div>
      <PageHeader title={t('workbench.heading')} subtitle={t('workbench.subtitle')}>
        <span
          className={`${styles.liveDot} ${status === 'connected' ? styles.liveDotOn : ''}`}
          data-testid="workbench-live-dot"
          title={status}
        />
      </PageHeader>

      {loading && <p className={styles.loading}>{t('common.loading')}</p>}

      {!loading && !error && tasks.length === 0 && (
        <p className={styles.empty}>{t('workbench.empty')}</p>
      )}

      {!loading && tasks.length > 0 && (
        <ul className={styles.taskList}>
          {tasks.map(task => {
            const cfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.backlog
            return (
              <li key={task.task_id} className={styles.taskCard} data-task-id={task.task_id}>
                <div className={styles.taskMain}>
                  <Link to={`/tasks/${task.task_id}`} className={styles.taskTitle}>
                    {task.title}
                  </Link>
                  {task.dependency_blocked && (
                    <span className={styles.blockedBadge}>🔒 {t('workbench.blocked')}</span>
                  )}
                </div>
                <div className={styles.taskMeta}>
                  <span className={styles.statusChip} data-status={task.status}>
                    <span className={styles.statusDot} style={{ background: cfg.color }} />
                    {t(cfg.labelKey)}
                  </span>
                  {task.project_name && (
                    <Link
                      to={`/projects/${task.project_id}?tab=overview`}
                      className={styles.projectName}
                    >
                      {task.project_name}
                    </Link>
                  )}
                  {task.deadline_at && (
                    <span className={styles.deadline}>{formatDate(task.deadline_at, lang)}</span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

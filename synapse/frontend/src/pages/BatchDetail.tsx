import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Lock, Package, ClipboardList, CheckCircle, Loader, AlertTriangle, ArrowLeft, ExternalLink } from 'lucide-react'
import { fetchBatch, fetchTasks, fetchWorker } from '../api/client'
import type { BatchSummary, TaskSummary, WorkerDetail } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import TaskCard from '../components/TaskCard'
import styles from './BatchDetail.module.css'

export default function BatchDetail() {
  const { batchId } = useParams<{ batchId: string }>()
  const { t, lang } = useI18n()
  const { token } = useAuth()
  const [batch, setBatch] = useState<BatchSummary | null>(null)
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [assignedWorker, setAssignedWorker] = useState<WorkerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [projectId] = useState(() => localStorage.getItem('synapse_project_id'))

  useEffect(() => {
    if (!token || !batchId) {
      setError(t('auth.setTokenHint'))
      setLoading(false)
      return
    }

    const projectId = localStorage.getItem('synapse_project_id')

    const fetches: [Promise<BatchSummary>, Promise<{ items: TaskSummary[]; total: number }> | null] = [
      fetchBatch(batchId, token),
      projectId ? fetchTasks(projectId, token, { batchId }) : null,
    ]

    Promise.all(fetches)
      .then(([b, tk]) => {
        setBatch(b)
        if (tk) setTasks(tk.items)
        // Fetch assigned agent name if assigned
        if (b.assigned_to) {
          fetchWorker(b.assigned_to, token)
            .then(a => setAssignedWorker(a))
            .catch((err) => { console.error('Failed to fetch assigned worker', err) /* Non-critical: assigned worker name enrichment */; setAssignedWorker(null) })
            .finally(() => setLoading(false))
        } else {
          setLoading(false)
        }
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [batchId, token, t])

  // ── Guards ─────────────────────────────────────────────────────

  if (!token) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  if (error) {
    return (
      <EmptyState icon={AlertTriangle} title={t('common.error')} description={error} />
    )
  }

  if (loading) {
    return (
      <div>
        <PageHeader title={t('batchDetail.heading')} />
        <p className={styles.loading}>{t('batchDetail.loading')}</p>
      </div>
    )
  }

  if (!batch) {
    return (
      <EmptyState icon={Package} title={t('batchDetail.notFound')} description={t('batchDetail.notFoundDesc')} />
    )
  }

  // ── Stats ───────────────────────────────────────────────────────

  const inProgressCount = tasks.filter(t => t.status === 'in_progress').length
  const completedCount = tasks.filter(t => t.status === 'completed').length

  return (
    <div>
      <Link to="/batches" className={styles.backLink}>
        <ArrowLeft size={14} /> {t('batchDetail.backToBatches')}
      </Link>

      <PageHeader title={batch.name} />

      {/* ── Stats row ─────────────────────────────────────────── */}
      <div className={styles.stats}>
        <StatCard label={t('batchDetail.totalTasks')} value={tasks.length} icon={ClipboardList} accent="primary" />
        <StatCard label={t('batchDetail.inProgress')} value={inProgressCount} icon={Loader} accent="warning" />
        <StatCard label={t('batchDetail.completed')} value={completedCount} icon={CheckCircle} accent="success" />
      </div>

      {/* ── Batch info card ────────────────────────────────────── */}
      <section className={styles.infoCard}>
        <h2 className={styles.sectionTitle}>{t('batchDetail.info')}</h2>
        <div className={styles.infoGrid}>
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>{t('batchDetail.status')}</span>
            <span className={`${styles.badge} ${badgeClass(batch.status, styles)}`}>{batch.status}</span>
          </div>
          {batch.phase && batch.batch_number != null ? (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('batchDetail.phase')}</span>
              <span className={styles.infoValue}>{batch.phase}-B{batch.batch_number}</span>
            </div>
          ) : (
            <>
              {batch.phase && (
                <div className={styles.infoItem}>
                  <span className={styles.infoLabel}>{t('batchDetail.phase')}</span>
                  <span className={styles.infoValue}>{batch.phase}</span>
                </div>
              )}
              {batch.batch_number != null && (
                <div className={styles.infoItem}>
                  <span className={styles.infoLabel}>{t('batchDetail.batchNumber')}</span>
                  <span className={styles.infoValue}>#{batch.batch_number}</span>
                </div>
              )}
            </>
          )}
          {batch.assigned_to && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('batchDetail.assignedTo')}</span>
              <span className={styles.infoValue}>
                <Link to={`/workers/${batch.assigned_to}`}>
                  {assignedWorker?.name || batch.assigned_to.slice(0, 12) + '…'}
                </Link>
              </span>
            </div>
          )}
          {batch.order != null && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('batchDetail.order')}</span>
              <span className={styles.infoValue}>#{batch.order}</span>
            </div>
          )}
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>ID</span>
            <span className={styles.monoValue}>{batch.id}</span>
          </div>
          {batch.created_at && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('batchDetail.created')}</span>
              <span className={styles.infoValue}>{formatDate(batch.created_at, lang)}</span>
            </div>
          )}
          {batch.completed_at && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('batchDetail.completedAt')}</span>
              <span className={styles.infoValue}>{formatDate(batch.completed_at, lang)}</span>
            </div>
          )}
        </div>

        {/* Description */}
        {batch.description && (
          <div className={styles.descriptionSection}>
            <span className={styles.infoLabel}>{t('batchDetail.description')}</span>
            <p className={styles.descriptionText}>{batch.description}</p>
          </div>
        )}
      </section>

      {/* ── Task list ──────────────────────────────────────────── */}
      <section className={styles.taskSection}>
        <div className={styles.taskSectionHeader}>
          <h2 className={styles.sectionTitle}>
            {t('batchDetail.tasks')}
            {tasks.length > 0 && <span className={styles.taskCount}>{tasks.length}</span>}
          </h2>
          {tasks.length > 0 && (
            <Link
              to={`/tasks?tab=history&batch=${batchId}`}
              className={styles.viewInTasksLink}
            >
              <ExternalLink size={13} />
              {t('batchDetail.viewInTasks')}
            </Link>
          )}
        </div>

        {!projectId && (
          <p className={styles.emptyText}>{t('batchDetail.noProject')}</p>
        )}

        {projectId && tasks.length === 0 && (
          <p className={styles.emptyText}>{t('batchDetail.noTasks')}</p>
        )}

        {tasks.length > 0 && (
          <div className={styles.taskList}>
            {tasks.map(task => (
              <TaskCard key={task.id} task={task} />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function badgeClass(status: string, s: typeof styles): string {
  switch (status) {
    case 'open': return s.badgeOpen
    case 'completed': return s.badgeCompleted
    default: return s.badgeDefault
  }
}

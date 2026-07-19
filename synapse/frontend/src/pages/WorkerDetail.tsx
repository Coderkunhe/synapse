import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { Lock, Bot, User, ClipboardList, CheckCircle, Loader, AlertTriangle, ChevronDown, ChevronRight, Download, BookOpen, Code, Pause, Play, Trash2, Zap, BarChart3 } from 'lucide-react'
import { fetchWorker, fetchTasks, fetchTokenUsageStats, suspendWorker, resumeWorker, deleteWorker, downloadSkillBlob, API_BASE } from '../api/client'
import type { WorkerDetail, TaskSummary, TokenUsageStats } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import TaskCard from '../components/TaskCard'
import ConfirmModal from '../components/ConfirmModal'
import styles from './WorkerDetail.module.css'

export default function WorkerDetail() {
  const { workerId } = useParams<{ workerId: string }>()
  const { t, lang } = useI18n()
  const { token } = useAuth()
  const [worker, setWorker] = useState<WorkerDetail | null>(null)
  const [tasks, setTasks] = useState<TaskSummary[]>([])
  const [tokenStats, setTokenStats] = useState<TokenUsageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showPrompt, setShowPrompt] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [projectId] = useState(() => localStorage.getItem('synapse_project_id'))

  const navigate = useNavigate()

  // ── Action state ──────────────────────────────────────────────
  const [modalAction, setModalAction] = useState<'suspend' | 'resume' | 'delete' | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    if (!token || !workerId) {
      setError(t('auth.setTokenHint'))
      setLoading(false)
      return
    }

    const projectId = localStorage.getItem('synapse_project_id')

    const fetches: [
      Promise<WorkerDetail>,
      Promise<{ items: TaskSummary[]; total: number }> | null,
      Promise<TokenUsageStats>,
    ] = [
      fetchWorker(workerId, token),
      projectId ? fetchTasks(projectId, token, { ownerId: workerId }) : null,
      fetchTokenUsageStats(workerId, token),
    ]

    Promise.all(fetches)
      .then(([a, t, ts]) => {
        setWorker(a)
        if (t) setTasks(t.items)
        setTokenStats(ts)
        setLoading(false)
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [workerId, token, t])

  // ── Guards ─────────────────────────────────────────────────────

  const downloadLinkRef = useRef<HTMLAnchorElement>(null)

  /** Download rendered SKILL.md for this worker. */
  const handleDownloadSkill = async () => {
    if (!token || !workerId || !projectId || !downloadLinkRef.current) return
    setDownloading(true)
    try {
      const blob = await downloadSkillBlob(workerId, projectId, token)
      const blobUrl = URL.createObjectURL(blob)
      const link = downloadLinkRef.current
      link.href = blobUrl
      link.download = `synapse-skill-${worker?.name || workerId}.md`
      link.click()
      URL.revokeObjectURL(blobUrl)
    } catch {
      // Skill download failed — user will see disabled button state
    } finally {
      setDownloading(false)
    }
  }

  /** Execute the confirmed action (suspend / resume / delete). */
  const executeAction = async () => {
    if (!token || !workerId || !modalAction) return
    setActionLoading(true)
    try {
      switch (modalAction) {
        case 'suspend': {
          const updated = await suspendWorker(workerId, token)
          setWorker(updated)
          break
        }
        case 'resume': {
          const updated = await resumeWorker(workerId, token)
          setWorker(updated)
          break
        }
        case 'delete': {
          await deleteWorker(workerId, token)
          navigate('/workers')
          return // navigate away — no need to reset loading
        }
      }
    } catch {
      // Action failed — modal will close, user can retry
    } finally {
      setActionLoading(false)
      setModalAction(null)
    }
  }

  // ── Token usage aggregation ──────────────────────────────────

  const tokenAggregate = useMemo(() => {
    if (!tokenStats || tokenStats.total_requests === 0) return null

    const topModel = Object.entries(tokenStats.models).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '-'

    return {
      totalTokens: tokenStats.total_tokens,
      totalRequests: tokenStats.total_requests,
      modelCount: tokenStats.model_count,
      providerMap: new Map(Object.entries(tokenStats.providers)),
      modelMap: new Map(Object.entries(tokenStats.models)),
      topModel,
      daily: tokenStats.daily,
    }
  }, [tokenStats])

  // ── Modal props ──────────────────────────────────────────────

  const modalConfig = (() => {
    if (!modalAction) return null
    const isDelete = modalAction === 'delete'
    const isSuspend = modalAction === 'suspend'
    return {
      title: isDelete ? t('workerDetail.delete') : isSuspend ? t('workerDetail.suspend') : t('workerDetail.resume'),
      message: isDelete ? t('workerDetail.deleteConfirm') : isSuspend ? t('workerDetail.suspendConfirm') : t('workerDetail.resumeConfirm'),
      confirmLabel: isDelete ? t('workerDetail.delete') : isSuspend ? t('workerDetail.suspend') : t('workerDetail.resume'),
      confirmVariant: (isDelete ? 'danger' : 'warning') as 'danger' | 'warning',
      loading: actionLoading,
      onConfirm: executeAction,
      onCancel: () => setModalAction(null),
    }
  })()

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
        <PageHeader title={t('workerDetail.heading')} />
        <p className={styles.loading}>{t('workerDetail.loading')}</p>
      </div>
    )
  }

  if (!worker) {
    return (
      <EmptyState icon={Bot} title={t('workerDetail.notFound')} description={t('workerDetail.notFoundDesc')} />
    )
  }

  // ── Stats ───────────────────────────────────────────────────────

  const inProgressCount = tasks.filter(t => t.status === 'in_progress').length
  const completedCount = tasks.filter(t => t.status === 'completed').length

  return (
    <div>
      {/* Hidden anchor for programmatic download trigger — managed by React, not document.createElement */}
      <a ref={downloadLinkRef} style={{ display: 'none' }} aria-hidden="true" />
      <Link to="/workers" className={styles.backLink}>
        ← {t('workerDetail.backToWorkers')}
      </Link>

      <PageHeader title={worker.name}>
        <span className={styles.typeIcon}>
          {worker.metadata?.worker_type === 'human'
            ? <User size={18} strokeWidth={1.5} />
            : <Bot size={18} strokeWidth={1.5} />
          }
        </span>
      </PageHeader>

      {/* ── Stats row ─────────────────────────────────────────── */}
      <div className={styles.stats}>
        <StatCard label={t('workerDetail.totalTasks')} value={tasks.length} icon={ClipboardList} accent="primary" />
        <StatCard label={t('workerDetail.inProgress')} value={inProgressCount} icon={Loader} accent="warning" />
        <StatCard label={t('workerDetail.completed')} value={completedCount} icon={CheckCircle} accent="success" />
        {tokenAggregate && (
          <StatCard label={t('workerDetail.totalTokens')} value={tokenAggregate.totalTokens.toLocaleString()} icon={Zap} accent="info" />
        )}
      </div>

      {/* ── Worker info card ────────────────────────────────────── */}
      <section className={styles.infoCard}>
        <h2 className={styles.sectionTitle}>{t('workerDetail.info')}</h2>
        <div className={styles.infoGrid}>
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>{t('workerDetail.status')}</span>
            <span className={`${styles.badge} ${badgeClass(worker.status, styles)}`}>{worker.status}</span>
          </div>
          {!!worker.metadata?.worker_type && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('workers.workerType')}</span>
              <span className={styles.infoValue}>
                {worker.metadata!.worker_type === 'human' ? t('workers.workerTypeHuman') : t('workers.workerTypeAgent')}
              </span>
            </div>
          )}
          {!!worker.metadata?.role && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('workers.role')}</span>
              <span className={styles.infoValue}>
                {(() => {
                  const rm: Record<string, string> = { orchestrator: t('workers.roleOrchestrator'), builder: t('workers.roleBuilder'), steward: t('workers.roleSteward'), guardian: t('workers.roleSteward') }
                  return rm[worker.metadata!.role as string] || String(worker.metadata!.role)
                })()}
              </span>
            </div>
          )}
          {worker.metadata?.worker_type !== 'human' && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('workerDetail.provider')}</span>
              <span className={styles.infoValue}>{worker.provider}{worker.provider_model ? ` / ${worker.provider_model}` : ''}</span>
            </div>
          )}
          {worker.metadata?.worker_type !== 'human' && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('workerDetail.batchSize')}</span>
              <span className={styles.infoValue}>{worker.batch_size}</span>
            </div>
          )}
          <div className={styles.infoItem}>
            <span className={styles.infoLabel}>ID</span>
            <span className={styles.monoValue}>{worker.id}</span>
          </div>
          {worker.created_at && (
            <div className={styles.infoItem}>
              <span className={styles.infoLabel}>{t('workerDetail.registered')}</span>
              <span className={styles.infoValue}>{formatDate(worker.created_at, lang)}</span>
            </div>
          )}
        </div>

        {/* System prompt — collapsible */}
        {worker.system_prompt && (
          <div className={styles.promptSection}>
            <button
              type="button"
              className={styles.promptToggle}
              onClick={() => setShowPrompt(!showPrompt)}
            >
              {showPrompt ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              {t('workerDetail.systemPrompt')}
            </button>
            {showPrompt && (
              <pre className={styles.promptText}>{worker.system_prompt}</pre>
            )}
          </div>
        )}

        {/* Metadata */}
        {worker.metadata && Object.keys(worker.metadata).length > 0 && (
          <div className={styles.metaSection}>
            <span className={styles.metaLabel}>{t('workerDetail.metadata')}</span>
            <pre className={styles.metaJson}>{JSON.stringify(worker.metadata, null, 2)}</pre>
          </div>
        )}

        {/* ── Action bar ──────────────────────────────────── */}
        <div className={styles.actionBar}>
          <button
            type="button"
            className={`${styles.actionBtn} ${worker.is_disabled ? styles.actionBtnResume : styles.actionBtnSuspend}`}
            onClick={() => setModalAction(worker.is_disabled ? 'resume' : 'suspend')}
            title={worker.is_disabled ? t('workerDetail.resume') : t('workerDetail.suspend')}
          >
            {worker.is_disabled ? <Play size={14} /> : <Pause size={14} />}
            <span>{worker.is_disabled ? t('workerDetail.resume') : t('workerDetail.suspend')}</span>
          </button>
          <button
            type="button"
            className={`${styles.actionBtn} ${styles.actionBtnDelete}`}
            onClick={() => setModalAction('delete')}
            title={t('workerDetail.delete')}
          >
            <Trash2 size={14} />
            <span>{t('workerDetail.delete')}</span>
          </button>
        </div>
      </section>

      {/* ── Onboarding guide ─────────────────────────────────── */}
      <section className={styles.onboardingSection}>
        <h2 className={styles.sectionTitle}>{t('workerDetail.onboarding')}</h2>
        <p className={styles.onboardingDesc}>{t('workerDetail.onboardingDesc')}</p>
        <div className={styles.onboardingActions}>
          <button
            type="button"
            className={`${styles.onboardingBtn} ${styles.onboardingBtnPrimary}`}
            onClick={handleDownloadSkill}
            disabled={downloading || !projectId}
          >
            <Download size={14} />
            {downloading ? t('common.saving') : t('workerDetail.downloadSkill')}
          </button>
          <a
            href={`${API_BASE}/v1/workers/${worker.id}/protocol`}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.onboardingBtn}
          >
            <Code size={14} />
            {t('workerDetail.viewProtocol')}
          </a>
          <Link to="/docs" className={styles.onboardingBtn}>
            <BookOpen size={14} />
            {t('workerDetail.viewDocs')}
          </Link>
        </div>
        <p className={styles.onboardingHint}>{t('workerDetail.onboardingHint')}</p>
      </section>

      {/* ── Task list ──────────────────────────────────────────── */}
      <section className={styles.taskSection}>
        <h2 className={styles.sectionTitle}>
          {t('workerDetail.tasks')}
          {tasks.length > 0 && <span className={styles.taskCount}>{tasks.length}</span>}
        </h2>

        {!projectId && (
          <p className={styles.emptyText}>{t('workerDetail.noProject')}</p>
        )}

        {projectId && tasks.length === 0 && (
          <p className={styles.emptyText}>{t('workerDetail.noTasks')}</p>
        )}

        {tasks.length > 0 && (
          <div className={styles.taskList}>
            {tasks.map(task => (
              <TaskCard key={task.id} task={task} />
            ))}
          </div>
        )}
      </section>

      {/* ── Token Usage ──────────────────────────────────────── */}
      <section className={styles.infoCard}>
        <h2 className={styles.sectionTitle}>
          <BarChart3 size={16} />
          {t('workerDetail.tokenUsage')}
        </h2>

        {!tokenAggregate ? (
          <p className={styles.emptyText}>{t('workerDetail.noTokenData')}</p>
        ) : (
          <>
            {/* Stat cards */}
            <div className={styles.stats}>
              <StatCard label={t('workerDetail.totalRequests')} value={tokenAggregate.totalRequests} icon={BarChart3} accent="primary" />
              <StatCard label={t('workerDetail.mostUsedModel')} value={tokenAggregate.topModel} icon={Bot} accent="success" />
              <StatCard label={t('workerDetail.modelCount')} value={tokenAggregate.modelCount} icon={Zap} accent="warning" />
            </div>

            {/* Daily time-series — 7 day bar chart */}
            {tokenAggregate.daily.length > 0 && (
              <div className={styles.tokenBars}>
                <span className={styles.tokenBarsTitle}>{t('workerDetail.dailyUsage')}</span>
                {tokenAggregate.daily.map((d) => (
                  <div key={d.date} className={styles.tokenBar}>
                    <span className={styles.tokenBarLabel}>{d.date.slice(5)}</span>
                    <span
                      className={styles.tokenBarFill}
                      style={{
                        width: `${Math.max(2, (d.tokens / Math.max(...tokenAggregate.daily.map(x => x.tokens), 1)) * 100)}%`,
                      }}
                    />
                    <span className={styles.tokenBarValue}>{d.tokens.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Provider breakdown */}
            {tokenAggregate.providerMap.size > 0 && (
              <div className={styles.tokenBars}>
                <span className={styles.tokenBarsTitle}>{t('workerDetail.byProvider')}</span>
                {[...tokenAggregate.providerMap.entries()]
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, tokens]) => (
                    <div key={name} className={styles.tokenBar}>
                      <span className={styles.tokenBarLabel}>{name}</span>
                      <span className={styles.tokenBarFill} style={{ width: `${Math.max(2, (tokens / tokenAggregate.totalTokens) * 100)}%` }} />
                      <span className={styles.tokenBarValue}>{tokens.toLocaleString()}</span>
                    </div>
                  ))}
              </div>
            )}

            {/* Model breakdown */}
            {tokenAggregate.modelMap.size > 0 && (
              <div className={styles.tokenBars}>
                <span className={styles.tokenBarsTitle}>{t('workerDetail.byModel')}</span>
                {[...tokenAggregate.modelMap.entries()]
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([name, tokens]) => (
                    <div key={name} className={styles.tokenBar}>
                      <span className={styles.tokenBarLabel}>{name}</span>
                      <span className={styles.tokenBarFill} style={{ width: `${Math.max(2, (tokens / tokenAggregate.totalTokens) * 100)}%` }} />
                      <span className={styles.tokenBarValue}>{tokens.toLocaleString()}</span>
                    </div>
                  ))}
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Confirm Modal ──────────────────────────────────────── */}
      {modalConfig && (
        <ConfirmModal
          isOpen
          title={modalConfig.title}
          message={modalConfig.message}
          confirmLabel={modalConfig.confirmLabel}
          confirmVariant={modalConfig.confirmVariant}
          loading={modalConfig.loading}
          onConfirm={modalConfig.onConfirm}
          onCancel={modalConfig.onCancel}
        />
      )}
    </div>
  )
}

function badgeClass(status: string, s: typeof styles): string {
  switch (status) {
    case 'active': return s.badgeActive
    case 'pending': return s.badgePending
    default: return s.badgeInactive
  }
}

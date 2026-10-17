import { useState, useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { Bot, ClipboardList, FolderOpen, Radio, Lock, Zap, ExternalLink } from 'lucide-react'
import StatCard from '../components/StatCard'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import { fetchTeamStats, fetchTeamEvents, fetchProjectsBreakdown, fetchWorkers } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { useFeatures } from '../contexts/FeaturesContext'
import { useWebSocket, TASK_EVENT_TYPES } from '../api/ws'
import { formatDate } from '../utils/format'
import type { TeamStats, EventSummary, ProjectBreakdown, WorkerSummary } from '../api/client'
import styles from './Dashboard.module.css'

export default function Dashboard() {
  const { t, lang } = useI18n()
  const { isMinimalProject } = useFeatures()
  const { token, teamId, logout } = useAuth()
  const [stats, setStats] = useState<TeamStats | null>(null)
  const [events, setEvents] = useState<EventSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [projects, setProjects] = useState<ProjectBreakdown[]>([])
  const [breakdownLoading, setBreakdownLoading] = useState(true)
  const [breakdownError, setBreakdownError] = useState<string | null>(null)
  const [workers, setWorkers] = useState<WorkerSummary[]>([])
  const [workerError, setWorkerError] = useState<string | null>(null)

  useEffect(() => {
    if (!token || !teamId) {
      setLoading(false)
      setError(t('auth.setTokenHint'))
      return
    }
    Promise.all([
      fetchTeamStats(teamId, token),
      fetchTeamEvents(teamId, token),
    ])
      .then(([s, e]) => { setStats(s); setEvents(e.items) })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))

    fetchProjectsBreakdown(teamId, token)
      .then(res => setProjects(res.projects))
      .catch(err => setBreakdownError(err.message))
      .finally(() => setBreakdownLoading(false))

    fetchWorkers(teamId, token)
      .then(res => setWorkers(res.items))
      .catch(err => setWorkerError(err instanceof Error ? err.message : 'Failed to load worker names'))
  }, [token, teamId, t])

  const workerNames = useMemo(() => {
    const map = new Map<string, string>()
    workers.forEach(w => map.set(w.id, w.name))
    return map
  }, [workers])

  // ── P17-B28: team rollup WS real-time ─────────────────────────────
  const { status, lastEvent } = useWebSocket(token, TASK_EVENT_TYPES, logout)
  const breakdownRefreshRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Any task.* event reshapes the per-project breakdown (team-scoped rollup, no
  // project isolation needed — unlike B6's single-project DAG view). 300ms
  // debounce aggregates a burst (claim→submit→complete) into a single fetch.
  useEffect(() => {
    if (!lastEvent) return
    if (!TASK_EVENT_TYPES.includes(lastEvent.event_type)) return

    if (breakdownRefreshRef.current) clearTimeout(breakdownRefreshRef.current)
    breakdownRefreshRef.current = setTimeout(() => {
      if (!token || !teamId) return
      fetchProjectsBreakdown(teamId, token)
        .then(res => setProjects(res.projects))
        .catch(() => { /* keep last known breakdown — non-critical refresh */ })
    }, 300)
  }, [lastEvent, token, teamId])

  // Clear the pending breakdown refresh on unmount
  useEffect(() => {
    return () => {
      if (breakdownRefreshRef.current) clearTimeout(breakdownRefreshRef.current)
    }
  }, [])

  if (error) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={error} />
    )
  }

  if (loading) {
    return (
      <div>
        <PageHeader title={t('dashboard.heading')} />
        <p className={styles.loading}>{t('common.loading')}</p>
      </div>
    )
  }

  return (
    <div>
      <PageHeader title={t('dashboard.heading')} subtitle={t('brand.slogan')} />

      {stats && (
        <div className={styles.stats}>
          <StatCard label={t('dashboard.agentCount')} value={stats.worker_count} icon={Bot} accent="primary" />
          <StatCard label={t('dashboard.activeTaskCount')} value={stats.active_task_count} icon={ClipboardList} accent="warning" />
          {isMinimalProject ? (
            <StatCard label={t('dashboard.projectCount')} value={stats.project_count} icon={FolderOpen} accent="info" />
          ) : (
            <Link to="/projects" className={styles.statLink}>
              <StatCard label={t('dashboard.projectCount')} value={stats.project_count} icon={FolderOpen} accent="info" />
            </Link>
          )}
          <StatCard label={t('dashboard.todayEventCount')} value={stats.today_event_count} icon={Radio} accent="success" />
          {stats.total_tokens > 0 && (
            <StatCard label={t('dashboard.totalTokens')} value={stats.total_tokens.toLocaleString()} icon={Zap} accent="info" />
          )}
          {stats.week_tokens > 0 && (
            <StatCard label={t('dashboard.weekTokens')} value={stats.week_tokens.toLocaleString()} icon={Zap} accent="info" />
          )}
        </div>
      )}

      <ProjectBreakdownSection
        projects={projects}
        loading={breakdownLoading}
        error={breakdownError}
        isMinimalProject={isMinimalProject}
        t={t}
        liveStatus={status}
      />

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>{t('dashboard.recentEvents')}</h2>
        {workerError && (
          <p className={styles.breakdownError}>{workerError}</p>
        )}
        {events.length === 0 ? (
          <p className={styles.emptyText}>{t('dashboard.noEvents')}</p>
        ) : (
          <div className={styles.eventList}>
            {events.map(evt => (
              <div key={evt.id} className={styles.eventRow}>
                <span className={`${styles.eventBadge} ${eventBadgeStyle(evt.event_type)}`}>
                  {evt.event_type}
                </span>
                <span className={styles.eventMeta}>
                  {workerNames.get(evt.actor_id) ?? `${evt.actor_type}:${evt.actor_id?.slice(0, 12)}`} → {evt.target_type}:{evt.target_id?.slice(0, 12)}
                </span>
                <span className={styles.eventTime}>
                  {formatDate(evt.created_at, lang)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function eventBadgeStyle(type: string): string {
  if (type.includes('created')) return styles.evtCreate
  if (type.includes('completed')) return styles.evtSuccess
  if (type.includes('failed') || type.includes('cancelled')) return styles.evtDanger
  if (type.includes('assigned') || type.includes('claimed')) return styles.evtWarning
  return styles.evtInfo
}

// ── Project Breakdown ──────────────────────────────────────────────────

const STATUS_CONFIG: Record<string, { color: string; labelKey: string }> = {
  backlog: { color: '#94a3b8', labelKey: 'task.columns.backlog' },
  ready: { color: '#60a5fa', labelKey: 'task.columns.ready' },
  in_progress: { color: '#f59e0b', labelKey: 'task.columns.inProgress' },
  in_verification: { color: '#a78bfa', labelKey: 'task.columns.inVerification' },
  completed: { color: '#4ade80', labelKey: 'task.columns.completed' },
  cancelled: { color: '#f87171', labelKey: 'task.columns.cancelled' },
}

function progressBarColor(pct: number): string {
  if (pct >= 80) return '#4ade80'
  if (pct >= 40) return '#60a5fa'
  return '#f59e0b'
}

interface ProjectBreakdownSectionProps {
  projects: ProjectBreakdown[]
  loading: boolean
  error: string | null
  isMinimalProject: boolean
  t: (key: string, vars?: Record<string, string | number>) => string
  liveStatus: string
}

function ProjectBreakdownSection({ projects, loading, error, isMinimalProject, t, liveStatus }: ProjectBreakdownSectionProps) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeader}>
        <h2 className={styles.sectionTitle}>
          {t('dashboard.projectsBreakdown')}
          <span
            className={`${styles.liveDot} ${liveStatus === 'connected' ? styles.liveDotOn : ''}`}
            data-testid="dashboard-live-dot"
            title={liveStatus}
          />
        </h2>
        {!isMinimalProject && projects.length > 0 && (
          <Link to="/projects" className={styles.sectionLink}>
            {t('dashboard.viewAllProjects')} <ExternalLink size={12} />
          </Link>
        )}
      </div>

      {error && (
        <p className={styles.breakdownError}>{error}</p>
      )}

      {loading && (
        <p className={styles.loading}>{t('common.loading')}</p>
      )}

      {!loading && !error && projects.length === 0 && (
        <div className={styles.emptyProjectCard}>
          {t('dashboard.noProjects')} — {t('dashboard.noProjectsHint')}
        </div>
      )}

      {!loading && projects.length > 0 && (
        <div className={styles.projectGrid}>
          {projects.map(p => {
            const pct = p.total_tasks > 0
              ? Math.round((p.completed_tasks / p.total_tasks) * 100)
              : 0

            return (
              <div key={p.project_id} className={styles.projectCard} data-project-id={p.project_id}>
                <div className={styles.projectNameRow}>
                  <Link to={`/projects/${p.project_id}?tab=overview`} className={styles.projectNameLink}>
                    {p.project_name}
                  </Link>
                  {p.dependency_blocked > 0 && (
                    <span className={styles.blockedBadge}>
                      🔒 {t('dashboard.blocked', { count: p.dependency_blocked })}
                    </span>
                  )}
                </div>

                {p.total_tasks === 0 ? (
                  <p className={styles.progressText}>
                    {t('dashboard.emptyProject', { count: 0 })}
                  </p>
                ) : (
                  <>
                    <div className={styles.progressBar}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${pct}%`, background: progressBarColor(pct) }}
                      />
                    </div>
                    <p className={styles.progressText}>
                      {t('dashboard.completionRate', {
                        done: p.completed_tasks,
                        total: p.total_tasks,
                        pct,
                      })}
                    </p>
                    <div className={styles.statusChips}>
                      {Object.entries(STATUS_CONFIG).map(([status, cfg]) => {
                        const count = p.by_status[status as keyof typeof p.by_status] ?? 0
                        if (count === 0) return null
                        return (
                          <span key={status} className={styles.statusChip} data-status={status} data-count={count}>
                            <span
                              className={styles.statusDot}
                              style={{ background: cfg.color }}
                            />
                            {t(cfg.labelKey)}&nbsp;{count}
                          </span>
                        )
                      })}
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

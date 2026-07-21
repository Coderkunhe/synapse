/**
 * Approvals — cross-Project aggregation of pending AuthorizationRequests.
 *
 * P10-B23: 议题 3 授权管道前端落地。
 * Fetches all projects for the user's team, then concurrently loads
 * pending authorization requests for each project. Supports approve/deny
 * with optional response note.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ShieldCheck, Clock, Check, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import {
  fetchProjects,
  fetchAuthRequests,
  respondToAuthRequest,
  type AuthRequestSummary,
} from '../api/client'
import { useWebSocket } from '../api/ws'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import styles from './Approvals.module.css'

/** Event types that should trigger an approvals list refresh. */
const AUTH_EVENT_TYPES = [
  'authorization_request.created',
  'authorization_request.responded',
  'authorization_request.expired',
  'authorization_request.cancelled',
]

/** Augmented request with resolved project name for display. */
interface ApprovalItem extends AuthRequestSummary {
  projectName: string
}

/** Format relative time for expiry display. */
function formatExpiresIn(expiresAt: string): string {
  const ms = new Date(expiresAt).getTime() - Date.now()
  if (ms <= 0) return 'expired'
  const mins = Math.floor(ms / 60000)
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.floor(hours / 24)}d`
}

export default function Approvals() {
  const { token, teamId } = useAuth()
  const { t } = useI18n()

  const [items, setItems] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [respondingId, setRespondingId] = useState<string | null>(null)
  const [noteInputs, setNoteInputs] = useState<Record<string, string>>({})

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    setError(null)

    fetchProjects(teamId, token)
      .then((res) => {
        const projects = res.items
        // Build project name lookup
        const nameMap = new Map(projects.map((p) => [p.id, p.name]))

        // Concurrently fetch pending requests for all projects
        return Promise.allSettled(
          projects.map((p) =>
            fetchAuthRequests(p.id, token, { status: 'pending', limit: 50 }),
          ),
        ).then((results) => {
          const merged: ApprovalItem[] = []
          for (let i = 0; i < results.length; i++) {
            const r = results[i]
            if (r.status === 'fulfilled') {
              for (const req of r.value) {
                merged.push({
                  ...req,
                  projectName: nameMap.get(req.project_id) || projects[i]?.name || t('approvals.unknownProject'),
                })
              }
            }
            // rejected (e.g. 403 on a project without admin role) → silently skip
          }
          // Sort by created_at descending (newest first)
          merged.sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          )
          setItems(merged)
          setLoading(false)
        })
      })
      .catch((err) => {
        setError(err.message || String(err))
        setLoading(false)
      })
  }, [token, teamId, t])

  useEffect(() => {
    load()
  }, [load])

  // ── P11-B22: WebSocket real-time updates ──────────────────────────────────
  const { lastEvent } = useWebSocket(token, AUTH_EVENT_TYPES)
  const pendingRefreshRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!lastEvent) return
    if (!AUTH_EVENT_TYPES.includes(lastEvent.event_type)) return

    // Debounce rapid events (e.g., batch expiry) into a single re-fetch
    if (pendingRefreshRef.current) {
      clearTimeout(pendingRefreshRef.current)
    }
    pendingRefreshRef.current = setTimeout(() => {
      load()
    }, 200)
  }, [lastEvent, load])

  const handleRespond = async (requestId: string, status: 'approved' | 'denied') => {
    if (!token) return
    setRespondingId(requestId)
    try {
      await respondToAuthRequest(requestId, {
        status,
        response_note: noteInputs[requestId] || undefined,
      }, token)
      // Optimistic removal
      setItems((prev) => prev.filter((it) => it.id !== requestId))
      setNoteInputs((prev) => {
        const next = { ...prev }
        delete next[requestId]
        return next
      })
    } catch {
      // Show inline error — the request may have expired
      alert(t('approvals.respondError'))
    } finally {
      setRespondingId(null)
    }
  }

  // ── Render states ──────────────────────────────────────────────────────

  if (error) {
    return (
      <EmptyState
        icon={ShieldCheck}
        title={t('approvals.loadError')}
        description={error}
      />
    )
  }

  return (
    <div className={styles.shell}>
      <PageHeader title={t('approvals.heading')} />

      {loading && <p className={styles.loading}>{t('approvals.loading')}</p>}

      {!loading && items.length === 0 && (
        <EmptyState
          icon={ShieldCheck}
          title={t('approvals.noPending')}
          description={t('approvals.noPendingDesc')}
        />
      )}

      {items.length > 0 && (
        <div className={styles.list}>
          {items.map((item) => (
            <div key={item.id} className={styles.card}>
              {/* ── Card header: type badge + project + time ── */}
              <div className={styles.cardHeader}>
                <span
                  className={`${styles.typeBadge} ${
                    item.request_type === 'api_auth'
                      ? styles.typeApiAuth
                      : styles.typeInteractive
                  }`}
                >
                  {item.request_type === 'api_auth'
                    ? t('approvals.requestTypeApiAuth')
                    : t('approvals.requestTypeInteractive')}
                </span>
                <span className={styles.projectName}>
                  {item.projectName}
                </span>
                <span className={styles.expires}>
                  <Clock size={14} />
                  {formatExpiresIn(item.expires_at)}
                </span>
              </div>

              {/* ── Card body: request-specific details ── */}
              <div className={styles.cardBody}>
                {item.request_type === 'api_auth' ? (
                  <div className={styles.apiAuthDetails}>
                    <div className={styles.detailRow}>
                      <span className={styles.detailLabel}>{t('approvals.operation')}</span>
                      <code className={styles.detailValue}>{item.operation || t('common.none')}</code>
                    </div>
                    {item.target_resource_type && (
                      <div className={styles.detailRow}>
                        <span className={styles.detailLabel}>{t('approvals.targetResource')}</span>
                        <span className={styles.detailValue}>
                          {item.target_resource_type}
                          {item.target_resource_id && ` / ${item.target_resource_id}`}
                        </span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className={styles.promptDetails}>
                    <p className={styles.promptMessage}>
                      {item.prompt_message || t('common.noDescription')}
                    </p>
                    {item.prompt_type && (
                      <span className={styles.promptTypeTag}>
                        {item.prompt_type === 'choice'
                          ? t('approvals.promptChoice')
                          : item.prompt_type === 'confirm'
                            ? t('approvals.promptConfirm')
                            : t('approvals.promptInput')}
                      </span>
                    )}
                    {item.prompt_choices && item.prompt_choices.length > 0 && (
                      <div className={styles.choices}>
                        {item.prompt_choices.map((c, i) => (
                          <span key={i} className={styles.choiceChip}>{c}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* ── Worker ID ── */}
                <div className={styles.workerRow}>
                  <span className={styles.detailLabel}>{t('approvals.workerLabel')}</span>
                  <code className={styles.workerId}>{item.worker_id}</code>
                </div>
              </div>

              {/* ── Card footer: actions ── */}
              <div className={styles.cardFooter}>
                <input
                  type="text"
                  className={styles.noteInput}
                  placeholder={t('approvals.responseNotePlaceholder')}
                  value={noteInputs[item.id] || ''}
                  onChange={(e) =>
                    setNoteInputs((prev) => ({ ...prev, [item.id]: e.target.value }))
                  }
                  disabled={respondingId === item.id}
                />
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={`${styles.actionBtn} ${styles.denyBtn}`}
                    onClick={() => handleRespond(item.id, 'denied')}
                    disabled={respondingId !== null}
                  >
                    {respondingId === item.id ? (
                      t('approvals.denying')
                    ) : (
                      <>
                        <X size={16} /> {t('approvals.deny')}
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    className={`${styles.actionBtn} ${styles.approveBtn}`}
                    onClick={() => handleRespond(item.id, 'approved')}
                    disabled={respondingId !== null}
                  >
                    {respondingId === item.id ? (
                      t('approvals.approving')
                    ) : (
                      <>
                        <Check size={16} /> {t('approvals.approve')}
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

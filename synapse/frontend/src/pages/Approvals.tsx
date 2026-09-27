/**
 * Approvals — cross-Project aggregation of pending AuthorizationRequests.
 *
 * P10-B23: 议题 3 授权管道前端落地。
 * Fetches all projects for the user's team, then concurrently loads
 * pending authorization requests for each project. Supports approve/deny
 * with optional response note.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ShieldCheck, Clock, Check, X, History } from 'lucide-react'
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

/** Format relative time for responded_at display. */
function formatTimeAgo(dateStr: string | null): string {
  if (!dateStr) return '—'
  const ms = Date.now() - new Date(dateStr).getTime()
  if (ms < 0) return 'just now'
  const mins = Math.floor(ms / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

/** Humanize operation codes — snake_case → Title Case. */
function humanizeOperation(op: string | null): string {
  if (!op) return '—'
  return op
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

{/* ── P12-B39: AuthRequestModal — read-only detail modal for history items ── */}

interface AuthRequestModalProps {
  isOpen: boolean
  item: ApprovalItem | null
  onClose: () => void
}

function AuthRequestModal({ isOpen, item, onClose }: AuthRequestModalProps) {
  // Lock body scroll
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [isOpen])

  // ESC dismiss
  const overlayRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (isOpen && overlayRef.current) {
      overlayRef.current.focus()
    }
  }, [isOpen])

  if (!isOpen || !item) return null

  return createPortal(
    <div
      className={styles.modalOverlay}
      onClick={onClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
      tabIndex={-1}
      ref={overlayRef}
    >
      <div
        className={styles.modalCard}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className={styles.modalHeader}>
          <span className={`${styles.typeBadge} ${
            item.request_type === 'api_auth'
              ? styles.typeApiAuth
              : styles.typeInteractive
          }`}>
            {item.request_type === 'api_auth'
              ? 'API Auth'
              : item.request_type === 'capability_exec'
                ? 'Capability'
                : 'Interactive'}
          </span>
          <span className={statusBadgeSimpleClass(item.status)}>
            {item.status}
          </span>
          <span className={styles.projectName}>{item.projectName}</span>
          <button
            type="button"
            className={styles.modalCloseBtn}
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className={styles.modalBody}>
          {item.operation && (
            <div className={styles.modalRow}>
              <span className={styles.detailLabel}>Operation</span>
              <span className={styles.detailValue}>{humanizeOperation(item.operation)}</span>
            </div>
          )}
          <div className={styles.modalRow}>
            <span className={styles.detailLabel}>Worker</span>
            <span className={styles.workerName}>{item.worker_name || item.worker_id}</span>
          </div>
          {item.target_resource_type && (
            <div className={styles.modalRow}>
              <span className={styles.detailLabel}>Resource</span>
              <span className={styles.detailValue}>
                {item.target_resource_type}
                {item.target_resource_id && ` / ${item.target_resource_id}`}
              </span>
            </div>
          )}
          {item.capability_id && (
            <div className={styles.modalRow}>
              <span className={styles.detailLabel}>Capability</span>
              <span className={styles.detailValue}>{item.capability_id}</span>
            </div>
          )}
          {item.prompt_message && (
            <div className={styles.modalRow}>
              <span className={styles.detailLabel}>Message</span>
              <span className={styles.detailValue}>{item.prompt_message}</span>
            </div>
          )}
          <div className={styles.modalRow}>
            <span className={styles.detailLabel}>Created</span>
            <span className={styles.detailValue}>
              {new Date(item.created_at).toLocaleString()}
            </span>
          </div>
          <div className={styles.modalRow}>
            <span className={styles.detailLabel}>Expires</span>
            <span className={styles.detailValue}>
              {new Date(item.expires_at).toLocaleString()}
            </span>
          </div>
          {item.responded_by_worker_id && (
            <>
              <div className={styles.modalDivider} />
              <div className={styles.modalRow}>
                <span className={styles.detailLabel}>Responded by</span>
                <span className={styles.workerName}>
                  {item.responded_by_worker_name || item.responded_by_worker_id}
                </span>
              </div>
              {item.responded_at && (
                <div className={styles.modalRow}>
                  <span className={styles.detailLabel}>Responded at</span>
                  <span className={styles.detailValue}>
                    {new Date(item.responded_at).toLocaleString()}
                  </span>
                </div>
              )}
              {item.response_note && (
                <div className={styles.modalRow}>
                  <span className={styles.detailLabel}>Note</span>
                  <span className={styles.detailValue}>"{item.response_note}"</span>
                </div>
              )}
            </>
          )}
          {item.outcome && (
            <div className={styles.modalRow}>
              <span className={styles.detailLabel}>Outcome</span>
              <span className={styles.detailValue}>
                {item.outcome === 'success' ? '✅' : '❌'} {item.outcome}
                {item.exit_code != null && ` (exit ${item.exit_code})`}
                {item.duration_ms != null && ` · ${item.duration_ms}ms`}
              </span>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={styles.modalFooter}>
          <button
            type="button"
            className={styles.modalCloseAction}
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/** P12-B39: Simple status badge class helper (used outside main component). */
function statusBadgeSimpleClass(status: string): string {
  const map: Record<string, string> = {
    approved: styles.statusApproved,
    denied: styles.statusDenied,
    expired: styles.statusExpired,
    cancelled: styles.statusCancelled,
    pending: styles.statusApproved, // fallback — pending shouldn't appear in history
  }
  return `${styles.statusBadge} ${map[status] || styles.statusCancelled}`
}

export default function Approvals() {
  const { token, teamId, logout } = useAuth()
  const { t } = useI18n()

  const [items, setItems] = useState<ApprovalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [respondingId, setRespondingId] = useState<string | null>(null)
  const [noteInputs, setNoteInputs] = useState<Record<string, string>>({})
  const [cardErrors, setCardErrors] = useState<Record<string, string>>({})

  // ── P11-B44: Tab + History state ──────────────────────────────────────
  const [viewTab, setViewTab] = useState<'pending' | 'history'>('pending')
  const [historyItems, setHistoryItems] = useState<ApprovalItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyStatusFilter, setHistoryStatusFilter] = useState<string>('all')
  const [historyLoaded, setHistoryLoaded] = useState(false)

  // ── P12-B39: Detail modal state ──────────────────────────────────────
  const [selectedItem, setSelectedItem] = useState<ApprovalItem | null>(null)

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

  // ── P11-B44: History loader ──────────────────────────────────────────
  const loadHistory = useCallback(() => {
    if (!token || !teamId) return
    setHistoryLoading(true)
    setHistoryError(null)

    fetchProjects(teamId, token)
      .then((res) => {
        const projects = res.items
        const nameMap = new Map(projects.map((p) => [p.id, p.name]))

        const statusParam = historyStatusFilter === 'all'
          ? 'all'
          : historyStatusFilter

        return Promise.allSettled(
          projects.map((p) =>
            fetchAuthRequests(p.id, token, { status: statusParam, limit: 50 }),
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
          }
          // Sort by responded_at descending (newest first), fallback to created_at
          merged.sort(
            (a, b) => new Date(b.responded_at || b.created_at).getTime() - new Date(a.responded_at || a.created_at).getTime(),
          )
          setHistoryItems(merged)
          setHistoryLoaded(true)
          setHistoryLoading(false)
        })
      })
      .catch((err) => {
        setHistoryError(err.message || String(err))
        setHistoryLoading(false)
      })
  }, [token, teamId, t, historyStatusFilter])

  // Auto-load history when tab switches or filter changes
  useEffect(() => {
    if (viewTab === 'history') {
      loadHistory()
    }
  }, [viewTab, loadHistory])

  // ── P11-B22: WebSocket real-time updates ──────────────────────────────────
  const { lastEvent } = useWebSocket(token, AUTH_EVENT_TYPES, logout)
  const pendingRefreshRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!lastEvent) return
    if (!AUTH_EVENT_TYPES.includes(lastEvent.event_type)) return

    // Debounce rapid events (e.g., batch expiry) into a single re-fetch
    if (pendingRefreshRef.current) {
      clearTimeout(pendingRefreshRef.current)
    }
    pendingRefreshRef.current = setTimeout(() => {
      // Only refresh the active tab
      if (viewTab === 'pending') {
        load()
      }
      // Always refresh history if it's been loaded (cross-tab sync)
      if (historyLoaded) {
        loadHistory()
      }
    }, 200)
  }, [lastEvent, load, loadHistory, historyLoaded, viewTab])

  const handleRespond = async (requestId: string, status: 'approved' | 'denied') => {
    if (!token) return
    setRespondingId(requestId)
    // Clear previous error for this card
    setCardErrors((prev) => {
      const next = { ...prev }
      delete next[requestId]
      return next
    })
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
    } catch (err: any) {
      // P12-B39: inline error instead of alert
      setCardErrors((prev) => ({
        ...prev,
        [requestId]: err.message || String(err),
      }))
    } finally {
      setRespondingId(null)
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────────

  const STATUS_FILTERS = [
    { key: 'all', label: t('approvals.filterAll') },
    { key: 'approved', label: t('approvals.statusApproved') },
    { key: 'denied', label: t('approvals.statusDenied') },
    { key: 'expired', label: t('approvals.statusExpired') },
    { key: 'cancelled', label: t('approvals.statusCancelled') },
  ] as const

  function statusBadgeClass(status: string): string {
    const map: Record<string, string> = {
      approved: styles.statusApproved,
      denied: styles.statusDenied,
      expired: styles.statusExpired,
      cancelled: styles.statusCancelled,
    }
    return `${styles.statusBadge} ${map[status] || styles.statusCancelled}`
  }

  /** Get human-readable operation description from i18n. */
  function describeOperation(op: string | null): string {
    if (!op) return '—'
    // Convert task.assign → task_assign for i18n dotted-path lookup
    const key = op.replace(/\./g, '_')
    const desc = t(`approvals.ops.${key}`)
    // If no translation found, fall back to humanized operation code
    return desc.startsWith('approvals.ops.') ? humanizeOperation(op) : desc
  }

  /** Format resource type + id for display. */
  function formatResource(type: string | null, id: string | null): string {
    if (!type) return ''
    const label = type.charAt(0).toUpperCase() + type.slice(1)
    return id ? `${label} ${id}` : label
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className={styles.shell}>
      <PageHeader title={t('approvals.heading')} />

      {/* ── Tab bar (P11-B44) ──────────────────────────────────────── */}
      <div className={styles.viewTabBar}>
        <button
          type="button"
          className={`${styles.viewTab} ${viewTab === 'pending' ? styles.viewTabActive : ''}`}
          onClick={() => setViewTab('pending')}
        >
          <Clock size={15} />
          {t('approvals.tabPending')}
          {items.length > 0 && (
            <span className={styles.tabBadge}>{items.length}</span>
          )}
        </button>
        <button
          type="button"
          className={`${styles.viewTab} ${viewTab === 'history' ? styles.viewTabActive : ''}`}
          onClick={() => setViewTab('history')}
        >
          <History size={15} />
          {t('approvals.tabHistory')}
        </button>
      </div>

      {/* ── Pending Tab ────────────────────────────────────────────── */}
      {viewTab === 'pending' && (
        <>
          {error && (
            <EmptyState
              icon={ShieldCheck}
              title={t('approvals.loadError')}
              description={error}
            />
          )}

          {!error && loading && (
            <p className={styles.loading}>{t('approvals.loading')}</p>
          )}

          {!error && !loading && items.length === 0 && (
            <EmptyState
              icon={ShieldCheck}
              title={t('approvals.noPending')}
              description={t('approvals.noPendingDesc')}
            />
          )}

          {!error && !loading && items.length > 0 && (
            <div className={styles.list}>
              {items.map((item) => (
                <div key={item.id} className={styles.card}>
                  {/* ── Card header ── */}
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

                  {/* ── Card body ── */}
                  <div className={styles.cardBody}>
                    {item.request_type === 'api_auth' ? (
                      <div className={styles.apiAuthDetails}>
                        <div className={styles.detailRow}>
                          <span className={styles.detailLabel}>{t('approvals.operation')}</span>
                          <span className={styles.detailValue}>{humanizeOperation(item.operation)}</span>
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
                    ) : item.request_type === 'capability_exec' ? (
                      <div className={styles.apiAuthDetails}>
                        <div className={styles.detailRow}>
                          <span className={styles.detailLabel}>{t('approvals.operation')}</span>
                          <span className={styles.detailValue}>{humanizeOperation(item.operation)}</span>
                        </div>
                        {item.capability_id && (
                          <div className={styles.detailRow}>
                            <span className={styles.detailLabel}>{t('approvals.capability')}</span>
                            <span className={styles.detailValue}>{item.capability_id}</span>
                          </div>
                        )}
                        {item.prompt_message && (
                          <div className={styles.promptDetails}>
                            <p className={styles.promptMessage}>
                              {item.prompt_message}
                            </p>
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

                    {/* ── Worker name ── */}
                    <div className={styles.workerRow}>
                      <span className={styles.detailLabel}>{t('approvals.workerLabel')}</span>
                      <span className={styles.workerName}>{item.worker_name || item.worker_id}</span>
                    </div>
                  </div>

                  {/* ── Card footer: actions ── */}
                  <div className={styles.cardFooter}>
                    {cardErrors[item.id] && (
                      <span className={styles.cardError}>{cardErrors[item.id]}</span>
                    )}
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
        </>
      )}

      {/* ── History Tab (P11-B44) ──────────────────────────────────── */}
      {viewTab === 'history' && (
        <>
          {/* Status filter chips */}
          <div className={styles.filterChips}>
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                type="button"
                className={`${styles.filterChip} ${historyStatusFilter === f.key ? styles.filterChipActive : ''}`}
                onClick={() => setHistoryStatusFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {historyError && (
            <EmptyState
              icon={History}
              title={t('approvals.historyLoadError')}
              description={historyError}
            />
          )}

          {!historyError && historyLoading && (
            <p className={styles.loading}>{t('approvals.loading')}</p>
          )}

          {!historyError && !historyLoading && historyItems.length === 0 && (
            <EmptyState
              icon={History}
              title={t('approvals.noHistory')}
              description={t('approvals.noHistoryDesc')}
            />
          )}

          {!historyError && !historyLoading && historyItems.length > 0 && (
            <div className={styles.list}>
              {historyItems.map((item) => (
                <div
                  key={item.id}
                  className={`${styles.card} ${styles.cardClickable}`}
                  onClick={() => setSelectedItem(item)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedItem(item)
                    }
                  }}
                >
                  {/* ── Card header: status badge + project + time ── */}
                  <div className={styles.cardHeader}>
                    <span className={statusBadgeClass(item.status)}>
                      {item.status === 'approved'
                        ? t('approvals.statusApproved')
                        : item.status === 'denied'
                          ? t('approvals.statusDenied')
                          : item.status === 'expired'
                            ? t('approvals.statusExpired')
                            : t('approvals.statusCancelled')}
                    </span>
                    <span className={styles.projectName}>
                      {item.projectName}
                    </span>
                    <span className={styles.expires}>
                      <Clock size={14} />
                      {formatTimeAgo(item.responded_at || item.created_at)}
                    </span>
                  </div>

                  {/* ── Card body ── */}
                  <div className={styles.cardBody}>
                    {item.request_type === 'api_auth' ? (
                      <>
                        {/* Primary: resource name (task title) — the actual content */}
                        {item.target_resource_name && (
                          <p className={styles.contentTitle}>{item.target_resource_name}</p>
                        )}
                        {/* Secondary: operation + resource type + worker in one meta line */}
                        <div className={styles.contentMeta}>
                          <span>{describeOperation(item.operation)}</span>
                          {item.target_resource_type && (
                            <span className={styles.metaDivider}>·</span>
                          )}
                          {item.target_resource_type && (
                            <span className={styles.metaMuted}>{item.target_resource_type}</span>
                          )}
                          <span className={styles.metaDivider}>·</span>
                          <span className={styles.metaMuted}>{item.worker_name || item.worker_id}</span>
                        </div>
                      </>
                    ) : item.request_type === 'capability_exec' ? (
                      <>
                        {/* Primary: operation name — the actual action */}
                        <p className={styles.contentTitle}>
                          {item.operation || item.capability_id || t('common.noDescription')}
                        </p>
                        {/* Secondary: capability_id + outcome + duration */}
                        <div className={styles.contentMeta}>
                          {item.capability_id && (
                            <span className={styles.metaMuted}>{item.capability_id}</span>
                          )}
                          {item.outcome && (
                            <>
                              <span className={styles.metaDivider}>·</span>
                              <span className={styles.metaMuted}>
                                {item.outcome === 'success' ? '✅' : '❌'} {item.outcome}
                                {item.exit_code != null && ` (exit ${item.exit_code})`}
                                {item.duration_ms != null && ` · ${item.duration_ms}ms`}
                              </span>
                            </>
                          )}
                          <span className={styles.metaDivider}>·</span>
                          <span className={styles.metaMuted}>{item.worker_name || item.worker_id}</span>
                        </div>
                      </>
                    ) : (
                      <>
                        {/* Interactive prompt: prompt_message is the primary content */}
                        <p className={styles.contentTitle}>
                          {item.prompt_message || t('common.noDescription')}
                        </p>
                        <div className={styles.contentMeta}>
                          {item.prompt_type && (
                            <span className={styles.metaMuted}>
                              {item.prompt_type === 'choice'
                                ? t('approvals.promptChoice')
                                : item.prompt_type === 'confirm'
                                  ? t('approvals.promptConfirm')
                                  : t('approvals.promptInput')}
                            </span>
                          )}
                          <span className={styles.metaDivider}>·</span>
                          <span className={styles.metaMuted}>{item.worker_name || item.worker_id}</span>
                        </div>
                        {item.prompt_choices && item.prompt_choices.length > 0 && (
                          <div className={styles.choices}>
                            {item.prompt_choices.map((c, i) => (
                              <span key={i} className={styles.choiceChip}>{c}</span>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>

                  {/* ── Card footer: responder info (read-only) ── */}
                  <div className={styles.responderFooter}>
                    <div className={styles.responderRow}>
                      <span className={styles.detailLabel}>{t('approvals.respondedBy')}</span>
                      <span className={styles.responderName}>
                        {item.responded_by_worker_name || item.responded_by_worker_id || '—'}
                      </span>
                      {item.responded_at && (
                        <span className={styles.responseTime}>
                          {formatTimeAgo(item.responded_at)}
                        </span>
                      )}
                    </div>
                    {item.response_note && (
                      <span className={styles.responseNote}>
                        "{item.response_note}"
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── P12-B39: Detail modal ─────────────────────────────────── */}
      <AuthRequestModal
        isOpen={selectedItem !== null}
        item={selectedItem}
        onClose={() => setSelectedItem(null)}
      />
    </div>
  )
}

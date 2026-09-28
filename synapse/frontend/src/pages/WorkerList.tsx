import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, Bot, User, UserPlus, Copy, Check, Pause, Play, AlertTriangle } from 'lucide-react'
import { fetchWorkers, createWorker, suspendWorker, resumeWorker } from '../api/client'
import type { WorkerSummary } from '../api/client'
import ConfirmModal from '../components/ConfirmModal'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import EmptyState from '../components/EmptyState'
import ChipSelect, { type ChipOption } from '../components/ChipSelect'
import styles from './WorkerList.module.css'

type WorkerType = 'human' | 'agent'
type ExpiryDays = 30 | 90 | 365 | null

export default function WorkerList() {
  const navigate = useNavigate()
  const { token, teamId } = useAuth()
  const { t } = useI18n()
  const [workers, setWorkers] = useState<WorkerSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('active')

  // Create form state
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newType, setNewType] = useState<WorkerType>('agent')
  const [newProvider, setNewProvider] = useState('claude')
  const [newProviderModel, setNewProviderModel] = useState('')
  const [newExpiry, setNewExpiry] = useState<ExpiryDays>(null)
  const [newExpiryDate, setNewExpiryDate] = useState('')
  const [newContact, setNewContact] = useState('')
  const [newNotes, setNewNotes] = useState('')
  const [newBatchSize, setNewBatchSize] = useState(3)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  const copyTextareaRef = useRef<HTMLTextAreaElement>(null)

  // API key display (one-time)
  const [createdApiKey, setCreatedApiKey] = useState<string | null>(null)
  const [createdWorkerName, setCreatedWorkerName] = useState<string>('')
  const [apiKeyCopied, setApiKeyCopied] = useState(false)
  const [keyConfirmed, setKeyConfirmed] = useState(false)

  // ── Modal state ───────────────────────────────────────────
  const [modalTarget, setModalTarget] = useState<WorkerSummary | null>(null)
  const [modalAction, setModalAction] = useState<'suspend' | 'resume' | null>(null)

  // i18n labels — computed once (not reactive to lang change during form fill, acceptable)
  const typeLabels: ChipOption<WorkerType>[] = [
    { value: 'agent', label: t('workers.workerTypeAgent') },
    { value: 'human', label: t('workers.workerTypeHuman') },
  ]
  const providerLabels: ChipOption<string>[] = [
    { value: 'claude', label: t('workers.providerClaude') },
    { value: 'openai', label: t('workers.providerOpenai') },
    { value: 'custom', label: t('workers.providerCustom') },
  ]
  const expiryLabels: ChipOption<ExpiryDays>[] = [
    { value: 30, label: t('workers.expiry30d') },
    { value: 90, label: t('workers.expiry90d') },
    { value: 365, label: t('workers.expiry365d') },
    { value: null, label: t('workers.expiryPermanent') },
  ]

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    setError(null)
    fetchWorkers(teamId, token, { status: statusFilter === 'all' ? undefined : statusFilter })
      .then(data => { setWorkers(data.items); setLoading(false) })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [token, teamId, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const resetForm = () => {
    setNewName('')
    setNewType('agent')
    setNewProvider('claude')
    setNewProviderModel('')
    setNewExpiry(null)
    setNewExpiryDate('')
    setNewContact('')
    setNewNotes('')
    setNewBatchSize(3)
    setCreateError(null)
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !teamId) return
    setCreating(true)
    setCreateError(null)

    // Pack extended fields into metadata for governance batch migration
    const metaPayload: Record<string, unknown> = {
      worker_type: newType,
      role: 'builder',
    }
    if (newNotes.trim()) {
      metaPayload.notes = newNotes.trim()
    }
    if (newContact.trim()) {
      metaPayload.contact = newContact.trim()
    }
    if (newType === 'agent') {
      // Determine expiry: custom date overrides preset
      if (newExpiryDate) {
        metaPayload.key_expiry_date = newExpiryDate
      } else if (newExpiry !== null) {
        metaPayload.key_expiry_days = newExpiry
      }
      // else: permanent (null expiry, no key set)
    }

    try {
      const res = await createWorker(
        teamId,
        {
          name: newName.trim(),
          provider: newType === 'agent' ? newProvider : 'claude',
          provider_model: newType === 'agent' && newProviderModel.trim()
            ? newProviderModel.trim()
            : null,
          metadata: metaPayload,
          batch_size: newBatchSize,
        },
        token,
      )
      setCreatedApiKey(res.api_key)
      setCreatedWorkerName(newName.trim())
      setApiKeyCopied(false)
      resetForm()
      setShowCreate(false)
      load()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  const handleCopyKey = async () => {
    if (!createdApiKey) return
    try {
      await navigator.clipboard.writeText(createdApiKey)
      setApiKeyCopied(true)
      setKeyConfirmed(true)
      setTimeout(() => setApiKeyCopied(false), 3000)
    } catch {
      // Fallback: use React-managed hidden textarea (no document.createElement)
      const ta = copyTextareaRef.current
      if (!ta) return
      ta.value = createdApiKey
      ta.select()
      document.execCommand('copy')
      setApiKeyCopied(true)
      setTimeout(() => setApiKeyCopied(false), 3000)
    }
  }

  const handleDismissKey = () => {
    setCreatedApiKey(null)
    setCreatedWorkerName('')
    setKeyConfirmed(false)
  }

  const openSuspendModal = (e: React.MouseEvent, w: WorkerSummary) => {
    e.stopPropagation()
    setModalTarget(w)
    setModalAction(w.is_disabled ? 'resume' : 'suspend')
  }

  const executeAction = async () => {
    if (!token || !modalTarget) return
    try {
      if (modalAction === 'resume') {
        await resumeWorker(modalTarget.id, token)
      } else {
        await suspendWorker(modalTarget.id, token)
      }
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setModalTarget(null)
      setModalAction(null)
    }
  }

  const modalConfig = (() => {
    if (!modalTarget || !modalAction) return null
    const isSuspend = modalAction === 'suspend'
    return {
      title: isSuspend ? t('workers.suspend') : t('workers.resume'),
      message: isSuspend ? t('workers.suspendConfirm') : t('workers.resumeConfirm'),
      confirmLabel: isSuspend ? t('workers.suspend') : t('workers.resume'),
      confirmVariant: 'warning' as const,
      onConfirm: executeAction,
      onCancel: () => { setModalTarget(null); setModalAction(null) },
    }
  })()

  if (error) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={error} />
    )
  }

  const isAiWorker = newType === 'agent'

  return (
    <div>
      {/* Hidden textarea for clipboard copy fallback — managed by React */}
      <textarea ref={copyTextareaRef} style={{ position: 'fixed', opacity: 0 }} readOnly aria-hidden="true" />
      {/* ── Register Worker ──────────────────────────────────── */}
      <div className={styles.createForm}>
        <div className={styles.formTitle}>
          {!showCreate ? (
            <button
              type="button"
              className={styles.submitBtn}
              onClick={() => { setShowCreate(true); setCreateError(null) }}
            >
              <UserPlus size={14} style={{ marginRight: 6 }} />
              {t('workers.registerWorker')}
            </button>
          ) : (
            <span>{t('workers.registerWorker')}</span>
          )}
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            {/* Name + Type inline */}
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="worker-create-name">{t('workers.name')} *</label>
                <div className={styles.nameRow}>
                  <input
                    id="worker-create-name"
                    type="text"
                    value={newName}
                    onChange={e => setNewName(e.target.value)}
                    placeholder={t('workers.namePlaceholder')}
                    className={styles.nameInput}
                    required
                    autoFocus
                  />
                  <ChipSelect
                    options={typeLabels}
                    value={newType}
                    onChange={setNewType}
                    name="workerType"
                  />
                </div>
              </div>
            </div>

            {/* ── Agent-only fields ── */}
            {isAiWorker && (
              <div className={styles.agentSection}>
                {/* Provider — chip select */}
                <div className={styles.formRow}>
                  <div className={styles.formField}>
                    <label id="worker-create-provider-label">{t('workers.provider')}</label>
                    <ChipSelect
                      options={providerLabels}
                      value={newProvider}
                      onChange={setNewProvider}
                      name="provider"
                      labelledBy="worker-create-provider-label"
                    />
                  </div>
                </div>

                {/* Model */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="worker-create-provider-model">{t('workers.providerModel')}</label>
                    <input
                      id="worker-create-provider-model"
                      type="text"
                      value={newProviderModel}
                      onChange={e => setNewProviderModel(e.target.value)}
                      placeholder={t('workers.providerModelPlaceholder')}
                      className={styles.modelInput}
                    />
                  </div>
                </div>

                {/* Batch Size */}
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="worker-create-batch-size">{t('workers.batchSize')}</label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <input
                        id="worker-create-batch-size"
                        type="number"
                        value={newBatchSize}
                        onChange={e => setNewBatchSize(Math.max(1, Math.min(20, Number(e.target.value))))}
                        min={1}
                        max={20}
                        style={{ width: '72px' }}
                      />
                      <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
                        {t('workers.batchSizeHint')}
                      </span>
                    </div>
                  </div>
                </div>

              </div>
            )}

            {/* Contact */}
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="worker-create-contact">{t('workers.contact')}</label>
                <input
                  id="worker-create-contact"
                  type="text"
                  value={newContact}
                  onChange={e => setNewContact(e.target.value)}
                  placeholder={t('workers.contactPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
            </div>

            {/* Notes */}
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="worker-create-notes">{t('workers.notes')}</label>
                <textarea
                  id="worker-create-notes"
                  value={newNotes}
                  onChange={e => setNewNotes(e.target.value)}
                  placeholder={t('workers.notesPlaceholder')}
                  style={{ width: '100%', minHeight: '80px', resize: 'vertical' }}
                />
              </div>
            </div>

            {/* Key Expiry — Worker account level, NOT model config */}
            {isAiWorker && (
              <div className={styles.formRow}>
                <div className={styles.formField} style={{ flex: 1 }}>
                  <label id="worker-create-key-expiry-label">{t('workers.keyExpiry')}</label>
                  <div className={styles.expiryRow}>
                    <ChipSelect
                      options={expiryLabels}
                      value={newExpiry}
                      onChange={(v) => { setNewExpiry(v); setNewExpiryDate('') }}
                      name="expiry"
                      labelledBy="worker-create-key-expiry-label"
                    />
                    <span className={styles.expiryOr}>{t('common.or')}</span>
                    <input
                      type="date"
                      value={newExpiryDate}
                      onChange={e => {
                        setNewExpiryDate(e.target.value)
                        if (e.target.value) setNewExpiry(null)
                      }}
                      className={styles.dateInput}
                      title={t('workers.expiryCustomDate')}
                    />
                  </div>
                </div>
              </div>
            )}

            {createError && <p className={styles.error}>{createError}</p>}

            {/* Actions */}
            <div className={styles.formRow}>
              <button
                type="submit"
                className={styles.submitBtn}
                disabled={creating || !newName.trim()}
              >
                {creating ? t('workers.registering') : t('workers.registerWorker')}
              </button>
              <button
                type="button"
                className={styles.cancelBtn}
                onClick={() => { setShowCreate(false); resetForm() }}
              >
                {t('common.cancel')}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* ── API Key display (one-time) ───────────────────────── */}
      {createdApiKey && (
        <div className={styles.apiKeyBox}>
          <div className={styles.apiKeyHeader}>
            <span>{t('workers.apiKeyTitle')}</span>
            <span className={styles.apiKeyAgentName}>{createdWorkerName}</span>
          </div>
          <div className={styles.apiKeyValue}>
            <code>{createdApiKey}</code>
            <button
              type="button"
              className={styles.copyBtn}
              onClick={handleCopyKey}
            >
              {apiKeyCopied ? (
                <><Check size={14} /> {t('workers.apiKeyCopied')}</>
              ) : (
                <><Copy size={14} /> {t('workers.copyKey')}</>
              )}
            </button>
          </div>
          <p className={styles.apiKeyWarning}>
            <AlertTriangle size={14} style={{ marginRight: 6, flexShrink: 0 }} />
            {t('workers.apiKeyWarning')}
          </p>
          <label className={styles.apiKeyConfirm}>
            <input
              type="checkbox"
              checked={keyConfirmed}
              onChange={(e) => setKeyConfirmed(e.target.checked)}
            />
            {t('workers.apiKeyConfirmSaved')}
          </label>
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={handleDismissKey}
            disabled={!keyConfirmed}
            style={{ marginTop: 8 }}
          >
            {t('common.close')}
          </button>
        </div>
      )}

      {/* ── Status filter tabs ──────────────────────────────── */}
      <div className={styles.filterTabs}>
        {([
          ['active', t('workers.statusActive')],
          ['suspended', t('workers.statusSuspended')],
          ['all', t('workers.statusAll')],
        ] as const).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`${styles.filterTab} ${statusFilter === key ? styles.filterTabActive : ''}`}
            onClick={() => setStatusFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Loading ─────────────────────────────────────────── */}
      {loading && <p className={styles.loading}>{t('workers.loading')}</p>}

      {/* ── Empty ───────────────────────────────────────────── */}
      {!loading && workers.length === 0 && !createdApiKey && (
        <EmptyState icon={Bot} title={t('workers.noAgents')} description={t('workers.noAgentsDesc')} />
      )}

      {/* ── Grid ────────────────────────────────────────────── */}
      {workers.length > 0 && (
        <div className={styles.grid}>
          {workers.map(w => {
            return (
              <div key={w.id} className={styles.card} onClick={() => navigate(`/workers/${w.id}`)} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/workers/${w.id}`) }}>
                <div className={styles.cardHeader}>
                  <span className={styles.agentIcon}>{w.metadata?.worker_type === 'human' ? <User size={20} strokeWidth={1.5} /> : <Bot size={20} strokeWidth={1.5} />}</span>
                  <div className={styles.cardTitle}>
                    <h3>{w.name}</h3>
                    <span className={styles.agentId}>{w.id.slice(0, 16)}&hellip;</span>
                  </div>
                  <span className={`${styles.badge} ${styles[`badge${w.status.charAt(0).toUpperCase() + w.status.slice(1)}`] || styles.badgeInactive}`}>
                    {w.status}
                  </span>
                </div>
                <div className={styles.cardBody}>
                  {w.metadata?.worker_type !== 'human' && (
                    <div className={styles.meta}>
                      <span className={styles.metaLabel}>{t('workers.provider')}</span>
                      <span className={styles.metaValue}>
                        {w.provider}{w.provider_model ? ` / ${w.provider_model}` : ''}
                      </span>
                    </div>
                  )}
                  <div className={styles.metaRow}>
                    {!!w.metadata?.worker_type && (
                      <span className={`${styles.chip} ${styles.chipType}`}>
                        {w.metadata!.worker_type === 'human' ? t('workers.workerTypeHuman') : t('workers.workerTypeAgent')}
                      </span>
                    )}
                    {!!w.metadata?.role && (
                      <span className={`${styles.chip} ${styles.chipRole}`}>
                        {(() => {
                          const roleMap: Record<string, string> = {
                            orchestrator: t('workers.roleOrchestrator'),
                            builder: t('workers.roleBuilder'),
                            steward: t('workers.roleSteward'),
                            guardian: t('workers.roleSteward'),
                          }
                          return roleMap[w.metadata!.role as string] || String(w.metadata!.role)
                        })()}
                      </span>
                    )}
                  </div>
                  {/* ── Workload indicator (P9-B73a) ──────────────── */}
                  <div className={styles.workload}>
                    <span className={`${styles.workloadBar} ${w.active_task_count >= w.batch_size ? styles.workloadBarFull : ''}`}>
                      {w.active_task_count > 0
                        ? `${w.active_task_count} ${t('workers.activeTasks')}`
                        : t('workers.idle')}
                    </span>
                    {w.active_batches > 0 && (
                      <span className={styles.workloadBatches}>
                        {`${w.active_batches} ${t('workers.batches')}`}
                      </span>
                    )}
                    {w.completed_task_count > 0 && (
                      <span className={styles.workloadDone}>
                        {`${w.completed_task_count} ${t('workers.completedTasks')}`}
                      </span>
                    )}
                  </div>
                </div>
                <div className={styles.cardActions}>
                  <button
                    type="button"
                    className={`${styles.actionBtn} ${w.is_disabled ? styles.actionBtnResume : styles.actionBtnSuspend}`}
                    onClick={(e) => openSuspendModal(e, w)}
                    title={w.is_disabled ? t('workers.resume') : t('workers.suspend')}
                  >
                    {w.is_disabled ? <Play size={12} /> : <Pause size={12} />}
                    <span>{w.is_disabled ? t('workers.resume') : t('workers.suspend')}</span>
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── Confirm Modal ──────────────────────────────────────── */}
      {modalConfig && (
        <ConfirmModal
          isOpen
          title={modalConfig.title}
          message={modalConfig.message}
          confirmLabel={modalConfig.confirmLabel}
          confirmVariant={modalConfig.confirmVariant}
          onConfirm={modalConfig.onConfirm}
          onCancel={modalConfig.onCancel}
        />
      )}
    </div>
  )
}

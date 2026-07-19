import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams, Link, useNavigate } from 'react-router-dom'
import { Lock, Package, ChevronUp, ChevronDown, ArrowLeft } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { BatchSummary } from '../api/client'
import { fetchBatches, createBatch, fetchProject } from '../api/client'
import { formatDate } from '../utils/format'
import { STATUS_ICONS, STATUS_COLORS } from '../utils/constants'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import ProjectSelect from '../components/ProjectSelect'
import styles from './Batches.module.css'

export default function Batches() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const highlightBatchId = searchParams.get('batch')
  const [batches, setBatches] = useState<BatchSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [projectId, setProjectId] = useState(
    () => localStorage.getItem('synapse_project_id') || '',
  )
  const [projectPhaseMode, setProjectPhaseMode] = useState(false)
  const [projectCurrentPhase, setProjectCurrentPhase] = useState<string | null>(null)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newOrder, setNewOrder] = useState('')
  const [newPhase, setNewPhase] = useState('')
  const [newBatchNumber, setNewBatchNumber] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Expanded card — auto-expand batch from ?batch= query param
  const [expandedId, setExpandedId] = useState<string | null>(highlightBatchId)

  // Status filter
  const [filterStatus, setFilterStatus] = useState('')

  const STATUS_FILTERS = [
    { value: '', label: t('common.all') },
    { value: 'open', label: t('batches.statusOpen') },
    { value: 'completed', label: t('batches.completed') },
  ]

  const { token, teamId } = useAuth()

  const load = useCallback(() => {
    if (!token || !projectId) return
    setLoading(true)
    fetchBatches(projectId, token)
      .then(res => {
        setBatches(res.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [projectId, token])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!token || !projectId) {
      setProjectPhaseMode(false)
      setProjectCurrentPhase(null)
      return
    }
    fetchProject(projectId, token)
      .then(p => {
        setProjectPhaseMode(p.use_phase_mode)
        setProjectCurrentPhase(p.current_phase)
      })
      .catch(() => {
        setProjectPhaseMode(false)
        setProjectCurrentPhase(null)
      })
  }, [projectId, token])

  const filteredBatches = useMemo(() => {
    if (!filterStatus) return batches
    return batches.filter(b => b.status === filterStatus)
  }, [batches, filterStatus])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !projectId) return
    setCreating(true)
    setCreateError(null)
    try {
      await createBatch(
        projectId,
        {
          name: newName.trim(),
          description: newDescription.trim() || undefined,
          order: newOrder.trim() ? parseInt(newOrder.trim(), 10) : undefined,
          phase: newPhase.trim() || undefined,
          batch_number: newBatchNumber.trim() ? parseInt(newBatchNumber.trim(), 10) : undefined,
        },
        token,
      )
      setNewName('')
      setNewDescription('')
      setNewOrder('')
      setNewPhase('')
      setNewBatchNumber('')
      setShowCreate(false)
      load()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <Link to="/tasks" className={styles.backLink}>
        <ArrowLeft size={14} /> {t('batches.backToTasks')}
      </Link>
      <PageHeader title={t('batches.heading')}>
        <ProjectSelect value={projectId} onChange={setProjectId} />
      </PageHeader>

      {!projectId ? (
        <EmptyState icon={Package} title={t('batches.enterProjectId')} description={t('batches.enterProjectIdDesc')} />
      ) : (
        <>
          {/* Create form */}
          <div className={styles.createForm}>
            <div className={styles.formTitle}>
              {showCreate ? t('batches.createBatch') : (
                <button
                  type="button"
                  className={styles.submitBtn}
                  onClick={() => {
                    setShowCreate(true)
                    setCreateError(null)
                    if (projectPhaseMode && projectCurrentPhase) {
                      setNewPhase(projectCurrentPhase)
                      setNewBatchNumber('')
                    }
                  }}
                >
                  + {t('batches.createBatch')}
                </button>
              )}
            </div>
            {showCreate && (
              <form onSubmit={handleCreate}>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 2 }}>
                    <label htmlFor="batch-create-name">{t('batches.name')}</label>
                    <input
                      type="text"
                      id="batch-create-name"
                      value={newName}
                      onChange={e => setNewName(e.target.value)}
                      placeholder={t('batches.namePlaceholder')}
                      style={{ width: '100%' }}
                      required
                    />
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="batch-create-order">{t('batches.order')}</label>
                    <input
                      type="number"
                      id="batch-create-order"
                      value={newOrder}
                      onChange={e => setNewOrder(e.target.value)}
                      placeholder={t('batches.orderPlaceholder')}
                      style={{ width: '80px' }}
                    />
                  </div>
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formField}>
                    <label htmlFor="batch-create-phase">{t('batches.phase')}</label>
                    <input
                      type="text"
                      id="batch-create-phase"
                      value={newPhase}
                      onChange={e => setNewPhase(e.target.value)}
                      placeholder={projectPhaseMode && projectCurrentPhase ? projectCurrentPhase : t('batches.phasePlaceholder')}
                      style={{ width: '100px' }}
                    />
                    {projectPhaseMode && (
                      <span className={styles.phaseHint}>{t('batches.phaseAutoHint')}</span>
                    )}
                  </div>
                  <div className={styles.formField}>
                    <label htmlFor="batch-create-batchNumber">{t('batches.batchNumber')}</label>
                    <input
                      type="number"
                      id="batch-create-batchNumber"
                      value={newBatchNumber}
                      onChange={e => setNewBatchNumber(e.target.value)}
                      placeholder={t('batches.batchNumberPlaceholder')}
                      style={{ width: '80px' }}
                    />
                  </div>
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="batch-create-description">{t('batches.description')}</label>
                    <textarea
                      id="batch-create-description"
                      value={newDescription}
                      onChange={e => setNewDescription(e.target.value)}
                      placeholder={t('batches.descPlaceholder')}
                      style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                    />
                  </div>
                </div>
                {createError && <p className={styles.error}>{createError}</p>}
                <div className={styles.formRow}>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={creating || !newName.trim()}
                  >
                    {creating ? t('batches.creating') : t('common.create')}
                  </button>
                  <button
                    type="button"
                    className={styles.filterChip}
                    onClick={() => { setShowCreate(false); setCreateError(null) }}
                  >
                    {t('common.cancel')}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Status filter */}
          <div className={styles.filterBar}>
            <span>{t('common.filter')}</span>
            {STATUS_FILTERS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                className={`${styles.filterChip} ${filterStatus === value ? styles.filterChipActive : ''}`}
                onClick={() => setFilterStatus(value)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Error */}
          {error && <p className={styles.error}>{error}</p>}

          {/* Loading */}
          {loading && <p className={styles.loading}>{t('batches.loading')}</p>}

          {/* Empty */}
          {!loading && !error && filteredBatches.length === 0 && (
            <EmptyState icon={Package} title={t('batches.noBatches')} description={t('batches.noBatchesDesc')} />
          )}

          {/* List */}
          {filteredBatches.length > 0 && (
            <div className={styles.list}>
              {filteredBatches.map(b => {
                const isExpanded = expandedId === b.id
                const StatusIcon = STATUS_ICONS[b.status]
                return (
                  <div key={b.id} className={styles.card}>
                    <div
                      className={styles.cardHeader}
                      onClick={() => navigate(`/batches/${b.id}`)}
                      style={{ cursor: 'pointer' }}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/batches/${b.id}`) }}
                    >
                      <span className={styles.cardIcon}>
                        {StatusIcon && <StatusIcon size={14} strokeWidth={2} color={STATUS_COLORS[b.status]} />}
                      </span>
                      <div className={styles.cardTitle}>
                        <div className={styles.cardTitleRow}>
                          <span className={styles.batchName}>{b.name}</span>
                          {b.phase && b.batch_number != null ? (
                            <span className={styles.combinedPhaseBadge}>{b.phase}-B{b.batch_number}</span>
                          ) : (
                            <>
                              {b.order != null && (
                                <span className={styles.orderBadge}>#{b.order}</span>
                              )}
                              {b.phase && (
                                <span className={styles.phaseBadge}>{b.phase}</span>
                              )}
                              {b.batch_number != null && !b.phase && (
                                <span className={styles.orderBadge}>#{b.batch_number}</span>
                              )}
                            </>
                          )}
                          <span
                            className={`${styles.statusBadge} ${
                              styles[`status${b.status.charAt(0).toUpperCase() + b.status.slice(1)}`] || styles.statusOpen
                            }`}
                          >
                            {b.status}
                          </span>
                        </div>
                      </div>
                      <button
                        type="button"
                        className={styles.expandBtn}
                        onClick={(e) => { e.stopPropagation(); setExpandedId(isExpanded ? null : b.id) }}
                      >
                        {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                      </button>
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <div className={styles.detail}>
                        {b.description && (
                          <>
                            <div className={styles.detailHeader}>{t('batches.description')}</div>
                            <p className={styles.detailText}>{b.description}</p>
                          </>
                        )}
                        <div className={styles.detailGrid}>
                          <div>
                            <div className={styles.detailHeader}>{t('batches.status')}</div>
                            <code className={styles.detailCode}>{b.status}</code>
                          </div>
                          {b.phase && b.batch_number != null ? (
                            <div>
                              <div className={styles.detailHeader}>{t('batches.phase')}</div>
                              <code className={styles.detailCode}>{b.phase}-B{b.batch_number}</code>
                            </div>
                          ) : (
                            <>
                              {b.phase && (
                                <div>
                                  <div className={styles.detailHeader}>{t('batches.phase')}</div>
                                  <code className={styles.detailCode}>{b.phase}</code>
                                </div>
                              )}
                              {b.batch_number != null && (
                                <div>
                                  <div className={styles.detailHeader}>{t('batches.batchNumber')}</div>
                                  <code className={styles.detailCode}>#{b.batch_number}</code>
                                </div>
                              )}
                            </>
                          )}
                          <div>
                            <div className={styles.detailHeader}>{t('batches.order')}</div>
                            <code className={styles.detailCode}>
                              {b.order != null ? `#${b.order}` : t('common.none')}
                            </code>
                          </div>
                          {b.completed_at && (
                            <div>
                              <div className={styles.detailHeader}>{t('batches.completed')}</div>
                              <code className={styles.detailCode}>
                                {formatDate(b.completed_at, lang)}
                              </code>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    <div className={styles.cardFooter}>
                      <span className={styles.actorInfo}>
                        {b.name}
                      </span>
                      <span>{formatDate(b.updated_at, lang)}</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}

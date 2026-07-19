import { useState, useEffect, useCallback } from 'react'
import { Lock, BarChart3, FileText, ChevronUp, ChevronDown } from 'lucide-react'
import { fetchAnalyses, createAnalysis } from '../api/client'
import type { AnalysisSummary } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate, truncate } from '../utils/format'
import { TYPE_ICONS } from '../utils/constants'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import ProjectSelect from '../components/ProjectSelect'
import styles from './Analyses.module.css'

export default function Analyses() {
  const { t, lang } = useI18n()

  const ANALYSIS_TYPE_LABELS: Record<string, string> = {
    requirement: t('analyses.analysisTypes.requirement'),
    discussion: t('analyses.analysisTypes.discussion'),
    design: t('analyses.analysisTypes.design'),
  }

  const ANALYSIS_TYPES = [
    { value: '', label: t('common.all') },
    { value: 'requirement', label: t('analyses.analysisTypes.requirement') },
    { value: 'discussion', label: t('analyses.analysisTypes.discussion') },
    { value: 'design', label: t('analyses.analysisTypes.design') },
  ]

  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [projectId, setProjectId] = useState(
    () => localStorage.getItem('synapse_project_id') || '',
  )
  const [filterType, setFilterType] = useState('')

  // Create form
  const [showForm, setShowForm] = useState(false)
  const [formType, setFormType] = useState('design')
  const [formTitle, setFormTitle] = useState('')
  const [formContent, setFormContent] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const { token, teamId } = useAuth()

  const load = useCallback(() => {
    if (!token || !projectId) return
    setLoading(true)
    const params: { analysis_type?: string } = {}
    if (filterType) params.analysis_type = filterType
    fetchAnalyses(projectId, token, params)
      .then(res => {
        setAnalyses(res.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [projectId, token, filterType])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !projectId || !formTitle.trim() || !formContent.trim()) return
    setSubmitting(true)
    setFormError(null)
    try {
      await createAnalysis(
        projectId,
        {
          analysis_type: formType,
          title: formTitle.trim(),
          content: formContent.trim(),
        },
        token,
      )
      setFormTitle('')
      setFormContent('')
      setShowForm(false)
      load()
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create analysis')
    } finally {
      setSubmitting(false)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('analyses.heading')}>
        <ProjectSelect value={projectId} onChange={setProjectId} />
      </PageHeader>

      {!projectId ? (
        <EmptyState icon={BarChart3} title={t('analyses.selectProject')} description={t('analyses.selectProjectDesc')} />
      ) : (
        <>
          {/* Create form */}
          <div className={styles.createForm}>
            <div className={styles.formTitle}>
              {showForm ? t('analyses.newAnalysis') : (
                <button
                  type="button"
                  className={styles.submitBtn}
                  onClick={() => setShowForm(true)}
                >
                  + {t('analyses.newAnalysis')}
                </button>
              )}
            </div>
            {showForm && (
              <form onSubmit={handleCreate}>
                <div className={styles.formRow}>
                  <div className={styles.formField}>
                    <label htmlFor="analysis-create-type">{t('common.type')}</label>
                    <select id="analysis-create-type" value={formType} onChange={e => setFormType(e.target.value)}>
                      {ANALYSIS_TYPES.filter(at => at.value).map(at => (
                        <option key={at.value} value={at.value}>{at.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="analysis-create-title">{t('tasks.title')}</label>
                    <input
                      type="text"
                      id="analysis-create-title"
                      value={formTitle}
                      onChange={e => setFormTitle(e.target.value)}
                      placeholder={t('analyses.titlePlaceholder')}
                      maxLength={500}
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="analysis-create-content">{t('analyses.content')}</label>
                    <textarea
                      id="analysis-create-content"
                      value={formContent}
                      onChange={e => setFormContent(e.target.value)}
                      placeholder={t('analyses.contentPlaceholder')}
                    />
                  </div>
                </div>
                {formError && <p className={styles.error}>{formError}</p>}
                <div className={styles.formRow}>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={submitting || !formTitle.trim() || !formContent.trim()}
                  >
                    {submitting ? t('analyses.creating') : t('analyses.createAnalysis')}
                  </button>
                  <button
                    type="button"
                    className={styles.filterChip}
                    onClick={() => {
                      setShowForm(false)
                      setFormError(null)
                    }}
                  >
                    {t('common.cancel')}
                  </button>
                </div>
              </form>
            )}
          </div>

          {/* Type filter */}
          <div className={styles.filterBar}>
            <span>{t('common.filter')}</span>
            {ANALYSIS_TYPES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                className={`${styles.filterChip} ${filterType === value ? styles.filterChipActive : ''}`}
                onClick={() => setFilterType(value)}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Error */}
          {error && <p className={styles.error}>{error}</p>}

          {/* Loading */}
          {loading && <p className={styles.loading}>{t('analyses.loading')}</p>}

          {/* Empty */}
          {!loading && !error && analyses.length === 0 && (
            <EmptyState icon={FileText} title={t('analyses.noAnalyses')} description={t('analyses.noAnalysesDesc')} />
          )}

          {/* List */}
          {analyses.length > 0 && (
            <div className={styles.list}>
              {analyses.map(a => {
                const TypeIcon = TYPE_ICONS[a.analysis_type]
                const isExpanded = expandedId === a.id
                const needsExpand = a.content.length > 200
                return (
                  <div key={a.id} className={styles.card}>
                    <div className={styles.cardHeader}>
                      <span className={styles.cardIcon}>
                        {TypeIcon && <TypeIcon size={16} strokeWidth={2} />}
                      </span>
                      <div className={styles.cardTitle}>
                        <h3>{a.title}</h3>
                        <div className={styles.cardMeta}>
                          <span className={styles.typeBadge}>{ANALYSIS_TYPE_LABELS[a.analysis_type] || a.analysis_type}</span>
                          <span className={styles.actorBadge}>
                            {a.actor_type}: {a.actor_id.slice(0, 12)}…
                          </span>
                        </div>
                      </div>
                      {needsExpand && (
                        <button
                          type="button"
                          className={styles.expandBtn}
                          onClick={() => setExpandedId(isExpanded ? null : a.id)}
                        >
                          {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                        </button>
                      )}
                    </div>
                    <div className={styles.cardBody}>
                      {isExpanded ? a.content : truncate(a.content, 200)}
                    </div>
                    <div className={styles.cardFooter}>
                      <span className={styles.actorInfo}>
                        {a.id.slice(0, 16)}…
                      </span>
                      <span>{formatDate(a.created_at, lang)}</span>
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

import { useState, useEffect, useCallback } from 'react'
import { Lock, Search, ChevronUp, ChevronDown } from 'lucide-react'
import { fetchScans, executeScan } from '../api/client'
import type { ScanDetail } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate, truncate } from '../utils/format'
import { STATUS_ICONS, STATUS_COLORS, TARGET_ICONS } from '../utils/constants'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import styles from './Scans.module.css'

export default function Scans() {
  const { t, lang } = useI18n()

  const TARGET_TYPE_LABELS: Record<string, string> = {
    task: t('scans.task'),
    batch: t('scans.batch'),
  }

  const TARGET_TYPES = [
    { value: '', label: t('common.all') },
    { value: 'task', label: t('scans.task') },
    { value: 'batch', label: t('scans.batch') },
  ]

  const [scans, setScans] = useState<ScanDetail[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [filterType, setFilterType] = useState('')

  // Trigger scan form
  const [showForm, setShowForm] = useState(false)
  const [scanTargetType, setScanTargetType] = useState('task')
  const [scanTargetId, setScanTargetId] = useState('')
  const [scanning, setScanning] = useState(false)
  const [scanError, setScanError] = useState<string | null>(null)
  const [scanSuccess, setScanSuccess] = useState<string | null>(null)

  // Expanded card for rules detail
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { token, teamId } = useAuth()

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    const params: { target_type?: string } = {}
    if (filterType) params.target_type = filterType
    fetchScans(teamId, token, params)
      .then(res => {
        setScans(res.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [teamId, token, filterType])

  useEffect(() => {
    load()
  }, [load])

  const handleScan = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !scanTargetId.trim()) return
    setScanning(true)
    setScanError(null)
    setScanSuccess(null)
    try {
      const result = await executeScan(scanTargetType, scanTargetId.trim(), token)
      setScanTargetId('')
      setShowForm(false)
      setScanSuccess(t('scans.scanSuccessDetail', {
        pass: result.summary.pass,
        fail: result.summary.fail,
        warn: result.summary.warn,
      }))
      load()
    } catch (err: unknown) {
      setScanError(err instanceof Error ? err.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('scans.heading')} />

      {/* Trigger scan form */}
      <div className={styles.createForm}>
        <div className={styles.formTitle}>
          {showForm ? t('scans.triggerScan') : (
            <button
              type="button"
              className={styles.submitBtn}
              onClick={() => { setShowForm(true); setScanError(null); setScanSuccess(null) }}
            >
              + {t('scans.triggerScan')}
            </button>
          )}
        </div>
        {showForm && (
          <form onSubmit={handleScan}>
            <div className={styles.formRow}>
              <div className={styles.formField}>
                <label htmlFor="scan-trigger-targetType">{t('scans.targetType')}</label>
                <select id="scan-trigger-targetType" value={scanTargetType} onChange={e => setScanTargetType(e.target.value)}>
                  {TARGET_TYPES.filter(tt => tt.value).map(tt => (
                    <option key={tt.value} value={tt.value}>{tt.label}</option>
                  ))}
                </select>
              </div>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="scan-trigger-targetId">{t('scans.targetId')}</label>
                <input
                  type="text"
                  id="scan-trigger-targetId"
                  value={scanTargetId}
                  onChange={e => setScanTargetId(e.target.value)}
                  placeholder={t('scans.targetIdPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
            {scanError && <p className={styles.error}>{scanError}</p>}
            <div className={styles.formRow}>
              <button
                type="submit"
                className={styles.submitBtn}
                disabled={scanning || !scanTargetId.trim()}
              >
                {scanning ? t('scans.scanning') : t('scans.runScan')}
              </button>
              <button
                type="button"
                className={styles.filterChip}
                onClick={() => { setShowForm(false); setScanError(null) }}
              >
                {t('common.cancel')}
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Success banner */}
      {scanSuccess && (
        <div className={styles.successBanner}>{scanSuccess}</div>
      )}

      {/* Target type filter */}
      <div className={styles.filterBar}>
        <span>{t('common.filter')}</span>
        {TARGET_TYPES.map(({ value, label }) => (
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
      {loading && <p className={styles.loading}>{t('scans.loading')}</p>}

      {/* Empty */}
      {!loading && !error && scans.length === 0 && (
        <EmptyState icon={Search} title={t('scans.noScans')} description={t('scans.noScansDesc')} />
      )}

      {/* List */}
      {scans.length > 0 && (
        <div className={styles.list}>
          {scans.map(s => {
            const isExpanded = expandedId === s.id
            const TargetIcon = TARGET_ICONS[s.target_type]
            return (
              <div key={s.id} className={styles.card}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardIcon}>
                    {TargetIcon && <TargetIcon size={16} strokeWidth={2} />}
                  </span>
                  <div className={styles.cardTitle}>
                    <div className={styles.cardTitleRow}>
                      <span className={styles.typeBadge}>{TARGET_TYPE_LABELS[s.target_type] || s.target_type}</span>
                      <span className={styles.targetId}>{truncate(s.target_id, 24)}</span>
                    </div>
                    <div className={styles.cardMeta}>
                      <span className={styles.actorBadge}>
                        {s.actor_type}: {truncate(s.actor_id, 16)}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className={styles.expandBtn}
                    onClick={() => setExpandedId(isExpanded ? null : s.id)}
                  >
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                </div>

                {/* Summary bar */}
                <div className={styles.summaryBar}>
                  <span className={styles.summaryItem} title="Pass">
                    <span className={styles.summaryDotPass} /> {s.summary.pass} {t('scans.pass')}
                  </span>
                  <span className={styles.summaryItem} title="Fail">
                    <span className={styles.summaryDotFail} /> {s.summary.fail} {t('scans.fail')}
                  </span>
                  <span className={styles.summaryItem} title="Warn">
                    <span className={styles.summaryDotWarn} /> {s.summary.warn} {t('scans.warn')}
                  </span>
                </div>

                {/* Expanded rules detail */}
                {isExpanded && (
                  <div className={styles.rulesList}>
                    <div className={styles.rulesHeader}>{t('scans.rulesChecked')}</div>
                    {s.rules_checked.length === 0 ? (
                      <p className={styles.noRules}>{t('scans.noRules')}</p>
                    ) : (
                      s.rules_checked.map(r => {
                        const RuleStatusIcon = STATUS_ICONS[r.status]
                        return (
                          <div key={r.rule_id} className={`${styles.ruleItem} ${styles[`rule${r.status.charAt(0).toUpperCase() + r.status.slice(1)}`]}`}>
                            <span className={styles.ruleStatus}>
                              {RuleStatusIcon && <RuleStatusIcon size={14} strokeWidth={2} color={STATUS_COLORS[r.status]} />}
                            </span>
                            <div className={styles.ruleBody}>
                              <div className={styles.ruleId}>{r.rule_id}</div>
                              <div className={styles.ruleDetail}>{r.detail}</div>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                )}

                <div className={styles.cardFooter}>
                  <span className={styles.actorInfo}>
                    {TARGET_TYPE_LABELS[s.target_type] || s.target_type}
                  </span>
                  <span>{formatDate(s.created_at, lang)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

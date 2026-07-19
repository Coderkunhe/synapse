import { useState, useEffect, useCallback } from 'react'
import { Lock, Wrench, ChevronUp, ChevronDown } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { SkillSummary } from '../api/client'
import {
  fetchSkills,
  createSkill,
  updateSkill,
} from '../api/client'
import { formatDate } from '../utils/format'
import { STATUS_ICONS, STATUS_COLORS } from '../utils/constants'
import EmptyState from '../components/EmptyState'
import ConfirmModal from '../components/ConfirmModal'
import PageHeader from '../components/PageHeader'
import styles from './Skills.module.css'

/** Parse a JSON metadata string, returning null on invalid input (non-empty, non-parseable). */
function parseMetadata(raw: string): Record<string, unknown> | null {
  const trimmed = raw.trim()
  if (!trimmed) return undefined as unknown as null
  try {
    const v = JSON.parse(trimmed)
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return null
    return v
  } catch {
    return null
  }
}

export default function Skills() {
  const { t, lang } = useI18n()

  const STATUS_FILTERS = [
    { value: '', label: t('common.all') },
    { value: 'active', label: t('skills.statusActive') },
    { value: 'deprecated', label: t('skills.statusDeprecated') },
  ]

  const [skills, setSkills] = useState<SkillSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [filterStatus, setFilterStatus] = useState('')

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newVersion, setNewVersion] = useState('1.0.0')
  const [newTemplate, setNewTemplate] = useState('')
  const [newMetadata, setNewMetadata] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Expanded card for detail
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Edit mode
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editVersion, setEditVersion] = useState('')
  const [editTemplate, setEditTemplate] = useState('')
  const [editMetadata, setEditMetadata] = useState('')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  // Deprecate confirmation
  const [deprecateTarget, setDeprecateTarget] = useState<string | null>(null)

  const { token, teamId } = useAuth()

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    const params: { status?: string } = {}
    if (filterStatus) params.status = filterStatus
    fetchSkills(teamId, token, params)
      .then(res => {
        setSkills(res.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [teamId, token, filterStatus])

  useEffect(() => {
    load()
  }, [load])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !teamId) return
    setCreating(true)
    setCreateError(null)
    try {
      const metadata = parseMetadata(newMetadata)
      if (metadata === null) { setCreateError('Invalid JSON in metadata'); setCreating(false); return }
      await createSkill(teamId, {
        name: newName.trim(),
        version: newVersion.trim() || '1.0.0',
        template_md: newTemplate.trim(),
        metadata: metadata || undefined,
      }, token)
      setNewName('')
      setNewVersion('1.0.0')
      setNewTemplate('')
      setNewMetadata('')
      setShowCreate(false)
      load()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  const startEdit = (skill: SkillSummary) => {
    setEditingId(skill.id)
    setEditName(skill.name)
    setEditVersion(skill.version)
    setEditTemplate(skill.template_md)
    setEditMetadata(skill.metadata ? JSON.stringify(skill.metadata, null, 2) : '')
    setEditError(null)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditError(null)
    setEditMetadata('')
  }

  const handleEdit = async (skillId: string) => {
    if (!token || !teamId) return
    setSaving(true)
    setEditError(null)
    try {
      const metadata = parseMetadata(editMetadata)
      if (metadata === null) { setEditError('Invalid JSON in metadata'); setSaving(false); return }
      await updateSkill(skillId, {
        name: editName.trim(),
        version: editVersion.trim(),
        template_md: editTemplate.trim(),
        metadata: metadata || undefined,
      }, token)
      setEditingId(null)
      load()
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDeprecate = async () => {
    if (!token || !deprecateTarget) return
    try {
      await updateSkill(deprecateTarget, { status: 'deprecated' }, token)
      setDeprecateTarget(null)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Deprecate failed')
      setDeprecateTarget(null)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('skills.heading')} />

      {/* Create form */}
      <div className={styles.createForm}>
        <div className={styles.formTitle}>
          {showCreate ? t('skills.createSkill') : (
            <button
              type="button"
              className={styles.submitBtn}
              onClick={() => { setShowCreate(true); setCreateError(null) }}
            >
              + {t('skills.createSkill')}
            </button>
          )}
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="skill-create-name">{t('skills.name')}</label>
                <input
                  type="text"
                  id="skill-create-name"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  placeholder={t('skills.namePlaceholder')}
                  style={{ width: '100%' }}
                  required
                />
              </div>
              <div className={styles.formField}>
                <label htmlFor="skill-create-version">{t('skills.version')}</label>
                <input
                  type="text"
                  id="skill-create-version"
                  value={newVersion}
                  onChange={e => setNewVersion(e.target.value)}
                  placeholder={t('skills.versionPlaceholder')}
                  style={{ width: '90px' }}
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="skill-create-template">{t('skills.template')}</label>
                <textarea
                  id="skill-create-template"
                  value={newTemplate}
                  onChange={e => setNewTemplate(e.target.value)}
                  placeholder={t('skills.templatePlaceholder')}
                  style={{ width: '100%', minHeight: '80px', resize: 'vertical' }}
                  required
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="skill-create-metadata">{t('skills.metadata')}</label>
                <textarea
                  id="skill-create-metadata"
                  value={newMetadata}
                  onChange={e => setNewMetadata(e.target.value)}
                  placeholder={t('skills.metadataPlaceholder')}
                  style={{ width: '100%', minHeight: '40px', resize: 'vertical', fontFamily: 'monospace', fontSize: '12px' }}
                />
              </div>
            </div>
            {createError && <p className={styles.error}>{createError}</p>}
            <div className={styles.formRow}>
              <button
                type="submit"
                className={styles.submitBtn}
                disabled={creating || !newName.trim() || !newTemplate.trim()}
              >
                {creating ? t('skills.creating') : t('common.create')}
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
      {loading && <p className={styles.loading}>{t('skills.loading')}</p>}

      {/* Empty */}
      {!loading && !error && skills.length === 0 && (
        <EmptyState icon={Wrench} title={t('skills.noSkills')} description={t('skills.noSkillsDesc')} />
      )}

      {/* List */}
      {skills.length > 0 && (
        <div className={styles.list}>
          {skills.map(s => {
            const isExpanded = expandedId === s.id
            const isEditing = editingId === s.id
            const StatusIcon = STATUS_ICONS[s.status]
            return (
              <div key={s.id} className={styles.card}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardIcon}>
                    {StatusIcon && <StatusIcon size={14} strokeWidth={2} color={STATUS_COLORS[s.status]} />}
                  </span>
                  <div className={styles.cardTitle}>
                    <div className={styles.cardTitleRow}>
                      <span className={styles.skillName}>{s.name}</span>
                      <span className={styles.versionBadge}>v{s.version}</span>
                      <span className={`${styles.statusBadge} ${s.status === 'deprecated' ? styles.statusDeprecated : styles.statusActive}`}>
                        {s.status}
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

                {/* Expanded detail / Edit form */}
                {isExpanded && !isEditing && (
                  <div className={styles.detail}>
                    <div className={styles.detailHeader}>{t('skills.template')}</div>
                    <pre className={styles.templatePre}>{s.template_md}</pre>

                    {s.protocol_spec && (
                      <>
                        <div className={styles.detailHeader}>{t('skills.protocolSpec')}</div>
                        <pre className={styles.jsonPre}>
                          {JSON.stringify(s.protocol_spec, null, 2)}
                        </pre>
                      </>
                    )}

                    {s.scan_rule_ids && s.scan_rule_ids.length > 0 && (
                      <>
                        <div className={styles.detailHeader}>{t('skills.scanRules')}</div>
                        <div className={styles.chips}>
                          {s.scan_rule_ids.map((rid: string) => (
                            <span key={rid} className={styles.ruleChip}>{rid}</span>
                          ))}
                        </div>
                      </>
                    )}

                    {s.metadata && Object.keys(s.metadata).length > 0 && (
                      <>
                        <div className={styles.detailHeader}>{t('skills.metadata')}</div>
                        <pre className={styles.jsonPre}>
                          {JSON.stringify(s.metadata, null, 2)}
                        </pre>
                      </>
                    )}

                    <div className={styles.detailActions}>
                      <button
                        type="button"
                        className={styles.submitBtn}
                        onClick={() => startEdit(s)}
                      >
                        {t('common.edit')}
                      </button>
                      {s.status !== 'deprecated' && (
                        <button
                          type="button"
                          className={styles.dangerBtn}
                          onClick={() => setDeprecateTarget(s.id)}
                        >
                          {t('skills.deprecate')}
                        </button>
                      )}
                    </div>
                  </div>
                )}

                {/* Edit form */}
                {isEditing && (
                  <div className={styles.detail}>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="skill-edit-name">{t('skills.name')}</label>
                        <input
                          type="text"
                          id="skill-edit-name"
                          value={editName}
                          onChange={e => setEditName(e.target.value)}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className={styles.formField}>
                        <label htmlFor="skill-edit-version">{t('skills.version')}</label>
                        <input
                          type="text"
                          id="skill-edit-version"
                          value={editVersion}
                          onChange={e => setEditVersion(e.target.value)}
                          style={{ width: '90px' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="skill-edit-template">{t('skills.template')}</label>
                        <textarea
                          id="skill-edit-template"
                          value={editTemplate}
                          onChange={e => setEditTemplate(e.target.value)}
                          style={{ width: '100%', minHeight: '80px', resize: 'vertical' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="skill-edit-metadata">{t('skills.metadata')}</label>
                        <textarea
                          id="skill-edit-metadata"
                          value={editMetadata}
                          onChange={e => setEditMetadata(e.target.value)}
                          placeholder={t('skills.metadataPlaceholder')}
                          style={{ width: '100%', minHeight: '40px', resize: 'vertical', fontFamily: 'monospace', fontSize: '12px' }}
                        />
                      </div>
                    </div>
                    {editError && <p className={styles.error}>{editError}</p>}
                    <div className={styles.detailActions}>
                      <button
                        type="button"
                        className={styles.submitBtn}
                        disabled={saving || !editName.trim() || !editTemplate.trim()}
                        onClick={() => handleEdit(s.id)}
                      >
                        {saving ? t('skills.saving') : t('skills.save')}
                      </button>
                      <button
                        type="button"
                        className={styles.filterChip}
                        onClick={cancelEdit}
                      >
                        {t('common.cancel')}
                      </button>
                    </div>
                  </div>
                )}

                <div className={styles.cardFooter}>
                  <span className={styles.actorInfo}>
                    {s.name}
                  </span>
                  <span>{formatDate(s.updated_at, lang)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── Deprecate Confirm Modal ──────────────────────────────── */}
      {deprecateTarget && (
        <ConfirmModal
          isOpen
          title={t('skills.deprecate')}
          message={t('skills.deprecateConfirm')}
          confirmLabel={t('skills.deprecate')}
          confirmVariant="danger"
          onConfirm={handleDeprecate}
          onCancel={() => setDeprecateTarget(null)}
        />
      )}
    </div>
  )
}

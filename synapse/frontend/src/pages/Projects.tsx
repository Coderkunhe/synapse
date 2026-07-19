import { useState, useEffect, useCallback } from 'react'
import { Lock, FolderOpen, ChevronUp, ChevronDown, Shield, ShieldOff, Trash2, ExternalLink } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { ProjectSummary } from '../api/client'
import ConfirmModal from '../components/ConfirmModal'
import {
  fetchProjects,
  fetchProject,
  createProject,
  updateProject,
  archiveProject,
  toggleProjectProtection,
  deleteProject,
} from '../api/client'
import { formatDate } from '../utils/format'
import { STATUS_ICONS, STATUS_COLORS } from '../utils/constants'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import styles from './Projects.module.css'

/** Parse a JSON metadata string, returning null on invalid input (non-empty, non-parseable). */
function parseMetadata(raw: string): Record<string, unknown> | null {
  const trimmed = raw.trim()
  if (!trimmed) return undefined as unknown as null // falsy → undefined for API omit
  try {
    const v = JSON.parse(trimmed)
    if (typeof v !== 'object' || v === null || Array.isArray(v)) return null
    return v
  } catch {
    return null
  }
}

export default function Projects() {
  const { t, lang } = useI18n()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [archiveTarget, setArchiveTarget] = useState<string | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [protecting, setProtecting] = useState<string | null>(null)

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [newGitRepo, setNewGitRepo] = useState('')
  const [newDefaultBranch, setNewDefaultBranch] = useState('')
  const [newApiDocsUrl, setNewApiDocsUrl] = useState('')
  const [newFrontendTestUrl, setNewFrontendTestUrl] = useState('')
  const [newOrganization, setNewOrganization] = useState('')
  const [newMetadata, setNewMetadata] = useState('')
  const [newUsePhaseMode, setNewUsePhaseMode] = useState(false)
  const [newCurrentPhase, setNewCurrentPhase] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Expanded card for detail
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Edit mode
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editGitRepo, setEditGitRepo] = useState('')
  const [editDefaultBranch, setEditDefaultBranch] = useState('')
  const [editApiDocsUrl, setEditApiDocsUrl] = useState('')
  const [editFrontendTestUrl, setEditFrontendTestUrl] = useState('')
  const [editOrganization, setEditOrganization] = useState('')
  const [editMetadata, setEditMetadata] = useState('')
  const [editUsePhaseMode, setEditUsePhaseMode] = useState(false)
  const [editCurrentPhase, setEditCurrentPhase] = useState('')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  const { token, teamId } = useAuth()

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    fetchProjects(teamId, token)
      .then(res => {
        setProjects(res.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [teamId, token])

  useEffect(() => {
    load()
  }, [load])

  // Auto-generate slug from name
  const handleNameChange = (value: string, isCreate: boolean) => {
    if (isCreate) {
      setNewName(value)
      setNewSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-|-$/g, ''),
      )
    } else {
      setEditName(value)
    }
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !teamId) return
    setCreating(true)
    setCreateError(null)
    try {
      const metadata = parseMetadata(newMetadata)
      if (metadata === null) { setCreateError('Invalid JSON in metadata'); setCreating(false); return }
      await createProject(
        teamId,
        {
          name: newName.trim(),
          slug: newSlug.trim(),
          description: newDescription.trim() || undefined,
          default_branch: newDefaultBranch.trim() || undefined,
          git_repo_url: newGitRepo.trim() || undefined,
          api_docs_url: newApiDocsUrl.trim() || undefined,
          frontend_test_url: newFrontendTestUrl.trim() || undefined,
          organization: newOrganization.trim() || undefined,
          metadata: metadata || undefined,
          use_phase_mode: newUsePhaseMode,
          current_phase: newCurrentPhase.trim() || undefined,
        },
        token,
      )
      setNewName('')
      setNewSlug('')
      setNewDescription('')
      setNewGitRepo('')
      setNewDefaultBranch('')
      setNewApiDocsUrl('')
      setNewFrontendTestUrl('')
      setNewOrganization('')
      setNewMetadata('')
      setNewUsePhaseMode(false)
      setNewCurrentPhase('')
      setShowCreate(false)
      load()
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  const startEdit = async (projectId: string) => {
    if (!token) return
    try {
      const p = await fetchProject(projectId, token)
      setEditingId(p.id)
      setEditName(p.name)
      setEditDescription(p.description || '')
      setEditGitRepo(p.git_repo_url || '')
      setEditDefaultBranch(p.default_branch || '')
      setEditApiDocsUrl(p.api_docs_url || '')
      setEditFrontendTestUrl(p.frontend_test_url || '')
      setEditOrganization(p.organization || '')
      setEditMetadata(p.metadata ? JSON.stringify(p.metadata, null, 2) : '')
      setEditUsePhaseMode(p.use_phase_mode || false)
      setEditCurrentPhase(p.current_phase || '')
      setEditError(null)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Load failed')
    }
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditError(null)
    setEditApiDocsUrl('')
    setEditFrontendTestUrl('')
    setEditOrganization('')
    setEditMetadata('')
    setEditUsePhaseMode(false)
    setEditCurrentPhase('')
  }

  const handleEdit = async (projectId: string) => {
    if (!token) return
    setSaving(true)
    setEditError(null)
    try {
      const metadata = parseMetadata(editMetadata)
      if (metadata === null) { setEditError('Invalid JSON in metadata'); setSaving(false); return }
      await updateProject(
        projectId,
        {
          name: editName.trim(),
          description: editDescription.trim() || undefined,
          default_branch: editDefaultBranch.trim() || undefined,
          git_repo_url: editGitRepo.trim() || undefined,
          api_docs_url: editApiDocsUrl.trim() || undefined,
          frontend_test_url: editFrontendTestUrl.trim() || undefined,
          organization: editOrganization.trim() || undefined,
          metadata: metadata || undefined,
          use_phase_mode: editUsePhaseMode,
          current_phase: editCurrentPhase.trim() || undefined,
        },
        token,
      )
      setEditingId(null)
      load()
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  const handleArchive = async () => {
    if (!token || !archiveTarget) return
    try {
      await archiveProject(archiveTarget, token)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Archive failed')
    } finally {
      setArchiveTarget(null)
    }
  }

  /** Compute days since archived_at. Returns null if not archived. */
  const daysSinceArchived = (p: ProjectSummary): number | null => {
    if (p.status !== 'archived' || !p.archived_at) return null
    const ms = Date.now() - new Date(p.archived_at).getTime()
    return Math.floor(ms / (1000 * 60 * 60 * 24))
  }

  const handleProtectionToggle = async (projectId: string, current: boolean) => {
    if (!token) return
    setProtecting(projectId)
    try {
      await toggleProjectProtection(projectId, !current, token)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Protection toggle failed')
    } finally {
      setProtecting(null)
    }
  }

  const handleDelete = async () => {
    if (!token || !deleteTarget) return
    try {
      await deleteProject(deleteTarget, token)
      setDeleteTarget(null)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
      setDeleteTarget(null)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('projects.heading')} />

      {/* Create form */}
      <div className={styles.createForm}>
        <div className={styles.formTitle}>
          {showCreate ? t('projects.createProject') : (
            <button
              type="button"
              className={styles.submitBtn}
              onClick={() => { setShowCreate(true); setCreateError(null) }}
            >
              + {t('projects.createProject')}
            </button>
          )}
        </div>
        {showCreate && (
          <form onSubmit={handleCreate}>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 2 }}>
                <label htmlFor="project-create-name">{t('projects.name')}</label>
                <input
                  type="text"
                  id="project-create-name"
                  value={newName}
                  onChange={e => handleNameChange(e.target.value, true)}
                  placeholder={t('projects.namePlaceholder')}
                  style={{ width: '100%' }}
                  required
                />
              </div>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-slug">{t('projects.slug')}</label>
                <input
                  type="text"
                  id="project-create-slug"
                  value={newSlug}
                  onChange={e => setNewSlug(e.target.value)}
                  placeholder={t('projects.slugPlaceholder')}
                  pattern="^[a-z0-9-]+$"
                  style={{ width: '100%' }}
                  required
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-description">{t('projects.description')}</label>
                <textarea
                  id="project-create-description"
                  value={newDescription}
                  onChange={e => setNewDescription(e.target.value)}
                  placeholder={t('projects.descPlaceholder')}
                  style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-gitRepoUrl">{t('projects.gitRepoUrl')}</label>
                <input
                  type="text"
                  id="project-create-gitRepoUrl"
                  value={newGitRepo}
                  onChange={e => setNewGitRepo(e.target.value)}
                  placeholder={t('projects.gitRepoPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
              <div className={styles.formField}>
                <label htmlFor="project-create-defaultBranch">{t('projects.defaultBranch')}</label>
                <input
                  type="text"
                  id="project-create-defaultBranch"
                  value={newDefaultBranch}
                  onChange={e => setNewDefaultBranch(e.target.value)}
                  placeholder={t('projects.branchPlaceholder')}
                  style={{ width: '120px' }}
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-apiDocsUrl">{t('projects.apiDocsUrl')}</label>
                <input
                  type="text"
                  id="project-create-apiDocsUrl"
                  value={newApiDocsUrl}
                  onChange={e => setNewApiDocsUrl(e.target.value)}
                  placeholder={t('projects.apiDocsUrlPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-frontendTestUrl">{t('projects.frontendTestUrl')}</label>
                <input
                  type="text"
                  id="project-create-frontendTestUrl"
                  value={newFrontendTestUrl}
                  onChange={e => setNewFrontendTestUrl(e.target.value)}
                  placeholder={t('projects.frontendTestUrlPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-organization">{t('projects.organization')}</label>
                <input
                  type="text"
                  id="project-create-organization"
                  value={newOrganization}
                  onChange={e => setNewOrganization(e.target.value)}
                  placeholder={t('projects.organizationPlaceholder')}
                  style={{ width: '100%' }}
                />
              </div>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label>
                  <input
                    type="checkbox"
                    id="project-create-usephasemode"
                    checked={newUsePhaseMode}
                    onChange={e => setNewUsePhaseMode(e.target.checked)}
                    style={{ marginRight: '6px' }}
                  />
                  {t('projects.usePhaseMode')}
                </label>
                <p style={{ color: 'var(--color-text-muted)', fontSize: '12px', margin: '4px 0 0 0' }}>
                  {t('projects.usePhaseModeDesc')}
                </p>
              </div>
            </div>
            {newUsePhaseMode && (
              <div className={styles.formRow}>
                <div className={styles.formField} style={{ flex: 1 }}>
                  <label htmlFor="project-create-currentphase">{t('projects.currentPhase')}</label>
                  <input
                    type="text"
                    id="project-create-currentphase"
                    value={newCurrentPhase}
                    onChange={e => setNewCurrentPhase(e.target.value)}
                    placeholder={t('projects.currentPhasePlaceholder')}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>
            )}
            <div className={styles.formRow}>
              <div className={styles.formField} style={{ flex: 1 }}>
                <label htmlFor="project-create-metadata">{t('projects.metadata')}</label>
                <textarea
                  id="project-create-metadata"
                  value={newMetadata}
                  onChange={e => setNewMetadata(e.target.value)}
                  placeholder={t('projects.metadataPlaceholder')}
                  style={{ width: '100%', minHeight: '40px', resize: 'vertical', fontFamily: 'monospace', fontSize: '12px' }}
                />
              </div>
            </div>
            {createError && <p className={styles.error}>{createError}</p>}
            <div className={styles.formRow}>
              <button
                type="submit"
                className={styles.submitBtn}
                disabled={creating || !newName.trim() || !newSlug.trim()}
              >
                {creating ? t('projects.creating') : t('common.create')}
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

      {/* Error */}
      {error && <p className={styles.error}>{error}</p>}

      {/* Loading */}
      {loading && <p className={styles.loading}>{t('projects.loading')}</p>}

      {/* Empty */}
      {!loading && !error && projects.length === 0 && (
        <EmptyState icon={FolderOpen} title={t('projects.noProjects')} description={t('projects.noProjectsDesc')} />
      )}

      {/* List */}
      {projects.length > 0 && (
        <div className={styles.list}>
          {projects.map(p => {
            const isExpanded = expandedId === p.id
            const isEditing = editingId === p.id
            const StatusIcon = STATUS_ICONS[p.status]
            return (
              <div key={p.id} className={styles.card}>
                <div className={styles.cardHeader}>
                  <span className={styles.cardIcon}>
                    {StatusIcon && <StatusIcon size={14} strokeWidth={2} color={STATUS_COLORS[p.status]} />}
                  </span>
                  <div className={styles.cardTitle}>
                    <div className={styles.cardTitleRow}>
                      <span className={styles.projectName}>{p.name}</span>
                      <span className={styles.slugBadge}>{p.slug}</span>
                      {p.is_protected && (
                        <span className={styles.protectedIcon} title={t('projects.protected')}>
                          <Shield size={14} strokeWidth={2} />
                        </span>
                      )}
                      <span
                        className={`${styles.statusBadge} ${
                          p.status === 'archived' ? styles.statusArchived : styles.statusActive
                        }`}
                      >
                        {p.status}
                        {p.status === 'archived' && daysSinceArchived(p) !== null && (
                          <> · {daysSinceArchived(p)! >= 7
                            ? t('projects.canDelete')
                            : `${daysSinceArchived(p)}d`}
                          </>
                        )}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className={styles.expandBtn}
                    onClick={() => setExpandedId(isExpanded ? null : p.id)}
                  >
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                </div>

                {/* Expanded detail */}
                {isExpanded && !isEditing && (
                  <div className={styles.detail}>
                    {p.description && (
                      <>
                        <div className={styles.detailHeader}>{t('projects.description')}</div>
                        <p className={styles.detailText}>{p.description}</p>
                      </>
                    )}

                    <div className={styles.detailGrid}>
                      {p.git_repo_url && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.gitRepo')}</div>
                          <code className={styles.detailCode}>{p.git_repo_url}</code>
                        </div>
                      )}
                      {p.default_branch && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.defaultBranch')}</div>
                          <code className={styles.detailCode}>{p.default_branch}</code>
                        </div>
                      )}
                      {p.api_docs_url && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.apiDocsUrl')}</div>
                          <code className={styles.detailCode}>{p.api_docs_url}</code>
                        </div>
                      )}
                      {p.frontend_test_url && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.frontendTestUrl')}</div>
                          <code className={styles.detailCode}>{p.frontend_test_url}</code>
                        </div>
                      )}
                      {p.organization && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.organization')}</div>
                          <code className={styles.detailCode}>{p.organization}</code>
                        </div>
                      )}
                      {p.use_phase_mode && (
                        <div>
                          <div className={styles.detailHeader}>{t('projects.usePhaseMode')}</div>
                          <code className={styles.detailCode}>
                            {p.current_phase || t('projects.phaseModeEnabled')}
                          </code>
                        </div>
                      )}
                    </div>

                    {p.metadata && Object.keys(p.metadata).length > 0 && (
                      <>
                        <div className={styles.detailHeader}>{t('projects.metadata')}</div>
                        <pre className={styles.jsonPre}>
                          {JSON.stringify(p.metadata, null, 2)}
                        </pre>
                      </>
                    )}

                    <div className={styles.detailActions}>
                      <Link
                        to={`/projects/${p.id}`}
                        className={styles.viewBtn}
                      >
                        <ExternalLink size={14} /> {t('common.view')}
                      </Link>
                      <button
                        type="button"
                        className={styles.submitBtn}
                        onClick={() => startEdit(p.id)}
                      >
                        {t('projects.edit')}
                      </button>
                      <button
                        type="button"
                        className={p.is_protected ? styles.warningBtn : styles.filterChip}
                        disabled={protecting === p.id}
                        onClick={() => handleProtectionToggle(p.id, p.is_protected)}
                      >
                        {p.is_protected
                          ? <><ShieldOff size={14} /> {t('projects.unprotect')}</>
                          : <><Shield size={14} /> {t('projects.protect')}</>
                        }
                      </button>
                      {p.status !== 'archived' && (
                        <button
                          type="button"
                          className={styles.dangerBtn}
                          disabled={p.is_protected}
                          onClick={() => setArchiveTarget(p.id)}
                          title={p.is_protected ? t('projects.cannotArchiveProtected') : undefined}
                        >
                          {t('projects.archive')}
                        </button>
                      )}
                      {p.status === 'archived' && daysSinceArchived(p) !== null && daysSinceArchived(p)! >= 7 && !p.is_protected && (
                        <button
                          type="button"
                          className={styles.dangerBtn}
                          onClick={() => setDeleteTarget(p.id)}
                        >
                          <Trash2 size={14} /> {t('projects.delete')}
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
                        <label htmlFor="project-edit-name">{t('projects.name')}</label>
                        <input
                          type="text"
                          id="project-edit-name"
                          value={editName}
                          onChange={e => handleNameChange(e.target.value, false)}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-description">{t('projects.description')}</label>
                        <textarea
                          id="project-edit-description"
                          value={editDescription}
                          onChange={e => setEditDescription(e.target.value)}
                          style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-gitRepoUrl">{t('projects.gitRepoUrl')}</label>
                        <input
                          type="text"
                          id="project-edit-gitRepoUrl"
                          value={editGitRepo}
                          onChange={e => setEditGitRepo(e.target.value)}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className={styles.formField}>
                        <label htmlFor="project-edit-defaultBranch">{t('projects.defaultBranch')}</label>
                        <input
                          type="text"
                          id="project-edit-defaultBranch"
                          value={editDefaultBranch}
                          onChange={e => setEditDefaultBranch(e.target.value)}
                          style={{ width: '120px' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-apiDocsUrl">{t('projects.apiDocsUrl')}</label>
                        <input
                          type="text"
                          id="project-edit-apiDocsUrl"
                          value={editApiDocsUrl}
                          onChange={e => setEditApiDocsUrl(e.target.value)}
                          placeholder={t('projects.apiDocsUrlPlaceholder')}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-frontendTestUrl">{t('projects.frontendTestUrl')}</label>
                        <input
                          type="text"
                          id="project-edit-frontendTestUrl"
                          value={editFrontendTestUrl}
                          onChange={e => setEditFrontendTestUrl(e.target.value)}
                          placeholder={t('projects.frontendTestUrlPlaceholder')}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </div>
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-organization">{t('projects.organization')}</label>
                        <input
                          type="text"
                          id="project-edit-organization"
                          value={editOrganization}
                          onChange={e => setEditOrganization(e.target.value)}
                          placeholder={t('projects.organizationPlaceholder')}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label>
                          <input
                            type="checkbox"
                            id="project-edit-usephasemode"
                            checked={editUsePhaseMode}
                            onChange={e => setEditUsePhaseMode(e.target.checked)}
                            style={{ marginRight: '6px' }}
                          />
                          {t('projects.usePhaseMode')}
                        </label>
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '12px', margin: '4px 0 0 0' }}>
                          {t('projects.usePhaseModeDesc')}
                        </p>
                      </div>
                    </div>
                    {editUsePhaseMode && (
                      <div className={styles.formRow}>
                        <div className={styles.formField} style={{ flex: 1 }}>
                          <label htmlFor="project-edit-currentphase">{t('projects.currentPhase')}</label>
                          <input
                            type="text"
                            id="project-edit-currentphase"
                            value={editCurrentPhase}
                            onChange={e => setEditCurrentPhase(e.target.value)}
                            placeholder={t('projects.currentPhasePlaceholder')}
                            style={{ width: '100%' }}
                          />
                        </div>
                      </div>
                    )}
                    <div className={styles.formRow}>
                      <div className={styles.formField} style={{ flex: 1 }}>
                        <label htmlFor="project-edit-metadata">{t('projects.metadata')}</label>
                        <textarea
                          id="project-edit-metadata"
                          value={editMetadata}
                          onChange={e => setEditMetadata(e.target.value)}
                          placeholder={t('projects.metadataPlaceholder')}
                          style={{ width: '100%', minHeight: '40px', resize: 'vertical', fontFamily: 'monospace', fontSize: '12px' }}
                        />
                      </div>
                    </div>
                    {editError && <p className={styles.error}>{editError}</p>}
                    <div className={styles.detailActions}>
                      <button
                        type="button"
                        className={styles.submitBtn}
                        disabled={saving || !editName.trim()}
                        onClick={() => handleEdit(p.id)}
                      >
                        {saving ? t('projects.saving') : t('common.save')}
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
                    {p.name}
                  </span>
                  <span>{formatDate(p.updated_at, lang)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── Archive Confirm Modal ──────────────────────────────── */}
      {archiveTarget && (
        <ConfirmModal
          isOpen
          title={t('projects.archiveProject')}
          message={t('projects.archiveConfirm')}
          confirmLabel={t('projects.archiveProject')}
          confirmVariant="warning"
          onConfirm={handleArchive}
          onCancel={() => setArchiveTarget(null)}
        />
      )}

      {/* ── Delete Confirm Modal ──────────────────────────────── */}
      {deleteTarget && (
        <ConfirmModal
          isOpen
          title={t('projects.deleteProject')}
          message={t('projects.deleteConfirm')}
          confirmLabel={t('projects.deleteProject')}
          confirmVariant="danger"
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
    </div>
  )
}

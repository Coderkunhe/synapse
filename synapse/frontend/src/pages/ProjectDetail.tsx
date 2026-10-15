import { useState, useEffect, useCallback } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Lock, AlertTriangle, ChevronLeft, Shield, ShieldOff, Trash2, X } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { ProjectSummary, WorkerSummary, ProjectRoleEntry } from '../api/client'
import {
  fetchProject,
  updateProject,
  archiveProject,
  toggleProjectProtection,
  deleteProject,
  fetchProjectRoles,
  assignProjectRole,
  revokeProjectRole,
  fetchWorkers,
} from '../api/client'
import ConfirmModal from '../components/ConfirmModal'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import ProjectOverview from '../components/ProjectOverview'
import { formatDate } from '../utils/format'
import styles from './ProjectDetail.module.css'

// ── Conventions shape ───────────────────────────────────────

interface ProjectConventions {
  projectDescription: string
  frontendStack: string
  backendStack: string
  database: string
  deployment: string
  adminName: string
  constraints: string
}

const EMPTY_CONVENTIONS: ProjectConventions = {
  projectDescription: '',
  frontendStack: '',
  backendStack: '',
  database: '',
  deployment: '',
  adminName: '',
  constraints: '',
}

function parseConventions(metadata: Record<string, unknown> | null | undefined): ProjectConventions {
  const c = metadata && typeof metadata === 'object' ? (metadata as Record<string, unknown>).conventions : undefined
  if (c && typeof c === 'object' && !Array.isArray(c)) {
    const conv = c as Record<string, unknown>
    return {
      projectDescription: String(conv.projectDescription ?? ''),
      frontendStack: String(conv.frontendStack ?? ''),
      backendStack: String(conv.backendStack ?? ''),
      database: String(conv.database ?? ''),
      deployment: String(conv.deployment ?? ''),
      adminName: String(conv.adminName ?? ''),
      constraints: String(conv.constraints ?? ''),
    }
  }
  return { ...EMPTY_CONVENTIONS }
}

// ── Component ────────────────────────────────────────────────

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const { t, lang } = useI18n()
  const { token, teamId } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // Project data
  const [project, setProject] = useState<ProjectSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Tab — 支持 ?tab=overview 钻取（团队态势 → 项目态势落地 overview tab）
  const [activeTab, setActiveTab] = useState<'info' | 'roles' | 'conventions' | 'overview'>(() => {
    const tab = searchParams.get('tab')
    return tab === 'info' || tab === 'roles' || tab === 'conventions' || tab === 'overview' ? tab : 'info'
  })

  // Info tab edit mode
  const [editing, setEditing] = useState(false)
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

  // Roles tab
  const [roles, setRoles] = useState<ProjectRoleEntry[]>([])
  const [rolesLoading, setRolesLoading] = useState(false)
  const [rolesError, setRolesError] = useState<string | null>(null)
  const [workers, setWorkers] = useState<WorkerSummary[]>([])
  const [selectedWorkerId, setSelectedWorkerId] = useState('')
  const [selectedRole, setSelectedRole] = useState('')
  const [assigning, setAssigning] = useState(false)
  const [revokingId, setRevokingId] = useState<string | null>(null)

  // Conventions tab
  const [conventions, setConventions] = useState<ProjectConventions>(EMPTY_CONVENTIONS)
  const [savingConventions, setSavingConventions] = useState(false)
  const [conventionsMsg, setConventionsMsg] = useState<string | null>(null)

  // Archive / Delete
  const [showArchive, setShowArchive] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [protecting, setProtecting] = useState(false)

  // ── Load project ──────────────────────────────────────────

  const load = useCallback(() => {
    if (!token || !projectId) return
    setLoading(true)
    fetchProject(projectId, token)
      .then(p => {
        setProject(p)
        setError(null)
        setLoading(false)
        setConventions(parseConventions(p.metadata))
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [projectId, token])

  useEffect(() => { load() }, [load])

  // ── Load roles ────────────────────────────────────────────

  const loadRoles = useCallback(() => {
    if (!token || !projectId) return
    setRolesLoading(true)
    fetchProjectRoles(projectId, token)
      .then(res => {
        setRoles(res.roles)
        setRolesError(null)
        setRolesLoading(false)
      })
      .catch(err => {
        setRolesError(err.message)
        setRolesLoading(false)
      })
  }, [projectId, token])

  useEffect(() => {
    if (activeTab === 'roles') loadRoles()
  }, [activeTab, loadRoles])

  // ── Load workers (for role assignment) ────────────────────

  const loadWorkers = useCallback(() => {
    if (!token || !teamId) return
    fetchWorkers(teamId, token, { status: 'active' })
      .then(res => setWorkers(res.items))
      .catch(() => { /* worker list is non-critical */ })
  }, [token, teamId])

  useEffect(() => {
    if (activeTab === 'roles') loadWorkers()
  }, [activeTab, loadWorkers])

  // ── Info tab handlers ─────────────────────────────────────

  const startEdit = () => {
    if (!project) return
    setEditName(project.name)
    setEditDescription(project.description || '')
    setEditGitRepo(project.git_repo_url || '')
    setEditDefaultBranch(project.default_branch || '')
    setEditApiDocsUrl(project.api_docs_url || '')
    setEditFrontendTestUrl(project.frontend_test_url || '')
    setEditOrganization(project.organization || '')
    setEditMetadata(project.metadata ? JSON.stringify(project.metadata, null, 2) : '')
    setEditUsePhaseMode(project.use_phase_mode || false)
    setEditCurrentPhase(project.current_phase || '')
    setEditError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setEditError(null)
  }

  const handleEdit = async () => {
    if (!token || !projectId) return
    setSaving(true)
    setEditError(null)
    try {
      let metadata: Record<string, unknown> | undefined
      const trimmed = editMetadata.trim()
      if (trimmed) {
        try {
          const parsed = JSON.parse(trimmed)
          if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
            metadata = parsed
          } else {
            setEditError('Invalid JSON in metadata')
            setSaving(false)
            return
          }
        } catch {
          setEditError('Invalid JSON in metadata')
          setSaving(false)
          return
        }
      }
      const updated = await updateProject(
        projectId,
        {
          name: editName.trim(),
          description: editDescription.trim() || undefined,
          default_branch: editDefaultBranch.trim() || undefined,
          git_repo_url: editGitRepo.trim() || undefined,
          api_docs_url: editApiDocsUrl.trim() || undefined,
          frontend_test_url: editFrontendTestUrl.trim() || undefined,
          organization: editOrganization.trim() || undefined,
          metadata,
          use_phase_mode: editUsePhaseMode,
          current_phase: editCurrentPhase.trim() || undefined,
        },
        token,
      )
      setProject(updated)
      setConventions(parseConventions(updated.metadata))
      setEditing(false)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  // ── Role handlers ─────────────────────────────────────────

  const handleAssignRole = async () => {
    if (!token || !projectId || !selectedWorkerId || !selectedRole) return
    setAssigning(true)
    try {
      await assignProjectRole(projectId, selectedWorkerId, selectedRole, token)
      setSelectedWorkerId('')
      setSelectedRole('')
      loadRoles()
    } catch (err: unknown) {
      setRolesError(err instanceof Error ? err.message : 'Assign failed')
    } finally {
      setAssigning(false)
    }
  }

  const handleRevokeRole = async (workerId: string) => {
    if (!token || !projectId) return
    setRevokingId(workerId)
    try {
      await revokeProjectRole(projectId, workerId, token)
      loadRoles()
    } catch (err: unknown) {
      setRolesError(err instanceof Error ? err.message : 'Revoke failed')
    } finally {
      setRevokingId(null)
    }
  }

  // ── Conventions handlers ──────────────────────────────────

  const handleSaveConventions = async () => {
    if (!token || !projectId || !project) return
    setSavingConventions(true)
    setConventionsMsg(null)
    try {
      const currentMetadata = project.metadata ?? {}
      const newMetadata: Record<string, unknown> = { ...(currentMetadata as Record<string, unknown>) }
      newMetadata.conventions = {
        projectDescription: conventions.projectDescription,
        frontendStack: conventions.frontendStack,
        backendStack: conventions.backendStack,
        database: conventions.database,
        deployment: conventions.deployment,
        adminName: conventions.adminName,
        constraints: conventions.constraints,
      }
      const updated = await updateProject(projectId, { metadata: newMetadata }, token)
      setProject(updated)
      setConventionsMsg(t('projectDetail.savedConventions'))
      setTimeout(() => setConventionsMsg(null), 3000)
    } catch (err: unknown) {
      setConventionsMsg(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSavingConventions(false)
    }
  }

  // ── Archive / Delete ──────────────────────────────────────

  const handleArchive = async () => {
    if (!token || !projectId) return
    try {
      await archiveProject(projectId, token)
      navigate('/projects')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Archive failed')
    } finally {
      setShowArchive(false)
    }
  }

  const handleProtectionToggle = async () => {
    if (!token || !project || !projectId) return
    setProtecting(true)
    try {
      const updated = await toggleProjectProtection(projectId, !project.is_protected, token)
      setProject(updated)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Protection toggle failed')
    } finally {
      setProtecting(false)
    }
  }

  const handleDelete = async () => {
    if (!token || !projectId) return
    try {
      await deleteProject(projectId, token)
      navigate('/projects')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setShowDelete(false)
    }
  }

  const daysSinceArchived = (p: ProjectSummary): number | null => {
    if (p.status !== 'archived' || !p.archived_at) return null
    const ms = Date.now() - new Date(p.archived_at).getTime()
    return Math.floor(ms / (1000 * 60 * 60 * 24))
  }

  const hasOrchestrator = roles.some(r => r.role === 'orchestrator')
  const selectedRoleIsOrch = selectedRole === 'orchestrator'

  // ── Render guards ─────────────────────────────────────────

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
        <PageHeader title={t('projectDetail.heading')} />
        <p className={styles.loading}>{t('projectDetail.loading')}</p>
      </div>
    )
  }

  if (!project) {
    return (
      <EmptyState icon={AlertTriangle} title={t('common.error')} description={t('common.noData')} />
    )
  }

  const archDays = daysSinceArchived(project)

  // ── Render ────────────────────────────────────────────────

  return (
    <div>
      <div className={styles.topBar}>
        <Link to="/projects" className={styles.backLink}>
          <ChevronLeft size={16} /> {t('projectDetail.backToProjects')}
        </Link>
      </div>

      <PageHeader title={project.name}>
        <span className={`${styles.statusBadge} ${project.status === 'archived' ? styles.statusArchived : styles.statusActive}`}>
          {project.status}
        </span>
        {project.is_protected && (
          <span className={styles.protectedBadge}><Shield size={12} /> {t('projects.protected')}</span>
        )}
      </PageHeader>

      {/* Tab bar */}
      <div className={styles.tabBar}>
        {(['info', 'roles', 'conventions', 'overview'] as const).map(tab => (
          <button
            key={tab}
            type="button"
            className={`${styles.tab} ${activeTab === tab ? styles.tabActive : ''}`}
            data-testid={`tab-${tab}`}
            onClick={() => setActiveTab(tab)}
          >
            {t(`projectDetail.${tab}`)}
          </button>
        ))}
      </div>

      {/* ── Tab: Info ─────────────────────────────────────── */}
      {activeTab === 'info' && !editing && (
        <div className={styles.tabContent}>
          {project.description && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('projects.description')}</div>
              <p className={styles.sectionText}>{project.description}</p>
            </div>
          )}

          <div className={styles.grid}>
            {project.git_repo_url && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.gitRepo')}</div>
                <code className={styles.code}>{project.git_repo_url}</code>
              </div>
            )}
            {project.default_branch && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.defaultBranch')}</div>
                <code className={styles.code}>{project.default_branch}</code>
              </div>
            )}
            {project.api_docs_url && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.apiDocsUrl')}</div>
                <code className={styles.code}>{project.api_docs_url}</code>
              </div>
            )}
            {project.frontend_test_url && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.frontendTestUrl')}</div>
                <code className={styles.code}>{project.frontend_test_url}</code>
              </div>
            )}
            {project.organization && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.organization')}</div>
                <code className={styles.code}>{project.organization}</code>
              </div>
            )}
            {project.use_phase_mode && (
              <div>
                <div className={styles.sectionLabel}>{t('projects.usePhaseMode')}</div>
                <code className={styles.code}>{project.current_phase || t('projects.phaseModeEnabled')}</code>
              </div>
            )}
          </div>

          <div className={styles.metaRow}>
            <span className={styles.sectionLabel}>{t('projects.slug')}: </span>
            <code className={styles.code}>{project.slug}</code>
          </div>

          <div className={styles.metaRow}>
            <span className={styles.sectionLabel}>{t('common.created')}: </span>
            <span>{formatDate(project.created_at, lang)}</span>
          </div>

          <div className={styles.metaRow}>
            <span className={styles.sectionLabel}>{t('common.updated')}: </span>
            <span>{formatDate(project.updated_at, lang)}</span>
          </div>

          {project.metadata && Object.keys(project.metadata).length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>{t('projects.metadata')}</div>
              <pre className={styles.jsonPre}>{JSON.stringify(project.metadata, null, 2)}</pre>
            </div>
          )}

          <div className={styles.actions}>
            <button type="button" className={styles.primaryBtn} onClick={startEdit}>
              {t('projects.edit')}
            </button>
            <button
              type="button"
              className={project.is_protected ? styles.warningBtn : styles.secondaryBtn}
              disabled={protecting}
              onClick={handleProtectionToggle}
            >
              {project.is_protected
                ? <><ShieldOff size={14} /> {t('projects.unprotect')}</>
                : <><Shield size={14} /> {t('projects.protect')}</>
              }
            </button>
            {project.status !== 'archived' && (
              <button
                type="button"
                className={styles.dangerBtn}
                disabled={project.is_protected}
                onClick={() => setShowArchive(true)}
                title={project.is_protected ? t('projects.cannotArchiveProtected') : undefined}
              >
                {t('projects.archive')}
              </button>
            )}
            {project.status === 'archived' && archDays !== null && archDays >= 7 && !project.is_protected && (
              <button type="button" className={styles.dangerBtn} onClick={() => setShowDelete(true)}>
                <Trash2 size={14} /> {t('projects.delete')}
              </button>
            )}
          </div>
        </div>
      )}

      {/* Info tab — Edit mode */}
      {activeTab === 'info' && editing && (
        <div className={styles.tabContent}>
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-name">{t('projects.name')}</label>
              <input id="pd-edit-name" value={editName} onChange={e => setEditName(e.target.value)} />
            </div>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-desc">{t('projects.description')}</label>
              <textarea id="pd-edit-desc" value={editDescription} onChange={e => setEditDescription(e.target.value)} style={{ minHeight: 60, resize: 'vertical' }} />
            </div>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-git">{t('projects.gitRepoUrl')}</label>
              <input id="pd-edit-git" value={editGitRepo} onChange={e => setEditGitRepo(e.target.value)} />
            </div>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-branch">{t('projects.defaultBranch')}</label>
              <input id="pd-edit-branch" value={editDefaultBranch} onChange={e => setEditDefaultBranch(e.target.value)} />
            </div>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-api">{t('projects.apiDocsUrl')}</label>
              <input id="pd-edit-api" value={editApiDocsUrl} onChange={e => setEditApiDocsUrl(e.target.value)} />
            </div>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-feurl">{t('projects.frontendTestUrl')}</label>
              <input id="pd-edit-feurl" value={editFrontendTestUrl} onChange={e => setEditFrontendTestUrl(e.target.value)} />
            </div>
          </div>
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-org">{t('projects.organization')}</label>
              <input id="pd-edit-org" value={editOrganization} onChange={e => setEditOrganization(e.target.value)} />
            </div>
            <div className={styles.formField}>
              <label>
                <input type="checkbox" checked={editUsePhaseMode} onChange={e => setEditUsePhaseMode(e.target.checked)} style={{ marginRight: 6 }} />
                {t('projects.usePhaseMode')}
              </label>
            </div>
          </div>
          {editUsePhaseMode && (
            <div className={styles.formRow}>
              <div className={styles.formField}>
                <label htmlFor="pd-edit-phase">{t('projects.currentPhase')}</label>
                <input id="pd-edit-phase" value={editCurrentPhase} onChange={e => setEditCurrentPhase(e.target.value)} />
              </div>
            </div>
          )}
          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label htmlFor="pd-edit-meta">{t('projects.metadata')}</label>
              <textarea id="pd-edit-meta" value={editMetadata} onChange={e => setEditMetadata(e.target.value)} style={{ minHeight: 40, resize: 'vertical', fontFamily: 'monospace', fontSize: 12 }} />
            </div>
          </div>
          {editError && <p className={styles.error}>{editError}</p>}
          <div className={styles.actions}>
            <button type="button" className={styles.primaryBtn} disabled={saving || !editName.trim()} onClick={handleEdit}>
              {saving ? t('projects.saving') : t('common.save')}
            </button>
            <button type="button" className={styles.secondaryBtn} onClick={cancelEdit}>
              {t('common.cancel')}
            </button>
          </div>
        </div>
      )}

      {/* ── Tab: Roles ────────────────────────────────────── */}
      {activeTab === 'roles' && (
        <div className={styles.tabContent}>
          {rolesError && <p className={styles.error}>{rolesError}</p>}

          <div className={styles.roleAssignRow}>
            <select
              value={selectedWorkerId}
              onChange={e => setSelectedWorkerId(e.target.value)}
              className={styles.select}
            >
              <option value="">{t('projectDetail.selectWorker')}</option>
              {workers.map(w => (
                <option key={w.id} value={w.id}>{w.name} ({w.id})</option>
              ))}
            </select>
            <select
              value={selectedRole}
              onChange={e => setSelectedRole(e.target.value)}
              className={styles.select}
            >
              <option value="">{t('projectDetail.selectRole')}</option>
              <option value="orchestrator">Orchestrator</option>
              <option value="builder">Builder</option>
              <option value="steward">Steward</option>
            </select>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={assigning || !selectedWorkerId || !selectedRole || (hasOrchestrator && selectedRoleIsOrch)}
              onClick={handleAssignRole}
            >
              {assigning ? t('common.creating') : t('projectDetail.assign')}
            </button>
          </div>

          {hasOrchestrator && selectedRoleIsOrch && (
            <p className={styles.warning}>{t('projectDetail.oneOrchWarning')}</p>
          )}

          {rolesLoading && <p className={styles.loading}>{t('common.loading')}</p>}

          {!rolesLoading && roles.length === 0 && (
            <div className={styles.emptyRoles}>
              <p>{t('projectDetail.noRoles')}</p>
              <p className={styles.emptyRolesDesc}>{t('projectDetail.noRolesDesc')}</p>
            </div>
          )}

          {roles.length > 0 && (
            <table className={styles.roleTable}>
              <thead>
                <tr>
                  <th>{t('common.name')}</th>
                  <th>{t('common.role')}</th>
                  <th>{t('common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {roles.map(r => (
                  <tr key={r.worker_id}>
                    <td>{r.worker_name}</td>
                    <td>
                      <span className={`${styles.roleBadge} ${styles[`role_${r.role}`] || ''}`}>
                        {r.role}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.iconBtn}
                        disabled={revokingId === r.worker_id}
                        onClick={() => handleRevokeRole(r.worker_id)}
                        title={t('projectDetail.revoke')}
                      >
                        <X size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Tab: Conventions ──────────────────────────────── */}
      {activeTab === 'conventions' && (
        <div className={styles.tabContent}>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>{t('projectDetail.projectDescription')}</div>
            <textarea
              value={conventions.projectDescription}
              onChange={e => setConventions(prev => ({ ...prev, projectDescription: e.target.value }))}
              placeholder={t('projects.descPlaceholder')}
              className={styles.conventionInput}
              style={{ minHeight: 60, resize: 'vertical' }}
            />
          </div>

          <div className={styles.grid}>
            <div>
              <div className={styles.sectionLabel}>{t('projectDetail.frontendStack')}</div>
              <input
                value={conventions.frontendStack}
                onChange={e => setConventions(prev => ({ ...prev, frontendStack: e.target.value }))}
                placeholder={t('projectDetail.frontendStackPlaceholder')}
                className={styles.conventionInput}
              />
            </div>
            <div>
              <div className={styles.sectionLabel}>{t('projectDetail.backendStack')}</div>
              <input
                value={conventions.backendStack}
                onChange={e => setConventions(prev => ({ ...prev, backendStack: e.target.value }))}
                placeholder={t('projectDetail.backendStackPlaceholder')}
                className={styles.conventionInput}
              />
            </div>
            <div>
              <div className={styles.sectionLabel}>{t('projectDetail.database')}</div>
              <input
                value={conventions.database}
                onChange={e => setConventions(prev => ({ ...prev, database: e.target.value }))}
                placeholder={t('projectDetail.databasePlaceholder')}
                className={styles.conventionInput}
              />
            </div>
            <div>
              <div className={styles.sectionLabel}>{t('projectDetail.deployment')}</div>
              <input
                value={conventions.deployment}
                onChange={e => setConventions(prev => ({ ...prev, deployment: e.target.value }))}
                placeholder={t('projectDetail.deploymentPlaceholder')}
                className={styles.conventionInput}
              />
            </div>
          </div>

          <div className={styles.section}>
            <div className={styles.sectionLabel}>{t('projectDetail.adminName')}</div>
            <input
              value={conventions.adminName}
              onChange={e => setConventions(prev => ({ ...prev, adminName: e.target.value }))}
              placeholder={t('projectDetail.adminNamePlaceholder')}
              className={styles.conventionInput}
              style={{ maxWidth: 300 }}
            />
          </div>

          <div className={styles.section}>
            <div className={styles.sectionLabel}>{t('projectDetail.constraints')}</div>
            <textarea
              value={conventions.constraints}
              onChange={e => setConventions(prev => ({ ...prev, constraints: e.target.value }))}
              placeholder={t('projectDetail.constraintsPlaceholder')}
              className={styles.conventionInput}
              style={{ minHeight: 80, resize: 'vertical' }}
            />
          </div>

          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primaryBtn}
              disabled={savingConventions}
              onClick={handleSaveConventions}
            >
              {savingConventions ? t('projectDetail.savingConventions') : t('projectDetail.saveConventions')}
            </button>
            {conventionsMsg && (
              <span className={conventionsMsg.includes('Error') || conventionsMsg.includes('fail') || conventionsMsg.includes('Save failed') ? styles.error : styles.successMsg}>
                {conventionsMsg}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Overview (态势) ──────────────────────────── */}
      {activeTab === 'overview' && (
        <div className={styles.tabContent}>
          <ProjectOverview projectId={projectId!} teamId={project.team_id} />
        </div>
      )}

      {/* ── Confirm Modals ─────────────────────────────────── */}
      {showArchive && (
        <ConfirmModal
          isOpen
          title={t('projects.archiveProject')}
          message={t('projects.archiveConfirm')}
          confirmLabel={t('projects.archiveProject')}
          confirmVariant="warning"
          onConfirm={handleArchive}
          onCancel={() => setShowArchive(false)}
        />
      )}
      {showDelete && (
        <ConfirmModal
          isOpen
          title={t('projects.deleteProject')}
          message={t('projects.deleteConfirm')}
          confirmLabel={t('projects.deleteProject')}
          confirmVariant="danger"
          onConfirm={handleDelete}
          onCancel={() => setShowDelete(false)}
        />
      )}
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import { Lock, Users, UserPlus } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { TeamResponse, MemberResponse } from '../api/client'
import ConfirmModal from '../components/ConfirmModal'
import {
  fetchTeam,
  updateTeam,
  fetchMembers,
  inviteMember,
  removeMember,
} from '../api/client'
import { formatDate } from '../utils/format'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import styles from './Teams.module.css'

const ROLE_STYLES: Record<string, string> = {
  admin: styles.roleAdmin,
  lead: styles.roleLead,
  member: styles.roleMember,
}

export default function Teams() {
  const { t, lang } = useI18n()
  const { token, teamId } = useAuth()

  const [team, setTeam] = useState<TeamResponse | null>(null)
  const [members, setMembers] = useState<MemberResponse[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Edit team
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editAvatarUrl, setEditAvatarUrl] = useState('')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  // Invite member
  const [showInvite, setShowInvite] = useState(false)
  const [inviteUserId, setInviteUserId] = useState('')
  const [inviteDisplayName, setInviteDisplayName] = useState('')
  const [inviteRole, setInviteRole] = useState('member')
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [removeTarget, setRemoveTarget] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!token || !teamId) return
    setLoading(true)
    Promise.all([
      fetchTeam(teamId, token),
      fetchMembers(teamId, token, { limit: 100 }),
    ])
      .then(([t, m]) => {
        setTeam(t)
        setMembers(m.items)
        setError(null)
        setLoading(false)
      })
      .catch(err => {
        setError(err.message)
        setLoading(false)
      })
  }, [teamId, token])

  useEffect(() => { load() }, [load])

  const startEdit = () => {
    if (!team) return
    setEditName(team.name)
    setEditDescription(team.description || '')
    setEditAvatarUrl(team.avatar_url || '')
    setEditError(null)
    setEditing(true)
  }

  const cancelEdit = () => {
    setEditing(false)
    setEditError(null)
  }

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !teamId) return
    setSaving(true)
    setEditError(null)
    try {
      const updated = await updateTeam(
        teamId,
        {
          name: editName.trim(),
          description: editDescription.trim() || undefined,
          avatar_url: editAvatarUrl.trim() || undefined,
        },
        token,
      )
      setTeam(updated)
      setEditing(false)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !teamId) return
    setInviting(true)
    setInviteError(null)
    try {
      const member = await inviteMember(
        teamId,
        {
          user_id: inviteUserId.trim(),
          display_name: inviteDisplayName.trim(),
          role: inviteRole,
        },
        token,
      )
      setMembers(prev => [...prev, member])
      setInviteUserId('')
      setInviteDisplayName('')
      setInviteRole('member')
      setShowInvite(false)
    } catch (err: unknown) {
      setInviteError(err instanceof Error ? err.message : 'Invite failed')
    } finally {
      setInviting(false)
    }
  }

  const handleRemove = async () => {
    if (!token || !teamId || !removeTarget) return
    try {
      await removeMember(teamId, removeTarget, token)
      setMembers(prev => prev.filter(m => m.id !== removeTarget))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Remove failed')
    } finally {
      setRemoveTarget(null)
    }
  }

  if (!token || !teamId) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('teams.heading')} />

      {error && <p className={styles.error}>{error}</p>}
      {loading && <p className={styles.loading}>{t('teams.loading')}</p>}

      {!loading && !error && !team && (
        <EmptyState icon={Users} title={t('teams.noTeam')} description={t('teams.noTeamDesc')} />
      )}

      {team && (
        <>
          {/* Team card */}
          <div className={styles.teamCard}>
            {!editing ? (
              <>
                <div className={styles.teamHeader}>
                  <div className={styles.teamAvatar}>
                    {team.name.charAt(0).toUpperCase()}
                  </div>
                  <div className={styles.teamInfo}>
                    <div className={styles.teamName}>{team.name}</div>
                    <div className={styles.teamSlug}>{team.slug}</div>
                  </div>
                </div>
                {team.description && (
                  <p className={styles.teamDescription}>{team.description}</p>
                )}
                <div className={styles.teamActions}>
                  <button type="button" className={styles.submitBtn} onClick={startEdit}>
                    {t('teams.edit')}
                  </button>
                </div>
              </>
            ) : (
              <form onSubmit={handleEdit}>
                <div className={styles.formTitle}>{t('teams.editing')}</div>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="team-edit-name">{t('teams.name')}</label>
                    <input
                      type="text"
                      id="team-edit-name"
                      value={editName}
                      onChange={e => setEditName(e.target.value)}
                      placeholder={t('teams.namePlaceholder')}
                      style={{ width: '100%' }}
                      required
                    />
                  </div>
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="team-edit-description">{t('teams.description')}</label>
                    <textarea
                      id="team-edit-description"
                      value={editDescription}
                      onChange={e => setEditDescription(e.target.value)}
                      placeholder={t('teams.descPlaceholder')}
                      style={{ width: '100%', minHeight: '60px', resize: 'vertical' }}
                    />
                  </div>
                </div>
                <div className={styles.formRow}>
                  <div className={styles.formField} style={{ flex: 1 }}>
                    <label htmlFor="team-edit-avatarUrl">{t('teams.avatarUrl')}</label>
                    <input
                      type="text"
                      id="team-edit-avatarUrl"
                      value={editAvatarUrl}
                      onChange={e => setEditAvatarUrl(e.target.value)}
                      placeholder={t('teams.avatarPlaceholder')}
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
                {editError && <p className={styles.error}>{editError}</p>}
                <div className={styles.formRow}>
                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={saving || !editName.trim()}
                  >
                    {saving ? t('common.saving') : t('common.save')}
                  </button>
                  <button type="button" className={styles.filterChip} onClick={cancelEdit}>
                    {t('common.cancel')}
                  </button>
                </div>
              </form>
            )}

            <div className={styles.cardFooter}>
              <span className={styles.actorInfo}>{team.name}</span>
              <span>{formatDate(team.updated_at, lang)}</span>
            </div>
          </div>

          {/* Members section */}
          <div className={styles.section}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionTitle}>
                {t('teams.members')}
                <span className={styles.memberCount}>
                  {' '}
                  — {t('teams.memberCount', { count: members.length })}
                </span>
              </div>
              <button
                type="button"
                className={styles.submitBtn}
                onClick={() => { setShowInvite(true); setInviteError(null) }}
              >
                <UserPlus size={14} style={{ marginRight: 4 }} />
                {t('teams.inviteMember')}
              </button>
            </div>

            {/* Invite form */}
            {showInvite && (
              <div className={styles.createForm}>
                <div className={styles.formTitle}>{t('teams.inviteMember')}</div>
                <form onSubmit={handleInvite}>
                  <div className={styles.formRow}>
                    <div className={styles.formField} style={{ flex: 1 }}>
                      <label htmlFor="team-invite-userId">{t('teams.userId')}</label>
                      <input
                        type="text"
                        id="team-invite-userId"
                        value={inviteUserId}
                        onChange={e => setInviteUserId(e.target.value)}
                        placeholder={t('teams.userIdPlaceholder')}
                        style={{ width: '100%' }}
                        required
                      />
                    </div>
                    <div className={styles.formField} style={{ flex: 2 }}>
                      <label htmlFor="team-invite-displayName">{t('teams.displayName')}</label>
                      <input
                        type="text"
                        id="team-invite-displayName"
                        value={inviteDisplayName}
                        onChange={e => setInviteDisplayName(e.target.value)}
                        placeholder={t('teams.displayNamePlaceholder')}
                        style={{ width: '100%' }}
                        required
                      />
                    </div>
                    <div className={styles.formField} style={{ flex: 0.7 }}>
                      <label htmlFor="team-invite-role">{t('teams.role')}</label>
                      <select
                        id="team-invite-role"
                        value={inviteRole}
                        onChange={e => setInviteRole(e.target.value)}
                        style={{ width: '100%' }}
                      >
                        <option value="member">{t('teams.roleMember')}</option>
                        <option value="lead">{t('teams.roleLead')}</option>
                        <option value="admin">{t('teams.roleAdmin')}</option>
                      </select>
                    </div>
                  </div>
                  {inviteError && <p className={styles.error}>{inviteError}</p>}
                  <div className={styles.formRow}>
                    <button
                      type="submit"
                      className={styles.submitBtn}
                      disabled={inviting || !inviteUserId.trim() || !inviteDisplayName.trim()}
                    >
                      {inviting ? t('teams.inviting') : t('teams.inviteMember')}
                    </button>
                    <button
                      type="button"
                      className={styles.filterChip}
                      onClick={() => { setShowInvite(false); setInviteError(null) }}
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </form>
              </div>
            )}

            {/* Member list */}
            {members.length === 0 ? (
              <p className={styles.loading}>{t('teams.noMembers')}</p>
            ) : (
              <div className={styles.memberList}>
                {members.map(m => (
                  <div key={m.id} className={styles.memberRow}>
                    <div className={styles.memberAvatar}>
                      {m.display_name.charAt(0).toUpperCase()}
                    </div>
                    <div className={styles.memberInfo}>
                      <div className={styles.memberName}>{m.display_name}</div>
                      <div className={styles.memberUserId}>{m.user_id}</div>
                    </div>
                    <span className={`${styles.memberRole} ${ROLE_STYLES[m.role] || styles.roleMember}`}>
                      {m.role === 'admin' ? t('teams.roleAdmin')
                        : m.role === 'lead' ? t('teams.roleLead')
                        : t('teams.roleMember')}
                    </span>
                    <span className={styles.memberMeta}>
                      {t('teams.joined')}: {formatDate(m.joined_at, lang)}
                    </span>
                    <button
                      type="button"
                      className={styles.removeBtn}
                      onClick={() => setRemoveTarget(m.id)}
                      title={t('teams.remove')}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Confirm Modal ──────────────────────────────────────── */}
      {removeTarget && (
        <ConfirmModal
          isOpen
          title={t('teams.removeMember')}
          message={t('teams.removeConfirm')}
          confirmLabel={t('teams.removeMember')}
          confirmVariant="danger"
          onConfirm={handleRemove}
          onCancel={() => setRemoveTarget(null)}
        />
      )}
    </div>
  )
}

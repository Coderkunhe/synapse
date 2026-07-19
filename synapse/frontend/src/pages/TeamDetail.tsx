import { useState, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { Lock, Users, ArrowLeft } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import type { TeamResponse, MemberResponse } from '../api/client'
import { fetchTeam, fetchMembers } from '../api/client'
import { formatDate } from '../utils/format'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import styles from './Teams.module.css'

const ROLE_STYLES: Record<string, string> = {
  admin: styles.roleAdmin,
  lead: styles.roleLead,
  member: styles.roleMember,
}

export default function TeamDetail() {
  const { t, lang } = useI18n()
  const { token } = useAuth()
  const { teamId } = useParams<{ teamId: string }>()

  const [team, setTeam] = useState<TeamResponse | null>(null)
  const [members, setMembers] = useState<MemberResponse[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

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

  if (!token) {
    return (
      <EmptyState icon={Lock} title={t('auth.connectToSynapse')} description={t('auth.setTokenHint')} />
    )
  }

  return (
    <div>
      <PageHeader title={t('teams.details')}>
        <Link to="/teams" className={styles.filterChip} style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <ArrowLeft size={14} />
          {t('common.back')}
        </Link>
      </PageHeader>

      {error && <p className={styles.error}>{error}</p>}
      {loading && <p className={styles.loading}>{t('teams.loading')}</p>}

      {!loading && !error && !team && (
        <EmptyState icon={Users} title={t('teams.noTeam')} description={t('teams.noTeamDesc')} />
      )}

      {team && (
        <>
          {/* Team card */}
          <div className={styles.teamCard}>
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
            {team.avatar_url && (
              <p className={styles.teamDescription}>
                <img
                  src={team.avatar_url}
                  alt={team.name}
                  style={{ width: 80, height: 80, borderRadius: 8, objectFit: 'cover' }}
                />
              </p>
            )}
            <div className={styles.cardFooter}>
              <span className={styles.actorInfo}>{team.name}</span>
              <span>{formatDate(team.updated_at, lang)}</span>
            </div>
          </div>

          {/* Members section (read-only) */}
          <div className={styles.section}>
            <div className={styles.sectionTitle} style={{ marginBottom: 12 }}>
              {t('teams.members')}
              <span className={styles.memberCount}>
                {' '}
                — {t('teams.memberCount', { count: members.length })}
              </span>
            </div>

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
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/**
 * ResetPassword page — complete password reset with token + new password.
 *
 * Renders a centered card with a reset token input (pre-filled from
 * ?token= query param if available) and a new password input. On
 * submit, calls POST /v1/auth/reset-password.
 *
 * On success, shows a confirmation and link back to /login.
 * If already authenticated, redirects to /dashboard.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { resetPassword } from '../api/client'
import { Zap } from 'lucide-react'
import styles from './Login.module.css'

export default function ResetPassword() {
  const { isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const tokenFromUrl = searchParams.get('token') ?? ''

  const [token, setToken] = useState(tokenFromUrl)
  const [newPassword, setNewPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token || !newPassword) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await resetPassword(token, newPassword)
      setSuccess(true)
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Reset failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <p className={styles.loading}>{t('auth.verifyingSession')}</p>
        </div>
      </div>
    )
  }

  if (success) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.logo}><Zap size={40} /></div>
          <h1 className={styles.title}>{t('auth.resetPasswordTitle')}</h1>
          <p className={styles.subtitle}>{t('auth.resetPasswordSuccess')}</p>

          <div className={styles.footerLink} style={{ marginTop: 'var(--gm-space-4)' }}>
            <a href="/login">{t('auth.backToLogin')}</a>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.logo}><Zap size={40} /></div>
        <h1 className={styles.title}>{t('auth.resetPasswordTitle')}</h1>
        <p className={styles.subtitle}>{t('auth.resetPasswordSubtitle')}</p>

        <form className={styles.emailForm} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <input
              className={styles.input}
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={t('auth.resetPasswordTokenLabel')}
              aria-label={t('auth.resetPasswordTokenLabel')}
              autoComplete="off"
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <input
              className={styles.input}
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder={t('auth.passwordPlaceholder')}
              aria-label={t('auth.resetPasswordNewPasswordLabel')}
              autoComplete="new-password"
              disabled={submitting}
              minLength={8}
            />
          </div>
          {submitError && <div className={styles.error}>{submitError}</div>}
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !token || !newPassword}
          >
            {submitting ? t('auth.resetPasswordResetting') : t('auth.resetPasswordButton')}
          </button>
        </form>

        <div className={styles.footerLink}>
          <a href="/login">{t('auth.backToLogin')}</a>
        </div>
      </div>
    </div>
  )
}

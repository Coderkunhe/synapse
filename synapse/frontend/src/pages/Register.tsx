/**
 * Register page — Email/Password account creation.
 *
 * Renders a centered card with email, password, and display name fields.
 * On success, auto-logs in via httpOnly cookie and redirects to /dashboard.
 * If already authenticated, redirects to /dashboard.
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { Zap } from 'lucide-react'
import styles from './Login.module.css'

export default function Register() {
  const { registerAndLogin, isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password || !displayName.trim()) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await registerAndLogin(email, password, displayName)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Registration failed')
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

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.logo}><Zap size={40} /></div>
        <h1 className={styles.title}>{t('auth.registerTitle')}</h1>
        <p className={styles.subtitle}>{t('auth.registerSubtitle')}</p>

        <form className={styles.emailForm} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <input
              className={styles.input}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t('auth.emailPlaceholder')}
              aria-label={t('auth.emailLabel')}
              autoComplete="email"
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <input
              className={styles.input}
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder={t('auth.displayNamePlaceholder')}
              aria-label={t('auth.displayNameLabel')}
              autoComplete="name"
              disabled={submitting}
            />
          </div>
          <div className={styles.field}>
            <input
              className={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('auth.passwordPlaceholder')}
              aria-label={t('auth.passwordLabel')}
              autoComplete="new-password"
              disabled={submitting}
              minLength={8}
            />
          </div>
          {submitError && <div className={styles.error}>{submitError}</div>}
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !email.trim() || !password || !displayName.trim()}
          >
            {submitting ? t('auth.registering') : t('auth.registerButton')}
          </button>
        </form>

        <div className={styles.footerLink}>
          <a href="/login">{t('auth.haveAccount')}</a>
        </div>
      </div>
    </div>
  )
}

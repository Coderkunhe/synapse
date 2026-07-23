/**
 * ForgotPassword page — request a password reset link.
 *
 * Renders a centered card with an email input. On submit, calls
 * POST /v1/auth/forgot-password. Always shows a success message
 * (prevents user enumeration). The reset token (if any) is
 * never displayed — use browser devtools Network tab to inspect.
 *
 * If already authenticated, redirects to /dashboard.
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { forgotPassword } from '../api/client'
import { Zap } from 'lucide-react'
import styles from './Auth.module.css'

export default function ForgotPassword() {
  const { isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return

    setSubmitting(true)
    setSubmitError(null)
    setSubmitted(false)
    try {
      await forgotPassword(email)
      setSubmitted(true)
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Request failed')
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

  // Success state — unified (always shows email-sent message)
  if (!submitting && !submitError && submitted) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.logo}><Zap size={40} /></div>
          <h1 className={styles.title}>{t('auth.forgotPasswordTitle')}</h1>
          <p className={styles.subtitle}>{t('auth.forgotPasswordCheckEmail')}</p>

          <div className={styles.footerLink} style={{ marginTop: 'var(--gm-space-4)' }}>
            <Link to="/login">{t('auth.backToLogin')}</Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.logo}><Zap size={40} /></div>
        <h1 className={styles.title}>{t('auth.forgotPasswordTitle')}</h1>
        <p className={styles.subtitle}>{t('auth.forgotPasswordSubtitle')}</p>

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
          {submitError && <div className={styles.error}>{submitError}</div>}
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !email.trim()}
          >
            {submitting ? t('auth.forgotPasswordSending') : t('auth.forgotPasswordButton')}
          </button>
        </form>

        <div className={styles.footerLink}>
          <Link to="/login">{t('auth.backToLogin')}</Link>
        </div>
      </div>
    </div>
  )
}

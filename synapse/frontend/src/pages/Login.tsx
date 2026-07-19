/**
 * Login page — GitHub OAuth entry point.
 *
 * Renders a centered card with a "Login with GitHub" button.
 * If already authenticated, redirects to /dashboard.
 * Displays error messages from ?error=... query param.
 */

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { fetchDevToken } from '../api/client'
import { Zap } from 'lucide-react'
import styles from './Login.module.css'

export default function Login() {
  const { login, loginWithEmail, isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [devLoading, setDevLoading] = useState(false)
  const [devError, setDevError] = useState<string | null>(null)

  // Email/Password form state
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const error = searchParams.get('error')

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleDevLogin = async () => {
    setDevLoading(true)
    setDevError(null)
    try {
      await fetchDevToken() // Backend sets httpOnly cookie
      window.location.href = '/dashboard'
    } catch (err) {
      setDevError(err instanceof Error ? err.message : 'Dev login failed')
      setDevLoading(false)
    }
  }

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await loginWithEmail(email, password)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  // Show nothing while checking existing token validity
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
        <h1 className={styles.title}>{t('auth.loginTitle')}</h1>
        <p className={styles.subtitle}>{t('brand.slogan')}</p>

        {/* Email/Password login form */}
        <form className={styles.emailForm} onSubmit={handleEmailLogin}>
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
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('auth.passwordPlaceholder')}
              aria-label={t('auth.passwordLabel')}
              autoComplete="current-password"
              disabled={submitting}
            />
          </div>
          {submitError && <div className={styles.error}>{submitError}</div>}
          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !email.trim() || !password}
          >
            {submitting ? t('auth.loggingInWithEmail') : t('auth.loginWithEmail')}
          </button>
        </form>

        {error && (
          <div className={styles.error}>
            {errorMessage(error, t)}
          </div>
        )}

        <button className={styles.githubBtn} onClick={login} type="button">
          <svg className={styles.githubIcon} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
          </svg>
          {t('auth.loginWithGithub')}
        </button>

        <div className={styles.footerLink}>
          <a href="/forgot-password">{t('auth.forgotPasswordLink')}</a>
        </div>

        <div className={styles.divider}>
          <span>{t('auth.loginOr')}</span>
        </div>

        <button
          className={styles.devBtn}
          onClick={handleDevLogin}
          disabled={devLoading}
          type="button"
        >
          {devLoading ? t('auth.loggingIn') : t('auth.devLogin')}
        </button>

        {devError && <div className={styles.error}>{devError}</div>}

        <div className={styles.footerLink}>
          <a href="/register">{t('auth.noAccount')}</a>
        </div>
      </div>
    </div>
  )
}

// ── Error translation ─────────────────────────────────────────────────────────

function errorMessage(code: string, t: (key: string) => string): string {
  switch (code) {
    case 'invalid_state':
      return t('auth.errorInvalidState')
    case 'missing_verifier':
      return t('auth.errorMissingVerifier')
    default:
      return t('auth.errorDefault')
  }
}

/**
 * Login page — GitHub OAuth + Email/Password entry point.
 *
 * B42: 品牌区重构 · 字段标签化 · Email/OAuth 分隔线 · 按钮 spinner · 错误图标化
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { Zap, AlertCircle, Mail, Lock } from 'lucide-react'
import { getEmailError, getPasswordError, mapAuthError } from '../utils/authHelpers'
import authStyles from './Auth.module.css'
import styles from './Login.module.css'

const REMEMBER_EMAIL_KEY = 'synapse_remembered_email'

export default function Login() {
  const { login, loginWithEmail, isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [emailError, setEmailError] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)

  const error = searchParams.get('error')

  useEffect(() => {
    const stored = localStorage.getItem(REMEMBER_EMAIL_KEY)
    if (stored) {
      setEmail(stored)
      setRememberMe(true)
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleEmailLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password) return

    // Client-side validation
    const emailErr = getEmailError(email, t)
    const passwordErr = getPasswordError(password, t)
    setEmailError(emailErr)
    setPasswordError(passwordErr)
    if (emailErr || passwordErr) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await loginWithEmail(email, password)
      if (rememberMe) {
        localStorage.setItem(REMEMBER_EMAIL_KEY, email)
      } else {
        localStorage.removeItem(REMEMBER_EMAIL_KEY)
      }
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSubmitError(mapAuthError(err, t))
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) {
    return (
      <div className={authStyles.shell}>
        <div className={authStyles.card}>
          <p className={authStyles.loading}>{t('auth.verifyingSession')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={authStyles.shell}>
      <div className={authStyles.card}>

        {/* ── Brand ──────────────────────────────────────────── */}
        <div className={authStyles.brand}>
          <div className={authStyles.brandIcon}><Zap size={20} /></div>
          <div className={authStyles.brandName}>Synapse</div>
        </div>

        <h1 className={authStyles.title}>{t('auth.loginGreeting')}</h1>
        <p className={authStyles.subtitle}>{t('auth.loginPrompt')}</p>

        {/* ── Email/Password form ─────────────────────────────── */}
        <form className={authStyles.emailForm} onSubmit={handleEmailLogin}>
          <div className={authStyles.fieldGroup}>
            <label className={authStyles.fieldLabel}>{t('auth.emailLabel')}</label>
            <div className={authStyles.inputWrapper}>
              <Mail size={16} className={authStyles.inputIcon} />
              <input
                className={`${authStyles.input}${emailError ? ` ${authStyles.inputError}` : ''}`}
                style={{ paddingLeft: '40px' }}
                type="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setEmailError(null) }}
                placeholder="you@example.com"
                autoComplete="email"
                disabled={submitting}
              />
            </div>
            {emailError && <p className={authStyles.fieldError}>{emailError}</p>}
          </div>

          <div className={authStyles.fieldGroup}>
            <label className={authStyles.fieldLabel}>{t('auth.passwordLabel')}</label>
            <div className={authStyles.inputWrapper}>
              <Lock size={16} className={authStyles.inputIcon} />
              <input
                className={`${authStyles.input}${passwordError ? ` ${authStyles.inputError}` : ''}`}
                style={{ paddingLeft: '40px' }}
                type="password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setPasswordError(null) }}
                placeholder="••••••••"
                autoComplete="current-password"
                disabled={submitting}
              />
            </div>
            {passwordError && <p className={authStyles.fieldError}>{passwordError}</p>}
          </div>

          {/* Remember Me + Forgot Password — symmetric row */}
          <div className={styles.rememberRow}>
            <label className={styles.rememberLabel}>
              <input
                id="remember-me"
                className={styles.rememberCheckbox}
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                disabled={submitting}
              />
              {t('auth.rememberMe')}
            </label>
            <Link to="/forgot-password" className={styles.forgotLink}>
              {t('auth.forgotPasswordLink')}
            </Link>
          </div>

          {submitError && (
            <div className={authStyles.error}>
              <AlertCircle size={16} className={authStyles.errorIcon} />
              <span>{submitError}</span>
            </div>
          )}

          <button
            type="submit"
            className={authStyles.submitBtn}
            disabled={submitting || !email.trim() || !password}
          >
            {submitting && <span className={authStyles.spinner} />}
            {submitting ? t('auth.loggingInWithEmail') : t('auth.loginTitle')}
          </button>
        </form>

        {/* ── Divider ─────────────────────────────────────────── */}
        <div className={authStyles.divider}>or</div>

        {/* ── GitHub OAuth ────────────────────────────────────── */}
        <button className={styles.githubBtn} onClick={login} type="button">
          <svg className={styles.githubIcon} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
          </svg>
          {t('auth.loginWithGithub')}
        </button>

        {/* ── OAuth error ─────────────────────────────────────── */}
        {error && (
          <div className={authStyles.error}>
            <AlertCircle size={16} className={authStyles.errorIcon} />
            <span>{errorMessage(error, t)}</span>
          </div>
        )}

        {/* ── Register link ───────────────────────────────────── */}
        <div className={authStyles.footerLink}>
          <Link to="/register">{t('auth.noAccount')}</Link>
        </div>
      </div>

      <p className={authStyles.copyright}>{t('brand.copyright')}</p>
    </div>
  )
}

// ── Error translation ─────────────────────────────────────────────────────

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

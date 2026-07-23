/**
 * Register page — Email/Password account creation.
 *
 * B42: 品牌区重构 · 字段标签化 · 密码 hint · 错误图标化 · 按钮 spinner
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { Zap, AlertCircle, Mail, User, Lock } from 'lucide-react'
import { getEmailError, getPasswordError, getDisplayNameError, mapAuthError } from '../utils/authHelpers'
import styles from './Auth.module.css'

export default function Register() {
  const { registerAndLogin, isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [emailError, setEmailError] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [displayNameError, setDisplayNameError] = useState<string | null>(null)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password || !displayName.trim()) return

    // Client-side validation
    const emailErr = getEmailError(email, t)
    const passwordErr = getPasswordError(password, t)
    const nameErr = getDisplayNameError(displayName, t)
    setEmailError(emailErr)
    setPasswordError(passwordErr)
    setDisplayNameError(nameErr)
    if (emailErr || passwordErr || nameErr) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await registerAndLogin(email, password, displayName)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSubmitError(mapAuthError(err, t))
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

        {/* ── Brand ──────────────────────────────────────────── */}
        <div className={styles.brand}>
          <div className={styles.brandIcon}><Zap size={20} /></div>
          <div className={styles.brandName}>Synapse</div>
        </div>

        <h1 className={styles.title}>{t('auth.registerGreeting')}</h1>
        <p className={styles.subtitle}>{t('auth.registerSubtitle')}</p>

        <form className={styles.emailForm} onSubmit={handleSubmit}>
          {/* Email */}
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>{t('auth.emailLabel')}</label>
            <div className={styles.inputWrapper}>
              <Mail size={16} className={styles.inputIcon} />
              <input
                className={`${styles.input}${emailError ? ` ${styles.inputError}` : ''}`}
                style={{ paddingLeft: '40px' }}
                type="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setEmailError(null); setSubmitError(null) }}
                placeholder="you@example.com"
                autoComplete="email"
                disabled={submitting}
              />
            </div>
            {emailError && <p className={styles.fieldError}>{emailError}</p>}
          </div>

          {/* Display Name */}
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>{t('auth.displayNameLabel')}</label>
            <div className={styles.inputWrapper}>
              <User size={16} className={styles.inputIcon} />
              <input
                className={`${styles.input}${displayNameError ? ` ${styles.inputError}` : ''}`}
                style={{ paddingLeft: '40px' }}
                type="text"
                value={displayName}
                onChange={(e) => { setDisplayName(e.target.value); setDisplayNameError(null); setSubmitError(null) }}
                placeholder={t('auth.displayNamePlaceholder')}
                autoComplete="name"
                disabled={submitting}
              />
            </div>
            {displayNameError && <p className={styles.fieldError}>{displayNameError}</p>}
          </div>

          {/* Password */}
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>{t('auth.passwordLabel')}</label>
            <div className={styles.inputWrapper}>
              <Lock size={16} className={styles.inputIcon} />
              <input
                className={`${styles.input}${passwordError ? ` ${styles.inputError}` : ''}`}
                style={{ paddingLeft: '40px' }}
                type="password"
                value={password}
                onChange={(e) => { setPassword(e.target.value); setPasswordError(null); setSubmitError(null) }}
                placeholder="••••••••"
                autoComplete="new-password"
                disabled={submitting}
                minLength={8}
              />
            </div>
            {passwordError ? <p className={styles.fieldError}>{passwordError}</p>
             : <p className={styles.fieldHint}>{t('auth.passwordHint')}</p>}
          </div>

          {submitError && (
            <div className={styles.error}>
              <AlertCircle size={16} className={styles.errorIcon} />
              <span>{submitError}</span>
            </div>
          )}

          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !email.trim() || !password || !displayName.trim()}
          >
            {submitting && <span className={styles.spinner} />}
            {submitting ? t('auth.registering') : t('auth.registerButton')}
          </button>
        </form>

        <div className={styles.footerLink}>
          <Link to="/login">{t('auth.haveAccount')}</Link>
        </div>
      </div>

      <p className={styles.copyright}>{t('brand.copyright')}</p>
    </div>
  )
}

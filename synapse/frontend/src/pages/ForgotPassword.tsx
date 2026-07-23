/**
 * ForgotPassword page — request a password reset link.
 *
 * B42: 品牌区重构 · 字段标签化 · 成功态 Mail 图标 · 错误图标化 · 按钮 spinner
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { forgotPassword } from '../api/client'
import { Zap, Mail, AlertCircle } from 'lucide-react'
import { getEmailError, mapAuthError } from '../utils/authHelpers'
import styles from './Auth.module.css'

export default function ForgotPassword() {
  const { isAuthenticated, isLoading } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [emailError, setEmailError] = useState<string | null>(null)

  useEffect(() => {
    if (isAuthenticated && !isLoading) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return

    // Client-side validation
    const emailErr = getEmailError(email, t)
    setEmailError(emailErr)
    if (emailErr) return

    setSubmitting(true)
    setSubmitError(null)
    setSubmitted(false)
    try {
      await forgotPassword(email)
      setSubmitted(true)
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

  // Success — email sent
  if (!submitting && !submitError && submitted) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.brand}>
            <div className={styles.brandIcon}><Zap size={20} /></div>
            <div className={styles.brandName}>Synapse</div>
          </div>

          <h1 className={styles.title}>{t('auth.forgotPasswordTitle')}</h1>

          <div className={styles.statusSuccess}>
            <Mail size={32} className={styles.statusSuccessIcon} />
            <span>{t('auth.forgotPasswordCheckEmail')}</span>
          </div>

          <div className={styles.footerLink}>
            <Link to="/login">{t('auth.backToLogin')}</Link>
          </div>
        </div>

        <p className={styles.copyright}>{t('brand.copyright')}</p>
      </div>
    )
  }

  return (
    <div className={styles.shell}>
      <div className={styles.card}>

        {/* ── Brand ──────────────────────────────────────────── */}
        <div className={styles.brand}>
          <div className={styles.brandIcon}><Zap size={18} /></div>
          <div className={styles.brandName}>Synapse</div>
        </div>

        <h1 className={styles.title}>{t('auth.forgotPasswordTitle')}</h1>
        <p className={styles.subtitle}>{t('auth.forgotPasswordSubtitle')}</p>

        <form className={styles.emailForm} onSubmit={handleSubmit}>
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

          {submitError && (
            <div className={styles.error}>
              <AlertCircle size={16} className={styles.errorIcon} />
              <span>{submitError}</span>
            </div>
          )}

          <button
            type="submit"
            className={styles.submitBtn}
            disabled={submitting || !email.trim()}
          >
            {submitting && <span className={styles.spinner} />}
            {submitting ? t('auth.forgotPasswordSending') : t('auth.forgotPasswordButton')}
          </button>
        </form>

        <div className={styles.footerLink}>
          <Link to="/login">{t('auth.backToLogin')}</Link>
        </div>
      </div>

      <p className={styles.copyright}>{t('brand.copyright')}</p>
    </div>
  )
}

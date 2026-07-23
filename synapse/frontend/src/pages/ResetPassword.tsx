/**
 * ResetPassword page — complete password reset with token + new password.
 *
 * B42: 品牌区重构 · 字段标签化 · token 字段 URL 传入时自动隐藏 · 成功态 CheckCircle 图标 · 错误图标化 · 按钮 spinner
 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { resetPassword } from '../api/client'
import { Zap, CheckCircle, AlertCircle, Key, Lock } from 'lucide-react'
import styles from './Auth.module.css'

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

  // Hide token field when URL already provides it
  const hasTokenFromUrl = tokenFromUrl.length > 0

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

  // Success
  if (success) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.brand}>
            <div className={styles.brandIcon}><Zap size={20} /></div>
            <div className={styles.brandName}>Synapse</div>
          </div>

          <h1 className={styles.title}>{t('auth.resetPasswordTitle')}</h1>

          <div className={styles.statusSuccess}>
            <CheckCircle size={32} className={styles.statusSuccessIcon} />
            <span>{t('auth.resetPasswordSuccess')}</span>
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

        <h1 className={styles.title}>{t('auth.resetPasswordTitle')}</h1>
        <p className={styles.subtitle}>{t('auth.resetPasswordSubtitle')}</p>

        <form className={styles.emailForm} onSubmit={handleSubmit}>
          {/* Token — hidden when URL provides it */}
          {!hasTokenFromUrl && (
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>{t('auth.resetPasswordTokenLabel')}</label>
              <div className={styles.inputWrapper}>
                <Key size={16} className={styles.inputIcon} />
                <input
                  className={styles.input}
                  style={{ paddingLeft: '40px' }}
                  type="text"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder={t('auth.resetPasswordTokenLabel')}
                  autoComplete="off"
                  disabled={submitting}
                />
              </div>
            </div>
          )}

          {/* New Password */}
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel}>{t('auth.resetPasswordNewPasswordLabel')}</label>
            <div className={styles.inputWrapper}>
              <Lock size={16} className={styles.inputIcon} />
              <input
                className={styles.input}
                style={{ paddingLeft: '40px' }}
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="new-password"
                disabled={submitting}
                minLength={8}
              />
            </div>
            <p className={styles.fieldHint}>{t('auth.passwordHint')}</p>
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
            disabled={submitting || !token || !newPassword}
          >
            {submitting && <span className={styles.spinner} />}
            {submitting ? t('auth.resetPasswordResetting') : t('auth.resetPasswordButton')}
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

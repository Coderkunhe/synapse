/**
 * OAuth callback handler.
 *
 * P100-B58: Backend now sets access_token as httpOnly cookie + redirects here
 * with NO URL params. This page calls /v1/auth/me to verify the cookie-based
 * session, then redirects to /dashboard.
 */

import { useEffect, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useI18n } from '../contexts/I18nContext'
import { fetchAuthMe } from '../api/client'
import styles from './OAuthCallback.module.css'
import { AlertTriangle, CheckCircle } from 'lucide-react'

export default function OAuthCallback() {
  const navigate = useNavigate()
  const { t } = useI18n()
  const processedRef = useRef(false)
  const [error, setError] = useState(false)
  const [displayName, setDisplayName] = useState('')

  useEffect(() => {
    if (processedRef.current) return
    processedRef.current = true

    // Verify the cookie-based session (backend set httpOnly cookie on redirect)
    fetchAuthMe()
      .then(res => {
        setDisplayName(res.display_name || '')
        const timer = setTimeout(() => {
          navigate('/dashboard', { replace: true })
        }, 800)
        return () => clearTimeout(timer)
      })
      .catch(() => {
        setError(true)
      })
  }, [navigate])

  if (error) {
    return (
      <div className={styles.shell}>
        <div className={styles.card}>
          <div className={styles.icon}><AlertTriangle size={48} /></div>
          <h1 className={styles.title}>{t('auth.loginFailed')}</h1>
          <p className={styles.message}>{t('auth.oauthMissingParams')}</p>
          <Link to="/login" className={styles.backLink}>
            {t('auth.backToLogin')}
          </Link>
        </div>
      </div>
    )
  }

  // Success — show welcome, then redirect
  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.icon}><CheckCircle size={48} /></div>
        <h1 className={styles.title}>{t('auth.loginSuccessful')}</h1>
        <p className={styles.message}>{t('auth.welcomeRedirect', { name: displayName })}</p>
      </div>
    </div>
  )
}

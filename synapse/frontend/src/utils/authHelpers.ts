/**
 * Auth form helpers — client-side validation + server error mapping.
 *
 * B43: Shared across Login / Register / ForgotPassword / ResetPassword
 * to avoid duplicating validation logic and error message mapping.
 */

import { ApiError } from '../api/client'

type TFunc = (key: string) => string

// ── Email validation ──────────────────────────────────────────────────────────

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function isValidEmail(email: string): boolean {
  return EMAIL_RE.test(email.trim())
}

export function getEmailError(email: string, t: TFunc): string | null {
  if (!email.trim()) return t('auth.errorInvalidEmail')
  if (!isValidEmail(email)) return t('auth.errorInvalidEmail')
  return null
}

// ── Password validation ───────────────────────────────────────────────────────

export function getPasswordError(password: string, t: TFunc): string | null {
  if (!password) return t('auth.errorPasswordTooShort')
  if (password.length < 8) return t('auth.errorPasswordTooShort')
  return null
}

// ── Display name validation ───────────────────────────────────────────────────

export function getDisplayNameError(name: string, t: TFunc): string | null {
  if (!name.trim()) return t('auth.errorDisplayNameRequired')
  return null
}

// ── Server / network error mapping ────────────────────────────────────────────

const CODE_MAP: Record<string, string> = {
  INVALID_CREDENTIALS: 'auth.errorInvalidCredentials',
  EMAIL_ALREADY_EXISTS: 'auth.errorEmailAlreadyExists',
  WEAK_PASSWORD: 'auth.errorWeakPassword',
  INVALID_EMAIL: 'auth.errorInvalidEmail',
  RESET_TOKEN_EXPIRED: 'auth.errorResetTokenExpired',
  RESET_TOKEN_ALREADY_USED: 'auth.errorResetTokenUsed',
  INVALID_RESET_TOKEN: 'auth.errorInvalidResetToken',
}

/**
 * Map any caught error to a user-facing message.
 *
 * Handles:
 * - ApiError with known server code → translated message
 * - ApiError with 429 → rate limit message
 * - ApiError unknown → server's own message or fallback
 * - TypeError (network failure) → connection error
 * - Everything else → generic fallback
 */
export function mapAuthError(err: unknown, t: TFunc): string {
  if (err instanceof ApiError) {
    // Rate limit
    if (err.status === 429) return t('auth.errorRateLimit')

    // Known server error code
    if (err.code && CODE_MAP[err.code]) return t(CODE_MAP[err.code])

    // Unknown ApiError — use server message if available
    return err.message || t('auth.errorDefault')
  }

  // Network failure (fetch throws TypeError)
  if (err instanceof TypeError) {
    return t('auth.errorNetwork')
  }

  // Fallback
  return t('auth.errorDefault')
}

/**
 * I18nContext — language switching context (no third-party library).
 *
 * Provides:
 *   - `t(key)`  — dotted-key translation lookup (e.g. t('nav.dashboard'))
 *   - `lang`    — current language ('en' | 'zh')
 *   - `setLang` — switch language, persisted to localStorage
 *
 * Wrap the app in <I18nProvider> to enable translations.
 *
 * B38: infrastructure only — pages consume this starting in B39.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { lookup, type Lang } from '../i18n/translations'

const LANG_STORAGE_KEY = 'synapse_lang'

function readStoredLang(): Lang {
  const stored = localStorage.getItem(LANG_STORAGE_KEY)
  return stored === 'zh' ? 'zh' : 'en'
}

// ── Context type ────────────────────────────────────────────────────────────

interface I18nContextValue {
  /** Current language. */
  lang: Lang
  /** Switch language (persisted to localStorage). */
  setLang: (lang: Lang) => void
  /** Translate a dotted-path key → localized string, with optional variable interpolation. */
  t: (key: string, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

// ── Provider ────────────────────────────────────────────────────────────────

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStoredLang)

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    localStorage.setItem(LANG_STORAGE_KEY, next)
  }, [])

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>): string => {
      const template = lookup(lang, key)
      if (!vars) return template
      return template.replace(/\{(\w+)\}/g, (_, name) => String(vars[name] ?? `{${name}}`))
    },
    [lang],
  )

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLang, t }),
    [lang, setLang, t],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) {
    throw new Error('useI18n must be used within an <I18nProvider>')
  }
  return ctx
}

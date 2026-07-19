/**
 * Shared formatting utilities.
 *
 * Every page had its own copy of these — now they live here.
 * Pages import from this module instead of redefining.
 */

import type { Lang } from '../i18n/translations'

/** Format an ISO date string to locale string using the active language. */
export function formatDate(iso: string, lang?: Lang): string {
  const locale = lang === 'zh' ? 'zh-CN' : 'en-US'
  return new Date(iso).toLocaleString(locale)
}

/** Truncate a string to max length, appending ellipsis if needed. */
export function truncate(str: string, max: number): string {
  return str.length > max ? str.slice(0, max) + '…' : str
}

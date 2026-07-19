/**
 * ConfirmModal — reusable portal-based confirmation dialog.
 *
 * Renders to document.body via createPortal. Supports danger/warning/primary
 * variants, ESC/backdrop dismiss, and loading state on confirm button.
 */

import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Loader } from 'lucide-react'
import { useI18n } from '../contexts/I18nContext'
import styles from './ConfirmModal.module.css'

export interface ConfirmModalProps {
  isOpen: boolean
  title: string
  message: string
  confirmLabel: string
  /** Visual variant: 'danger' (red), 'warning' (amber), 'primary' (blue). */
  confirmVariant?: 'danger' | 'warning' | 'primary'
  /** When true, confirm button shows spinner and is disabled. */
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmLabel,
  confirmVariant = 'primary',
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const { t } = useI18n()
  const overlayRef = useRef<HTMLDivElement>(null)

  // Lock body scroll while modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.body.style.overflow = ''
    }
  }, [isOpen])

  // Auto-focus overlay so React onKeyDown captures Escape without document.addEventListener
  useEffect(() => {
    if (isOpen && overlayRef.current) {
      overlayRef.current.focus()
    }
  }, [isOpen])

  // React synthetic onKeyDown — no document.addEventListener needed
  const handleOverlayKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape' && !loading) {
      onCancel()
    }
  }

  if (!isOpen) return null

  const variantClass =
    confirmVariant === 'danger'
      ? styles.confirmDanger
      : confirmVariant === 'warning'
        ? styles.confirmWarning
        : styles.confirmPrimary

  return createPortal(
    <div
      className={styles.overlay}
      onClick={loading ? undefined : onCancel}
      onKeyDown={handleOverlayKeyDown}
      tabIndex={-1}
      ref={overlayRef}
    >
      <div
        className={styles.card}
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
      >
        <div className={styles.iconRow}>
          <AlertTriangle size={24} className={styles.icon} />
        </div>
        <h3 id="confirm-modal-title" className={styles.title}>
          {title}
        </h3>
        <p className={styles.message}>{message}</p>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.cancelBtn}
            onClick={onCancel}
            disabled={loading}
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            className={`${styles.confirmBtn} ${variantClass}`}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading && <Loader size={14} className={styles.spinner} />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

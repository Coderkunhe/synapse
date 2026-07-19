/**
 * WebSocket connection status indicator.
 *
 * Shows a small colored dot with connection state. Green = connected,
 * Yellow = connecting, Red = disconnected.
 */

import { useI18n } from '../contexts/I18nContext'
import type { WSStatus as WSStatusType } from '../api/ws'
import styles from './WSStatus.module.css'

interface WSStatusProps {
  status: WSStatusType
}

export default function WSStatus({ status }: WSStatusProps) {
  const { t } = useI18n()
  const label = t(`ws.${status}`)

  return (
    <span className={styles.container} title={`WebSocket: ${label}`}>
      <span className={`${styles.dot} ${styles[status]}`} />
      <span className={styles.label}>{label}</span>
    </span>
  )
}

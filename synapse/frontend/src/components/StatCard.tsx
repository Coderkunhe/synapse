import type { LucideIcon } from 'lucide-react'
import styles from './StatCard.module.css'

interface StatCardProps {
  label: string
  value: number | string
  icon: LucideIcon
  accent?: 'primary' | 'success' | 'warning' | 'info'
}

export default function StatCard({ label, value, icon: Icon, accent = 'primary' }: StatCardProps) {
  return (
    <div className={`${styles.card} ${styles[accent]}`}>
      <span className={styles.icon}><Icon size={24} strokeWidth={1.5} /></span>
      <div className={styles.body}>
        <span className={styles.value}>{value}</span>
        <span className={styles.label}>{label}</span>
      </div>
    </div>
  )
}

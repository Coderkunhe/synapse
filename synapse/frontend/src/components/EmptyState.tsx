/**
 * EmptyState — shared empty/placeholder component.
 *
 * Every page had its own copy of the empty-state JSX + CSS.
 * Extract once, use everywhere.
 */

import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import styles from './EmptyState.module.css'

export interface EmptyStateProps {
  /** Lucide icon component displayed large above the title. */
  icon: LucideIcon
  /** Heading text, e.g. "No Agents", "Connect to Synapse". */
  title: string
  /** Optional supporting paragraph below the title. */
  description?: string
  /** Optional extra content (hints, code blocks, action buttons). */
  children?: ReactNode
}

export default function EmptyState({ icon: Icon, title, description, children }: EmptyStateProps) {
  return (
    <div className={styles.empty}>
      <div className={styles.icon}><Icon size={48} strokeWidth={1.5} /></div>
      <h2 className={styles.title}>{title}</h2>
      {description && <p className={styles.description}>{description}</p>}
      {children}
    </div>
  )
}

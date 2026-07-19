/**
 * PageHeader — shared page title bar.
 *
 * Every page had <div className={styles.topBar}><h1 className={styles.heading}>X</h1></div>.
 * Extract once, support optional action slot via children.
 */

import type { ReactNode } from 'react'
import styles from './PageHeader.module.css'

export interface PageHeaderProps {
  /** Page title displayed as the main heading. */
  title: string
  /** Optional subtitle rendered below the title. */
  subtitle?: string
  /** Optional actions rendered on the right side of the bar. */
  children?: ReactNode
}

export default function PageHeader({ title, subtitle, children }: PageHeaderProps) {
  return (
    <div className={styles.topBar}>
      <div>
        <h1 className={styles.heading}>{title}</h1>
        {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
      </div>
      {children && <div className={styles.actions}>{children}</div>}
    </div>
  )
}

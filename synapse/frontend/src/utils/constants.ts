/**
 * Shared constants — status icons, filter helpers, labels.
 *
 * B43: Emoji icons → Lucide React flat icons (Elevated Flat).
 * Each map pairs a status/type key with a LucideIcon component.
 * Colors are controlled via STATUS_COLORS, not hardcoded in the icon.
 */

import type { LucideIcon } from 'lucide-react'
import {
  Circle,
  CheckCircle,
  XCircle,
  AlertTriangle,
  ClipboardList,
  Package,
  MessageSquare,
  Palette,
} from 'lucide-react'

/** Entity-status → Lucide icon component. */
export const STATUS_ICONS: Record<string, LucideIcon> = {
  open: Circle,
  locked: Circle,
  closed: Circle,
  active: Circle,
  archived: Circle,
  deprecated: Circle,
  pass: CheckCircle,
  fail: XCircle,
  warn: AlertTriangle,
}

/** Entity-status → CSS color (links to design tokens). */
export const STATUS_COLORS: Record<string, string> = {
  open: 'var(--gm-primary)',
  locked: 'var(--gm-warning)',
  closed: 'var(--gm-success)',
  active: 'var(--gm-success)',
  archived: 'var(--gm-text-secondary)',
  deprecated: 'var(--gm-text-secondary)',
  pass: 'var(--gm-success)',
  fail: 'var(--gm-danger)',
  warn: 'var(--gm-warning)',
}

/** Target-type → Lucide icon component (Scans page). */
export const TARGET_ICONS: Record<string, LucideIcon> = {
  task: ClipboardList,
  batch: Package,
}

/** Analysis-type → Lucide icon component (Analyses page). */
export const TYPE_ICONS: Record<string, LucideIcon> = {
  requirement: ClipboardList,
  discussion: MessageSquare,
  design: Palette,
}

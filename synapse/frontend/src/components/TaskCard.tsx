import { useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import { hashBatchColor } from '../utils/color'
import type { TaskSummary } from '../api/client'
import styles from './TaskCard.module.css'

interface TaskCardProps {
  task: TaskSummary
  selectable?: boolean
  selected?: boolean
  onSelect?: (id: string) => void
  batchNames?: Map<string, string>
  workerNames?: Map<string, string>
  hoveredBatchId?: string | null
  onBatchHover?: (id: string | null) => void
  currentWorkerId?: string
  onPromote?: (taskId: string, version: number) => void
  onClaim?: (taskId: string, version: number) => void
}

const PRIORITY_KEYS: Record<string, string> = {
  p0: 'taskCard.priorityP0',
  p1: 'taskCard.priorityP1',
  p2: 'taskCard.priorityP2',
  p3: 'taskCard.priorityP3',
}

export default function TaskCard({ task, selectable, selected, onSelect, batchNames, hoveredBatchId, onBatchHover, currentWorkerId, onPromote, onClaim, workerNames }: TaskCardProps) {
  const { t, lang } = useI18n()
  const navigate = useNavigate()

  const batchName = task.batch_id ? batchNames?.get(task.batch_id) : undefined
  const batchColor = task.batch_id ? hashBatchColor(task.batch_id) : undefined
  const isHighlighted = !!(hoveredBatchId && task.batch_id && hoveredBatchId === task.batch_id)
  const isUnclaimed = task.status === 'ready' && !task.owner_id
  const isMine = !!(currentWorkerId && task.owner_id === currentWorkerId)

  const cardContent = (
    <>
      <div className={styles.header}>
        <span className={`${styles.priority} ${styles[task.priority] || ''}`}>
          {t(PRIORITY_KEYS[task.priority] || task.priority)}
        </span>
        {task.deadline_at && (
          <span className={`${styles.deadline} ${task.is_overdue ? styles.overdue : ''}`}>
            {task.is_overdue && <AlertTriangle size={11} style={{ marginRight: 3 }} />}
            {formatDate(task.deadline_at, lang)}
            {task.is_overdue && <span className={styles.overdueLabel}>{t('taskCard.overdue')}</span>}
          </span>
        )}
      </div>
      <p className={styles.title}>{task.title}</p>
      {(task.depends_on?.length || task.batch_id) && (
        <div className={styles.badges}>
          {task.depends_on?.length ? (
            <span className={styles.depBadge}>
              ↳{task.depends_on.length}
            </span>
          ) : null}
          {task.batch_id ? (
            <button
              type="button"
              className={`${styles.batchBadge} ${hoveredBatchId === task.batch_id ? styles.batchBadgeHovered : ''}`}
              style={{ '--badge-color': batchColor } as React.CSSProperties}
              title={`${batchName || task.batch_id} — ${t('taskCard.viewBatch')}`}
              onMouseEnter={() => onBatchHover?.(task.batch_id!)}
              onMouseLeave={() => onBatchHover?.(null)}
              onClick={(e) => {
                e.preventDefault()
                e.stopPropagation()
                navigate(`/batches/${task.batch_id}`)
              }}
            >
              {batchName || task.batch_id.slice(0, 12) + '…'}
            </button>
          ) : null}
        </div>
      )}
      <div className={styles.footer}>
        <span className={styles.owner}>
          {task.owner_type ? (workerNames?.get(task.owner_id ?? '') ?? `${task.owner_type}:${task.owner_id?.slice(0, 10)}`) : t('common.unowned')}
        </span>
        {/* ── Quick action buttons (P9-B37) ────────────────── */}
        {task.status === 'backlog' && onPromote && (
          <button
            type="button"
            className={`${styles.quickAction} ${styles.quickActionPromote}`}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onPromote(task.id, task.version_no)
            }}
          >
            {t('tasks.moveToReady')}
          </button>
        )}
        {isUnclaimed && onClaim && (
          <button
            type="button"
            className={`${styles.quickAction} ${styles.quickActionClaim}`}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              onClaim(task.id, task.version_no)
            }}
          >
            {t('tasks.claimNow')}
          </button>
        )}
        {task.status === 'in_progress' && isMine && (
          <button
            type="button"
            className={`${styles.quickAction} ${styles.quickActionSubmit}`}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              navigate(`/tasks/${task.id}`)
            }}
          >
            {t('tasks.submitQuick')}
          </button>
        )}
        {/* Legacy unclaimed badge — only when onClaim not provided */}
        {isUnclaimed && !onClaim && (
          <span className={styles.unclaimedBadge}>{t('tasks.unclaimedBadge')}</span>
        )}
      </div>
    </>
  )

  if (selectable) {
    return (
      <div
        className={`${styles.card} ${selected ? styles.selected : ''} ${isHighlighted ? styles.highlighted : ''} ${isUnclaimed ? styles.unclaimed : ''} ${isMine ? styles.mine : ''}`}
        style={batchColor ? { '--badge-color': batchColor } as React.CSSProperties : undefined}
      >
        <input
          type="checkbox"
          className={styles.selectCheckbox}
          checked={selected ?? false}
          onChange={() => onSelect?.(task.id)}
          onClick={e => e.stopPropagation()}
          aria-label={`Select ${task.title}`}
        />
        <div
          className={styles.cardLink}
          onClick={() => navigate(`/tasks/${task.id}`)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              navigate(`/tasks/${task.id}`)
            }
          }}
          role="link"
          tabIndex={0}
          aria-label={task.title}
        >
          {cardContent}
        </div>
      </div>
    )
  }

  return (
    <div
      className={`${styles.card} ${isHighlighted ? styles.highlighted : ''} ${isUnclaimed ? styles.unclaimed : ''} ${isMine ? styles.mine : ''}`}
      style={batchColor ? { '--badge-color': batchColor } as React.CSSProperties : undefined}
      onClick={() => navigate(`/tasks/${task.id}`)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          navigate(`/tasks/${task.id}`)
        }
      }}
      role="link"
      tabIndex={0}
      aria-label={task.title}
    >
      {cardContent}
    </div>
  )
}

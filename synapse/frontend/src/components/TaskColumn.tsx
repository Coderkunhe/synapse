import type { TaskSummary } from '../api/client'
import { useI18n } from '../contexts/I18nContext'
import TaskCard from './TaskCard'
import styles from './TaskColumn.module.css'

interface TaskColumnProps {
  label: string
  tasks: TaskSummary[]
  selectable?: boolean
  selectedIds?: Set<string>
  onSelect?: (id: string) => void
  batchNames?: Map<string, string>
  workerNames?: Map<string, string>
  hoveredBatchId?: string | null
  onBatchHover?: (id: string | null) => void
  currentWorkerId?: string
  onPromote?: (taskId: string, version: number) => void
  onClaim?: (taskId: string, version: number) => void
}

export default function TaskColumn({ label, tasks, selectable, selectedIds, onSelect, batchNames, workerNames, hoveredBatchId, onBatchHover, currentWorkerId, onPromote, onClaim }: TaskColumnProps) {
  const { t } = useI18n()
  return (
    <div className={styles.column}>
      <div className={styles.header}>
        <span className={styles.label}>{label}</span>
        <span className={styles.count}>{tasks.length}</span>
      </div>
      <div className={styles.cards}>
        {tasks.map(task => (
          <TaskCard
            key={task.id}
            task={task}
            selectable={selectable}
            selected={selectedIds?.has(task.id)}
            onSelect={onSelect}
            batchNames={batchNames}
            workerNames={workerNames}
            hoveredBatchId={hoveredBatchId}
            onBatchHover={onBatchHover}
            currentWorkerId={currentWorkerId}
            onPromote={onPromote}
            onClaim={onClaim}
          />
        ))}
        {tasks.length === 0 && <p className={styles.empty}>{t('tasks.columnEmpty')}</p>}
      </div>
    </div>
  )
}

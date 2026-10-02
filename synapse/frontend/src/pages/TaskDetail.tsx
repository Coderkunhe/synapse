import { useState, useEffect, useCallback, useMemo, useRef, Fragment } from 'react'
import { useParams, Link } from 'react-router-dom'
import { AlertTriangle, Search } from 'lucide-react'
import { fetchTask, fetchTaskEvents, fetchTaskMessages, createTaskMessage, resolveTaskMessage, claimTask, submitTask, updateTask, fetchVerifications, verifyVerification, fetchBatch, fetchWorker, fetchMyProjectRole, fetchWorkers } from '../api/client'
import type { TaskDetail as TaskDetailType, EventSummary, VerificationResponse, ConversationMessage, WorkerSummary } from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { useWebSocket } from '../api/ws'
import { formatDate } from '../utils/format'
import { hashBatchColor } from '../utils/color'
import EmptyState from '../components/EmptyState'
import BatchSelect from '../components/BatchSelect'
import DependencyGraph from '../components/DependencyGraph'
import styles from './TaskDetail.module.css'

const PRIORITIES = ['p0', 'p1', 'p2', 'p3']
const EFFORTS = ['xs', 's', 'm', 'l', 'xl']
// 模块级常量 — useWebSocket 用 topics.join(',') 做 stableTopics，内联字面量会触发重连循环
const MESSAGE_EVENT_TYPES = ['conversation.message.created', 'conversation.message.resolved']

// 与后端 _MENTION_RE = r"@(worker|role):(\S+)"（conversation_service.py:38）一致，保证高亮范围 = 后端实际解析范围
const MENTION_RE = /@(worker|role):(\S+)/g

// 把正文里的 @worker:<name> / @role:<rolename> token 渲染成高亮 span。
// 用 React 分段渲染（非 dangerouslySetInnerHTML）→ body 是用户/agent 输入，天然 XSS 安全。
// P17-B16：命中 worker 的 @worker:<name> 渲染成 <Link> 跳 worker detail；@role 或未命中（含尾随标点）保持 span。
function renderMentionedBody(body: string, workerByName: Map<string, string>): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let last = 0
  let key = 0
  for (const m of body.matchAll(MENTION_RE)) {
    const i = m.index ?? 0
    if (i > last) parts.push(body.slice(last, i))
    const kind = m[1]
    const name = m[2]
    const workerId = kind === 'worker' ? workerByName.get(name) : undefined
    if (workerId) {
      parts.push(
        <Link
          key={key++}
          to={`/workers/${workerId}`}
          className={`${styles.mentionHighlight} ${styles.mentionLink}`}
          data-testid="mention-highlight"
        >
          {m[0]}
        </Link>,
      )
    } else {
      parts.push(
        <span key={key++} className={styles.mentionHighlight} data-testid="mention-highlight">
          {m[0]}
        </span>,
      )
    }
    last = i + m[0].length
  }
  if (last < body.length) parts.push(body.slice(last))
  return parts
}

export default function TaskDetail() {
  const { taskId } = useParams<{ taskId: string }>()
  const { t, lang } = useI18n()
  const [task, setTask] = useState<TaskDetailType | null>(null)
  const [events, setEvents] = useState<EventSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionError, setActionError] = useState<string | null>(null)
  const [summary, setSummary] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // ── Output access evidence (PFL-270) ─────────────────
  const [outputAccessType, setOutputAccessType] = useState('inline')
  const [outputAccessValue, setOutputAccessValue] = useState('')

  // ── Verification state ─────────────────────────────────
  const [verifications, setVerifications] = useState<VerificationResponse[]>([])
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const [rejectingId, setRejectingId] = useState<string | null>(null)
  const [rejectionReason, setRejectionReason] = useState('')
  const [verifying, setVerifying] = useState(false)

  // ── Batch name fetch ────────────────────────────────────
  const [batchName, setBatchName] = useState<string | null>(null)

  // ── Worker name fetch ────────────────────────────────────
  const [ownerName, setOwnerName] = useState<string | null>(null)

  // ── Collaboration messages (S-020 · P17-B8) ─────────────
  const [messages, setMessages] = useState<ConversationMessage[]>([])
  const [messageType, setMessageType] = useState('clarification')
  const [messageBody, setMessageBody] = useState('')
  const [sendingMessage, setSendingMessage] = useState(false)
  const [resolvingMessageId, setResolvingMessageId] = useState<string | null>(null)
  const [replyToId, setReplyToId] = useState<string | null>(null)
  const [messageError, setMessageError] = useState<string | null>(null)

  // ── @mention 补全 (P17-B14) ─────────────────────────────
  const [mentionCandidates, setMentionCandidates] = useState<WorkerSummary[]>([])
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)
  const messageInputRef = useRef<HTMLTextAreaElement>(null)

  // 反查父消息（threading：reply 标识展示父 sender）
  const messagesById = useMemo(() => new Map(messages.map(m => [m.id, m])), [messages])

  // 按当前 @ 前缀过滤候选（case-insensitive contains，与后端 resolve_mentions 的 %name% 语义一致）
  const filteredMentions = useMemo(() => {
    const q = mentionQuery.toLowerCase()
    return mentionCandidates.filter(w => w.name.toLowerCase().includes(q))
  }, [mentionCandidates, mentionQuery])

  // name → worker id 映射（P17-B16：@mention 点击跳 worker detail）
  const workerByName = useMemo(
    () => new Map(mentionCandidates.map(w => [w.name, w.id])),
    [mentionCandidates],
  )

  // ── Edit state ─────────────────────────────────────────
  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editPriority, setEditPriority] = useState('p2')
  const [editEffort, setEditEffort] = useState('')
  const [editTags, setEditTags] = useState('')
  const [editDeadline, setEditDeadline] = useState('')
  const [editBatchId, setEditBatchId] = useState('')
  const [editDependsOn, setEditDependsOn] = useState<Array<{ task_id: string; type: string }>>([])
  const [editDepInput, setEditDepInput] = useState('')
  const [editDepType, setEditDepType] = useState('sequential')
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)
  const [dismissedGuidance, setDismissedGuidance] = useState(false)

  const { token, role, teamId, logout } = useAuth()

  // 拉取团队 worker 作为 @mention 候选（仅 active 且未禁用）
  useEffect(() => {
    if (!teamId || !token) return
    fetchWorkers(teamId, token, { status: 'active' })
      .then(r => setMentionCandidates(r.items.filter(w => !w.is_disabled)))
      .catch(() => { /* 非关键：mention 补全失败不阻断消息 */ })
  }, [teamId, token])

  // P12-B18: project-level role for permission checks (not team-level role from AuthContext)
  const [projectRole, setProjectRole] = useState<string | null>(null)

  const STATUS_LABELS: Record<string, string> = {
    backlog: t('tasks.columns.backlog'),
    ready: t('tasks.columns.ready'),
    in_progress: t('tasks.columns.inProgress'),
    in_verification: t('tasks.columns.inVerification'),
    completed: t('tasks.columns.completed'),
    cancelled: t('tasks.columns.cancelled'),
    rejected: t('tasks.columns.rejected') || 'Rejected',
  }

  const PRIORITY_LABELS: Record<string, string> = {
    p0: t('taskDetail.priorityP0'),
    p1: t('taskDetail.priorityP1'),
    p2: t('taskDetail.priorityP2'),
    p3: t('taskDetail.priorityP3'),
  }

  const STATUS_CLASS: Record<string, string> = {
    backlog: 'stBacklog',
    ready: 'stReady',
    in_progress: 'stInProgress',
    in_verification: 'stVerify',
    completed: 'stCompleted',
    cancelled: 'stCancelled',
    rejected: 'stRejected',
  }

  const MESSAGE_TYPE_LABELS: Record<string, string> = {
    clarification: t('taskDetail.msgType.clarification'),
    blocking: t('taskDetail.msgType.blocking'),
    review_request: t('taskDetail.msgType.review_request'),
    proposal: t('taskDetail.msgType.proposal'),
  }

  useEffect(() => {
    if (!token || !taskId) {
      setError(t('taskDetail.missingAuth'))
      setLoading(false)
      return
    }
    Promise.all([
      fetchTask(taskId, token),
      fetchTaskEvents(taskId, token),
    ])
      .then(([tk, e]) => {
        setTask(tk)
        setEvents(e.items)
        setLoading(false)
        // Fetch verifications if task is in verification
        if (tk.status === 'in_verification') {
          fetchVerifications(taskId, token)
            .then(v => setVerifications(v))
            .catch((err) => { console.error('Failed to fetch verifications', err) /* Non-critical: verification list enrichment */ })
        }
        // Fetch batch name if task has batch_id
        if (tk.batch_id) {
          fetchBatch(tk.batch_id, token)
            .then(b => setBatchName(b.name))
            .catch((err) => { console.error('Failed to fetch batch name', err) /* Non-critical: batch name enrichment */ })
        }
        // Fetch worker name if owner is a worker
        if (tk.owner_type === 'worker' && tk.owner_id) {
          fetchWorker(tk.owner_id, token)
            .then(w => setOwnerName(w.name))
            .catch((err) => { console.error('Failed to fetch worker name', err) /* Non-critical: worker name enrichment */ })
        }
        // P12-B18: fetch current actor's project role for permission checks
        if (tk.project_id) {
          fetchMyProjectRole(tk.project_id, token)
            .then(r => setProjectRole(r.role))
            .catch((err) => { console.error('Failed to fetch project role', err) /* Non-critical: degrades to team role */ })
        }
      })
      .catch(err => { setError(err.message); setLoading(false) })
  }, [taskId, token, t])

  // ── Collaboration messages (S-020 · P17-B8) ─────────────
  const { lastEvent } = useWebSocket(token, MESSAGE_EVENT_TYPES, logout)

  const loadMessages = useCallback(() => {
    if (!task?.project_id || !taskId || !token) return
    fetchTaskMessages(task.project_id, taskId, token)
      .then(r => setMessages(r.messages))
      .catch((err) => { console.error('Failed to fetch messages', err) /* Non-critical: message list */ })
  }, [task?.project_id, taskId, token])

  // 初始拉取
  useEffect(() => { loadMessages() }, [loadMessages])

  // WS 事件触发刷新（新消息到达 / 消息被解决 → refetch 线程）
  useEffect(() => {
    if (
      lastEvent &&
      (lastEvent.event_type === 'conversation.message.created' ||
        lastEvent.event_type === 'conversation.message.resolved') &&
      lastEvent.payload.task_id === taskId
    ) {
      loadMessages()
    }
  }, [lastEvent, taskId, loadMessages])

  const handleSendMessage = async () => {
    if (!task?.project_id || !taskId || !token) return
    if (!messageBody.trim()) return
    setMessageError(null)
    setSendingMessage(true)
    try {
      await createTaskMessage(task.project_id, taskId, {
        task_id: taskId,
        message_type: messageType,
        body: messageBody.trim(),
        in_reply_to_id: replyToId ?? undefined,
      }, token)
      setMessageBody('')
      setReplyToId(null)
      setMentionOpen(false)
      loadMessages()
    } catch {
      setMessageError(t('taskDetail.failedToSendMessage'))
    } finally {
      setSendingMessage(false)
    }
  }

  const handleToggleResolve = async (msg: ConversationMessage) => {
    if (!task?.project_id || !taskId || !token) return
    setMessageError(null)
    setResolvingMessageId(msg.id)
    try {
      await resolveTaskMessage(task.project_id, taskId, msg.id, !msg.is_resolved, token)
      loadMessages()
    } catch {
      setMessageError(t('taskDetail.failedToResolveMessage'))
    } finally {
      setResolvingMessageId(null)
    }
  }

  const handleReply = (msg: ConversationMessage) => {
    setReplyToId(msg.id)
  }

  const handleCancelReply = () => {
    setReplyToId(null)
  }

  // ── @mention 补全 (P17-B14) ─────────────────────────────

  // 光标前最近的 @ 触发点：@ 必须位于句首或空白之后，且 @ 与光标之间为纯 name 片段
  const activeMentionTrigger = (value: string, cursor: number): number => {
    const before = value.slice(0, cursor)
    const lastAt = before.lastIndexOf('@')
    if (lastAt === -1) return -1
    const charBefore = lastAt > 0 ? before[lastAt - 1] : ' '
    if (!/\s/.test(charBefore)) return -1
    const query = before.slice(lastAt + 1)
    // 已成形 mention（含 ':') 或含空白 → 不触发
    if (!/^[A-Za-z0-9._-]*$/.test(query)) return -1
    return lastAt
  }

  const handleMessageChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    setMessageBody(value)
    const cursor = e.target.selectionStart ?? value.length
    const trigger = activeMentionTrigger(value, cursor)
    if (trigger === -1) {
      setMentionOpen(false)
      return
    }
    setMentionQuery(value.slice(trigger + 1, cursor))
    setMentionIndex(0)
    setMentionOpen(true)
  }

  const insertMention = (name: string) => {
    const el = messageInputRef.current
    const cursor = el?.selectionStart ?? messageBody.length
    const trigger = activeMentionTrigger(messageBody, cursor)
    if (trigger === -1) return
    const insert = `@worker:${name} `
    const newBody = messageBody.slice(0, trigger) + insert + messageBody.slice(cursor)
    const newCursor = trigger + insert.length
    setMessageBody(newBody)
    setMentionOpen(false)
    requestAnimationFrame(() => {
      if (el) {
        el.focus()
        el.setSelectionRange(newCursor, newCursor)
      }
    })
  }

  const handleMentionKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (!mentionOpen || filteredMentions.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setMentionIndex(i => (i + 1) % filteredMentions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setMentionIndex(i => (i - 1 + filteredMentions.length) % filteredMentions.length)
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      insertMention(filteredMentions[mentionIndex]?.name ?? filteredMentions[0].name)
    } else if (e.key === 'Escape') {
      setMentionOpen(false)
    }
  }

  const handleClaim = async () => {
    if (!taskId || !token || !task) return
    setActionError(null)
    try {
      const updated = await claimTask(taskId, task.version_no, token)
      setTask(updated)
    } catch {
      setActionError(t('taskDetail.failedToClaim'))
    }
  }

  const handleSubmit = async () => {
    if (!taskId || !token || !task) return
    if (!summary.trim()) {
      setActionError(t('taskDetail.enterSummary'))
      return
    }
    setActionError(null)
    setSubmitting(true)
    try {
      const updated = await submitTask(
        taskId,
        {
          summary: summary.trim(),
          evidence: {
            output_access: {
              type: outputAccessType,
              value: outputAccessValue.trim() || summary.trim(),
            },
          },
          expected_version: task.version_no,
        },
        token,
      )
      setTask(updated)
      setSummary('')
    } catch {
      setActionError(t('taskDetail.failedToSubmit'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleVerify = async (verificationId: string, status: 'passed' | 'failed') => {
    if (!taskId || !token || !task) return
    setVerifyError(null)
    setVerifying(true)
    try {
      await verifyVerification(
        verificationId,
        {
          status,
          rejection_reason: status === 'failed' ? rejectionReason.trim() || undefined : undefined,
          expected_task_version: task.version_no,
        },
        token,
      )
      setRejectingId(null)
      setRejectionReason('')
      // Refresh task and verifications
      const [updatedTask, updatedVers] = await Promise.all([
        fetchTask(taskId, token),
        fetchVerifications(taskId, token),
      ])
      setTask(updatedTask)
      setVerifications(updatedVers)
    } catch {
      setVerifyError(t('taskDetail.failedToVerify'))
    } finally {
      setVerifying(false)
    }
  }

  // ── Edit handlers ──────────────────────────────────────
  // P12-B18: use project-level role for permission checks, fall back to team role
  const effectiveRole = projectRole ?? role
  const canEdit = effectiveRole === 'admin' || effectiveRole === 'lead' || effectiveRole === 'orchestrator'

  const handleStartEdit = () => {
    if (!task) return
    setEditTitle(task.title)
    setEditDescription(task.description || '')
    setEditPriority(task.priority)
    setEditEffort(task.estimated_effort || '')
    setEditTags(task.tags?.join(', ') || '')
    setEditDeadline(task.deadline_at ? task.deadline_at.slice(0, 16) : '')
    setEditBatchId(task.batch_id || '')
    setEditDependsOn(task.depends_on?.map(d => ({ task_id: d.task_id, type: d.type || 'sequential' })) || [])
    setEditDepInput('')
    setEditDepType('sequential')
    setEditError(null)
    setEditing(true)
  }

  const handleCancelEdit = () => {
    setEditing(false)
    setEditError(null)
  }

  const handleSave = async () => {
    if (!taskId || !token || !task) return
    // S-057: validate description before API call to avoid DESCRIPTION_REQUIRED server error
    if (!editDescription.trim()) {
      setEditError(t('taskDetail.descriptionRequired'))
      return
    }
    setSaving(true)
    setEditError(null)
    try {
      const body: Record<string, unknown> = { expected_version: task.version_no }
      if (editTitle.trim() !== task.title) body.title = editTitle.trim()
      if (editDescription.trim() !== (task.description || '')) body.description = editDescription.trim() || null
      if (editPriority !== task.priority) body.priority = editPriority
      if ((editEffort || null) !== (task.estimated_effort || null)) body.estimated_effort = editEffort || null
      const newTags = editTags.trim() ? editTags.split(',').map(t => t.trim()).filter(Boolean) : null
      const oldTags = task.tags?.length ? task.tags : null
      if (JSON.stringify(newTags) !== JSON.stringify(oldTags)) body.tags = newTags
      const newDeadline = editDeadline ? new Date(editDeadline).toISOString() : null
      const oldDeadline = task.deadline_at || null
      if (newDeadline !== oldDeadline) body.deadline_at = newDeadline
      const newDependsOn = editDependsOn.length ? editDependsOn : null
      const oldDependsOn = task.depends_on?.length ? task.depends_on.map(d => ({ task_id: d.task_id, type: d.type || 'sequential' })) : null
      if (JSON.stringify(newDependsOn) !== JSON.stringify(oldDependsOn)) body.depends_on = newDependsOn

      const updated = await updateTask(taskId, body as Parameters<typeof updateTask>[1], token)
      setTask(updated)
      setEditing(false)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : t('taskDetail.failedToUpdate'))
    } finally {
      setSaving(false)
    }
  }

  const showRejectInput = (verId: string) => {
    setRejectingId(verId === rejectingId ? null : verId)
    setRejectionReason('')
    setVerifyError(null)
  }

  // ── Role check for verify buttons ───────────────────────
  const canVerify = effectiveRole === 'admin' || effectiveRole === 'lead' || effectiveRole === 'orchestrator'

  // ── Lifecycle stepper ───────────────────────────────────
  const LIFECYCLE = ['backlog', 'ready', 'in_progress', 'in_verification', 'completed']
  const STEP_LABELS: Record<string, string> = {
    backlog: t('tasks.columns.backlog'),
    ready: t('tasks.columns.ready'),
    in_progress: t('tasks.columns.inProgress'),
    in_verification: t('tasks.columns.inVerification'),
    completed: t('tasks.columns.completed'),
  }
  if (error) {
    return (
      <EmptyState icon={AlertTriangle} title={t('taskDetail.failedToLoad')} description={error}>
        <Link to="/tasks" className={styles.backLink}>{t('taskDetail.backToTasks')}</Link>
      </EmptyState>
    )
  }

  if (loading) {
    return (
      <div>
        <Link to="/tasks" className={styles.back}>&larr; {t('taskDetail.backToTasks')}</Link>
        <p className={styles.loading}>{t('taskDetail.loading')}</p>
      </div>
    )
  }

  if (!task) {
    return (
      <EmptyState icon={Search} title={t('taskDetail.taskNotFound')}>
        <Link to="/tasks" className={styles.backLink}>{t('taskDetail.backToTasks')}</Link>
      </EmptyState>
    )
  }

  const currentIdx = LIFECYCLE.indexOf(task.status)
  const GUIDANCE_KEYS: Record<string, string> = {
    backlog: 'taskDetail.guidance.backlog',
    ready: 'taskDetail.guidance.ready',
    in_progress: 'taskDetail.guidance.inProgress',
    in_verification: 'taskDetail.guidance.inVerification',
    rejected: 'taskDetail.guidance.rejected',
  }
  const guidanceText = GUIDANCE_KEYS[task.status] ? t(GUIDANCE_KEYS[task.status]) : null

  const statusCfg = STATUS_LABELS[task.status] || task.status

  return (
    <div>
      <Link to="/tasks" className={styles.back}>&larr; {t('taskDetail.backToTasks')}</Link>

      {/* ── Header ────────────────────────────────────────── */}
      <div className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.heading}>{task.title}</h1>
          <span className={`${styles.statusBadge} ${styles[STATUS_CLASS[task.status]] || ''}`}>
            {statusCfg}
          </span>
          {canEdit && !editing && (
            <button className={styles.btnEdit} onClick={handleStartEdit}>
              {t('taskDetail.edit')}
            </button>
          )}
        </div>
        <div className={styles.metaRow}>
          <span className={styles.priority}>
            {PRIORITY_LABELS[task.priority] || task.priority}
          </span>
          {task.owner_type && (
            <span className={styles.owner}>
              {t('taskDetail.owner')}: <strong>{ownerName ?? `${task.owner_type}:${task.owner_id?.slice(0, 14)}`}</strong>
            </span>
          )}
          <span className={styles.id}>{t('taskDetail.id')}: <code>{task.id.slice(0, 18)}&hellip;</code></span>
        </div>
      </div>

      {/* ── Lifecycle Stepper ──────────────────────────────── */}
      {currentIdx >= 0 && (
        <div className={styles.stepper}>
          {LIFECYCLE.map((step, idx) => {
            const isDone = idx < currentIdx
            const isCurrent = idx === currentIdx
            const stepCls = `${styles.stepperStep} ${isDone ? styles.stepperStepDone : isCurrent ? styles.stepperStepCurrent : ''}`
            const dotCls = `${styles.stepperDot} ${isDone ? styles.stepperDotDone : isCurrent ? styles.stepperDotCurrent : styles.stepperDotPending}`
            return (
              <Fragment key={step}>
                {idx > 0 && (
                  <div className={`${styles.stepperLine} ${isDone ? styles.stepperLineDone : ''}`} />
                )}
                <div className={stepCls}>
                  <div className={dotCls}>
                    {isDone ? '✓' : isCurrent ? '●' : ''}
                  </div>
                  <span className={styles.stepperLabel}>{STEP_LABELS[step]}</span>
                </div>
              </Fragment>
            )
          })}
        </div>
      )}

      {/* ── Contextual Guidance ────────────────────────────── */}
      {guidanceText && !dismissedGuidance && (
        <div className={styles.guidance}>
          <span className={styles.guidanceText}>{guidanceText}</span>
          <button className={styles.guidanceDismiss} onClick={() => setDismissedGuidance(true)}>
            {t('taskDetail.guidance.dismiss')}
          </button>
        </div>
      )}

      {/* ── Actions ───────────────────────────────────────── */}
      <div className={styles.actions}>
        {task.status === 'ready' && (
          <button className={styles.btnPrimary} onClick={handleClaim}>
            {t('taskDetail.claimTask')}
          </button>
        )}
        {task.status === 'in_progress' && (
          <div className={styles.submitGroup}>
            <textarea
              id="task-submit-summary"
              className={styles.summaryInput}
              placeholder={t('taskDetail.summaryPlaceholder')}
              aria-label={t('taskDetail.summaryPlaceholder')}
              value={summary}
              onChange={e => setSummary(e.target.value)}
              rows={3}
            />
            {/* PFL-270: 采集 output_access 证据，避免后端 409 OUTPUT_ACCESS_REQUIRED */}
            <div className={styles.editRow}>
              <div className={styles.editField}>
                <label htmlFor="task-submit-output-type">{t('taskDetail.outputAccessType')}</label>
                <select
                  id="task-submit-output-type"
                  value={outputAccessType}
                  onChange={e => setOutputAccessType(e.target.value)}
                >
                  <option value="git_branch">git_branch</option>
                  <option value="file_url">file_url</option>
                  <option value="web_link">web_link</option>
                  <option value="inline">inline</option>
                </select>
              </div>
              <div className={styles.editField}>
                <label htmlFor="task-submit-output-value">{t('taskDetail.outputAccessValue')}</label>
                <input
                  id="task-submit-output-value"
                  type="text"
                  value={outputAccessValue}
                  onChange={e => setOutputAccessValue(e.target.value)}
                  placeholder={t('taskDetail.outputAccessValuePlaceholder')}
                />
              </div>
            </div>
            <button
              className={styles.btnPrimary}
              onClick={handleSubmit}
              disabled={submitting}
            >
              {submitting ? t('taskDetail.submitting') : t('taskDetail.submitForVerification')}
            </button>
          </div>
        )}
        {actionError && <span className={styles.actionError}>{actionError}</span>}
      </div>

      {/* ── Verification ──────────────────────────────────── */}
      {task.status === 'in_verification' && (
        <div className={styles.verifySection}>
          <h2 className={styles.sectionTitle}>
            {t('taskDetail.verifySection')}
            {verifications.length > 0 && <span className={styles.count}>{verifications.length}</span>}
          </h2>
          {verifications.length === 0 ? (
            <p className={styles.noData}>{t('taskDetail.verifyNone')}</p>
          ) : (
            <div className={styles.verifyList}>
              {verifications.map(v => {
                const isPending = v.status === 'pending'
                const isRejecting = rejectingId === v.id
                return (
                  <div
                    key={v.id}
                    className={`${styles.verifyItem} ${v.status === 'passed' ? styles.verifyItemPassed : v.status === 'failed' ? styles.verifyItemFailed : styles.verifyItemPending}`}
                  >
                    <div className={styles.verifyItemHeader}>
                      <span className={styles.verifyItemType}>{v.type}</span>
                      <span className={`${styles.verifyItemStatus} ${v.status === 'passed' ? styles.verifyItemStatusPassed : v.status === 'failed' ? styles.verifyItemStatusFailed : styles.verifyItemStatusPending}`}>
                        {v.status === 'passed' ? t('taskDetail.verificationPassed') : v.status === 'failed' ? t('taskDetail.verificationFailed') : t('taskDetail.verificationPending')}
                      </span>
                    </div>
                    <p className={styles.verifyItemDesc}>{v.description}</p>
                    {v.rejection_reason && (
                      <p className={styles.verifyItemEvidence}>❌ {v.rejection_reason}</p>
                    )}
                    {isPending && canVerify && (
                      <>
                        {!isRejecting ? (
                          <div className={styles.verifyActions}>
                            <button
                              className={styles.btnPass}
                              onClick={() => handleVerify(v.id, 'passed')}
                              disabled={verifying}
                            >
                              {t('taskDetail.pass')}
                            </button>
                            <button
                              className={styles.btnFail}
                              onClick={() => showRejectInput(v.id)}
                              disabled={verifying}
                            >
                              {t('taskDetail.fail')}
                            </button>
                          </div>
                        ) : (
                          <div className={styles.rejectionGroup}>
                            <textarea
                              id="verify-rejection-reason"
                              className={styles.rejectionInput}
                              placeholder={t('taskDetail.verifyRejectionReason')}
                              aria-label={t('taskDetail.verifyRejectionReason')}
                              value={rejectionReason}
                              onChange={e => setRejectionReason(e.target.value)}
                              rows={2}
                            />
                            <div className={styles.verifyActions}>
                              <button
                                className={styles.btnFail}
                                onClick={() => handleVerify(v.id, 'failed')}
                                disabled={verifying || !rejectionReason.trim()}
                              >
                                {verifying ? '…' : t('taskDetail.fail')}
                              </button>
                              <button
                                className={styles.btnPass}
                                onClick={() => showRejectInput(v.id)}
                              >
                                {t('common.cancel')}
                              </button>
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )
              })}
            </div>
          )}
          {verifyError && <span className={styles.actionError}>{verifyError}</span>}
        </div>
      )}

      {/* ── Edit Form ─────────────────────────────────────── */}
      {editing && (
        <div className={styles.editForm}>
          <h2 className={styles.sectionTitle}>{t('taskDetail.editTask')}</h2>

          <div className={styles.editField}>
            <label htmlFor="task-edit-title">{t('tasks.title')}</label>
            <input
              id="task-edit-title"
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              placeholder={t('tasks.titlePlaceholder')}
            />
          </div>

          <div className={styles.editField}>
            <label htmlFor="task-edit-description">{t('taskDetail.description')}</label>
            <textarea
              id="task-edit-description"
              value={editDescription}
              onChange={e => setEditDescription(e.target.value)}
              placeholder={t('tasks.descPlaceholder')}
              rows={4}
            />
          </div>

          <div className={styles.editRow}>
            <div className={styles.editField}>
              <label htmlFor="task-edit-priority">{t('taskDetail.priority')}</label>
              <select id="task-edit-priority" value={editPriority} onChange={e => setEditPriority(e.target.value)}>
                {PRIORITIES.map(p => (
                  <option key={p} value={p}>{PRIORITY_LABELS[p] || p}</option>
                ))}
              </select>
            </div>
            <div className={styles.editField}>
              <label htmlFor="task-edit-effort">{t('taskDetail.estimatedEffort')}</label>
              <select id="task-edit-effort" value={editEffort} onChange={e => setEditEffort(e.target.value)}>
                <option value="">{t('common.none')}</option>
                {EFFORTS.map(e => (
                  <option key={e} value={e}>{e.toUpperCase()}</option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.editField}>
            <label htmlFor="task-edit-tags">{t('taskDetail.tags')}</label>
            <input
              id="task-edit-tags"
              type="text"
              value={editTags}
              onChange={e => setEditTags(e.target.value)}
              placeholder={t('tasks.tagsPlaceholder')}
            />
          </div>

          <div className={styles.editField}>
            <label htmlFor="task-edit-depends-on">{t('taskDetail.dependsOn')}</label>
            <div className={styles.dependsOnEditor}>
              <div className={styles.dependsOnInputRow}>
                <input
                  id="task-edit-depends-on"
                  type="text"
                  value={editDepInput}
                  onChange={e => setEditDepInput(e.target.value)}
                  placeholder="task_id"
                  className={styles.dependsOnTaskInput}
                />
                <select
                  value={editDepType}
                  onChange={e => setEditDepType(e.target.value)}
                  className={styles.dependsOnTypeSelect}
                >
                  <option value="sequential">sequential</option>
                  <option value="artifact">artifact</option>
                </select>
                <button
                  type="button"
                  className={styles.btnAddDep}
                  onClick={() => {
                    const tid = editDepInput.trim()
                    if (tid && !editDependsOn.some(d => d.task_id === tid)) {
                      setEditDependsOn([...editDependsOn, { task_id: tid, type: editDepType }])
                      setEditDepInput('')
                    }
                  }}
                  disabled={!editDepInput.trim()}
                >
                  {t('taskDetail.addDependency')}
                </button>
              </div>
              {editDependsOn.length > 0 && (
                <ul className={styles.dependsOnEditList}>
                  {editDependsOn.map((dep, idx) => (
                    <li key={dep.task_id} className={styles.dependsOnEditItem}>
                      <Link to={`/tasks/${dep.task_id}`} className={styles.depLink} target="_blank">
                        {dep.task_id.slice(0, 18)}…
                      </Link>
                      <span className={styles.dependsOnEditType}>({dep.type})</span>
                      <button
                        type="button"
                        className={styles.btnRemoveDep}
                        onClick={() => setEditDependsOn(editDependsOn.filter((_, i) => i !== idx))}
                      >
                        {t('taskDetail.removeDependency')}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <div className={styles.editRow}>
            <div className={styles.editField}>
              <label htmlFor="task-edit-deadline">{t('taskDetail.deadline')}</label>
              <input
                id="task-edit-deadline"
                type="datetime-local"
                value={editDeadline}
                onChange={e => setEditDeadline(e.target.value)}
              />
            </div>
            <div className={styles.editField}>
              <label htmlFor="task-edit-batch">{t('taskDetail.batch')}</label>
              <BatchSelect
                id="task-edit-batch"
                projectId={task.project_id}
                value={editBatchId}
                onChange={setEditBatchId}
              />
            </div>
          </div>

          {editError && <p className={styles.actionError}>{editError}</p>}

          <div className={styles.editActions}>
            <button
              className={styles.btnPrimary}
              onClick={handleSave}
              disabled={saving || !editTitle.trim() || !editDescription.trim()}
            >
              {saving ? t('common.saving') : t('taskDetail.save')}
            </button>
            <button className={styles.btnCancel} onClick={handleCancelEdit}>
              {t('taskDetail.cancelEdit')}
            </button>
          </div>
        </div>
      )}

      {/* ── Body grid ─────────────────────────────────────── */}
      {!editing && (
      <div className={styles.body}>
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('taskDetail.description')}</h2>
          {task.description ? (
            <p className={styles.description}>{task.description}</p>
          ) : (
            <p className={styles.noData}>{t('common.noDescription')}</p>
          )}
        </section>

        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>{t('taskDetail.details')}</h2>
          <dl className={styles.dl}>
            <dt>{t('taskDetail.estimatedEffort')}</dt>
            <dd>{task.estimated_effort || t('common.none')}</dd>
            <dt>{t('taskDetail.tags')}</dt>
            <dd>{task.tags?.length ? task.tags.join(', ') : t('common.none')}</dd>
            <dt>{t('taskDetail.batch')}</dt>
            <dd>
              {task.batch_id ? (
                <Link
                  to={`/batches/${task.batch_id}`}
                  className={styles.batchLink}
                  style={{
                    '--badge-color': hashBatchColor(task.batch_id),
                  } as React.CSSProperties}
                >
                  {batchName || task.batch_id.slice(0, 12) + '…'}
                </Link>
              ) : (
                t('common.none')
              )}
            </dd>
            <dt>{t('taskDetail.parentTask')}</dt>
            <dd>{task.parent_task_id ? task.parent_task_id.slice(0, 16) + '...' : t('common.none')}</dd>
            <dt>{t('taskDetail.dependsOn')}</dt>
            <dd>
              {task.depends_on?.length ? (
                <div className={styles.depList}>
                  {task.depends_on.map(d => (
                    <Link key={d.task_id} to={`/tasks/${d.task_id}`} className={styles.depLink}>
                      {d.task_id.slice(0, 14)}…
                      {d.type && ` (${d.type})`}
                    </Link>
                  ))}
                </div>
              ) : (
                t('common.none')
              )}
            </dd>
            <dt>{t('taskDetail.created')}</dt>
            <dd>{formatDate(task.created_at, lang)}</dd>
            {task.completed_at && (
              <>
                <dt>{t('taskDetail.completed')}</dt>
                <dd>{formatDate(task.completed_at, lang)}</dd>
              </>
            )}
            {task.deadline_at && (
              <>
                <dt>{t('taskDetail.deadline')}</dt>
                <dd>{formatDate(task.deadline_at, lang)}</dd>
              </>
            )}
          </dl>
        </section>

        {task.metadata && Object.keys(task.metadata).length > 0 && (
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>{t('common.metadata')}</h2>
            <pre className={styles.metadata}>{JSON.stringify(task.metadata, null, 2)}</pre>
          </section>
        )}
      </div>
      )}

      {/* ── Dependency Graph ─────────────────────────────── */}
      <DependencyGraph
        projectId={task.project_id}
        taskId={task.id}
        token={token!}
        currentTask={{
          id: task.id,
          title: task.title,
          status: task.status,
          priority: task.priority,
          version_no: task.version_no,
          depends_on: task.depends_on,
        }}
      />

      {/* ── Event Timeline ────────────────────────────────── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>
          {t('taskDetail.eventTimeline')}
          {events.length > 0 && <span className={styles.count}>{events.length}</span>}
        </h2>
        {events.length === 0 ? (
          <p className={styles.noData}>{t('taskDetail.noEvents')}</p>
        ) : (
          <div className={styles.timeline}>
            {events.map(evt => (
              <div key={evt.id} className={styles.timelineItem}>
                <span className={`${styles.eventDot} ${eventDotStyle(evt.event_type, styles)}`} />
                <div className={styles.eventBody}>
                  <span className={styles.eventType}>{evt.event_type}</span>
                  <span className={styles.eventMeta}>
                    {t('taskDetail.by')} {evt.actor_type}:{evt.actor_id?.slice(0, 12)}
                  </span>
                </div>
                <span className={styles.eventTime}>
                  {formatDate(evt.created_at, lang)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Collaboration Messages (S-020 · P17-B8) ─────── */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>
          {t('taskDetail.messages')}
          {messages.length > 0 && <span className={styles.count}>{messages.length}</span>}
        </h2>
        {messages.length === 0 ? (
          <p className={styles.noData}>{t('taskDetail.noMessages')}</p>
        ) : (
          <div className={styles.messageList} data-testid="message-list">
            {messages.map(msg => {
              const parent = msg.in_reply_to_id ? messagesById.get(msg.in_reply_to_id) : undefined
              return (
                <div
                  key={msg.id}
                  className={msg.in_reply_to_id ? styles.messageItemReply : styles.messageItem}
                  data-testid="message-item"
                  data-resolved={msg.is_resolved}
                  data-in-reply-to={msg.in_reply_to_id ?? ''}
                >
                  {parent && (
                    <span className={styles.replyIndicator}>
                      ↩ {t('taskDetail.by')} {parent.sender_worker_id?.slice(0, 12)}
                    </span>
                  )}
                  <div className={styles.messageHeader}>
                    <span className={styles.messageTypeGroup}>
                      <span className={styles.messageType}>
                        {MESSAGE_TYPE_LABELS[msg.message_type] ?? msg.message_type}
                      </span>
                      {msg.is_resolved && <span className={styles.resolvedBadge}>{t('taskDetail.resolved')}</span>}
                    </span>
                    <span className={styles.messageMeta}>
                      {t('taskDetail.by')} {msg.sender_worker_id?.slice(0, 12)} · {formatDate(msg.created_at, lang)}
                    </span>
                  </div>
                  <span className={styles.messageText}>{renderMentionedBody(msg.body, workerByName)}</span>
                  <div className={styles.messageActions}>
                    <button
                      className={styles.replyButton}
                      data-testid="message-reply"
                      onClick={() => handleReply(msg)}
                    >
                      {t('taskDetail.reply')}
                    </button>
                    <button
                      className={styles.resolveButton}
                      data-testid="message-toggle-resolve"
                      onClick={() => handleToggleResolve(msg)}
                      disabled={resolvingMessageId === msg.id}
                    >
                      {resolvingMessageId === msg.id
                        ? t('taskDetail.resolving')
                        : msg.is_resolved
                          ? t('taskDetail.reopen')
                          : t('taskDetail.resolve')}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        {replyToId && (
          <div className={styles.replyBanner} data-testid="message-reply-banner">
            <span>
              {t('taskDetail.replyingTo')}{' '}
              {messagesById.get(replyToId)?.sender_worker_id?.slice(0, 12) ?? ''}
            </span>
            <button className={styles.replyBannerCancel} onClick={handleCancelReply}>
              {t('taskDetail.cancelReply')}
            </button>
          </div>
        )}
        <div className={styles.composer}>
          <select
            className={styles.messageTypeSelect}
            data-testid="message-type-select"
            value={messageType}
            onChange={e => setMessageType(e.target.value)}
            aria-label={t('taskDetail.msgTypeLabel')}
          >
            <option value="clarification">{t('taskDetail.msgType.clarification')}</option>
            <option value="blocking">{t('taskDetail.msgType.blocking')}</option>
            <option value="review_request">{t('taskDetail.msgType.review_request')}</option>
            <option value="proposal">{t('taskDetail.msgType.proposal')}</option>
          </select>
          <div className={styles.composerInputWrap}>
            <textarea
              className={styles.messageInput}
              data-testid="message-input"
              ref={messageInputRef}
              value={messageBody}
              onChange={handleMessageChange}
              onKeyDown={handleMentionKeyDown}
              placeholder={t('taskDetail.composerPlaceholder')}
              rows={2}
            />
            {mentionOpen && filteredMentions.length > 0 && (
              <ul className={styles.mentionDropdown} data-testid="mention-dropdown" role="listbox" aria-label={t('taskDetail.mentionSuggestions')}>
                {filteredMentions.map((w, i) => (
                  <li
                    key={w.id}
                    role="option"
                    aria-selected={i === mentionIndex}
                    className={`${styles.mentionOption}${i === mentionIndex ? ` ${styles.mentionActive}` : ''}`}
                    data-testid="mention-option"
                    onMouseDown={e => { e.preventDefault(); insertMention(w.name) }}
                  >
                    {w.name}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            className={styles.sendButton}
            data-testid="message-send"
            onClick={handleSendMessage}
            disabled={sendingMessage || !messageBody.trim()}
          >
            {sendingMessage ? t('taskDetail.sending') : t('taskDetail.send')}
          </button>
        </div>
        {messageError && <p className={styles.messageError}>{messageError}</p>}
      </section>
    </div>
  )
}

function eventDotStyle(type: string, styles: Record<string, string>): string {
  if (type.includes('created')) return styles.dotCreate
  if (type.includes('completed') || type.includes('submitted')) return styles.dotSuccess
  if (type.includes('failed') || type.includes('cancelled')) return styles.dotDanger
  if (type.includes('assigned') || type.includes('claimed')) return styles.dotWarning
  return styles.dotInfo
}


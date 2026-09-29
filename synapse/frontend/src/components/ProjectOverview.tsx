import { useState, useEffect, useMemo } from 'react'
import {
  fetchProjectDependencyGraph,
  fetchProjectEvents,
  fetchWorkers,
} from '../api/client'
import type {
  EventSummary,
  ProjectDependencyGraph,
  WorkerSummary,
} from '../api/client'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { formatDate } from '../utils/format'
import { STATUS_COLORS, STATUS_LABELS } from './statusColors'
import styles from './ProjectOverview.module.css'

interface Props {
  projectId: string
  teamId: string
}

// ── DAG layout (topological layering) ──────────────────────

interface DagNode {
  id: string
  title: string
  status: string
  layer: number
  index: number
  totalInLayer: number
}

const NODE_W = 170
const NODE_H = 58
const LAYER_GAP = 100
const NODE_GAP = 24
const ARROW_SIZE = 6

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '…' : text
}

/**
 * Assign each node a topological layer (layer 0 = no dependencies, rendered
 * leftmost) then an index within its layer. Nodes trapped in cycles fall to a
 * trailing layer so nothing is dropped.
 */
function layoutDag(graph: ProjectDependencyGraph): DagNode[] {
  const { nodes, edges } = graph
  const byId = new Map(nodes.map(n => [n.id, n]))
  const indegree = new Map<string, number>()
  const children = new Map<string, string[]>()
  for (const n of nodes) {
    indegree.set(n.id, 0)
    children.set(n.id, [])
  }
  for (const e of edges) {
    if (!byId.has(e.from) || !byId.has(e.to)) continue
    if (e.from === e.to) continue
    children.get(e.from)!.push(e.to)
    indegree.set(e.to, (indegree.get(e.to) ?? 0) + 1)
  }

  const layerOf = new Map<string, number>()
  let frontier = nodes.filter(n => (indegree.get(n.id) ?? 0) === 0).map(n => n.id)
  let layer = 0
  while (frontier.length > 0) {
    const next: string[] = []
    for (const id of frontier) {
      if (layerOf.has(id)) continue
      layerOf.set(id, layer)
      for (const child of children.get(id) ?? []) {
        const d = (indegree.get(child) ?? 1) - 1
        indegree.set(child, d)
        if (d === 0) next.push(child)
      }
    }
    frontier = next
    layer++
  }

  const maxAssigned = layerOf.size > 0 ? Math.max(...layerOf.values()) : -1
  for (const n of nodes) {
    if (!layerOf.has(n.id)) layerOf.set(n.id, maxAssigned + 1)
  }

  const groups = new Map<number, DagNode[]>()
  for (const n of nodes) {
    const l = layerOf.get(n.id) ?? 0
    const group = groups.get(l) ?? []
    group.push({ id: n.id, title: n.title, status: n.status, layer: l, index: 0, totalInLayer: 0 })
    groups.set(l, group)
  }
  const result: DagNode[] = []
  for (const [, group] of [...groups.entries()].sort((a, b) => a[0] - b[0])) {
    group.forEach((node, idx) => {
      node.index = idx
      node.totalInLayer = group.length
      result.push(node)
    })
  }
  return result
}

function nodeX(layer: number): number {
  return 20 + layer * (NODE_W + LAYER_GAP)
}

function nodeY(index: number, total: number, svgH: number): number {
  const totalHeight = total * NODE_H + (total - 1) * NODE_GAP
  const startY = (svgH - totalHeight) / 2
  return startY + index * (NODE_H + NODE_GAP)
}

function eventBadgeClass(type: string): string {
  if (type.includes('created')) return styles.evtCreate
  if (type.includes('completed')) return styles.evtSuccess
  if (type.includes('failed') || type.includes('cancelled')) return styles.evtDanger
  if (type.includes('assigned') || type.includes('claimed')) return styles.evtWarning
  return styles.evtInfo
}

// ── Component ──────────────────────────────────────────────

export default function ProjectOverview({ projectId, teamId }: Props) {
  const { token } = useAuth()
  const { t, lang } = useI18n()
  const [graph, setGraph] = useState<ProjectDependencyGraph | null>(null)
  const [events, setEvents] = useState<EventSummary[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [workers, setWorkers] = useState<WorkerSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)

  useEffect(() => {
    if (!token) return
    setLoading(true)
    setError(null)
    Promise.all([
      fetchProjectDependencyGraph(projectId, token),
      fetchProjectEvents(projectId, token, { limit: 50 }),
      fetchWorkers(teamId, token),
    ])
      .then(([g, ev, w]) => {
        setGraph(g)
        setEvents(ev.items)
        setNextCursor(ev.next_cursor)
        setWorkers(w.items)
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [projectId, teamId, token])

  const workerNames = useMemo(() => {
    const map = new Map<string, string>()
    workers.forEach(w => map.set(w.id, w.name))
    return map
  }, [workers])

  const loadMore = () => {
    if (!token || !nextCursor || loadingMore) return
    setLoadingMore(true)
    fetchProjectEvents(projectId, token, { cursor: nextCursor, limit: 50 })
      .then(ev => {
        setEvents(prev => [...prev, ...ev.items])
        setNextCursor(ev.next_cursor)
      })
      .catch(err => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoadingMore(false))
  }

  if (loading) {
    return <p className={styles.loading}>{t('common.loading')}</p>
  }

  if (error) {
    return <p className={styles.error}>{error}</p>
  }

  const dagNodes = graph ? layoutDag(graph) : []
  const edges = graph ? graph.edges : []
  const maxLayer = dagNodes.reduce((m, n) => Math.max(m, n.layer), 0)
  const totalLayers = maxLayer + 1
  const svgW = 20 + totalLayers * (NODE_W + LAYER_GAP) + 20
  const maxNodesInLayer = dagNodes.reduce((m, n) => Math.max(m, n.totalInLayer), 1)
  const svgH = maxNodesInLayer * NODE_H + (maxNodesInLayer - 1) * NODE_GAP + 40
  const nodeById = new Map(dagNodes.map(n => [n.id, n]))

  return (
    <div className={styles.container}>
      {/* ── Dependency panorama ─────────────────────────────── */}
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>
          {t('overview.dependencyGraph')}
          <span className={styles.count}>{t('overview.nodeCount', { count: dagNodes.length })}</span>
        </h3>
        {dagNodes.length === 0 ? (
          <p className={styles.emptyText}>{t('overview.noTasks')}</p>
        ) : (
          <div className={styles.svgWrapper}>
            <svg
              viewBox={`0 0 ${svgW} ${svgH}`}
              className={styles.svg}
              preserveAspectRatio="xMidYMid meet"
            >
              <defs>
                <marker
                  id="overviewArrow"
                  viewBox="0 0 10 10"
                  refX={10}
                  refY={5}
                  markerWidth={ARROW_SIZE}
                  markerHeight={ARROW_SIZE}
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#4a5568" />
                </marker>
              </defs>

              {edges.map(edge => {
                const from = nodeById.get(edge.from)
                const to = nodeById.get(edge.to)
                if (!from || !to) return null
                const x1 = nodeX(from.layer) + NODE_W
                const y1 = nodeY(from.index, from.totalInLayer, svgH) + NODE_H / 2
                const x2 = nodeX(to.layer)
                const y2 = nodeY(to.index, to.totalInLayer, svgH) + NODE_H / 2
                const midX = (x1 + x2) / 2
                const d = y1 === y2
                  ? `M ${x1} ${y1} L ${x2} ${y2}`
                  : `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`
                return (
                  <path
                    key={`${edge.from}->${edge.to}`}
                    d={d}
                    fill="none"
                    stroke="#4a5568"
                    strokeWidth={1.5}
                    markerEnd="url(#overviewArrow)"
                  />
                )
              })}

              {dagNodes.map(node => {
                const colors = STATUS_COLORS[node.status] || STATUS_COLORS.backlog
                const x = nodeX(node.layer)
                const y = nodeY(node.index, node.totalInLayer, svgH)
                return (
                  <g key={node.id}>
                    <rect
                      x={x}
                      y={y}
                      width={NODE_W}
                      height={NODE_H}
                      rx={8}
                      fill={colors.bg}
                      stroke={colors.border}
                      strokeWidth={1.5}
                      strokeDasharray={node.status === 'cancelled' ? '4 3' : undefined}
                    />
                    <text
                      x={x + NODE_W / 2}
                      y={y + 22}
                      textAnchor="middle"
                      fill={colors.text}
                      fontSize={12}
                      fontWeight={600}
                      fontFamily="inherit"
                    >
                      {truncate(node.title, 20)}
                    </text>
                    <text
                      x={x + NODE_W / 2}
                      y={y + 42}
                      textAnchor="middle"
                      fill={colors.text}
                      fontSize={11}
                      opacity={0.7}
                      fontFamily="inherit"
                    >
                      {STATUS_LABELS[node.status] || node.status}
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>
        )}
      </section>

      {/* ── Event stream ────────────────────────────────────── */}
      <section className={styles.section}>
        <h3 className={styles.sectionTitle}>{t('overview.events')}</h3>
        {events.length === 0 ? (
          <p className={styles.emptyText}>{t('overview.noEvents')}</p>
        ) : (
          <div className={styles.eventList}>
            {events.map(evt => (
              <div key={evt.id} className={styles.eventRow}>
                <span className={`${styles.eventBadge} ${eventBadgeClass(evt.event_type)}`}>
                  {evt.event_type}
                </span>
                <span className={styles.eventMeta}>
                  {workerNames.get(evt.actor_id) ?? `${evt.actor_type}:${evt.actor_id?.slice(0, 12)}`} → {evt.target_type}:{evt.target_id?.slice(0, 12)}
                </span>
                <span className={styles.eventTime}>
                  {formatDate(evt.created_at, lang)}
                </span>
              </div>
            ))}
          </div>
        )}
        {nextCursor && (
          <button
            type="button"
            className={styles.loadMore}
            onClick={loadMore}
            disabled={loadingMore}
          >
            {loadingMore ? t('common.loading') : t('overview.loadMore')}
          </button>
        )}
      </section>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { fetchTask } from '../api/client'
import type { TaskSummary } from '../api/client'
import { STATUS_COLORS, STATUS_LABELS } from './statusColors'
import styles from './DependencyGraph.module.css'

// ── Types ──────────────────────────────────────────────────

interface DepNode {
  id: string
  title: string
  status: string
  priority: string
  version_no: number
  layer: number        // 0 = root (current task), 1 = direct dep, 2 = dep-of-dep...
  index: number        // position within layer
  totalInLayer: number // total nodes in this layer
}

interface DepEdge {
  from: string   // node id
  to: string     // node id
}

interface Props {
  taskId: string
  token: string
  currentTask: {
    id: string
    title: string
    status: string
    priority: string
    version_no: number
    depends_on: Array<{ task_id: string; type?: string }> | null
  }
}

// ── Constants ──────────────────────────────────────────────

const NODE_W = 170
const NODE_H = 58
const LAYER_GAP = 100   // horizontal gap between layers
const NODE_GAP = 24     // vertical gap between nodes in same layer
const ARROW_SIZE = 6

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max - 1) + '…' : text
}

// ── Layout engine ──────────────────────────────────────────

/**
 * BFS from the current task outward through depends_on chains.
 * Returns nodes arranged in layers (layer 0 = current task, layer 1 = direct deps, etc.)
 * and edges connecting them.
 *
 * Max depth: 3 layers to avoid infinite recursion and API spam.
 */
async function buildGraph(
  taskId: string,
  token: string,
  dependsOn: Array<{ task_id: string; type?: string }> | null,
): Promise<{ nodes: DepNode[]; edges: DepEdge[] }> {
  const nodeMap = new Map<string, DepNode>()
  const edges: DepEdge[] = []
  const MAX_DEPTH = 3

  // Layer 0: current task (status already known from props)
  // We'll add it after building deeper layers so we know totalInLayer per layer

  // BFS queue: [taskId, layer, parentId?]
  // Start with direct deps at layer 1
  const queue: Array<{ tid: string; layer: number; parentId: string }> = []
  const visited = new Set<string>([taskId])

  if (dependsOn) {
    for (const d of dependsOn) {
      if (!visited.has(d.task_id)) {
        visited.add(d.task_id)
        queue.push({ tid: d.task_id, layer: 1, parentId: taskId })
        edges.push({ from: d.task_id, to: taskId })
      }
    }
  }

  // BFS
  while (queue.length > 0) {
    const { tid, layer } = queue.shift()!
    if (layer > MAX_DEPTH) continue

    // Fetch task detail to get status + its own depends_on
    let taskSummary: TaskSummary | null = null
    try {
      const detail = await fetchTask(tid, token)
      taskSummary = {
        id: detail.id,
        title: detail.title,
        status: detail.status,
        priority: detail.priority,
        version_no: detail.version_no,
        owner_type: detail.owner_type,
        owner_id: detail.owner_id,
        batch_id: detail.batch_id,
        tags: detail.tags,
        depends_on: detail.depends_on,
        deadline_at: detail.deadline_at,
        is_overdue: detail.is_overdue,
        completed_at: detail.completed_at,
        created_at: detail.created_at,
      }
    } catch {
      // Task not found — create a placeholder node
      taskSummary = {
        id: tid,
        title: `[Missing: ${tid.slice(0, 12)}…]`,
        status: 'cancelled',
        priority: 'p3',
        version_no: 0,
        owner_type: null,
        owner_id: null,
        batch_id: null,
        tags: null,
        depends_on: null,
        deadline_at: null,
        is_overdue: false,
        completed_at: null,
        created_at: '',
      }
    }

    // Register node
    if (!nodeMap.has(tid)) {
      nodeMap.set(tid, {
        id: tid,
        title: taskSummary.title,
        status: taskSummary.status,
        priority: taskSummary.priority,
        version_no: taskSummary.version_no,
        layer,
        index: 0,       // will be set after BFS
        totalInLayer: 0, // will be set after BFS
      })
    }

    // Enqueue children if not at max depth
    if (layer < MAX_DEPTH && taskSummary.depends_on) {
      for (const d of taskSummary.depends_on) {
        if (!visited.has(d.task_id)) {
          visited.add(d.task_id)
          queue.push({ tid: d.task_id, layer: layer + 1, parentId: tid })
          edges.push({ from: d.task_id, to: tid })
        }
      }
    }
  }

  // Group nodes by layer, assign indices
  const layerGroups = new Map<number, DepNode[]>()
  for (const node of nodeMap.values()) {
    const group = layerGroups.get(node.layer) || []
    group.push(node)
    layerGroups.set(node.layer, group)
  }

  for (const [, group] of layerGroups) {
    group.sort((a, b) => a.id.localeCompare(b.id)) // deterministic ordering
    group.forEach((node, idx) => {
      node.index = idx
      node.totalInLayer = group.length
    })
  }

  // Collect all nodes
  const nodes: DepNode[] = [...nodeMap.values()]

  return { nodes, edges }
}

// ── SVG coordinate helpers ─────────────────────────────────

function nodeX(layer: number, maxLayer: number): number {
  // layer 0 (current task) → right side
  // higher layers → left side
  const totalLayers = maxLayer + 1
  const layerFromLeft = totalLayers - 1 - layer
  return 40 + layerFromLeft * (NODE_W + LAYER_GAP)
}

function nodeY(index: number, total: number, svgH: number): number {
  const totalHeight = total * NODE_H + (total - 1) * NODE_GAP
  const startY = (svgH - totalHeight) / 2
  return startY + index * (NODE_H + NODE_GAP)
}

// ── Component ──────────────────────────────────────────────

export default function DependencyGraph({ taskId, token, currentTask }: Props) {
  const [nodes, setNodes] = useState<DepNode[]>([])
  const [edges, setEdges] = useState<DepEdge[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await buildGraph(taskId, token, currentTask.depends_on)

        // Add current task node (layer 0)
        const currentDepNode: DepNode = {
          id: currentTask.id,
          title: currentTask.title,
          status: currentTask.status,
          priority: currentTask.priority,
          version_no: currentTask.version_no,
          layer: 0,
          index: 0,
          totalInLayer: 1,
        }

        if (!cancelled) {
          const allNodes = [currentDepNode, ...result.nodes]
          setNodes(allNodes)
          setEdges(result.edges)
          setLoading(false)
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to build dependency graph')
          setLoading(false)
        }
      }
    }
    load()
    return () => { cancelled = true }
  }, [taskId, token, currentTask.depends_on, currentTask.id, currentTask.title, currentTask.status, currentTask.priority, currentTask.version_no])

  // ── Empty state ────────────────────────────────────────
  if (!loading && !error && nodes.length <= 1 && (!currentTask.depends_on || currentTask.depends_on.length === 0)) {
    // Single node: just show the current task centered
    const w = NODE_W + 80
    const h = NODE_H + 40
    const colors = STATUS_COLORS[currentTask.status] || STATUS_COLORS.backlog
    return (
      <div className={styles.container}>
        <h3 className={styles.title}>Dependency Graph</h3>
        <svg
          viewBox={`0 0 ${w} ${h}`}
          className={styles.svg}
          style={{ maxWidth: w }}
        >
          {/* Single node, centered */}
          <rect
            x={(w - NODE_W) / 2}
            y={(h - NODE_H) / 2}
            width={NODE_W}
            height={NODE_H}
            rx={8}
            fill={colors.bg}
            stroke={colors.border}
            strokeWidth={1.5}
          />
          <text
            x={w / 2}
            y={h / 2 - 6}
            textAnchor="middle"
            fill={colors.text}
            fontSize={12}
            fontWeight={600}
            fontFamily="inherit"
          >
            {truncate(currentTask.title, 20)}
          </text>
          <text
            x={w / 2}
            y={h / 2 + 14}
            textAnchor="middle"
            fill={colors.text}
            fontSize={11}
            opacity={0.7}
            fontFamily="inherit"
          >
            {STATUS_LABELS[currentTask.status] || currentTask.status}
          </text>
        </svg>
        <p className={styles.hint}>No dependencies — this task stands alone.</p>
      </div>
    )
  }

  // ── Loading / Error ─────────────────────────────────────
  if (loading) {
    return (
      <div className={styles.container}>
        <h3 className={styles.title}>Dependency Graph</h3>
        <p className={styles.hint}>Loading dependency graph…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles.container}>
        <h3 className={styles.title}>Dependency Graph</h3>
        <p className={styles.hint} style={{ color: 'var(--gm-danger, #ef4444)' }}>{error}</p>
      </div>
    )
  }

  // ── Compute layout ──────────────────────────────────────
  const maxLayer = Math.max(...nodes.map(n => n.layer), 0)
  const totalLayers = maxLayer + 1
  const svgW = 40 + totalLayers * (NODE_W + LAYER_GAP) + 40

  // Compute max nodes per layer for SVG height
  const layerCounts = new Map<number, number>()
  for (const n of nodes) {
    layerCounts.set(n.layer, Math.max(layerCounts.get(n.layer) || 0, n.totalInLayer))
  }
  const maxNodesInLayer = Math.max(...layerCounts.values(), 1)
  const svgH = maxNodesInLayer * NODE_H + (maxNodesInLayer - 1) * NODE_GAP + 40

  // Build a map for quick lookups
  const nodeById = new Map(nodes.map(n => [n.id, n]))

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>
        Dependency Graph
        <span className={styles.count}>{nodes.length} nodes</span>
      </h3>
      <div className={styles.svgWrapper}>
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className={styles.svg}
          preserveAspectRatio="xMidYMid meet"
        >
          {/* ── Arrowhead marker ──────────────────────────── */}
          <defs>
            <marker
              id="depArrow"
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

          {/* ── Edges ─────────────────────────────────────── */}
          {edges.map(edge => {
            const from = nodeById.get(edge.from)
            const to = nodeById.get(edge.to)
            if (!from || !to) return null

            const x1 = nodeX(from.layer, maxLayer) + NODE_W
            const y1 = nodeY(from.index, from.totalInLayer, svgH) + NODE_H / 2
            const x2 = nodeX(to.layer, maxLayer)
            const y2 = nodeY(to.index, to.totalInLayer, svgH) + NODE_H / 2

            // Curved path if nodes are in different vertical positions
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
                markerEnd="url(#depArrow)"
              />
            )
          })}

          {/* ── Nodes ─────────────────────────────────────── */}
          {nodes.map(node => {
            const colors = STATUS_COLORS[node.status] || STATUS_COLORS.backlog
            const x = nodeX(node.layer, maxLayer)
            const y = nodeY(node.index, node.totalInLayer, svgH)
            const isCurrent = node.id === currentTask.id

            return (
              <g key={node.id}>
                {/* Node background */}
                <rect
                  x={x}
                  y={y}
                  width={NODE_W}
                  height={NODE_H}
                  rx={8}
                  fill={colors.bg}
                  stroke={isCurrent ? colors.border : colors.border}
                  strokeWidth={isCurrent ? 2 : 1.5}
                  strokeDasharray={node.status === 'cancelled' ? '4 3' : undefined}
                />

                {/* Current task indicator */}
                {isCurrent && (
                  <rect
                    x={x}
                    y={y}
                    width={NODE_W}
                    height={NODE_H}
                    rx={8}
                    fill="none"
                    stroke={colors.border}
                    strokeWidth={2}
                    opacity={0.4}
                  />
                )}

                {/* Title */}
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

                {/* Status */}
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
                  {isCurrent ? ' (this)' : ''}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

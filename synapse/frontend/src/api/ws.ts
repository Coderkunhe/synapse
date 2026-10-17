/**
 * WebSocket client hook for real-time event streaming.
 *
 * Manages connection lifecycle, auto-reconnect with exponential backoff,
 * heartbeat, and subscription management.
 *
 * Usage:
 *   const { status, lastEvent } = useWebSocket(token, ['task.assigned', 'task.completed']);
 */

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'

// ── Constants ────────────────────────────────────────────────────────────────

const WS_BASE = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/v1/ws'
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30000
const MAX_RETRY_ATTEMPTS = 5
const TOKEN_REFRESH_DEBOUNCE_MS = 10_000
const PING_INTERVAL_MS = 25000 // slightly less than server's 30s to be safe

// ── Types ─────────────────────────────────────────────────────────────────────

export type WSStatus = 'disconnected' | 'connecting' | 'connected'

export interface WSEvent {
  id: string
  event_type: string
  actor_type: string
  actor_id: string
  target_type: string
  target_id: string
  payload: Record<string, unknown>
  team_id: string
  created_at: string
}

interface WSMessage {
  type: string
  data?: WSEvent
  detail?: string
  actor_id?: string
  actor_type?: string
  team_id?: string
}

/** Task lifecycle topics the server auto-subscribes humans to (ws.py task_topics).
 *  Shared by ProjectOverview (project DAG), Dashboard (team rollup), and
 *  Workbench (my tasks) — three consumers, so it lives here (rule of three). */
export const TASK_EVENT_TYPES = [
  'task.created',
  'task.readied',
  'task.assigned',
  'task.claimed',
  'task.submitted',
  'task.completed',
  'task.rejected',
  'task.cancelled',
  'task.paused',
  'task.resumed',
]

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useWebSocket(
  token: string | null,
  topics: string[] = [],
  onTokenExpired?: () => void,
) {
  const [status, setStatus] = useState<WSStatus>('disconnected')
  const [lastEvent, setLastEvent] = useState<WSEvent | null>(null)
  const [eventLog, setEventLog] = useState<WSEvent[]>([])

  // Stabilize topics array to prevent reconnection on every render
  const stableTopics = useMemo(() => topics, [topics.join(',')])

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const mountedRef = useRef(true)
  const lastTokenRefreshRef = useRef(0)

  // Clear all timers
  const clearTimers = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (pingTimerRef.current) {
      clearInterval(pingTimerRef.current)
      pingTimerRef.current = null
    }
  }, [])

  // Connect function
  const connect = useCallback(() => {
    if (!token) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    setStatus('connecting')

    // P100-B171: browser clients authenticate via the httpOnly access_token
    // cookie (P100-B58), sent automatically on the WS handshake — no
    // ?token= query param (avoids token-in-URL logging). The `token` arg is
    // the "cookie" sentinel from AuthContext, used only as an auth gate here.
    const url = WS_BASE
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (!mountedRef.current) {
        ws.close()
        return
      }
      setStatus('connected')
      reconnectAttemptRef.current = 0

      // Subscribe to requested topics
      if (stableTopics.length > 0) {
        ws.send(JSON.stringify({ type: 'subscribe', topics: stableTopics }))
      }

      // Start ping interval
      pingTimerRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, PING_INTERVAL_MS)
    }

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return
      try {
        const msg: WSMessage = JSON.parse(event.data)

        if (msg.type === 'event' && msg.data) {
          const evt = msg.data
          setLastEvent(evt)
          setEventLog(prev => [evt, ...prev].slice(0, 100)) // keep last 100
        }
        // ping/pong/connected messages are handled silently here
      } catch (err) {
        console.error('Failed to parse WebSocket message', err) /* Non-critical: malformed message dropped, connection stays alive */
      }
    }

    ws.onclose = (event: CloseEvent) => {
      if (!mountedRef.current) return
      setStatus('disconnected')
      clearTimers()

      // P100-B172: 4001 = auth failure (missing/invalid token). The cookie is
      // gone, and reconnecting would just re-trigger 4001, so log out instead
      // (the ProtectedRoute then redirects to /login). Non-4001 keeps the
      // exponential-backoff reconnect below.
      if (event.code === 4001) {
        onTokenExpired?.()
        return
      }

      const attempt = reconnectAttemptRef.current
      if (attempt >= MAX_RETRY_ATTEMPTS) {
        // Max retries exceeded — notify parent to refresh token (debounced)
        const now = Date.now()
        if (onTokenExpired && now - lastTokenRefreshRef.current > TOKEN_REFRESH_DEBOUNCE_MS) {
          lastTokenRefreshRef.current = now
          onTokenExpired()
        }
        return
      }

      // Auto-reconnect with exponential backoff
      const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, attempt), RECONNECT_MAX_MS)
      reconnectAttemptRef.current = attempt + 1

      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current) {
          connect()
        }
      }, delay)
    }

    ws.onerror = () => {
      // onclose will fire after this, triggering reconnect
    }
  }, [token, stableTopics, clearTimers, onTokenExpired])

  // Connect on mount and when token changes
  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      clearTimers()
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [connect, clearTimers])

  // Re-subscribe when topics change while connected
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN && stableTopics.length > 0) {
      wsRef.current.send(JSON.stringify({ type: 'subscribe', topics: stableTopics }))
    }
  }, [stableTopics])

  // Clear event log
  const clearEventLog = useCallback(() => {
    setEventLog([])
    setLastEvent(null)
  }, [])

  return {
    status,
    lastEvent,
    eventLog,
    clearEventLog,
  }
}

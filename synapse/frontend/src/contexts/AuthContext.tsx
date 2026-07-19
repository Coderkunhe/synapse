/**
 * AuthContext — centralized OAuth authentication state management.
 *
 * P100-B58: JWT migrated from localStorage to httpOnly cookie.
 * Auth state is verified via /v1/auth/me (cookie auto-sent by browser).
 * Non-sensitive user metadata (memberId, teamId, role, displayName)
 * is held in React state only — no localStorage.
 *
 * Usage:
 *   const { token, isAuthenticated, login, logout } = useAuth()
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  refreshAccessToken,
  logoutRequest,
  fetchAuthMe,
  fetchDevToken,
  loginWithEmail as loginWithEmailApi,
  registerUser as registerUserApi,
  API_BASE,
} from '../api/client'

// ── Constants ────────────────────────────────────────────────────────────────

// Access token expires in 15 min; refresh proactively at 14 min
const ACCESS_TOKEN_EXPIRY_MS = 15 * 60 * 1000
const REFRESH_MARGIN_MS = 60 * 1000
const REFRESH_INTERVAL_MS = ACCESS_TOKEN_EXPIRY_MS - REFRESH_MARGIN_MS

// ── Types ─────────────────────────────────────────────────────────────────────

interface AuthState {
  token: string | null  // sentinel "cookie" when authenticated (not the real JWT)
  memberId: string | null
  teamId: string | null
  role: string | null
  displayName: string | null
  isAuthenticated: boolean
  isLoading: boolean
}

interface AuthContextValue extends AuthState {
  login: () => void
  logout: () => Promise<void>
  refreshToken: () => Promise<string | null>
  loginWithEmail: (email: string, password: string) => Promise<void>
  registerAndLogin: (email: string, password: string, displayName: string) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    token: null,
    memberId: null,
    teamId: null,
    role: null,
    displayName: null,
    isAuthenticated: false,
    isLoading: true, // start loading — will call /v1/auth/me to resolve
  })

  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const mountedRef = useRef(true)

  // ── Token refresh (proactive timer, no JWT decode needed) ──────────────────

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) {
      clearInterval(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
  }, [])

  const startRefreshTimer = useCallback(
    (doRefresh: () => Promise<string | null>) => {
      clearRefreshTimer()
      refreshTimerRef.current = setInterval(() => {
        doRefresh()
      }, REFRESH_INTERVAL_MS)
    },
    [clearRefreshTimer],
  )

  const refreshAccessTokenInternal = useCallback(async (): Promise<string | null> => {
    try {
      const data = await refreshAccessToken()
      setState({
        token: 'cookie', // sentinel — real token is in httpOnly cookie
        memberId: data.member_id,
        teamId: data.team_id,
        role: data.role,
        displayName: data.display_name,
        isAuthenticated: true,
        isLoading: false,
      })
      return 'cookie'
    } catch {
      return null
    }
  }, [])

  // Validate session on mount via /v1/auth/me (cookie auto-sent)
  useEffect(() => {
    mountedRef.current = true

    const initAuth = async () => {
      try {
        // Try cookie-based auth first (no explicit token)
        const me = await fetchAuthMe()
        if (!mountedRef.current) return
        setState({
          token: 'cookie',
          memberId: me.member_id,
          teamId: me.team_id,
          role: me.role,
          displayName: me.display_name,
          isAuthenticated: true,
          isLoading: false,
        })
        startRefreshTimer(refreshAccessTokenInternal)
      } catch {
        // Not authenticated — try dev auto-login in dev mode
        if (import.meta.env.DEV) {
          try {
            const data = await fetchDevToken()
            if (!mountedRef.current) return
            // Backend sets httpOnly cookie; verify with /v1/auth/me
            const me = await fetchAuthMe()
            if (!mountedRef.current) return
            setState({
              token: 'cookie',
              memberId: me.member_id ?? data.member_id,
              teamId: me.team_id ?? data.team_id,
              role: me.role ?? data.role,
              displayName: me.display_name ?? data.display_name,
              isAuthenticated: true,
              isLoading: false,
            })
            startRefreshTimer(refreshAccessTokenInternal)
          } catch {
            if (mountedRef.current) {
              setState((prev) => ({ ...prev, isLoading: false }))
            }
          }
        } else {
          if (mountedRef.current) {
            setState((prev) => ({ ...prev, isLoading: false }))
          }
        }
      }
    }

    initAuth()

    return () => {
      mountedRef.current = false
      clearRefreshTimer()
    }
  }, [clearRefreshTimer, startRefreshTimer, refreshAccessTokenInternal])

  // ── Public API ────────────────────────────────────────────────────────────

  const login = useCallback(() => {
    window.location.href = `${API_BASE}/v1/auth/oauth/github`
  }, [])

  const logout = useCallback(async () => {
    clearRefreshTimer()
    try {
      await logoutRequest()
    } catch {
      // Best-effort — clear local state regardless
    }
    setState({
      token: null,
      memberId: null,
      teamId: null,
      role: null,
      displayName: null,
      isAuthenticated: false,
      isLoading: false,
    })
  }, [clearRefreshTimer])

  const refreshToken = useCallback(async (): Promise<string | null> => {
    return refreshAccessTokenInternal()
  }, [refreshAccessTokenInternal])

  const loginWithEmail = useCallback(async (email: string, password: string) => {
    // Backend sets httpOnly cookie; verify with /v1/auth/me
    await loginWithEmailApi(email, password)
    const me = await fetchAuthMe()
    setState({
      token: 'cookie',
      memberId: me.member_id,
      teamId: me.team_id,
      role: me.role,
      displayName: me.display_name,
      isAuthenticated: true,
      isLoading: false,
    })
    startRefreshTimer(refreshAccessTokenInternal)
  }, [startRefreshTimer, refreshAccessTokenInternal])

  const registerAndLogin = useCallback(
    async (email: string, password: string, displayName: string) => {
      // Backend sets httpOnly cookie on successful registration
      await registerUserApi(email, password, displayName)
      const me = await fetchAuthMe()
      setState({
        token: 'cookie',
        memberId: me.member_id,
        teamId: me.team_id,
        role: me.role,
        displayName: me.display_name,
        isAuthenticated: true,
        isLoading: false,
      })
      startRefreshTimer(refreshAccessTokenInternal)
    },
    [startRefreshTimer, refreshAccessTokenInternal],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, refreshToken, loginWithEmail, registerAndLogin }),
    [state, login, logout, refreshToken, loginWithEmail, registerAndLogin],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an <AuthProvider>')
  }
  return ctx
}

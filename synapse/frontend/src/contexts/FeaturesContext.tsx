/**
 * FeaturesContext — feature flag state for S-015 极简模式.
 *
 * Provides:
 *   - `projectCount`   — max projects (0 = unlimited)
 *   - `batchSize`      — max batch size (0 = unlimited)
 *   - `isMinimalProject` — true when project_count === 1
 *   - `isMinimalBatch`   — true when batch_size === 1
 *   - `loading`          — true while initial fetch is in flight
 *
 * Fetches GET /v1/features on mount (public endpoint, no auth).
 * Fails open: defaults to unlimited (0) so the app never breaks on
 * a config endpoint failure.
 *
 * Follows I18nContext pattern — simple createContext + provider + hook.
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { fetchFeatures, type Features } from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

interface FeaturesContextValue {
  projectCount: number
  batchSize: number
  teams: boolean
  isMinimalProject: boolean
  isMinimalBatch: boolean
  isMinimalTeams: boolean
  loading: boolean
}

const FeaturesContext = createContext<FeaturesContextValue | null>(null)

// ── Provider ──────────────────────────────────────────────────────────────────

export function FeaturesProvider({ children }: { children: ReactNode }) {
  const [features, setFeatures] = useState<Features>({ project_count: 0, batch_size: 0, teams: true })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetchFeatures()
      .then((data) => {
        if (!cancelled) {
          setFeatures(data)
          setLoading(false)
        }
      })
      .catch(() => {
        // Fail open — show everything if config endpoint is unreachable
        if (!cancelled) {
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [])

  const value = useMemo<FeaturesContextValue>(
    () => ({
      projectCount: features.project_count,
      batchSize: features.batch_size,
      teams: features.teams,
      isMinimalProject: features.project_count === 1,
      isMinimalBatch: features.batch_size === 1,
      isMinimalTeams: !features.teams,
      loading,
    }),
    [features, loading],
  )

  return (
    <FeaturesContext.Provider value={value}>
      {children}
    </FeaturesContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useFeatures(): FeaturesContextValue {
  const ctx = useContext(FeaturesContext)
  if (!ctx) {
    throw new Error('useFeatures must be used within a <FeaturesProvider>')
  }
  return ctx
}

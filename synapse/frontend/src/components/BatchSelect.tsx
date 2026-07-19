/**
 * BatchSelect — shared batch dropdown for task creation.
 *
 * Replaces the hand-typed UUID <input placeholder="batch_xxx"> pattern
 * in the Tasks create form. Fetches batches for the selected project.
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { fetchBatches } from '../api/client'
import type { BatchSummary } from '../api/client'
import styles from './ProjectSelect.module.css'

interface BatchSelectProps {
  projectId: string
  value: string
  onChange: (batchId: string) => void
  placeholder?: string
  id?: string
}

export default function BatchSelect({ projectId, value, onChange, placeholder, id }: BatchSelectProps) {
  const { t } = useI18n()
  const { token } = useAuth()
  const [batches, setBatches] = useState<BatchSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!token || !projectId) {
      setBatches([])
      setError(false)
      return
    }
    setLoading(true)
    setError(false)
    fetchBatches(projectId, token)
      .then(res => {
        setBatches(res.items)
        setLoading(false)
      })
      .catch((err) => {
        console.error('Failed to fetch batches for select', err)
        setError(true)
        setLoading(false)
      })
  }, [token, projectId])

  // Group batches by phase for optgroup rendering
  const grouped: Record<string, BatchSummary[]> = {}
  for (const b of batches) {
    const key = b.phase || 'Other'
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(b)
  }
  const phases = Object.keys(grouped).sort((a, b) => {
    if (a === 'Other') return 1
    if (b === 'Other') return -1
    return b.localeCompare(a)
  })

  const renderOption = (b: BatchSummary) => (
    <option key={b.id} value={b.id}>
      {b.order != null ? `#${b.order} ` : ''}{b.name}
    </option>
  )

  return (
    <select
      id={id}
      className={styles.select}
      value={value}
      onChange={e => onChange(e.target.value)}
      disabled={!projectId}
    >
      <option value="">{loading ? '…' : error ? t('batches.selectLoadError') : (placeholder || t('tasks.batchId'))}</option>
      {phases.length > 1 ? (
        phases.map(phase => (
          <optgroup key={phase} label={phase}>
            {grouped[phase].map(renderOption)}
          </optgroup>
        ))
      ) : (
        batches.map(renderOption)
      )}
    </select>
  )
}

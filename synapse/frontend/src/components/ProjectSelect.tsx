/**
 * ProjectSelect — shared project dropdown.
 *
 * Replaces the hand-typed UUID <input placeholder="Project ID"> pattern
 * used across Batches, Tasks, and Analyses pages.
 */

import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useI18n } from '../contexts/I18nContext'
import { fetchProjects } from '../api/client'
import type { ProjectSummary } from '../api/client'
import styles from './ProjectSelect.module.css'

interface ProjectSelectProps {
  value: string
  onChange: (projectId: string) => void
}

export default function ProjectSelect({ value, onChange }: ProjectSelectProps) {
  const { t } = useI18n()
  const { token, teamId } = useAuth()
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    if (!token || !teamId) return
    setLoading(true)
    setError(false)
    fetchProjects(teamId, token)
      .then(res => {
        setProjects(res.items)
        setLoading(false)
      })
      .catch((err) => {
        console.error('Failed to fetch projects for select', err)
        setError(true)
        setLoading(false)
      })
  }, [token, teamId])

  return (
    <select
      className={styles.select}
      value={value}
      onChange={e => {
        const next = e.target.value
        onChange(next)
        // Persist last-used project to localStorage for session restoration.
        // This is an intentional cross-cutting concern — lifting it to every
        // parent would scatter the same line across N call sites.
        if (next) localStorage.setItem('synapse_project_id', next)
      }}
    >
      <option value="">{loading ? '…' : error ? t('projects.selectLoadError') : t('common.projectId')}</option>
      {projects.map(p => (
        <option key={p.id} value={p.id}>
          {p.name} ({p.slug})
        </option>
      ))}
    </select>
  )
}

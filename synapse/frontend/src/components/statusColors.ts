// Shared task-status visual constants for DAG rendering.
// Extracted to a standalone module so DependencyGraph and ProjectOverview
// share one source of truth without degrading Fast Refresh (react-refresh
// requires component files to export only components).

export const STATUS_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  backlog:         { bg: 'rgba(136, 146, 166, 0.12)', border: '#8892a6', text: '#8892a6' },
  ready:           { bg: 'rgba(56, 189, 248, 0.12)',  border: '#38bdf8', text: '#38bdf8' },
  in_progress:     { bg: 'rgba(245, 158, 11, 0.12)',  border: '#f59e0b', text: '#f59e0b' },
  in_verification: { bg: 'rgba(108, 140, 245, 0.12)', border: '#6c8cf5', text: '#6c8cf5' },
  completed:       { bg: 'rgba(74, 222, 128, 0.12)',  border: '#4ade80', text: '#4ade80' },
  cancelled:       { bg: 'rgba(239, 68, 68, 0.12)',   border: '#ef4444', text: '#ef4444' },
  rejected:        { bg: 'rgba(239, 68, 68, 0.12)',   border: '#ef4444', text: '#ef4444' },
}

export const STATUS_LABELS: Record<string, string> = {
  backlog: 'Backlog', ready: 'Ready', in_progress: 'In Progress',
  in_verification: 'Verify', completed: 'Done', cancelled: 'Cancelled', rejected: 'Rejected',
}

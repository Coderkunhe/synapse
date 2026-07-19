import { Navigate, Outlet, Route, Routes, Link } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { I18nProvider, useI18n } from './contexts/I18nContext'
import { FeaturesProvider, useFeatures } from './contexts/FeaturesContext'
import Layout from './components/Layout'
import Workers from './pages/Workers'
import Analyses from './pages/Analyses'
import Scans from './pages/Scans'
import Skills from './pages/Skills'
import Docs from './pages/Docs'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Register from './pages/Register'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword from './pages/ResetPassword'
import OAuthCallback from './pages/OAuthCallback'
import Batches from './pages/Batches'
import BatchDetail from './pages/BatchDetail'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import TaskDetail from './pages/TaskDetail'
import WorkerDetail from './pages/WorkerDetail'
import Tasks from './pages/Tasks'
import Teams from './pages/Teams'
import TeamDetail from './pages/TeamDetail'
import Approvals from './pages/Approvals'

/** Full-screen spinner shown while AuthProvider validates the stored token. */
function AuthSpinner() {
  const { t } = useI18n()
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      gap: '1rem',
      color: 'var(--color-text-secondary)',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        width: 32,
        height: 32,
        border: '3px solid var(--color-border)',
        borderTopColor: 'var(--color-accent)',
        borderRadius: '50%',
        animation: 'syn-spin 0.7s linear infinite',
      }} />
      <style>{`@keyframes syn-spin { to { transform: rotate(360deg); } }`}</style>
      <span>{t('common.loading')}</span>
    </div>
  )
}

/** 404 page for unmatched routes. */
function NotFound() {
  const { t } = useI18n()
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '60vh',
      gap: '0.75rem',
      fontFamily: 'system-ui, sans-serif',
    }}>
      <h1 style={{ fontSize: '3rem', margin: 0, color: 'var(--color-text)' }}>404</h1>
      <p style={{ color: 'var(--color-text-secondary)', margin: 0 }}>{t('error404.message')}</p>
      <Link
        to="/dashboard"
        style={{
          marginTop: '0.5rem',
          color: 'var(--color-accent)',
          textDecoration: 'none',
        }}
      >
        ← {t('nav.dashboard')}
      </Link>
    </div>
  )
}

/** Redirect to /login if not authenticated. */
function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return <AuthSpinner />
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

/** Inner routes component — reads feature flags and conditionally renders routes. */
function AppRoutes() {
  const { isMinimalBatch, isMinimalTeams, loading } = useFeatures()

  if (loading) {
    return <AuthSpinner />
  }

  return (
    <Routes>
      {/* Public auth pages — no Layout wrapper */}
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/oauth/callback" element={<OAuthCallback />} />

      {/* Protected pages — wrapped in Layout */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/:projectId" element={<ProjectDetail />} />
          {!isMinimalBatch && (
            <Route path="/batches" element={<Batches />} />
          )}
          {!isMinimalBatch && (
            <Route path="/batches/:batchId" element={<BatchDetail />} />
          )}
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/tasks/:taskId" element={<TaskDetail />} />
          <Route path="/workers" element={<Workers />} />
          <Route path="/agents" element={<Navigate to="/workers" replace />} />
          <Route path="/workers/:workerId" element={<WorkerDetail />} />
          <Route path="/analyses" element={<Analyses />} />
          <Route path="/scans" element={<Scans />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/docs" element={<Docs />} />
          {!isMinimalTeams && (
            <Route path="/teams" element={<Teams />} />
          )}
          {!isMinimalTeams && (
            <Route path="/teams/:teamId" element={<TeamDetail />} />
          )}
          <Route path="/approvals" element={<Approvals />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <I18nProvider>
        <FeaturesProvider>
          <AppRoutes />
        </FeaturesProvider>
      </I18nProvider>
    </AuthProvider>
  )
}

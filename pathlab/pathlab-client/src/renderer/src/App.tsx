import type React from 'react'
import { useTranslation } from 'react-i18next'
import { Routes, Route, Link, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import IntroductionPage from './pages/IntroductionPage'
import LoginPage from './pages/LoginPage'
import AIChatPage from './pages/AIChatPage'
import SettingsPage from './pages/SettingsPage'
import NewTaskPage from './pages/NewTaskPage'
import TaskListPage from './pages/TaskListPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ListPage from './pages/ListPage'
import WSIViewerPage from './pages/WSIViewerPage'
import RegisterPage from './pages/UploadPage'
import ResultsViewerPage from './pages/ResultsViewerPage'
import ReportGeneratorPage from './pages/ReportGeneratorPage'
import ToolsPage from './pages/ToolsPage'
import PathScientistLayout from './components/pathscientist/PathScientistLayout'
import PathScientistWorkspaceLayout from './components/pathscientist/PathScientistWorkspaceLayout'
import PathScientistNewSessionPage from './pages/PathScientistNewSessionPage'
import PathScientistSessionPage from './pages/PathScientistSessionPage'
import { isPathScientistStandaloneMode } from './lib/pathscientistStandalone'

function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh]">
      <h2 className="text-4xl font-bold text-gray-900 mb-4">{t('common.notFound')}</h2>
      <Link to="/" className="text-primary-600 hover:text-primary-700 font-medium">
        {t('common.backToHome')}
      </Link>
    </div>
  )
}

interface AppProps {
  pathScientistStandalone?: boolean
}

function pathScientistRouteElements(useMainLayout: boolean) {
  const workspace = <PathScientistWorkspaceLayout />
  const shell = useMainLayout ? (
    <ProtectedRoute>
      <Layout>{workspace}</Layout>
    </ProtectedRoute>
  ) : (
    <PathScientistLayout>{workspace}</PathScientistLayout>
  )

  return (
    <Route path="/pathscientist" element={shell}>
      <Route index element={<Navigate to="new" replace />} />
      <Route path="new" element={<PathScientistNewSessionPage />} />
      <Route path="sessions/:id" element={<PathScientistSessionPage />} />
    </Route>
  )
}

export default function App({ pathScientistStandalone }: AppProps = {}) {
  const standalone = pathScientistStandalone ?? isPathScientistStandaloneMode({
    isElectron: !!(window as any).electron || window.location.protocol === 'file:',
  })

  if (standalone) {
    return (
      <Routes>
        <Route path="/" element={<Navigate to="/pathscientist/new" replace />} />
        <Route path="/login" element={<Navigate to="/pathscientist/new" replace />} />
        {pathScientistRouteElements(false)}
        <Route path="*" element={<Navigate to="/pathscientist/new" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<IntroductionPage />} />
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes - Require Authentication */}
      {pathScientistRouteElements(true)}
      <Route path="/dashboard" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/dashboard/:conversationId" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/tools" element={<ProtectedRoute><Layout><ToolsPage /></Layout></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute requireAdmin><Layout><SettingsPage /></Layout></ProtectedRoute>} />
      <Route path="/task-setup" element={<ProtectedRoute requireGpu><Layout><NewTaskPage /></Layout></ProtectedRoute>} />
      <Route path="/task-list" element={<ProtectedRoute><Layout><TaskListPage /></Layout></ProtectedRoute>} />
      <Route path="/task/:task_id" element={<ProtectedRoute><Layout><TaskDetailPage /></Layout></ProtectedRoute>} />
      <Route path="/wsi-list" element={<ProtectedRoute><Layout><ListPage /></Layout></ProtectedRoute>} />
      <Route path="/register" element={<ProtectedRoute><Layout><RegisterPage /></Layout></ProtectedRoute>} />
      <Route path="/results" element={<ProtectedRoute requireGpu><Layout><ResultsViewerPage /></Layout></ProtectedRoute>} />
      <Route path="/reports" element={<ProtectedRoute><Layout><ReportGeneratorPage /></Layout></ProtectedRoute>} />

      {/* WSIViewerPage without Layout (full screen viewer) - Also protected */}
      <Route path="/wsi/:wsi_id" element={<ProtectedRoute><WSIViewerPage /></ProtectedRoute>} />

      {/* 404 - Protected */}
      <Route path="*" element={
        <ProtectedRoute>
          <Layout>
            <NotFoundPage />
          </Layout>
        </ProtectedRoute>
      } />
    </Routes>
  )
}

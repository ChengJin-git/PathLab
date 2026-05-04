import { useTranslation } from 'react-i18next'
import { Routes, Route, Link } from 'react-router-dom'
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
import PaperGenerationPage from './pages/PaperGenerationPage'
import PaperRunDetailPage from './pages/PaperRunDetailPage'

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

export default function App() {
  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<IntroductionPage />} />
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes - Require Authentication */}
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
      <Route path="/papers" element={<ProtectedRoute><Layout><PaperGenerationPage /></Layout></ProtectedRoute>} />
      <Route path="/papers/:paper_id" element={<ProtectedRoute><Layout><PaperRunDetailPage /></Layout></ProtectedRoute>} />

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

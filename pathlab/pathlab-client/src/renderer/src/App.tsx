import React from 'react'
import { Routes, Route, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
import DeepResearchPage from './pages/DeepResearchPage'

export default function App() {
  const { t } = useTranslation()

  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<IntroductionPage />} />
      <Route path="/login" element={<LoginPage />} />

      {/* Protected Routes - Require Authentication */}
      <Route path="/dashboard" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/dashboard/:conversationId" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/ai-chat" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/ai-chat/:conversationId" element={<ProtectedRoute><Layout><AIChatPage /></Layout></ProtectedRoute>} />
      <Route path="/deep-research" element={<ProtectedRoute><Layout><DeepResearchPage /></Layout></ProtectedRoute>} />
      <Route path="/deep-research/:conversationId" element={<ProtectedRoute><Layout><DeepResearchPage /></Layout></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><Layout><SettingsPage /></Layout></ProtectedRoute>} />
      <Route path="/task-setup" element={<ProtectedRoute><Layout><NewTaskPage /></Layout></ProtectedRoute>} />
      <Route path="/task-list" element={<ProtectedRoute><Layout><TaskListPage /></Layout></ProtectedRoute>} />
      <Route path="/task/:task_id" element={<ProtectedRoute><Layout><TaskDetailPage /></Layout></ProtectedRoute>} />
      <Route path="/wsi-list" element={<ProtectedRoute><Layout><ListPage /></Layout></ProtectedRoute>} />
      <Route path="/register" element={<ProtectedRoute><Layout><RegisterPage /></Layout></ProtectedRoute>} />
      <Route path="/results" element={<ProtectedRoute><Layout><ResultsViewerPage /></Layout></ProtectedRoute>} />
      <Route path="/reports" element={<ProtectedRoute><Layout><ReportGeneratorPage /></Layout></ProtectedRoute>} />

      {/* DetailPage without Layout (full screen viewer) - Also protected */}
      <Route path="/wsi/:wsi_id" element={<ProtectedRoute><WSIViewerPage /></ProtectedRoute>} />

      {/* 404 - Protected */}
      <Route path="*" element={
        <ProtectedRoute>
          <Layout>
            <div className="flex flex-col items-center justify-center min-h-[60vh]">
              <h2 className="text-4xl font-bold text-gray-900 mb-4">{t('app.notFound.title')}</h2>
              <Link to="/" className="text-primary-600 hover:text-primary-700 font-medium">
                {t('app.notFound.backHome')}
              </Link>
            </div>
          </Layout>
        </ProtectedRoute>
      } />
    </Routes>
  )
}

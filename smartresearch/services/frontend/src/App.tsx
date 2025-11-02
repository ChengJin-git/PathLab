import React from 'react'
import { Routes, Route, Link } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import AIChatPage from './pages/AIChatPage'
import SettingsPage from './pages/SettingsPage'
import NewTaskPage from './pages/NewTaskPage'
import TaskListPage from './pages/TaskListPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ListPage from './pages/ListPage'
import DetailPage from './pages/DetailPage'
import UploadPage from './pages/UploadPage'
import ResultsViewerPage from './pages/ResultsViewerPage'
import ReportGeneratorPage from './pages/ReportGeneratorPage'

export default function App() {
  return (
    <Routes>
      {/* Main Routes */}
      <Route path="/" element={<Layout><DashboardPage /></Layout>} />
      <Route path="/ai-chat" element={<Layout><AIChatPage /></Layout>} />
      <Route path="/settings" element={<Layout><SettingsPage /></Layout>} />
      <Route path="/task-setup" element={<Layout><NewTaskPage /></Layout>} />
      <Route path="/task-list" element={<Layout><TaskListPage /></Layout>} />
      <Route path="/task/:task_id" element={<Layout><TaskDetailPage /></Layout>} />
      <Route path="/wsi-list" element={<Layout><ListPage /></Layout>} />
      <Route path="/upload" element={<Layout><UploadPage /></Layout>} />
      <Route path="/results" element={<Layout><ResultsViewerPage /></Layout>} />
      <Route path="/reports" element={<Layout><ReportGeneratorPage /></Layout>} />

      {/* DetailPage without Layout (full screen viewer) */}
      <Route path="/wsi/:wsi_id" element={<DetailPage />} />

      {/* 404 */}
      <Route path="*" element={
        <Layout>
          <div className="flex flex-col items-center justify-center min-h-[60vh]">
            <h2 className="text-4xl font-bold text-gray-900 mb-4">404 - Not Found</h2>
            <Link to="/" className="text-primary-600 hover:text-primary-700 font-medium">
              ← Back to Home
            </Link>
          </div>
        </Layout>
      } />
    </Routes>
  )
}


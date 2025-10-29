import React from 'react'
import { Routes, Route, Link } from 'react-router-dom'
import Layout from './components/Layout'
import DashboardPage from './pages/DashboardPage'
import NewTaskPage from './pages/NewTaskPage'
import TaskSetupPage from './pages/TaskSetupPage'
import TrainingDataSelectionPage from './pages/TrainingDataSelectionPage'
import TrainingPage from './pages/TrainingPage'
import ListPage from './pages/ListPage'
import DetailPage from './pages/DetailPage'

export default function App() {
  return (
    <Routes>
      {/* Routes with Layout */}
      <Route path="/" element={<Layout><DashboardPage /></Layout>} />
      <Route path="/task-setup" element={<Layout><NewTaskPage /></Layout>} />

      {/* Legacy routes - keep for backward compatibility */}
      <Route path="/training-data-selection" element={<Layout><TrainingDataSelectionPage /></Layout>} />
      <Route path="/training" element={<Layout><TrainingPage /></Layout>} />

      <Route path="/wsi-list" element={<Layout><ListPage /></Layout>} />

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


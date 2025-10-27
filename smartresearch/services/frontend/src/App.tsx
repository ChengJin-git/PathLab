import React from 'react'
import { Routes, Route, Link } from 'react-router-dom'
import TaskSetupPage from './pages/TaskSetupPage'
import TrainingDataSelectionPage from './pages/TrainingDataSelectionPage'
import TrainingPage from './pages/TrainingPage'
import InferencePage from './pages/InferencePage'
import ListPage from './pages/ListPage'
import DetailPage from './pages/DetailPage'

export default function App() {
  return (
    <div style={styles.app}>
      <Routes>
        {/* 主流程路由 */}
        <Route path="/" element={<TaskSetupPage />} />
        <Route path="/training-data-selection" element={<TrainingDataSelectionPage />} />
        <Route path="/training" element={<TrainingPage />} />
        <Route path="/inference" element={<InferencePage />} />

        {/* WSI浏览路由 */}
        <Route path="/wsi-list" element={<ListPage />} />
        <Route path="/wsi/:wsi_id" element={<DetailPage />} />

        {/* 404 */}
        <Route path="*" element={
          <div style={styles.notFound}>
            <h2>404 - Not Found</h2>
            <Link to="/" style={styles.link}>← Back to Home</Link>
          </div>
        } />
      </Routes>
    </div>
  )
}

const styles = {
  app: { minHeight: '100vh' },
  notFound: {
    padding: 40,
    textAlign: 'center' as const,
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    background: '#f6f8fa'
  },
  link: { color: '#0969da', textDecoration: 'none' }
}


import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Routes, Route, Link, Navigate, Outlet } from 'react-router-dom'
import Layout from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { isAutoResearchStandaloneMode } from './lib/autoresearchStandalone'
import { useAuth } from './contexts/AuthContext'
import PageLoading from './components/common/PageLoading'
import { loadDatasetsPage, loadUploadPage } from './lib/dataPages'

const PublicSite = lazy(() => import('./pages/PublicSite'))
const AbilitiesPage = lazy(()=>import('./pages/AbilitiesPage'))
const FileLibraryPage=lazy(()=>import('./pages/FileLibraryPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const NewTaskPage = lazy(() => import('./pages/NewTaskPage'))
const TaskListPage = lazy(() => import('./pages/TaskListPage'))
const TaskDetailPage = lazy(() => import('./pages/TaskDetailPage'))
const ListPage = lazy(loadDatasetsPage)
const WSIViewerPage = lazy(() => import('./pages/WSIViewerPage'))
const UploadPage = lazy(loadUploadPage)
const ResultsViewerPage = lazy(() => import('./pages/ResultsViewerPage'))
const EvaluationPage = lazy(() => import('./pages/EvaluationPage'))
const ReportGeneratorPage = lazy(() => import('./pages/ReportGeneratorPage'))
const ToolsPage = lazy(() => import('./pages/ToolsPage'))
const AutoResearchLayout = lazy(() => import('./components/autoresearch/AutoResearchLayout'))
const AutoResearchWorkspaceLayout = lazy(() => import('./components/autoresearch/AutoResearchWorkspaceLayout'))
const AutoResearchNewSessionPage = lazy(() => import('./pages/AutoResearchNewSessionPage'))
const AutoResearchSessionPage = lazy(() => import('./pages/AutoResearchSessionPage'))

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
  autoResearchStandalone?: boolean
}

function ResearchRouteShell({ useMainLayout }: { useMainLayout: boolean }) {
  const { user } = useAuth()
  const workspace = <AutoResearchWorkspaceLayout key={`${user?.id}:${user?.role}`} />
  return (
    <ProtectedRoute requireResearch>{useMainLayout
      ? <Layout>{workspace}</Layout>
      : <AutoResearchLayout>{workspace}</AutoResearchLayout>}
    </ProtectedRoute>
  )
}

function autoResearchRouteElements(useMainLayout: boolean) {
  return (
    <Route path="/autoresearch" element={<ResearchRouteShell useMainLayout={useMainLayout} />}>
      <Route index element={<Navigate to="new" replace />} />
      <Route path="new" element={<AutoResearchNewSessionPage />} />
      <Route path="sessions/:id" element={<AutoResearchSessionPage />} />
    </Route>
  )
}

export default function App({ autoResearchStandalone }: AppProps = {}) {
  return (
    <Suspense fallback={<PageLoading fullPage/>}>
      <AppRoutes autoResearchStandalone={autoResearchStandalone} />
    </Suspense>
  )
}

function AppRoutes({ autoResearchStandalone }: AppProps) {
  const standalone = autoResearchStandalone ?? isAutoResearchStandaloneMode()

  if (standalone) {
    return (
      <Routes>
        <Route path="/" element={<Navigate to="/autoresearch/new" replace />} />
        <Route path="/login" element={<PublicSite page="login" />} />
        {autoResearchRouteElements(false)}
        <Route path="/reports" element={<ProtectedRoute requireResearch><AutoResearchLayout><ReportGeneratorPage /></AutoResearchLayout></ProtectedRoute>} />
        <Route path="*" element={<Navigate to="/autoresearch/new" replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      {/* Public Routes */}
      <Route path="/" element={<PublicSite page="landing" />} />
      <Route path="/login" element={<PublicSite page="login" />} />

      {/* Protected Routes - Require Authentication */}
      <Route element={<ProtectedRoute><Layout><Suspense fallback={<PageLoading/>}><Outlet/></Suspense></Layout></ProtectedRoute>}>
      <Route path="/dashboard" element={null} />
      <Route path="/dashboard/:conversationId" element={null} />
      <Route path="/abilities" element={<AbilitiesPage/>}/>
      <Route path="/files" element={<FileLibraryPage/>}/>
      <Route path="/tools" element={<ToolsPage/>}/>
      <Route path="/settings" element={<ProtectedRoute requireAdmin><SettingsPage /></ProtectedRoute>} />
      <Route path="/task-setup" element={<ProtectedRoute requireGpu><NewTaskPage /></ProtectedRoute>} />
      <Route path="/task-list" element={<TaskListPage/>}/>
      <Route path="/task/:task_id" element={<TaskDetailPage/>}/>
      <Route path="/datasets" element={<ListPage/>}/>
      <Route path="/upload" element={<UploadPage/>}/>
      <Route path="/results" element={<ProtectedRoute requireGpu><ResultsViewerPage /></ProtectedRoute>} />
      <Route path="/evaluate" element={<ProtectedRoute requireGpu><EvaluationPage /></ProtectedRoute>} />
      <Route path="/reports" element={<ProtectedRoute requireResearch><ReportGeneratorPage /></ProtectedRoute>} />
      <Route path="/autoresearch" element={<ProtectedRoute requireResearch><AutoResearchWorkspaceLayout/></ProtectedRoute>}><Route index element={<Navigate to="new" replace/>}/><Route path="new" element={<AutoResearchNewSessionPage/>}/><Route path="sessions/:id" element={<AutoResearchSessionPage/>}/></Route>
      </Route>

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

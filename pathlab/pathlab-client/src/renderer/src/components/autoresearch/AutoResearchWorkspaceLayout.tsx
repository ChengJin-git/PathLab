import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'
import AutoResearchSessionSidebar from './AutoResearchSessionSidebar'
import { useAutoResearchTranslation } from '../../lib/useAutoResearchTranslation'

export default function AutoResearchWorkspaceLayout() {
  const { t } = useAutoResearchTranslation()
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const { pathname } = useLocation()

  useEffect(() => {
    setIsSidebarOpen(false)
  }, [pathname])

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-50 lg:flex-row">
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2 lg:hidden">
        <button
          type="button"
          onClick={() => setIsSidebarOpen(true)}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100"
        >
          <Menu className="h-5 w-5" />
          {t('autoResearch.sessions')}
        </button>
      </div>

      {isSidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/30 lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      <div
        className={`fixed inset-y-0 left-0 z-50 w-72 transform transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0 ${
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-end border-b border-gray-200 bg-white p-2 lg:hidden">
            <button
              type="button"
              onClick={() => setIsSidebarOpen(false)}
              className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <AutoResearchSessionSidebar />
          </div>
        </div>
      </div>

      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl p-3 sm:p-4 lg:p-5" data-testid="autoresearch-workspace-content">
          <Outlet />
        </div>
      </div>
    </section>
  )
}

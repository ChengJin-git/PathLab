import { Outlet } from 'react-router-dom'
import AutoResearchSessionSidebar from './AutoResearchSessionSidebar'

export default function AutoResearchWorkspaceLayout() {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-50 lg:flex-row">
      <AutoResearchSessionSidebar />
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl p-3 sm:p-4 lg:p-5" data-testid="autoresearch-workspace-content">
          <Outlet />
        </div>
      </div>
    </section>
  )
}

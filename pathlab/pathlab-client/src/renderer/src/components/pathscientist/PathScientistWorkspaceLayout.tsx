import { Outlet } from 'react-router-dom'
import PathScientistSessionSidebar from './PathScientistSessionSidebar'

export default function PathScientistWorkspaceLayout() {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-50 lg:flex-row">
      <PathScientistSessionSidebar />
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-7xl p-3 sm:p-4 lg:p-5" data-testid="pathscientist-workspace-content">
          <Outlet />
        </div>
      </div>
    </section>
  )
}

import { Outlet } from 'react-router-dom'
import PathScientistSessionSidebar from './PathScientistSessionSidebar'

export default function PathScientistWorkspaceLayout() {
  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-gray-50 lg:flex-row">
      <PathScientistSessionSidebar />
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl p-4 sm:p-6 lg:p-8">
          <Outlet />
        </div>
      </div>
    </section>
  )
}

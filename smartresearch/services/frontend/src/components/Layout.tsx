import React, { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BarChart3, Bot, Rocket, ClipboardList, FolderOpen, Settings, Menu, TrendingUp, FileText, Upload } from 'lucide-react'

interface LayoutProps {
  children: React.ReactNode
}

interface NavigationItem {
  name: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

export default function Layout({ children }: LayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const location = useLocation()

  // Check if current page is AI Chat
  const isAIChatPage = location.pathname === '/ai-chat'

  const navigation: NavigationItem[] = [
    { name: 'Dashboard', href: '/', icon: BarChart3 },
    { name: 'New Task', href: '/ai-chat', icon: Bot },
    { name: 'Custom Setup', href: '/task-setup', icon: Rocket },
    { name: 'Task Browser', href: '/task-list', icon: ClipboardList },
    { name: 'Upload Slides', href: '/upload', icon: Upload },
    { name: 'Slide Browser', href: '/wsi-list', icon: FolderOpen },
    { name: 'Results Viewer', href: '/results', icon: TrendingUp },
    { name: 'Report Generator', href: '/reports', icon: FileText },
    { name: 'Settings', href: '/settings', icon: Settings },
  ]

  const isActive = (path: string) => {
    if (path === '/') {
      return location.pathname === '/'
    }
    return location.pathname.startsWith(path)
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar */}
      <aside
        className={`fixed top-0 left-0 z-40 h-screen transition-transform ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        } bg-white border-r border-gray-200 w-64`}
      >
        <div className="h-full px-3 py-4 overflow-y-auto custom-scrollbar">
          {/* Logo */}
          <Link to="/" className="flex items-center mb-8 px-3 hover:opacity-80 transition-opacity">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 via-purple-500 to-pink-500 rounded-lg flex items-center justify-center shadow-sm">
                <span className="text-white text-lg font-bold">SR</span>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">SmartResearch</h1>
                <p className="text-xs text-gray-500">Pathology Slide Research Platform</p>
              </div>
            </div>
          </Link>

          {/* Navigation */}
          <nav className="space-y-1">
            {navigation.map((item) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={`flex items-center px-3 py-2.5 text-sm font-medium rounded-lg transition-colors ${
                    isActive(item.href)
                      ? 'bg-primary-50 text-primary-700'
                      : 'text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  <Icon className="w-5 h-5 mr-3" />
                  {item.name}
                </Link>
              )
            })}
          </nav>

          {/* Footer */}
          <div className="absolute bottom-4 left-0 right-0 px-6">
            <div className="bg-gradient-to-r from-primary-50 to-secondary-50 rounded-lg p-4 border border-primary-100">
              <p className="text-xs font-semibold text-gray-700 mb-1">System Status</p>
              <div className="flex items-center space-x-2">
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                <span className="text-xs text-gray-600">All Services Online</span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className={`${sidebarOpen ? 'ml-64' : 'ml-0'} transition-all duration-300`}>
        {/* Top Bar */}
        <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
          <div className="px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-16">
              <button
                onClick={() => setSidebarOpen(!sidebarOpen)}
                className="p-2 rounded-lg text-gray-600 hover:bg-gray-100 transition-colors"
              >
                <Menu className="w-6 h-6" />
              </button>

              <div className="flex items-center space-x-4">
                <div className="text-sm text-gray-600">
                  <span className="font-medium">Welcome, Doctor</span>
                </div>
                <div className="w-8 h-8 bg-gradient-to-br from-primary-400 to-secondary-400 rounded-full flex items-center justify-center text-white text-sm font-bold">
                  D
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className={isAIChatPage ? "h-[calc(100vh-4rem)] overflow-hidden" : "p-4 sm:p-6 lg:p-8"}>
          {isAIChatPage ? (
            <div className="h-full">
              {children}
            </div>
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  )
}


import React, { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { LogOut, Settings, User } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { Button } from './ui/button'

interface LayoutProps {
  children: React.ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  // Check if current page is AI Chat
  const isAIChatPage = location.pathname === '/ai-chat'
  const isDashboardPage = location.pathname === '/dashboard' || location.pathname === '/'
  const isRegisterPage = location.pathname === '/register'

  const handleLogout = async () => {
    await logout()
    navigate('/')
  }

  return (
    <div className={`bg-gray-50 flex flex-col ${isAIChatPage || location.pathname === '/task-setup' || isDashboardPage || isRegisterPage
      ? 'h-screen overflow-hidden' 
      : 'min-h-screen'}`}>
      {/* Top Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-gray-200/50 sticky top-0 z-50 shadow-sm flex-shrink-0">
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 w-full">
          <div className="flex justify-between h-16">
            {/* Logo Area */}
            <div className="flex items-center">
              <Link to="/dashboard" className="flex-shrink-0 flex items-center hover:opacity-80 transition-opacity">
                <img
                  src="/images/pathlab-logo.png"
                  alt="PathLab"
                  className="h-10 w-auto"
                />
              </Link>
            </div>

            {/* Right Side Actions */}
            <div className="flex items-center space-x-4">
              {/* Settings Shortcut */}
              <button
                onClick={() => navigate('/settings')}
                className="p-2 text-gray-500 hover:text-primary-600 hover:bg-gray-100 rounded-lg transition-colors"
                title="Settings"
              >
                <Settings className="w-5 h-5" />
              </button>

              <div className="h-6 w-px bg-gray-200 mx-2"></div>

              {/* User Profile */}
              <div className="flex items-center space-x-3">
                <div className="flex flex-col items-end hidden sm:flex">
                  <span className="text-sm font-medium text-gray-900 leading-none">
                    {user?.nickname || user?.username || 'Guest'}
                  </span>
                  <span className="text-xs text-gray-500 mt-1">Free Plan</span>
                </div>
                <div className="w-9 h-9 bg-primary-100 rounded-full flex items-center justify-center text-sm font-bold text-primary-700 ring-2 ring-white shadow-sm">
                  {(user?.nickname || user?.username || 'G').charAt(0).toUpperCase()}
                </div>
              </div>

              {/* Logout */}
              <Button
                variant="ghost"
                size="icon"
                onClick={handleLogout}
                className="text-gray-500 hover:text-red-600 hover:bg-red-50"
                title="Logout"
              >
                <LogOut className="w-5 h-5" />
              </Button>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main
        className={`flex-1 ${isAIChatPage || location.pathname === '/task-setup'
            ? 'h-full overflow-hidden'
            : isDashboardPage
              ? 'max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8 h-full overflow-hidden flex flex-col justify-center'
              : isRegisterPage
                ? 'max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8 h-full overflow-hidden'
                : `max-w-[1600px] w-full mx-auto p-4 sm:p-6 lg:p-8`
          }`}
      >
        {children}
      </main>
    </div>
  )
}

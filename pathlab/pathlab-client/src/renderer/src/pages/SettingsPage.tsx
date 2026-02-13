import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, ClipboardList, Database, Info, BookOpen, HardDrive, RefreshCw, ArrowLeft, Users, MessageSquare } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE, PREPROCESSING_BASE, AI_BASE } from '../config'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import {
  ConfirmDialog,
  GeneralTab,
  TasksTab,
  ModelsTab,
  StorageTab,
  UsersTab,
  FeedbackTab
} from '../components/settings'
import type { ConfirmDialogState, ShowConfirmDialog } from '../components/settings'

type TabType = 'general' | 'tasks' | 'models' | 'storage' | 'users' | 'feedback'

type ServiceStatus = 'online' | 'offline' | 'checking'

interface ServiceHealth {
  gateway: ServiceStatus
  wsi: ServiceStatus
  ai: ServiceStatus
}

export default function SettingsPage() {
  const navigate = useNavigate()
  const { isAdmin, isLoading: authLoading, user: currentUser } = useAuth()

  // Redirect non-admin users to dashboard
  useEffect(() => {
    if (!authLoading && !isAdmin) {
      navigate('/dashboard')
    }
  }, [isAdmin, authLoading, navigate])

  // Active Tab
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const savedTab = localStorage.getItem('settingsActiveTab')
    const validTabs: TabType[] = ['general', 'tasks', 'models', 'storage', 'users', 'feedback']
    return (validTabs.includes(savedTab as TabType) ? savedTab as TabType : 'general')
  })

  // Persist active tab to localStorage
  useEffect(() => {
    localStorage.setItem('settingsActiveTab', activeTab)
  }, [activeTab])

  // Service Health Status
  const [serviceHealth, setServiceHealth] = useState<ServiceHealth>({
    gateway: 'checking',
    wsi: 'checking',
    ai: 'checking'
  })

  // Confirmation Dialog State (shared across tabs)
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {},
    confirmText: 'Confirm',
    confirmVariant: 'danger'
  })

  // Shared confirm dialog helpers
  const showConfirmDialog: ShowConfirmDialog = (config) => {
    setConfirmDialog({ ...config, isOpen: true })
  }

  const closeConfirmDialog = () => {
    setConfirmDialog(prev => ({ ...prev, isOpen: false }))
  }

  const checkServiceHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) })
      setServiceHealth(prev => ({ ...prev, gateway: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, gateway: 'offline' }))
    }
    try {
      const res = await fetch(`${PREPROCESSING_BASE}/health`, { signal: AbortSignal.timeout(3000) })
      setServiceHealth(prev => ({ ...prev, wsi: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, wsi: 'offline' }))
    }
    try {
      const res = await fetch(`${AI_BASE.replace('/api/ai', '')}/health`, { signal: AbortSignal.timeout(30000) })
      setServiceHealth(prev => ({ ...prev, ai: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, ai: 'offline' }))
    }
  }, [])

  useEffect(() => {
    checkServiceHealth()
  }, [checkServiceHealth])

  const tabs = [
    { id: 'general' as TabType, name: 'General', icon: Bot, description: 'AI & API Configuration' },
    { id: 'tasks' as TabType, name: 'Tasks', icon: ClipboardList, description: 'Task Management' },
    { id: 'models' as TabType, name: 'Models', icon: Database, description: 'Model Management' },
    { id: 'storage' as TabType, name: 'Storage', icon: HardDrive, description: 'Storage & Cleanup' },
    { id: 'users' as TabType, name: 'Users', icon: Users, description: 'User Management' },
    { id: 'feedback' as TabType, name: 'Feedback', icon: MessageSquare, description: 'User Feedback Analytics' },
  ]

  return (
    <div className="w-full">
      <PageHeader title="Settings" description="Configure your PathLab platform">
        <Button variant="outline" onClick={() => navigate('/dashboard')} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Button>
      </PageHeader>

      {/* Tab Navigation */}
      <Card className="mb-6">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px overflow-x-auto w-full" aria-label="Tabs">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`
                    group inline-flex items-center justify-center px-4 py-3 sm:px-6 sm:py-4 border-b-2 font-medium text-sm whitespace-nowrap flex-1 transition-colors
                    ${isActive
                      ? 'border-primary-500 text-primary-600 bg-primary-50/10'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 hover:bg-gray-50/50'
                    }
                  `}
                >
                  <Icon className={`mr-2 h-5 w-5 ${isActive ? 'text-primary-600' : 'text-gray-400 group-hover:text-gray-500'}`} />
                  <div className="text-left">
                    <div>{tab.name}</div>
                    <div className="text-xs text-gray-400 font-normal">{tab.description}</div>
                  </div>
                </button>
              )
            })}
          </nav>
        </div>
      </Card>

      {/* Tab Content */}
      <div className="space-y-6">
        {activeTab === 'general' && (
          <GeneralTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />
        )}
        {activeTab === 'tasks' && (
          <TasksTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />
        )}
        {activeTab === 'models' && (
          <ModelsTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />
        )}
        {activeTab === 'storage' && (
          <StorageTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />
        )}
        {activeTab === 'users' && (
          <UsersTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} currentUserId={currentUser?.id} />
        )}
        {activeTab === 'feedback' && (
          <FeedbackTab showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />
        )}

        {/* System Information - Show on all tabs except storage and feedback */}
        {activeTab !== 'storage' && activeTab !== 'feedback' && (
          <Card className="p-4 sm:p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
                <Info className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700" />
                System Information
              </h2>
              <button
                onClick={checkServiceHealth}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                title="Refresh status"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">Platform Version</span>
                <span className="text-sm text-gray-600">v1.0.0</span>
              </div>
              {(['gateway', 'wsi', 'ai'] as const).map((service) => (
                <div key={service} className={`flex justify-between py-2 ${service !== 'ai' ? 'border-b border-gray-100' : ''}`}>
                  <span className="text-sm font-medium text-gray-700">
                    {service === 'gateway' ? 'Gateway Service' : service === 'wsi' ? 'WSI Service' : 'AI Service'}
                  </span>
                  <span className={`text-sm flex items-center ${
                    serviceHealth[service] === 'online' ? 'text-green-600' :
                    serviceHealth[service] === 'checking' ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                    <div className={`w-2 h-2 rounded-full mr-2 ${
                      serviceHealth[service] === 'online' ? 'bg-green-500' :
                      serviceHealth[service] === 'checking' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
                    }`}></div>
                    {serviceHealth[service] === 'online' ? 'Online' :
                      serviceHealth[service] === 'checking' ? 'Checking...' : 'Offline'}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Confirmation Dialog */}
        <ConfirmDialog dialog={confirmDialog} onClose={closeConfirmDialog} />

        {/* About - Show on all tabs except storage, users, and feedback */}
        {activeTab !== 'storage' && activeTab !== 'users' && activeTab !== 'feedback' && (
          <Card className="p-4 sm:p-6">
            <h2 className="text-lg sm:text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <BookOpen className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700" />
              About
            </h2>
            <div className="space-y-3 text-sm text-gray-600">
              <p>
                <strong className="text-gray-900">PathLab</strong> is an AI-powered pathology analysis platform
                for pathology image analysis.
              </p>
              <p>
                The platform integrates state-of-the-art deep learning models with an intuitive
                AI assistant to help researchers set up and run pathology analysis tasks.
              </p>
              <p>
                Proudly developed by <a href="https://smartlab.cse.ust.hk/" target="_blank" rel="noopener noreferrer">SmartLab</a>.
              </p>
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}

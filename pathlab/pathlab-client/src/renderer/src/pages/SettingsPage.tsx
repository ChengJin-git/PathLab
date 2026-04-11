import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bot, ClipboardList, Database, Info, BookOpen, HardDrive, RefreshCw, ArrowLeft, Users, MessageSquare } from 'lucide-react'

import { useAuth } from '../contexts/AuthContext'
import { API_BASE, PREPROCESSING_BASE, AI_BASE } from '../config'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Tooltip } from '../components/ui/tooltip'
import {
  ConfirmDialog,
  GeneralTab,
  TasksTab,
  ModelsTab,
  StorageTab,
  UsersTab,
  FeedbackTab
} from '../components/settings'
import { useConfirmDialog } from '../lib/useConfirmDialog'

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
  const { t } = useTranslation()

  // Redirect non-admin users to AI chat
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
  const { dialogState: confirmDialog, showConfirmDialog, closeConfirmDialog } = useConfirmDialog()

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
    { id: 'general' as TabType, name: t('settings.tabs.general'), icon: Bot, description: t('settings.tabs.generalDesc') },
    { id: 'tasks' as TabType, name: t('settings.tabs.tasks'), icon: ClipboardList, description: t('settings.tabs.tasksDesc') },
    { id: 'models' as TabType, name: t('settings.tabs.models'), icon: Database, description: t('settings.tabs.modelsDesc') },
    { id: 'storage' as TabType, name: t('settings.tabs.storage'), icon: HardDrive, description: t('settings.tabs.storageDesc') },
    { id: 'users' as TabType, name: t('settings.tabs.users'), icon: Users, description: t('settings.tabs.usersDesc') },
    { id: 'feedback' as TabType, name: t('settings.tabs.feedback'), icon: MessageSquare, description: t('settings.tabs.feedbackDesc') },
  ]

  return (
    <div className="w-full">
      <PageHeader title={t('settings.title')} description={t('settings.description')}>
        <Button variant="outline" onClick={() => navigate('/dashboard')} className="gap-2">
          <ArrowLeft className="w-4 h-4" />
          {t('settings.backToDashboard')}
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
                    group inline-flex items-center justify-center px-3 py-3 sm:px-6 sm:py-4 border-b-2 font-medium text-sm whitespace-nowrap flex-1 transition-colors
                    ${isActive
                      ? 'border-primary-500 text-primary-600 bg-primary-50/10'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 hover:bg-gray-50/50'
                    }
                  `}
                >
                  <Icon className={`h-5 w-5 sm:mr-2 ${isActive ? 'text-primary-600' : 'text-gray-400 group-hover:text-gray-500'}`} />
                  <div className="text-left hidden sm:block">
                    <div>{tab.name}</div>
                    <div className="text-xs text-gray-400 font-normal hidden md:block">{tab.description}</div>
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
                {t('settings.systemInfo')}
              </h2>
              <Tooltip content={t('settings.refreshStatus')}>
              <button
                onClick={checkServiceHealth}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
              </Tooltip>
            </div>
            <div className="space-y-3">
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">{t('settings.platformVersion')}</span>
                <span className="text-sm text-gray-600">v1.0.5</span>
              </div>
              {(['gateway', 'wsi', 'ai'] as const).map((service) => (
                <div key={service} className={`flex justify-between py-2 ${service !== 'ai' ? 'border-b border-gray-100' : ''}`}>
                  <span className="text-sm font-medium text-gray-700">
                    {service === 'gateway' ? t('settings.gatewayService') : service === 'wsi' ? t('settings.wsiService') : t('settings.aiService')}
                  </span>
                  <span className={`text-sm flex items-center ${
                    serviceHealth[service] === 'online' ? 'text-green-600' :
                    serviceHealth[service] === 'checking' ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                    <div className={`w-2 h-2 rounded-full mr-2 ${
                      serviceHealth[service] === 'online' ? 'bg-green-500' :
                      serviceHealth[service] === 'checking' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
                    }`}></div>
                    {serviceHealth[service] === 'online' ? t('common.online') :
                      serviceHealth[service] === 'checking' ? t('common.checking') : t('common.offline')}
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
            <div>
              <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
                <BookOpen className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700" />
                {t('settings.about')}
              </h2>

              <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.9fr)] lg:gap-8">
                <div className="space-y-4 sm:space-y-5">
                  <div>
                    <h3 className="text-2xl sm:text-3xl font-semibold tracking-tight text-gray-900">
                      {t('settings.aboutText1Part1')}
                    </h3>
                  </div>

                  <p className="text-sm sm:text-base leading-7 text-gray-600">
                    {t('settings.aboutText1Part2').trim()}
                  </p>

                  <p className="text-sm leading-7 text-gray-600">
                    {t('settings.aboutText2')}
                  </p>
                </div>

                <div className="border-t border-gray-100 pt-5 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8">
                  <div className="flex flex-col items-start">
                    <a
                      href="https://smartx.ust.hk/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex max-w-full items-center transition-opacity hover:opacity-100 opacity-90"
                    >
                      <img src="/images/smartlab-logo.svg" alt="SmartLab" className="h-10 sm:h-11 w-auto" />
                    </a>

                    <p className="mt-4 text-sm leading-6 text-gray-700">{t('settings.aboutText3')}</p>

                    <a
                      href="https://smartx.ust.hk/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-4 inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-700 hover:underline"
                    >
                      <span className="break-all">smartx.ust.hk</span>
                    </a>

                    <p className="mt-4 text-xs leading-5 text-gray-500">
                      {t('common.copyright')} <a href="https://smartx.ust.hk/" target="_blank" rel="noopener noreferrer" className="font-medium text-gray-700 hover:underline">SmartXLab</a> · {t('introduction.allRightsReserved')}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}

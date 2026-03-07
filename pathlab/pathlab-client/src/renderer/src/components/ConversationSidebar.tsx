import React, { useState, useEffect, useCallback, useRef } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Clock, History, Loader2, MessageSquare, Plus, Trash2, Menu,
  Database, Brain, LineChart, ChevronRight, Wrench
} from 'lucide-react'
import { deleteConversation, getConversations, type Conversation } from '../api'
import { listActiveResearchJobs } from '../lib/deep-research/api/chat'
import { resetDeepResearchSession, useStore } from '../lib/deep-research/store'
import { stripResearchMeta } from '../lib/deep-research/utils/strip-research-meta'
import { cn } from '../lib/utils'

export default function ConversationSidebar() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { conversationId: urlConversationId } = useParams<{ conversationId?: string }>()

  // Sidebar visibility state (synced with localStorage)
  const [showHistory, setShowHistory] = useState(() => {
    if (window.innerWidth < 1024) return false
    const saved = localStorage.getItem('ai-chat-sidebar-open')
    if (saved !== null) return saved === 'true'
    return true
  })

  // Conversation list
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [isLoadingConversations, setIsLoadingConversations] = useState(false)

  // Delete confirmation modal
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  // Active research jobs from zustand store
  const activeResearchJobs = useStore((state) => state.activeResearchJobs)
  const currentConversationHasCompletedReport = useStore((state) => {
    return state.researchIds.some((researchId) => {
      const reportId = state.researchReportIds.get(researchId)
      const reportMessage = reportId ? state.messages.get(reportId) : undefined
      return stripResearchMeta(reportMessage?.content ?? '').trim().length > 0
    })
  })

  // Derive current conversation ID from URL
  const currentConversationId = urlConversationId || null

  // Persist sidebar state & broadcast width via CSS variable
  useEffect(() => {
    localStorage.setItem('ai-chat-sidebar-open', String(showHistory))
    // Expose sidebar width so fixed-position input boxes can offset their left edge
    document.documentElement.style.setProperty(
      '--sidebar-width',
      showHistory ? '288px' : '56px',   // w-72 = 288px, w-14 = 56px
    )
  }, [showHistory])

  // Listen for mobile sidebar toggle from Layout header hamburger button
  useEffect(() => {
    const handleToggle = () => setShowHistory((prev) => !prev)
    window.addEventListener('toggle-ai-sidebar', handleToggle)
    return () => window.removeEventListener('toggle-ai-sidebar', handleToggle)
  }, [])

  // Load conversations
  const loadConversations = useCallback(async () => {
    try {
      setIsLoadingConversations(true)
      const data = await getConversations(0, 100)
      setConversations(data)
    } catch (error) {
      console.warn('[ConversationSidebar] Failed to load conversations:', error)
    } finally {
      setIsLoadingConversations(false)
    }
  }, [])

  // Stable ref for event handlers
  const loadConversationsRef = useRef(loadConversations)
  loadConversationsRef.current = loadConversations

  // Listen for conversation changes from child pages (e.g., new conversation created)
  useEffect(() => {
    const handleConversationsChanged = () => void loadConversationsRef.current()
    window.addEventListener('conversations-changed', handleConversationsChanged)
    return () => window.removeEventListener('conversations-changed', handleConversationsChanged)
  }, [])

  // Load on mount
  useEffect(() => {
    void loadConversations()
  }, [loadConversations])

  // Reload when the sidebar opens.
  // Do not reload just because the selected conversation changed; opening an
  // existing history item should keep the current list stable instead of
  // flashing a loading state.
  useEffect(() => {
    if (showHistory) {
      void loadConversations()
    }
  }, [showHistory, loadConversations])

  // Poll active research jobs every 15 seconds
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      if (cancelled) return
      try {
        const jobs = await listActiveResearchJobs()
        if (cancelled) return
        const jobMap = new Map<string, { jobId: string; status: string; currentStage?: string }>()
        for (const j of jobs) {
          if (j.conversationId) {
            jobMap.set(j.conversationId, {
              jobId: j.jobId,
              status: j.status,
              currentStage: j.currentStage,
            })
          }
        }
        useStore.getState().setActiveResearchJobs(jobMap)
      } catch {
        // ignore polling errors
      }
    }
    void poll()
    const timer = setInterval(poll, 15000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  // Navigate to a conversation based on its type
  const preserveAIChatReturnContext = useCallback(() => {
    if (!location.pathname.startsWith('/dashboard') && !location.pathname.startsWith('/ai-chat')) {
      return null
    }

    const messagesContainer = document.querySelector('[data-chat-messages-container]') as HTMLElement | null
    if (messagesContainer) {
      sessionStorage.setItem('ai-chat-scroll-position', String(messagesContainer.scrollTop))
    }

    const aiConversationId =
      urlConversationId
      || document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
      || null

    if (aiConversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', aiConversationId)
    }

    return aiConversationId
  }, [location.pathname, urlConversationId])

  const openConversation = (targetConversationId: string) => {
    const conv = conversations.find(c => c.conversation_id === targetConversationId)
    const route = conv?.conversation_type === 'ai_chat' ? 'dashboard' : 'deep-research'
    const returnToAIChatConversationId = route === 'deep-research'
      ? preserveAIChatReturnContext()
      : null

    navigate(`/${route}/${targetConversationId}`, {
      state: returnToAIChatConversationId ? { returnToAIChatConversationId } : undefined
    })
    if (window.innerWidth < 1024) {
      setShowHistory(false)
    }
  }

  // New chat → reset DR state and force AI Chat welcome page (do not restore old session)
  const handleNewChat = () => {
    resetDeepResearchSession()
    navigate('/dashboard', {
      replace: true,
      state: { forceNewChat: true }
    })
    if (window.innerWidth < 1024) {
      setShowHistory(false)
    }
  }

  // Delete handlers (modal-based)
  const handleDeleteConversation = (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setDeleteConfirmId(conversationId)
  }

  const handleDeleteAllHistory = () => {
    if (conversations.length === 0) return
    setDeleteConfirmId('all-conversations')
  }

  const confirmDelete = async () => {
    if (!deleteConfirmId) return
    try {
      if (deleteConfirmId === 'all-conversations') {
        await Promise.all(conversations.map(conv => deleteConversation(conv.conversation_id)))
        await loadConversations()
        handleNewChat()
      } else {
        await deleteConversation(deleteConfirmId)
        await loadConversations()
        if (currentConversationId === deleteConfirmId) {
          handleNewChat()
        }
      }
    } catch (error) {
      console.warn('[ConversationSidebar] Failed to delete:', error)
    } finally {
      setDeleteConfirmId(null)
    }
  }

  const cancelDelete = () => {
    setDeleteConfirmId(null)
  }

  // Determine active conversation ID for highlighting.
  // For deep-research pages, also check the zustand store's conversationId
  // (which gets set before the URL updates).
  const storeConversationId = useStore((state) => state.conversationId)
  const isViewingDeepResearchConversation = location.pathname.startsWith('/deep-research')
  const activeConversationId = currentConversationId
    || (location.pathname.startsWith('/deep-research') ? storeConversationId : null)

  return (
    <>
      {/* Mobile sidebar overlay backdrop */}
      {showHistory && (
        <div
          className="fixed top-16 inset-x-0 bottom-0 bg-black/20 z-30 lg:hidden backdrop-blur-sm transition-opacity"
          onClick={() => setShowHistory(false)}
        />
      )}

      {/* Sidebar panel */}
      <div
        className={`bg-gray-50 border-r border-gray-200 flex flex-col overflow-hidden
          fixed top-16 bottom-0 left-0 z-40 w-72 transition-transform duration-300 ease-in-out
          ${showHistory ? 'translate-x-0' : '-translate-x-full'}
          lg:relative lg:top-auto lg:bottom-auto lg:z-auto lg:flex-shrink-0 lg:translate-x-0 lg:transition-all
          ${showHistory ? 'lg:w-72' : 'lg:w-14'}
        `}
        role="navigation"
        aria-label={t('aiChat.history')}
      >
        {/* Desktop toggle button */}
        <div className={`hidden lg:flex items-center gap-1 p-2 pt-3 ${showHistory ? 'px-3' : 'flex-col'}`}>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors flex-shrink-0"
            title={showHistory ? t('aiChat.closeChatHistory') : t('aiChat.openChatHistory')}
          >
            <Menu className="w-5 h-5" />
          </button>
        </div>

        {/* Expanded sidebar content */}
        <div className={`w-[268px] min-w-[268px] flex flex-col flex-1 overflow-hidden transition-opacity duration-300 ease-in-out pt-6 lg:pt-0 ${showHistory ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}>
          {/* New Chat Button */}
          <div className="px-3 pb-3 pt-0">
            <button
              onClick={handleNewChat}
              className="w-full px-4 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-all shadow-sm flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              {t('aiChat.newChat')}
            </button>
          </div>

          {/* Tools Section */}
          <div className="px-3 pb-2 border-b border-gray-100">
            <div className="flex items-center gap-2 px-2 mb-2">
              <Wrench className="w-4 h-4 text-gray-400" />
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">{t('aiChat.sidebar.tools')}</h3>
            </div>
            <div className="space-y-0.5">
              <button
                onClick={() => { navigate('/register'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-orange-50 hover:text-orange-700 transition-colors group"
              >
                <Plus className="w-4 h-4 text-orange-500 group-hover:text-orange-600" />
                <span className="flex-1 text-left">{t('aiChat.sidebar.registerData')}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-orange-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/wsi-list'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-700 transition-colors group"
              >
                <Database className="w-4 h-4 text-blue-500 group-hover:text-blue-600" />
                <span className="flex-1 text-left">{t('aiChat.sidebar.dataRepository')}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/task-list'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-violet-50 hover:text-violet-700 transition-colors group"
              >
                <Brain className="w-4 h-4 text-violet-500 group-hover:text-violet-600" />
                <span className="flex-1 text-left">{t('aiChat.sidebar.analysisLab')}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-violet-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/tools'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors group"
              >
                <LineChart className="w-4 h-4 text-emerald-500 group-hover:text-emerald-600" />
                <span className="flex-1 text-left">{t('aiChat.sidebar.insightsReports')}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-emerald-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
            </div>
          </div>

          {/* History Section */}
          <div className="flex items-center justify-between px-5 pt-3 pb-1">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-gray-400" />
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">{t('aiChat.history')}</h3>
            </div>
            {conversations.length > 0 && (
              <button
                onClick={handleDeleteAllHistory}
                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                title={t('aiChat.deleteAllHistory')}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-3">
            {isLoadingConversations ? (
              <div className="flex flex-col items-center justify-center py-12">
                <Loader2 className="w-8 h-8 text-primary-500 animate-spin mb-3" />
                <p className="text-sm text-gray-500">{t('aiChat.loadingConversations')}</p>
              </div>
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-3">
                  <MessageSquare className="w-8 h-8 text-gray-300" />
                </div>
                <p className="text-sm font-medium text-gray-900 mb-1">{t('aiChat.noConversationsYet')}</p>
                <p className="text-xs text-gray-500">{t('aiChat.startNewChat')}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {conversations.map((conv) => (
                  (() => {
                    const shouldSuppressActiveJobIndicator =
                      isViewingDeepResearchConversation
                      && conv.conversation_id === storeConversationId
                      && currentConversationHasCompletedReport
                    const activeResearchJob = shouldSuppressActiveJobIndicator
                      ? undefined
                      : activeResearchJobs.get(conv.conversation_id)

                    return (
                  <div
                    key={conv.conversation_id}
                    onClick={() => openConversation(conv.conversation_id)}
                    className={cn(
                      'group relative p-3 rounded-xl cursor-pointer transition-all border',
                      activeConversationId === conv.conversation_id
                        ? 'bg-primary-50 border-primary-200 shadow-sm'
                        : 'hover:bg-gray-50 border-transparent hover:border-gray-100'
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <h3 className={cn(
                          'text-sm font-medium truncate mb-1',
                          activeConversationId === conv.conversation_id
                            ? 'text-primary-900'
                            : 'text-gray-900'
                        )}>
                          {conv.title || t('aiChat.untitledConversation')}
                        </h3>
                        {activeResearchJob ? (
                          <div className="flex items-center gap-1.5 text-xs text-blue-600">
                            <Loader2 className="w-3 h-3 animate-spin" />
                            <span>
                              {(() => {
                                const stage = activeResearchJob.currentStage
                                const stageLabels: Record<string, string> = {
                                  coordinating: t('aiChat.researchStages.coordinating'),
                                  planning: t('aiChat.researchStages.planning'),
                                  researching: t('aiChat.researchStages.researching'),
                                  coding: t('aiChat.researchStages.coding'),
                                  writing_report: t('aiChat.researchStages.writingReport'),
                                }
                                return stage && stageLabels[stage]
                                  ? stageLabels[stage]
                                  : t('aiChat.researchStages.researching')
                              })()}
                            </span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-xs text-gray-500">
                            <Clock className="w-3 h-3" />
                            {new Date(conv.updated_at).toLocaleDateString([], {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </div>
                        )}
                      </div>
                      <button
                        onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                        className="sm:opacity-0 sm:group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                        title={t('aiChat.deleteConversation')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                    )
                  })()
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div
          className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-dialog-title"
          onKeyDown={(e) => e.key === 'Escape' && cancelDelete()}
        >
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all scale-100">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <div className="flex-1">
                <h3 id="delete-dialog-title" className="text-lg font-semibold text-gray-900 mb-2">
                  {deleteConfirmId === 'all-conversations' ? t('aiChat.deleteAllHistoryTitle') : t('aiChat.deleteConversationTitle')}
                </h3>
                <p className="text-sm text-gray-600 mb-6">
                  {deleteConfirmId === 'all-conversations'
                    ? t('aiChat.deleteAllHistoryConfirm')
                    : t('aiChat.deleteConversationConfirm')}
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={cancelDelete}
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                  >
                    {t('common.cancel')}
                  </button>
                  <button
                    onClick={confirmDelete}
                    className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors shadow-sm"
                  >
                    {t('common.delete')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

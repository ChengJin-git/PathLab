import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Upload, PlayCircle, FlaskConical, X } from 'lucide-react'
import { getWorkspaceSelection } from '../../lib/workspaceSelection'
import { Button } from '../ui/button'

export interface NavigationConfig {
  target: string
  state?: {
    datasetName?: string
    uploadMode?: 'classification' | 'survival' | 'segmentation'
    dataLevel?: 'case' | 'file'
    csvContent?: string
    csvFileName?: string
    researchGoal?: string
    datasetIds?: string[]
  }
  buttonText?: string
  /** i18n key for buttonText — takes priority over buttonText when present */
  buttonTextKey?: string
  description?: string
  /** i18n key for description — takes priority over description when present */
  descriptionKey?: string
  /** Navigation type: 'register' for upload page, 'task' for task detail page, 'batch-task' for batch inference task detail */
  type?: 'register' | 'task' | 'batch-task' | 'research'
  execute?: boolean
  /** Task ID for task navigation */
  taskId?: string
  /** Task name for display */
  taskName?: string
}

interface NavigationCardProps {
  config: NavigationConfig
  csvContent?: string
  csvFileName?: string
  conversationId?: string
}

/**
 * Parse [NAVIGATE] block from message content
 */
export function parseNavigateBlock(content: string): NavigationConfig | null {
  const match = content.match(/\[NAVIGATE\]\s*([\s\S]*?)\s*\[\/NAVIGATE\]/i)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    const config = JSON.parse(jsonStr) as NavigationConfig
    
    // Validate required fields
    if (!config.target || (config.type !== 'research' && !config.buttonText && !config.buttonTextKey)) {
      console.error('NavigationCard: Missing target or navigation button label')
      return null
    }
    
    return config
  } catch (e) {
    console.error('Failed to parse NAVIGATE block:', e)
    return null
  }
}

/**
 * Remove [NAVIGATE] block from message content for display
 */
export function removeNavigateBlock(content: string): string {
  return content.replace(/\[NAVIGATE\]\s*[\s\S]*?\s*\[\/NAVIGATE\]/gi, '').trim()
}

/**
 * NavigationCard component - renders a clickable card to navigate to another page
 * Used by AI Chat to guide users to Registration Page or Task Detail Page
 */
export function NavigationCard({ config, csvContent, csvFileName, conversationId }: NavigationCardProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(false)
  const dismissalKey = `chat:research-hint-dismissed:${conversationId || 'new'}`
  useEffect(() => {
    const restore = () => {
      try { setDismissed(sessionStorage.getItem(dismissalKey) === '1') } catch { /* Storage may be unavailable. */ }
    }
    restore()
    window.addEventListener('chat:research-hint-dismissed', restore)
    return () => window.removeEventListener('chat:research-hint-dismissed', restore)
  }, [dismissalKey])
  const dismiss = () => {
    setDismissed(true)
    try { sessionStorage.setItem(dismissalKey, '1') } catch { /* Keep the in-memory choice. */ }
    window.dispatchEvent(new Event('chat:research-hint-dismissed'))
  }

  const resolvedButtonText = config.buttonTextKey ? t(config.buttonTextKey) : config.buttonText
  const resolvedDescription = config.descriptionKey ? t(config.descriptionKey) : config.description

  const handleNavigate = () => {
    if (config.type === 'research') {
      window.dispatchEvent(new CustomEvent('workbench:select-research', { detail: {
        goal: String(config.state?.researchGoal || '').slice(0, 12000), conversationId,
        datasetIds: (Array.isArray(config.state?.datasetIds) ? config.state.datasetIds : []).filter(id => typeof id === 'string')
      } }))
      return
    }
    // Save current conversation ID from the data attribute
    const activeConversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
    if (activeConversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', activeConversationId)
    }

    // Build navigation state
    const state: Record<string, unknown> = { ...config.state, fromAIChat: true }

    // If we have CSV content from the chat, include it
    if (csvContent && csvFileName) {
      state.csvContent = csvContent
      state.csvFileName = csvFileName
    }

    navigate(config.target, { state })
  }

  if (config.type === 'research') {
    if (config.execute) return null
    if (dismissed || getWorkspaceSelection().executionMode === 'read_only') return null
    return <aside role="status" className="my-4 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
      <div className="flex items-start gap-3"><FlaskConical size={20} className="mt-0.5 shrink-0 text-blue-600" /><div className="flex-1"><h3 className="text-sm font-semibold text-gray-900">{t('autoResearch.title')}</h3><p className="mt-1 text-sm leading-6 text-gray-600">{resolvedDescription}</p></div><button onClick={dismiss} aria-label={t('common.close')} className="cursor-pointer rounded p-1 text-gray-500 hover:bg-blue-100 hover:text-gray-700"><X size={16} /></button></div>
      <button onClick={handleNavigate} className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">{t('autoResearch.open')}<ArrowRight size={15} /></button>
    </aside>
  }

  // Batch inference task navigation card (purple theme)
  if (config.type === 'batch-task') {
    return (
      <div className="my-4 p-4 bg-gradient-to-r from-purple-50 to-violet-50 border border-purple-200 rounded-xl shadow-sm">
        {resolvedDescription && (
          <p className="text-sm text-slate-600 mb-3">{resolvedDescription}</p>
        )}

        <Button
          onClick={handleNavigate}
          className="w-full bg-purple-600 hover:bg-purple-700 text-white font-medium py-3 rounded-lg flex items-center justify-center gap-2 shadow-md hover:shadow-lg transition-all"
        >
          <PlayCircle className="w-4 h-4" />
          {resolvedButtonText}
          <ArrowRight className="w-4 h-4" />
        </Button>

        {(config.taskId || config.taskName) && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {config.taskName && (
              <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
                {t('chatComponents.navigationCard.task')}{' '}<strong className="text-slate-800">{config.taskName}</strong>
              </span>
            )}
            {config.taskId && (
              <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
                {t('chatComponents.navigationCard.id')}{' '}<strong className="text-slate-800 font-mono text-[10px]">{config.taskId}</strong>
              </span>
            )}
            <span className="px-2 py-1 bg-purple-50 rounded-md border border-purple-200 text-purple-700">
              ✓ {t('chatComponents.navigationCard.inferenceStarted')}
            </span>
          </div>
        )}
      </div>
    )
  }


  // Task navigation card (green theme)
  if (config.type === 'task') {
    return (
      <div className="my-4 p-4 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-xl shadow-sm">
        {resolvedDescription && (
          <p className="text-sm text-slate-600 mb-3">{resolvedDescription}</p>
        )}

        <Button
          onClick={handleNavigate}
          className="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-3 rounded-lg flex items-center justify-center gap-2 shadow-md hover:shadow-lg transition-all"
        >
          <PlayCircle className="w-4 h-4" />
          {resolvedButtonText}
          <ArrowRight className="w-4 h-4" />
        </Button>

        {(config.taskId || config.taskName) && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            {config.taskName && (
              <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
                {t('chatComponents.navigationCard.task')}{' '}<strong className="text-slate-800">{config.taskName}</strong>
              </span>
            )}
            {config.taskId && (
              <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
                {t('chatComponents.navigationCard.id')}{' '}<strong className="text-slate-800 font-mono text-[10px]">{config.taskId}</strong>
              </span>
            )}
            <span className="px-2 py-1 bg-green-50 rounded-md border border-green-200 text-green-700">
              ✓ {t('chatComponents.navigationCard.trainingStarted')}
            </span>
          </div>
        )}
      </div>
    )
  }

  // Default: Registration navigation card (blue theme)
  return (
    <div className="my-4 p-4 bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl shadow-sm">
      {resolvedDescription && (
        <p className="text-sm text-slate-600 mb-3">{resolvedDescription}</p>
      )}

      <Button
        onClick={handleNavigate}
        className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-3 rounded-lg flex items-center justify-center gap-2 shadow-md hover:shadow-lg transition-all"
      >
        <Upload className="w-4 h-4" />
        {resolvedButtonText}
        <ArrowRight className="w-4 h-4" />
      </Button>

      {config.state?.datasetName && (
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
            {t('chatComponents.navigationCard.dataset')}{' '}<strong className="text-slate-800">{config.state.datasetName}</strong>
          </span>
          {config.state.uploadMode && (
            <span className="px-2 py-1 bg-white rounded-md border border-slate-200 text-slate-600">
              {t('chatComponents.navigationCard.type')}{' '}<strong className="text-slate-800 capitalize">{config.state.uploadMode}</strong>
            </span>
          )}
          {(csvContent || config.state.csvContent) && (
            <span className="px-2 py-1 bg-green-50 rounded-md border border-green-200 text-green-700">
              ✓ {t('chatComponents.navigationCard.csvReady')}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

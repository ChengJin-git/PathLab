import React, { useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { BookOpenText, ArrowRight, AlertTriangle } from 'lucide-react'
import { getConversation } from '../../api/chat'
import { ApiError } from '../../api/client'

export interface DeepResearchLinkConfig {
  conversation_id: string
  research_id?: string
  title?: string
}

export function parseDeepResearchLinkBlock(content: string): DeepResearchLinkConfig | null {
  const match = content.match(/\[DEEP_RESEARCH_LINK\]\s*([\s\S]*?)\s*\[\/DEEP_RESEARCH_LINK\]/i)
  if (!match) return null
  try {
    const config = JSON.parse(match[1].trim()) as DeepResearchLinkConfig
    if (!config.conversation_id) return null
    return config
  } catch {
    return null
  }
}

export function removeDeepResearchLinkBlock(content: string): string {
  return content.replace(/\[DEEP_RESEARCH_LINK\]\s*[\s\S]*?\s*\[\/DEEP_RESEARCH_LINK\]/gi, '').trim()
}

export function DeepResearchLinkCard({ config }: { config: DeepResearchLinkConfig }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [status, setStatus] = useState<'idle' | 'checking' | 'notFound'>('idle')

  const handleView = useCallback(async () => {
    if (status === 'checking') return
    setStatus('checking')
    try {
      await getConversation(config.conversation_id)
      navigate(`/deep-research/${config.conversation_id}`)
      setStatus('idle')
    } catch (e) {
      if (e instanceof ApiError && e.isNotFound()) {
        setStatus('notFound')
      } else {
        // Network or other error — still navigate; page will handle it
        navigate(`/deep-research/${config.conversation_id}`)
        setStatus('idle')
      }
    }
  }, [config.conversation_id, navigate, status])

  if (status === 'notFound') {
    return (
      <div className="my-2 p-4 bg-gray-50 border border-gray-200 rounded-xl shadow-sm">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gray-100">
            <AlertTriangle className="h-4 w-4 text-gray-400" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-gray-500">
              {t('chatComponents.deepResearchLink.title', { defaultValue: 'Deep Research Report' })}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              {t('chatComponents.deepResearchLink.notFound', { defaultValue: 'The linked deep research has been deleted.' })}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="my-2 p-4 bg-gradient-to-r from-violet-50 to-purple-50 border border-violet-200 rounded-xl shadow-sm">
      <div className="flex items-start gap-3 mb-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-violet-100">
          <BookOpenText className="h-4 w-4 text-violet-600" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-violet-900">
            {t('chatComponents.deepResearchLink.title', { defaultValue: 'Deep Research Report' })}
          </p>
          {config.title && (
            <p className="text-xs text-violet-600 mt-0.5 truncate">{config.title}</p>
          )}
        </div>
      </div>
      <button
        onClick={handleView}
        disabled={status === 'checking'}
        className="w-full px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white text-sm font-medium rounded-lg flex items-center justify-center gap-2 shadow-sm hover:shadow-md transition-all"
      >
        <BookOpenText className="w-4 h-4" />
        {status === 'checking'
          ? t('chatComponents.deepResearchLink.checking', { defaultValue: 'Loading...' })
          : t('chatComponents.deepResearchLink.viewReport', { defaultValue: 'View Full Research Report' })}
        {status !== 'checking' && <ArrowRight className="w-4 h-4" />}
      </button>
    </div>
  )
}

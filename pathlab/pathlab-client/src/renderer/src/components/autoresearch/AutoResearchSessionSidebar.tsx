import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAutoResearchTranslation } from '../../lib/useAutoResearchTranslation'
import { Beaker, History, Loader2, Plus, Trash2 } from 'lucide-react'
import { listAutoResearchSessions, deleteAutoResearchSession } from '../../api/autoresearch'
import type { AutoResearchSessionSummary } from '../../types/autoresearch'
import { dedupeAutoResearchSessions, isLiveSessionStatus } from '../../lib/autoresearchSessions'
import {
  AUTORESEARCH_SESSION_CREATED_EVENT,
  sessionFromAutoResearchSessionCreatedEvent,
} from '../../lib/autoresearchSessionEvents'
import AutoResearchBackButton from './AutoResearchBackButton'
import AutoResearchSessionListItem from './AutoResearchSessionListItem'
import { ConfirmDialog } from '../settings/ConfirmDialog'

export default function AutoResearchSessionSidebar() {
  type LoadSessionsOptions = {
    merge?: boolean
  }

  const { t } = useAutoResearchTranslation()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<AutoResearchSessionSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set())
  const [sharingIds, setSharingIds] = useState<Set<string>>(new Set())
  const [dialogState, setDialogState] = useState({ isOpen: false, title: '', message: '', onConfirm: () => {} })

  const showConfirmDialog = (config: { title: string; message: string; onConfirm: () => void }) => {
    setDialogState({ isOpen: true, ...config })
  }

  const closeConfirmDialog = () => {
    setDialogState({ isOpen: false, title: '', message: '', onConfirm: () => {} })
  }

  const loadSessions = async (silent = false, options: LoadSessionsOptions = {}) => {
    if (!silent) setIsLoading(true)
    try {
      const result = await listAutoResearchSessions()
      const nextSessions = result.items || []
      setSessions((current) => options.merge
        ? dedupeAutoResearchSessions([...nextSessions, ...current])
        : nextSessions)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : t('autoResearch.loadSessionsFailed'))
    } finally {
      if (!silent) setIsLoading(false)
    }
  }

  useEffect(() => {
    void loadSessions()
  }, [])

  useEffect(() => {
    const handleSessionCreated = (event: Event) => {
      const session = sessionFromAutoResearchSessionCreatedEvent(event)
      if (!session) return
      setSessions((current) => dedupeAutoResearchSessions([session, ...current]))
      void loadSessions(true, { merge: true })
    }
    window.addEventListener(AUTORESEARCH_SESSION_CREATED_EVENT, handleSessionCreated)
    return () => {
      window.removeEventListener(AUTORESEARCH_SESSION_CREATED_EVENT, handleSessionCreated)
    }
  }, [t])

  const visibleSessions = useMemo(() => dedupeAutoResearchSessions(sessions), [sessions])

  useEffect(() => {
    if (!visibleSessions.some((session) => isLiveSessionStatus(session.status))) return undefined
    const timer = window.setInterval(() => {
      void loadSessions(true)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [visibleSessions])

  const handleSessionDeleted = (sessionId: string) => {
    setSessions((current) => current.filter((session) => session.session_id !== sessionId))
  }

  const handleClearAll = () => {
    const nonLiveSessions = visibleSessions.filter((session) => !isLiveSessionStatus(session.status))
    if (nonLiveSessions.length === 0) return
    showConfirmDialog({
      title: t('autoResearch.clearAllConfirmTitle'),
      message: t('autoResearch.clearAllConfirmMessage', { count: nonLiveSessions.length }),
      onConfirm: async () => {
        closeConfirmDialog()
        const idsToDelete = nonLiveSessions.map((s) => s.session_id)
        setDeletingIds((current) => new Set([...current, ...idsToDelete]))
        try {
          await Promise.all(idsToDelete.map((id) => deleteAutoResearchSession(id)))
          setSessions((current) => current.filter((session) => !idsToDelete.includes(session.session_id)))
        } catch (err) {
          setError(err instanceof Error ? err.message : t('autoResearch.clearAllFailed'))
        } finally {
          setDeletingIds((current) => {
            const next = new Set(current)
            idsToDelete.forEach((id) => next.delete(id))
            return next
          })
        }
      },
    })
  }

  const hasNonLiveSessions = visibleSessions.some((session) => !isLiveSessionStatus(session.status))

  return (
    <nav
      className="flex h-full w-full flex-col border-r border-gray-200 bg-gray-50 lg:w-72 lg:shrink-0"
      aria-label={t('autoResearch.sessions')}
    >
      <div className="space-y-3 border-b border-gray-100 p-3">
        <AutoResearchBackButton />
        <button
          type="button"
          onClick={() => navigate('/autoresearch/new')}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-gray-800"
        >
          <Plus className="h-4 w-4" />
          {t('autoResearch.newSession')}
        </button>
      </div>

      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-gray-400" />
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
            {t('autoResearch.sessions')}
          </h3>
        </div>
        {hasNonLiveSessions && (
          <button
            type="button"
            onClick={() => void handleClearAll()}
            className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-gray-500 transition-colors hover:bg-gray-200 hover:text-gray-700"
            aria-label={t('autoResearch.clearAll')}
          >
            <Trash2 className="h-3 w-3" />
            {t('autoResearch.clearAll')}
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {error && (
          <p className="mx-2 mb-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 px-3 py-8 text-sm text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('autoResearch.loadingSessions')}
          </div>
        ) : visibleSessions.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <Beaker className="mx-auto h-8 w-8 text-gray-300" />
            <p className="mt-2 text-sm text-gray-500">{t('autoResearch.noSessions')}</p>
          </div>
        ) : (
          <ul className="space-y-1">
            {visibleSessions.map((session) => (
              <AutoResearchSessionListItem
                key={session.session_id}
                session={session}
                isDeleting={deletingIds.has(session.session_id)}
                isDownloading={downloadingIds.has(session.session_id)}
                isSharing={sharingIds.has(session.session_id)}
                onDeleteStart={(sessionId) => setDeletingIds((current) => new Set(current).add(sessionId))}
                onDeleteEnd={(sessionId) => setDeletingIds((current) => {
                  const next = new Set(current)
                  next.delete(sessionId)
                  return next
                })}
                onDownloadStart={(sessionId) => setDownloadingIds((current) => new Set(current).add(sessionId))}
                onDownloadEnd={(sessionId) => setDownloadingIds((current) => {
                  const next = new Set(current)
                  next.delete(sessionId)
                  return next
                })}
                onShareStart={(sessionId) => setSharingIds((current) => new Set(current).add(sessionId))}
                onShareEnd={(sessionId) => setSharingIds((current) => {
                  const next = new Set(current)
                  next.delete(sessionId)
                  return next
                })}
                onSessionDeleted={handleSessionDeleted}
              />
            ))}
          </ul>
        )}
      </div>

      <ConfirmDialog
        dialog={dialogState}
        onClose={closeConfirmDialog}
      />
    </nav>
  )
}

import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePathScientistTranslation } from '../../lib/usePathScientistTranslation'
import { Beaker, History, Loader2, Plus } from 'lucide-react'
import { listPathScientistSessions } from '../../api/pathscientist'
import type { PathScientistSessionSummary } from '../../types/pathscientist'
import { dedupePathScientistSessions } from '../../lib/pathscientistSessions'
import PathScientistBackButton from './PathScientistBackButton'
import PathScientistSessionListItem from './PathScientistSessionListItem'

export default function PathScientistSessionSidebar() {
  const { t } = usePathScientistTranslation()
  const navigate = useNavigate()
  const [sessions, setSessions] = useState<PathScientistSessionSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
  const [downloadingIds, setDownloadingIds] = useState<Set<string>>(new Set())
  const [sharingIds, setSharingIds] = useState<Set<string>>(new Set())

  const loadSessions = async (silent = false) => {
    if (!silent) setIsLoading(true)
    try {
      const result = await listPathScientistSessions()
      setSessions(result.items || [])
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : t('pathScientist.loadSessionsFailed'))
    } finally {
      if (!silent) setIsLoading(false)
    }
  }

  useEffect(() => {
    void loadSessions()
  }, [t])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSessions(true)
    }, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const visibleSessions = useMemo(() => dedupePathScientistSessions(sessions), [sessions])

  const handleSessionDeleted = (sessionId: string) => {
    setSessions((current) => current.filter((session) => session.session_id !== sessionId))
  }

  return (
    <nav
      className="flex h-full w-full flex-col border-r border-gray-200 bg-gray-50 lg:w-72 lg:shrink-0"
      aria-label={t('pathScientist.sessions')}
    >
      <div className="space-y-3 border-b border-gray-100 p-3">
        <PathScientistBackButton />
        <button
          type="button"
          onClick={() => navigate('/pathscientist/new')}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-gray-800"
        >
          <Plus className="h-4 w-4" />
          {t('pathScientist.newSession')}
        </button>
      </div>

      <div className="flex items-center gap-2 px-4 py-3">
        <History className="h-4 w-4 text-gray-400" />
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          {t('pathScientist.sessions')}
        </h3>
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
            {t('pathScientist.loadingSessions')}
          </div>
        ) : visibleSessions.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <Beaker className="mx-auto h-8 w-8 text-gray-300" />
            <p className="mt-2 text-sm text-gray-500">{t('pathScientist.noSessions')}</p>
          </div>
        ) : (
          <ul className="space-y-1">
            {visibleSessions.map((session) => (
              <PathScientistSessionListItem
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
    </nav>
  )
}

import { useState, type MouseEvent } from 'react'
import { Download, Loader2, Share2, Trash2 } from 'lucide-react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { usePathScientistTranslation } from '../../lib/usePathScientistTranslation'
import { Tooltip } from '../ui/tooltip'
import {
  deletePathScientistSession,
  downloadPathScientistSession,
  sharePathScientistSession,
} from '../../api/pathscientist'
import type { PathScientistSessionSummary } from '../../types/pathscientist'
import {
  displaySessionStatus,
  isLiveSessionStatus,
  sessionStatusClass,
  sessionTrainingProgressLabel,
} from '../../lib/pathscientistSessions'
import { useToast } from '../../contexts/ToastContext'
import { ConfirmDialog } from '../settings/ConfirmDialog'

interface PathScientistSessionListItemProps {
  session: PathScientistSessionSummary
  isDeleting: boolean
  isDownloading: boolean
  isSharing: boolean
  onDeleteStart: (sessionId: string) => void
  onDeleteEnd: (sessionId: string) => void
  onDownloadStart: (sessionId: string) => void
  onDownloadEnd: (sessionId: string) => void
  onShareStart: (sessionId: string) => void
  onShareEnd: (sessionId: string) => void
  onSessionDeleted: (sessionId: string) => void
}

export default function PathScientistSessionListItem({
  session,
  isDeleting,
  isDownloading,
  isSharing,
  onDeleteStart,
  onDeleteEnd,
  onDownloadStart,
  onDownloadEnd,
  onShareStart,
  onShareEnd,
  onSessionDeleted,
}: PathScientistSessionListItemProps) {
  const { t } = usePathScientistTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const toast = useToast()
  const titlePending = Boolean(session.title_pending && !session.title && isLiveSessionStatus(session.status))
  const title = titlePending
    ? t('pathScientist.generatingTitle')
    : session.title || t('pathScientist.untitledSession')
  const status = displaySessionStatus(session.status)
  const isActive = location.pathname === `/pathscientist/sessions/${session.session_id}`
  const canDelete = !isLiveSessionStatus(session.status)
  const trainingProgressLabel = sessionTrainingProgressLabel(session)
  const [dialogState, setDialogState] = useState({ isOpen: false, title: '', message: '', onConfirm: () => {} })

  const showConfirmDialog = (config: { title: string; message: string; onConfirm: () => void }) => {
    setDialogState({ isOpen: true, ...config })
  }

  const closeConfirmDialog = () => {
    setDialogState({ isOpen: false, title: '', message: '', onConfirm: () => {} })
  }

  const handleShare = async (event: MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (isSharing) return
    onShareStart(session.session_id)
    try {
      const method = await sharePathScientistSession(session.session_id)
      toast.success(
        method === 'share'
          ? t('pathScientist.sessionActions.shareSuccess')
          : t('pathScientist.sessionActions.shareCopied'),
      )
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return
      toast.error(error instanceof Error ? error.message : t('pathScientist.sessionActions.shareFailed'))
    } finally {
      onShareEnd(session.session_id)
    }
  }

  const handleDownload = async (event: MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (isDownloading) return
    onDownloadStart(session.session_id)
    try {
      await downloadPathScientistSession(session.session_id)
      toast.success(t('pathScientist.sessionActions.downloadSuccess'))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('pathScientist.sessionActions.downloadFailed'))
    } finally {
      onDownloadEnd(session.session_id)
    }
  }

  const handleDelete = async (event: MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (!canDelete || isDeleting) return
    showConfirmDialog({
      title: t('pathScientist.sessionActions.deleteConfirmTitle'),
      message: t('pathScientist.sessionActions.deleteConfirm'),
      onConfirm: async () => {
        closeConfirmDialog()
        onDeleteStart(session.session_id)
        try {
          await deletePathScientistSession(session.session_id)
          onSessionDeleted(session.session_id)
          if (isActive) {
            navigate('/pathscientist/new')
          }
          toast.success(t('pathScientist.sessionActions.deleteSuccess'))
        } catch (error) {
          toast.error(error instanceof Error ? error.message : t('pathScientist.sessionActions.deleteFailed'))
        } finally {
          onDeleteEnd(session.session_id)
        }
      },
    })
  }

  return (
    <li className="group">
      <div
        className={`flex items-start gap-1 rounded-xl border transition-colors ${
          isActive
            ? 'border-blue-200 bg-blue-50 shadow-sm'
            : 'border-transparent bg-white hover:border-gray-200 hover:bg-white'
        }`}
      >
        <NavLink
          to={`/pathscientist/sessions/${session.session_id}`}
          className="min-w-0 flex-1 px-3 py-2.5"
        >
          <div className="flex min-w-0 items-start gap-2 pr-1">
            {titlePending && <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-blue-600" />}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-gray-900">{title}</p>
              {session.question && (
                <p className="mt-0.5 line-clamp-2 text-xs leading-5 text-gray-500">{session.question}</p>
              )}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${sessionStatusClass(session.status)}`}>
                  {status}
                </span>
                {isLiveSessionStatus(session.status) && (
                  <span className="text-[10px] font-medium text-blue-600">{t('pathScientist.live')}</span>
                )}
                {trainingProgressLabel && (
                  <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-bold text-sky-700 ring-1 ring-sky-100">
                    {trainingProgressLabel}
                  </span>
                )}
              </div>
            </div>
          </div>
        </NavLink>

        <div className="flex shrink-0 items-center gap-0.5 self-center px-1 opacity-100 sm:opacity-0 sm:group-hover:opacity-100">
          <Tooltip content={t('pathScientist.sessionActions.share')}>
            <button
              type="button"
              onClick={(event) => void handleShare(event)}
              disabled={isSharing}
              aria-label={t('pathScientist.sessionActions.share')}
              className="rounded-lg p-1.5 text-gray-400 transition-all hover:bg-emerald-50 hover:text-emerald-600 disabled:opacity-50"
            >
              {isSharing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Share2 className="h-4 w-4" />}
            </button>
          </Tooltip>
          <Tooltip content={t('pathScientist.sessionActions.download')}>
            <button
              type="button"
              onClick={(event) => void handleDownload(event)}
              disabled={isDownloading}
              aria-label={t('pathScientist.sessionActions.download')}
              className="rounded-lg p-1.5 text-gray-400 transition-all hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50"
            >
              {isDownloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            </button>
          </Tooltip>
          <Tooltip content={t('pathScientist.sessionActions.delete')}>
            <button
              type="button"
              onClick={(event) => void handleDelete(event)}
              disabled={!canDelete || isDeleting}
              aria-label={t('pathScientist.sessionActions.delete')}
              className="rounded-lg p-1.5 text-gray-400 transition-all hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
            </button>
          </Tooltip>
        </div>
      </div>

      <ConfirmDialog
        dialog={dialogState}
        onClose={closeConfirmDialog}
      />
    </li>
  )
}

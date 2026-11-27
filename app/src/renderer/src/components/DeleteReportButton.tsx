import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Trash2 } from 'lucide-react'
import { deleteReport } from '../api/reports'
import { Button } from './ui/button'
import { ModalShell } from './ui/modal-shell'

export default function DeleteReportButton({
  reportId,
  title,
  disabled,
  onDeleted,
}: {
  reportId: string
  title: string
  disabled?: boolean
  onDeleted: () => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        disabled={disabled}
        aria-label={t('reports.deleteNamed', { title })}
        title={t(disabled ? 'reports.deleteRunning' : 'reports.delete')}
        className="h-10 w-10 shrink-0 p-2 text-gray-400 hover:bg-red-50 hover:text-red-600"
        onClick={() => {
          setError('')
          setOpen(true)
        }}
      >
        <Trash2 size={16} />
      </Button>
      <ModalShell
        isOpen={open}
        title={t('reports.deleteTitle')}
        onClose={busy ? undefined : () => setOpen(false)}
        className="p-6"
      >
        <h2 className="text-lg font-semibold text-gray-950">
          {t('reports.deleteTitle')}
        </h2>
        <p className="mt-3 break-words text-sm font-medium text-gray-800">
          {title}
        </p>
        <p className="mt-2 text-sm leading-6 text-gray-600">
          {t('reports.deleteDescription')}
        </p>
        {error && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {error}
          </p>
        )}
        <div className="mt-6 flex justify-end gap-3">
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            {t('reports.cancelDelete')}
          </Button>
          <Button
            disabled={busy}
            className="bg-red-600 text-white hover:bg-red-700"
            onClick={async () => {
              setBusy(true)
              setError('')
              try {
                await deleteReport(reportId)
                if (alive.current) {
                  setOpen(false)
                  onDeleted()
                }
              } catch {
                if (alive.current) setError(t('reports.deleteFailed'))
              } finally {
                if (alive.current) setBusy(false)
              }
            }}
          >
            {t(busy ? 'reports.deleting' : 'reports.delete')}
          </Button>
        </div>
      </ModalShell>
    </>
  )
}

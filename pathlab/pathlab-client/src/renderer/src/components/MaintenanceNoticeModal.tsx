import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Construction, Loader2 } from 'lucide-react'
import { Button } from './ui/button'

interface MaintenanceNoticeModalProps {
  isOpen: boolean
  message: string
  onAcknowledge: () => Promise<void>
}

export function MaintenanceNoticeModal({ isOpen, message, onAcknowledge }: MaintenanceNoticeModalProps) {
  const { t } = useTranslation()
  const [isLoading, setIsLoading] = useState(false)

  if (!isOpen || !message) return null

  const handleAcknowledge = async () => {
    setIsLoading(true)
    try {
      await onAcknowledge()
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-2 sm:p-4 animate-in fade-in duration-200">
      <div className="bg-white rounded-xl sm:rounded-2xl shadow-2xl max-w-lg w-full overflow-hidden scale-100 animate-in zoom-in-95 duration-200 max-h-[90vh] flex flex-col">
        <div className="p-4 sm:p-6 border-b border-amber-100 bg-amber-50/50 flex-shrink-0">
          <h3 className="text-base sm:text-xl font-bold text-gray-900 flex items-center gap-2">
            <Construction className="w-4 h-4 sm:w-5 sm:h-5 text-amber-600 flex-shrink-0" />
            {t('maintenanceNotice.title')}
          </h3>
        </div>
        <div className="p-4 sm:p-6 text-slate-600 space-y-3 sm:space-y-4 text-sm leading-relaxed overflow-y-auto flex-1">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 sm:p-4 text-amber-900 whitespace-pre-wrap text-xs sm:text-sm">
            {message}
          </div>
          <p className="text-xs text-slate-500">
            {t('maintenanceNotice.pleaseAcknowledge')}
          </p>
        </div>
        <div className="p-4 sm:p-6 bg-gray-50 flex justify-end gap-3 border-t border-gray-100 flex-shrink-0">
          <Button
            onClick={handleAcknowledge}
            disabled={isLoading}
            className="bg-amber-600 hover:bg-amber-700 text-white shadow-md hover:shadow-lg transition-all text-sm sm:text-base"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                {t('maintenanceNotice.processing')}
              </>
            ) : (
              t('maintenanceNotice.acknowledge')
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}


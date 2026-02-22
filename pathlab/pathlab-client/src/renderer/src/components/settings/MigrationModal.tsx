import { useTranslation } from 'react-i18next'
import { RefreshCw, Database, ChevronRight, HardDrive } from 'lucide-react'
import { Button } from '../ui/button'

export interface MigrationModalProps {
  isOpen: boolean
  currentPath: string | undefined
  targetPath: string
  deleteSource: boolean
  onDeleteSourceChange: (checked: boolean) => void
  onCancel: () => void
  onSkipMigration: () => void
  onConfirmMigration: () => void
}

export function MigrationModal({
  isOpen,
  currentPath,
  targetPath,
  deleteSource,
  onDeleteSourceChange,
  onCancel,
  onSkipMigration,
  onConfirmMigration
}: MigrationModalProps) {
  const { t } = useTranslation()

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/60 backdrop-blur-md p-4 animate-in fade-in duration-300">
      <div className="bg-white rounded-3xl shadow-2xl max-w-lg w-full overflow-hidden animate-in zoom-in-95 duration-300 border border-gray-100">
        {/* Soft Header */}
        <div className="p-8 pb-4 text-center">
          <div className="w-20 h-20 bg-primary-50 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-sm border border-primary-100/50">
            <RefreshCw className="w-10 h-10 text-primary-500 animate-spin-slow" />
          </div>
          <h3 className="text-2xl font-bold text-gray-900">{t('settings.migrationModal.title')}</h3>
          <p className="text-gray-500 mt-3 text-sm leading-relaxed max-w-sm mx-auto">
            {t('settings.migrationModal.description')}
          </p>
        </div>

        <div className="px-8 py-6">
          {/* Path Comparison Visualization */}
          <div className="bg-gray-50/80 rounded-2xl p-6 mb-6 border border-gray-100/50">
            <div className="flex items-center justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-6 h-6 rounded-md bg-gray-200 flex items-center justify-center">
                    <Database className="w-3.5 h-3.5 text-gray-500" />
                  </div>
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{t('settings.migrationModal.from')}</span>
                </div>
                <div className="text-xs text-gray-600 font-mono break-all truncate-2" title={currentPath}>
                  {currentPath}
                </div>
              </div>

              <div className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-white shadow-sm border border-gray-100">
                <ChevronRight className="w-4 h-4 text-primary-400" />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-6 h-6 rounded-md bg-primary-100 flex items-center justify-center">
                    <HardDrive className="w-3.5 h-3.5 text-primary-500" />
                  </div>
                  <span className="text-[10px] font-bold text-primary-400 uppercase tracking-widest">{t('settings.migrationModal.to')}</span>
                </div>
                <div className="text-xs text-primary-900 font-mono font-medium break-all truncate-2" title={targetPath}>
                  {targetPath}
                </div>
              </div>
            </div>
          </div>

          {/* Cleanup Option */}
          <div className={`p-4 rounded-xl border transition-all duration-300 ${deleteSource ? 'bg-red-50 border-red-100' : 'bg-white border-gray-100 shadow-sm'}`}>
            <label className="flex items-center gap-4 cursor-pointer group">
              <div className="relative flex items-center justify-center">
                <input
                  type="checkbox"
                  id="deleteSource"
                  checked={deleteSource}
                  onChange={(e) => onDeleteSourceChange(e.target.checked)}
                  className="w-5 h-5 text-primary-500 border-gray-200 rounded-lg focus:ring-primary-500 focus:ring-offset-0 transition-all cursor-pointer"
                />
              </div>
              <div className="flex-1">
                <span className={`text-sm font-semibold block ${deleteSource ? 'text-red-700' : 'text-gray-700'}`}>
                  {t('settings.migrationModal.cleanupOriginalFiles')}
                </span>
                <p className="text-xs text-gray-400 mt-0.5">
                  {t('settings.migrationModal.deleteFromSource')}
                </p>
              </div>
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="p-8 pt-0 flex flex-col sm:flex-row gap-3">
          <Button
            variant="outline"
            className="flex-1 py-6 border-gray-100 hover:bg-gray-50 hover:text-gray-900 rounded-xl font-medium text-gray-500"
            onClick={onCancel}
          >
            {t('settings.migrationModal.cancel')}
          </Button>
          <div className="flex-[2] flex gap-2">
            <Button
              variant="outline"
              className="flex-1 py-6 border-transparent bg-gray-50 hover:bg-gray-100 rounded-xl font-medium text-gray-600 transition-colors"
              onClick={onSkipMigration}
            >
              {t('settings.migrationModal.skipMove')}
            </Button>
            <Button
              variant="default"
              className="flex-[1.5] py-6 bg-primary-600 hover:bg-primary-700 shadow-lg shadow-primary-500/20 rounded-xl font-bold border-none transition-all active:scale-[0.98]"
              onClick={onConfirmMigration}
            >
              {t('settings.migrationModal.startMove')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

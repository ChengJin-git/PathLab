import React from 'react'
import { useTranslation } from 'react-i18next'
import { Database, Search, Trash2, CheckCircle } from 'lucide-react'
import { Card } from '../../ui/card'
import { OrphanedRecordsInfo, OrphanedRecordsCleanupResult } from '../../../api'

interface OrphanedRecordsCardProps {
  orphanedRecords: OrphanedRecordsInfo | null
  loadingOrphanedRecords: boolean
  isCleaningUpRecords: boolean
  recordsCleanupResult: OrphanedRecordsCleanupResult | null
  detectOrphanedRecordsHandler: (clearCleanupResult?: boolean) => void
  handleRecordsCleanup: (e: React.MouseEvent) => void
  anyStorageOpInProgress: boolean
}

export const OrphanedRecordsCard: React.FC<OrphanedRecordsCardProps> = ({
  orphanedRecords,
  loadingOrphanedRecords,
  isCleaningUpRecords,
  recordsCleanupResult,
  detectOrphanedRecordsHandler,
  handleRecordsCleanup,
  anyStorageOpInProgress
}) => {
  const { t } = useTranslation()

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
        <h2 className="text-lg sm:text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Database className="w-5 h-5 text-gray-700" />
          {t('settings.storage.orphanedRecords')}
        </h2>
        <button
          type="button"
          onClick={() => detectOrphanedRecordsHandler()}
          disabled={anyStorageOpInProgress || isCleaningUpRecords}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
        >
          <Search className="w-4 h-4" />
          {loadingOrphanedRecords ? t('settings.storage.scanning') : t('settings.storage.scan')}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">{t('settings.storage.orphanedRecordsDescription')}</p>

      {orphanedRecords && (
        <div className="space-y-3">
          {orphanedRecords.total_orphaned_count > 0 ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-yellow-800 mb-1">{t('settings.storage.foundOrphanedRecords')}</div>
                  <div className="text-xl font-bold text-yellow-900">
                    {orphanedRecords.total_orphaned_count} <span className="text-sm font-normal">{t('settings.storage.records')}</span>
                  </div>
                  <div className="text-xs text-yellow-700 mt-1">
                    {Object.entries(orphanedRecords.summary)
                      .filter(([, count]) => count > 0)
                      .map(([cat, count]) => `${count} ${cat.replace(/_/g, ' ')}`)
                      .join(', ')}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleRecordsCleanup}
                  disabled={anyStorageOpInProgress || isCleaningUpRecords}
                  className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  {isCleaningUpRecords ? t('settings.storage.cleaning') : t('settings.storage.cleanUp')}
                </button>
              </div>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center gap-2 text-green-800">
                <CheckCircle className="w-5 h-5" />
                <span className="text-sm font-medium">{t('settings.storage.noOrphanedRecords')}</span>
              </div>
            </div>
          )}

          {recordsCleanupResult && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center gap-2 text-green-800 font-semibold mb-1">
                <CheckCircle className="w-5 h-5" />
                {t('settings.storage.cleanupComplete')}
              </div>
              <div className="text-sm text-green-700">{recordsCleanupResult.summary}</div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

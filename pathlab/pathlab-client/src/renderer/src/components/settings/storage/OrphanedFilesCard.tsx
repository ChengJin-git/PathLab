import React from 'react'
import { useTranslation } from 'react-i18next'
import { Search, Trash2, CheckCircle } from 'lucide-react'
import { Card } from '../../ui/card'
import { OrphanedFilesInfo, CleanupResult } from '../../../api'

interface OrphanedFilesCardProps {
  orphanedFiles: OrphanedFilesInfo | null
  loadingOrphaned: boolean
  isCleaningUp: boolean
  cleanupResult: CleanupResult | null
  detectOrphaned: (clearCleanupResult?: boolean) => void
  handleCleanup: (e: React.MouseEvent) => void
  formatFileSize: (bytes: number) => string
  anyStorageOpInProgress: boolean
}

export const OrphanedFilesCard: React.FC<OrphanedFilesCardProps> = ({
  orphanedFiles,
  loadingOrphaned,
  isCleaningUp,
  cleanupResult,
  detectOrphaned,
  handleCleanup,
  formatFileSize,
  anyStorageOpInProgress
}) => {
  const { t } = useTranslation()

  return (
    <Card className="p-4 sm:p-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
        <h2 className="text-lg sm:text-lg font-semibold text-gray-900 flex items-center gap-2">
          <svg className="w-5 h-5 text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          {t('settings.storage.orphanedFiles')}
        </h2>
        <button
          type="button"
          onClick={() => detectOrphaned()}
          disabled={anyStorageOpInProgress || isCleaningUp}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
        >
          <Search className="w-4 h-4" />
          {loadingOrphaned ? t('settings.storage.scanning') : t('settings.storage.scan')}
        </button>
      </div>
      <p className="text-xs text-gray-500 mb-3">{t('settings.storage.orphanedFilesDescription')}</p>

      {orphanedFiles && (
        <div className="space-y-3">
          {cleanupResult ? (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center gap-2 text-green-800 font-semibold mb-1">
                <CheckCircle className="w-5 h-5" />
                {t('settings.storage.cleanupComplete')}
              </div>
              <div className="text-sm text-green-700">
                {t('settings.storage.orphanedFilesCleanupSummary', {
                  files: cleanupResult.deleted_files.length,
                  dirs: cleanupResult.deleted_dirs.length,
                  emptyDirs: cleanupResult.deleted_empty_dirs.length,
                  failed: cleanupResult.failed.length,
                   size: formatFileSize(cleanupResult.total_size)
                })}
              </div>
            </div>
          ) : orphanedFiles.total_orphaned_count > 0 ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-yellow-800 mb-1">{t('settings.storage.foundOrphanedItems')}</div>
                  <div className="text-xl font-bold text-yellow-900">
                    {orphanedFiles.total_orphaned_file_count > 0 && (
                      <>{orphanedFiles.total_orphaned_file_count} <span className="text-sm font-normal">{t('settings.storage.files')}</span></>
                    )}
                    {orphanedFiles.total_orphaned_file_count > 0 && orphanedFiles.total_orphaned_dir_count > 0 && ', '}
                    {orphanedFiles.total_orphaned_dir_count > 0 && (
                      <>{orphanedFiles.total_orphaned_dir_count} <span className="text-sm font-normal">{t('settings.storage.dirs')}</span></>
                    )}
                  </div>
                  <div className="text-xs text-yellow-700 mt-1">
                    {t('settings.storage.canBeFreed', { size: formatFileSize(orphanedFiles.total_orphaned_size) })}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleCleanup}
                  disabled={anyStorageOpInProgress || isCleaningUp}
                  className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  {isCleaningUp ? t('settings.storage.cleaning') : t('settings.storage.cleanUp')}
                </button>
              </div>
            </div>
          ) : (
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center gap-2 text-green-800">
                <CheckCircle className="w-5 h-5" />
                <span className="text-sm font-medium">{t('settings.storage.noOrphanedFiles')}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

import React from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Loader2 } from 'lucide-react'
import type { WSIStorageInfo } from '../../api/storage'
import { formatFileSize } from '../../lib/utils'
import { ModalShell } from '../ui/modal-shell'

// ─── DeleteConfirmModal ──────────────────────────────────────────────────────

export interface DeleteConfirmModalProps {
  wsiToDelete: { wsi_id: string; label: string; original_filename?: string }
  wsiStorageInfo: WSIStorageInfo | null
  loadingStorageInfo: boolean
  deleteMode: 'standard' | 'complete'
  onDeleteModeChange: (mode: 'standard' | 'complete') => void
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteConfirmModal({
  wsiToDelete, wsiStorageInfo, loadingStorageInfo, deleteMode,
  onDeleteModeChange, onCancel, onConfirm,
}: DeleteConfirmModalProps) {
  const { t } = useTranslation()
  return (
    <ModalShell isOpen={true} maxWidth="lg" className="p-4 sm:p-6">
      {/* Header */}
      <div className="text-center mb-3 sm:mb-6">
        <div className="w-10 h-10 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
          <AlertCircle className="w-6 h-6 sm:w-10 sm:h-10 text-red-600" />
        </div>
        <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2 leading-tight">{t('listComponents.deleteSlide')}</h3>
        <p className="text-xs sm:text-base text-gray-600">{t('listComponents.cannotBeUndone')}</p>
      </div>

        {/* WSI Info */}
        <div className="bg-gray-50 rounded-xl p-3 sm:p-4 mb-3 sm:mb-4 border border-gray-100">
          <div className="space-y-1 sm:space-y-2">
            <div className="flex justify-between items-start gap-4">
              <span className="text-xs sm:text-sm font-medium text-gray-500 whitespace-nowrap">{t('listComponents.file')}:</span>
              <span className="text-xs sm:text-sm text-gray-900 font-semibold break-all text-right">{wsiToDelete.original_filename || wsiToDelete.wsi_id}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs sm:text-sm font-medium text-gray-500">{t('listComponents.label')}:</span>
              <span className="text-xs sm:text-sm text-gray-900 font-medium">{wsiToDelete.label || t('listComponents.unknown')}</span>
            </div>
          </div>
        </div>

        {/* Storage Info */}
        {loadingStorageInfo && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 sm:p-4 mb-3 sm:mb-4">
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
              <span className="text-xs sm:text-sm text-blue-800">{t('listComponents.calculatingSize')}</span>
            </div>
          </div>
        )}

        {wsiStorageInfo && !loadingStorageInfo && (() => {
          const featuresSize = wsiStorageInfo.features.reduce((sum, f) => sum + f.size, 0)
          const featuresCount = wsiStorageInfo.features.length
          const displaySize = deleteMode === 'complete' ? wsiStorageInfo.total_size : wsiStorageInfo.total_size - featuresSize
          const displayFiles = deleteMode === 'complete' ? wsiStorageInfo.total_files : wsiStorageInfo.total_files - featuresCount
          return (
            <div className="bg-blue-50/50 border border-blue-100 rounded-xl p-3 sm:p-4 mb-3 sm:mb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs sm:text-sm font-semibold text-blue-900">{t('listComponents.reducedStorage')}:</span>
                <span className="text-base sm:text-lg font-bold text-blue-900">
                  {formatFileSize(displaySize)}
                </span>
              </div>
              <details className="text-xs sm:text-sm">
                <summary className="cursor-pointer text-blue-700 hover:text-blue-900 font-medium">
                  {t('listComponents.filesToBeRemoved', { count: displayFiles })}
                </summary>
                <ul className="mt-2 space-y-1 text-blue-600/80 ml-4 border-l border-blue-100 pl-3">
                  {wsiStorageInfo.wsi_file.exists && (
                    <li>• {t('listComponents.wsiFile')} ({formatFileSize(wsiStorageInfo.wsi_file.size)})</li>
                  )}
                  {wsiStorageInfo.coordinates.exists && (
                    <li>• {t('listComponents.coordinatesCache')} ({formatFileSize(wsiStorageInfo.coordinates.size)})</li>
                  )}
                  {wsiStorageInfo.mask.exists && (
                    <li>• {t('listComponents.tissueMask')} ({formatFileSize(wsiStorageInfo.mask.size)})</li>
                  )}
                  {wsiStorageInfo.ai_results.file_count > 0 && (
                    <li>• {t('listComponents.aiResults')} ({wsiStorageInfo.ai_results.file_count} {t('listComponents.filesLower')}, {formatFileSize(wsiStorageInfo.ai_results.size)})</li>
                  )}
                  {deleteMode === 'complete' && wsiStorageInfo.features.length > 0 && (
                    <li>• {t('listComponents.features')} ({wsiStorageInfo.features.length} {t('listComponents.filesLower')}, {formatFileSize(wsiStorageInfo.features.reduce((sum, f) => sum + f.size, 0))})</li>
                  )}
                </ul>
              </details>
            </div>
          )
        })()}

        {/* Delete Mode Selection */}
        <div className="mb-4">
          <label className="block text-xs sm:text-sm font-bold text-gray-700 mb-2">
            {t('listComponents.deletionMode')}
          </label>
          <div className="space-y-2">
            <label className={`flex items-start gap-3 p-2 sm:p-3 border-2 rounded-xl cursor-pointer hover:bg-gray-50 transition-all ${deleteMode === 'standard' ? 'border-blue-500 bg-blue-50/20' : 'border-gray-100'}`}>
              <input
                type="radio"
                name="deleteMode"
                value="standard"
                checked={deleteMode === 'standard'}
                onChange={(e) => onDeleteModeChange(e.target.value as 'standard' | 'complete')}
                className="mt-1 h-4 w-4 text-blue-600"
              />
              <div className="flex-1 min-w-0">
                <div className="font-bold text-gray-900 text-sm">{t('listComponents.standardDelete')}</div>
                <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                  {t('listComponents.standardDeleteDesc')} <span className="text-blue-600 font-semibold">{t('listComponents.keepsTrainingFeatures')}</span> {t('listComponents.forFutureResearch')}
                </div>
              </div>
            </label>

            <label className={`flex items-start gap-3 p-2 sm:p-3 border-2 rounded-xl cursor-pointer hover:bg-gray-50 transition-all ${deleteMode === 'complete' ? 'border-red-500 bg-red-50/20' : 'border-gray-100'}`}>
              <input
                type="radio"
                name="deleteMode"
                value="complete"
                checked={deleteMode === 'complete'}
                onChange={(e) => onDeleteModeChange(e.target.value as 'standard' | 'complete')}
                className="mt-1 h-4 w-4 text-red-600"
              />
              <div className="flex-1 min-w-0">
                <div className="font-bold text-gray-900 text-sm">{t('listComponents.completeDelete')}</div>
                <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                  {t('listComponents.completeDeleteDesc')} <span className="text-red-500 font-bold">{t('listComponents.irreversible')}</span>
                </div>
              </div>
            </label>
          </div>
        </div>

        {/* Warning - only on mobile */}
        <div className="sm:hidden bg-amber-50 border border-amber-200 rounded-lg p-2.5 mb-4">
          <p className="text-[10px] text-amber-800 leading-tight">
            <strong>{t('listComponents.attention')}:</strong> {t('listComponents.permanentAction')}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-bold shadow-sm"
          >
            {t('common.delete')}
          </button>
      </div>
    </ModalShell>
  )
}

// ─── BatchDeleteModal ────────────────────────────────────────────────────────

export interface BatchDeleteModalProps {
  selectedIds: Set<string>
  selectedCount?: number
  datasetToDeleteId: string | null
  datasetToDeleteName: string
  deleteMode: 'standard' | 'complete'
  onDeleteModeChange: (mode: 'standard' | 'complete') => void
  deleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function BatchDeleteModal({
  selectedIds, selectedCount, datasetToDeleteId, datasetToDeleteName, deleteMode,
  onDeleteModeChange, deleting, onCancel, onConfirm,
}: BatchDeleteModalProps) {
  const { t } = useTranslation()
  const effectiveCount = selectedCount ?? selectedIds.size
  return (
    <ModalShell isOpen={true} maxWidth="lg" className="p-4 sm:p-6">
      {/* Header */}
      <div className="text-center mb-3 sm:mb-6">
        <div className="w-10 h-10 sm:w-16 sm:h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
          <AlertCircle className="w-6 h-6 sm:w-10 sm:h-10 text-red-600" />
        </div>
        <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2 text-balance leading-tight">
          {datasetToDeleteId ? t('listComponents.deleteDataset') : t('listComponents.deleteMultipleSlides')}
        </h3>
        <p className="text-xs sm:text-base text-gray-600">{t('listComponents.cannotBeUndone')}</p>
      </div>

        {/* Selection Info */}
        <div className="bg-gray-50 rounded-xl p-3 sm:p-4 mb-4 sm:mb-6 border border-gray-100 text-center">
          <p className="text-xs sm:text-sm text-gray-700 leading-relaxed">
            {datasetToDeleteId ? (
              <>{t('listComponents.aboutToDeleteDataset')} <span className="font-bold text-red-600">{datasetToDeleteName}</span> {t('listComponents.andAllIts')} <span className="font-bold">{effectiveCount}</span> {t('listComponents.filesLower')}</>
            ) : (
              <>{t('listComponents.aboutToDelete')} <span className="font-bold text-red-600">{effectiveCount}</span> {t('listComponents.fileCount', { count: effectiveCount })}</>
            )}
          </p>
        </div>

        {/* Delete Mode Selection */}
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            {t('listComponents.deletionMode')}
          </label>
          <div className="space-y-2">
            <label className="flex items-start gap-3 p-3 border-2 rounded-lg cursor-pointer hover:bg-gray-50 transition-colors"
              style={{ borderColor: deleteMode === 'standard' ? '#3b82f6' : '#e5e7eb' }}>
              <input
                type="radio"
                name="batchDeleteMode"
                value="standard"
                checked={deleteMode === 'standard'}
                onChange={(e) => onDeleteModeChange(e.target.value as 'standard' | 'complete')}
                className="mt-1 h-4 w-4 text-blue-600"
              />
              <div className="flex-1 min-w-0">
                <div className="font-bold text-gray-900 text-sm">{t('listComponents.standardDelete')}</div>
                <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                  {t('listComponents.standardDeleteDesc')} <span className="text-blue-600 font-semibold">{t('listComponents.keepsTrainingFeatures')}</span> {t('listComponents.forFutureResearch')}
                </div>
              </div>
            </label>

            <label className={`flex items-start gap-3 p-2 sm:p-3 border-2 rounded-xl cursor-pointer hover:bg-gray-50 transition-all ${deleteMode === 'complete' ? 'border-red-500 bg-red-50/20' : 'border-gray-100'}`}>
              <input
                type="radio"
                name="batchDeleteMode"
                value="complete"
                checked={deleteMode === 'complete'}
                onChange={(e) => onDeleteModeChange(e.target.value as 'standard' | 'complete')}
                className="mt-1 h-4 w-4 text-red-600"
              />
              <div className="flex-1 min-w-0">
                <div className="font-bold text-gray-900 text-sm">{t('listComponents.completeDelete')}</div>
                <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed">
                  {t('listComponents.completeDeleteDesc')} <span className="text-red-500 font-bold">{t('listComponents.irreversible')}</span>
                </div>
              </div>
            </label>
          </div>
        </div>

        {/* Warning - only on mobile */}
        <div className="sm:hidden bg-amber-50 border border-amber-200 rounded-lg p-2.5 mb-4">
          <p className="text-[10px] text-amber-800 leading-tight">
            <strong>{t('listComponents.attention')}:</strong> {t('listComponents.permanentAction')}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-bold disabled:opacity-50 flex items-center justify-center gap-2 shadow-sm"
          >
            {deleting && <Loader2 className="w-4 h-4 animate-spin" />}
            {deleting ? t('listComponents.deleting') : (datasetToDeleteId ? t('common.delete') : t('listComponents.deleteCount', { count: effectiveCount }))}
          </button>
        </div>
    </ModalShell>
  )
}

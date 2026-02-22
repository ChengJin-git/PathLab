/**
 * DeleteConfirmModal Component
 *
 * Modal for confirming deletion of a single slide or batch deletion.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle } from 'lucide-react'

export interface WSIDeleteInfo {
  wsi_id: string
  original_filename?: string
  label?: string
}

export interface DeleteConfirmModalProps {
  // Mode: single or batch
  mode: 'single' | 'batch'

  // For single deletion
  wsiToDelete?: WSIDeleteInfo | null

  // For batch deletion
  selectedCount?: number

  // State
  deleting: boolean

  // Actions
  onConfirm: () => void
  onCancel: () => void
}

export function DeleteConfirmModal({
  mode,
  wsiToDelete,
  selectedCount = 0,
  deleting,
  onConfirm,
  onCancel,
}: DeleteConfirmModalProps) {
  const { t } = useTranslation()
  const isBatch = mode === 'batch'
  const title = isBatch ? t('training.deleteConfirm.titleBatch') : t('training.deleteConfirm.titleSingle')
  const buttonText = deleting
    ? t('training.deleteConfirm.deleting')
    : isBatch
      ? t('training.deleteConfirm.deleteCount', { count: selectedCount })
      : t('common.delete')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
            <AlertTriangle className="w-8 h-8 text-red-600" />
          </div>
          <h3 className="text-2xl font-bold text-gray-900 mb-2">{title}</h3>
          <p className="text-gray-600">{t('training.deleteConfirm.cannotUndo')}</p>
        </div>

        {/* Info */}
        {!isBatch && wsiToDelete && (
          <div className="bg-gray-50 rounded-lg p-4 mb-6">
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sm font-medium text-gray-700">{t('training.deleteConfirm.filename')}:</span>
                <span className="text-sm text-gray-900 font-semibold">{wsiToDelete.original_filename || wsiToDelete.wsi_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sm font-medium text-gray-700">{t('training.deleteConfirm.label')}:</span>
                <span className="text-sm text-gray-900">{wsiToDelete.label || t('training.deleteConfirm.unknown')}</span>
              </div>
            </div>
          </div>
        )}

        {isBatch && (
          <div className="bg-gray-50 rounded-lg p-4 mb-6">
            <p className="text-sm text-gray-900">
              {t('training.deleteConfirm.aboutToDelete', { count: selectedCount })}
            </p>
          </div>
        )}

        {/* Warning */}
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-6">
          <p className="text-sm text-red-800">
            <strong>{t('training.deleteConfirm.warning')}:</strong>{' '}
            {isBatch
              ? t('training.deleteConfirm.warningBatchText')
              : t('training.deleteConfirm.warningSingleText')}
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={deleting}
            className="flex-1 px-6 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-medium disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="flex-1 px-6 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-semibold disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {buttonText}
          </button>
        </div>
      </div>
    </div>
  )
}

import { useTranslation } from 'react-i18next'
import { AvailableHeatmap } from '../../api'
import { Trash2, Loader2 } from 'lucide-react'

interface DeleteResultsModalProps {
  showDeleteConfirm: boolean
  setShowDeleteConfirm: (show: boolean) => void
  deleteMode: 'all' | 'task'
  setDeleteMode: (mode: 'all' | 'task') => void
  deletingResults: boolean
  handleDeleteResults: () => void
  availableHeatmaps: AvailableHeatmap[]
  selectedTaskId: string | undefined
}

export function DeleteResultsModal({
  showDeleteConfirm,
  setShowDeleteConfirm,
  deleteMode,
  setDeleteMode,
  deletingResults,
  handleDeleteResults,
  availableHeatmaps,
  selectedTaskId
}: DeleteResultsModalProps) {
  const { t } = useTranslation()
  if (!showDeleteConfirm) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-red-100 rounded-lg">
              <Trash2 className="w-5 h-5 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">{t('wsiViewerComponents.deleteResults.deleteAIResults')}</h3>
          </div>

          <p className="text-gray-600 mb-4">
            {t('wsiViewerComponents.deleteResults.chooseWhatToDelete')}
          </p>

          <div className="space-y-2 mb-6">
            <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition-colors">
              <input
                type="radio"
                name="deleteMode"
                checked={deleteMode === 'task'}
                onChange={() => setDeleteMode('task')}
                className="w-4 h-4 text-red-600"
              />
              <div>
                <div className="font-medium text-gray-900">{t('wsiViewerComponents.deleteResults.deleteSelectedTaskOnly')}</div>
                <div className="text-sm text-gray-500">
                  {t('wsiViewerComponents.deleteResults.removeResultsFor', { taskName: availableHeatmaps.find(h => h.task_id === selectedTaskId)?.task_name || selectedTaskId || 'N/A' })}
                </div>
              </div>
            </label>

            <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition-colors">
              <input
                type="radio"
                name="deleteMode"
                checked={deleteMode === 'all'}
                onChange={() => setDeleteMode('all')}
                className="w-4 h-4 text-red-600"
              />
              <div>
                <div className="font-medium text-gray-900">{t('wsiViewerComponents.deleteResults.deleteAllResults')}</div>
                <div className="text-sm text-gray-500">
                  {t('wsiViewerComponents.deleteResults.removeAllResults', { count: availableHeatmaps.length })}
                </div>
              </div>
            </label>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6">
            <p className="text-sm text-amber-800">
              <strong>{t('wsiViewerComponents.deleteResults.warning')}:</strong> {t('wsiViewerComponents.deleteResults.warningMessage')}
            </p>
          </div>
        </div>

        <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
          <button
            onClick={() => setShowDeleteConfirm(false)}
            disabled={deletingResults}
            className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {t('wsiViewerComponents.deleteResults.cancel')}
          </button>
          <button
            onClick={handleDeleteResults}
            disabled={deletingResults}
            className="flex-1 px-4 py-2 text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {deletingResults ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('wsiViewerComponents.deleteResults.deleting')}
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                {t('wsiViewerComponents.deleteResults.delete')}
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}


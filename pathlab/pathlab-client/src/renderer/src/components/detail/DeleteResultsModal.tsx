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
  if (!showDeleteConfirm) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]">
      <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
        <div className="p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="p-2 bg-red-100 rounded-lg">
              <Trash2 className="w-5 h-5 text-red-600" />
            </div>
            <h3 className="text-lg font-semibold text-gray-900">Delete AI Results</h3>
          </div>

          <p className="text-gray-600 mb-4">
            Choose what to delete for this slide:
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
                <div className="font-medium text-gray-900">Delete selected task only</div>
                <div className="text-sm text-gray-500">
                  Remove results for: {availableHeatmaps.find(h => h.task_id === selectedTaskId)?.task_name || selectedTaskId || 'N/A'}
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
                <div className="font-medium text-gray-900">Delete all results</div>
                <div className="text-sm text-gray-500">
                  Remove all {availableHeatmaps.length} analysis results for this slide
                </div>
              </div>
            </label>
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6">
            <p className="text-sm text-amber-800">
              <strong>Warning:</strong> This will permanently delete the attention weights and prediction data. This action cannot be undone.
            </p>
          </div>
        </div>

        <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
          <button
            onClick={() => setShowDeleteConfirm(false)}
            disabled={deletingResults}
            className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleDeleteResults}
            disabled={deletingResults}
            className="flex-1 px-4 py-2 text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {deletingResults ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Deleting...
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                Delete
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}


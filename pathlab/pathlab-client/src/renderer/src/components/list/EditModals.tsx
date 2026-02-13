import React from 'react'
import { Edit, X, Users, FileImage } from 'lucide-react'
import { Button } from '../ui/button'

// ─── EditMetadataModal ───────────────────────────────────────────────────────

export interface EditMetadataModalProps {
  editingWSI: { wsi_id: string; label: string; case_id: string; age?: number; gender?: string; source?: string }
  editLabel: string
  editCaseId: string
  editAge: string
  editGender: string
  editSource: string
  onEditLabelChange: (v: string) => void
  onEditCaseIdChange: (v: string) => void
  onEditAgeChange: (v: string) => void
  onEditGenderChange: (v: string) => void
  onEditSourceChange: (v: string) => void
  updating: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function EditMetadataModal({
  editingWSI, editLabel, editCaseId, editAge, editGender, editSource,
  onEditLabelChange, onEditCaseIdChange, onEditAgeChange, onEditGenderChange, onEditSourceChange,
  updating, onCancel, onConfirm,
}: EditMetadataModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="text-center mb-3 sm:mb-6">
          <div className="w-10 h-10 sm:w-16 sm:h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
            <Edit className="w-6 h-6 sm:w-10 sm:h-10 text-blue-600" />
          </div>
          <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2">Edit Metadata</h3>
          <p className="text-xs sm:text-sm text-gray-600">Update slide information</p>
        </div>

        {/* WSI ID (read-only) */}
        <div className="mb-3 sm:mb-4">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Slide ID</label>
          <input type="text" value={editingWSI.wsi_id} disabled
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed text-xs sm:text-sm" />
        </div>

        {/* Label Input */}
        <div className="mb-3 sm:mb-4">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Label (Disease Classification)</label>
          <input type="text" value={editLabel} onChange={(e) => onEditLabelChange(e.target.value)}
            placeholder="e.g., Benign, Malignant, Grade 1"
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
        </div>

        {/* Case ID Input */}
        <div className="mb-3 sm:mb-4">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Case ID</label>
          <input type="text" value={editCaseId} onChange={(e) => onEditCaseIdChange(e.target.value)}
            placeholder="e.g., case_001"
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-blue-100 rounded-lg focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 text-xs sm:text-sm transition-all" />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-3 sm:mb-4">
          {/* Age Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Age</label>
            <input type="number" value={editAge} onChange={(e) => onEditAgeChange(e.target.value)}
              placeholder="e.g., 45"
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>
          {/* Gender Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Gender</label>
            <select value={editGender} onChange={(e) => onEditGenderChange(e.target.value)}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
              <option value="">Select Gender</option>
              <option value="Male">Male</option>
              <option value="Female">Female</option>
              <option value="Unspecified">Unspecified</option>
            </select>
          </div>
        </div>

        {/* Source Input */}
        <div className="mb-6 sm:mb-8">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Source (Organ/Tissue)</label>
          <input type="text" value={editSource} onChange={(e) => onEditSourceChange(e.target.value)}
            placeholder="e.g., Cervix, Lung, Breast"
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={updating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            Cancel
          </button>
          <button onClick={onConfirm} disabled={updating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-blue-500/10">
            {updating ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── BatchEditModal ──────────────────────────────────────────────────────────

export interface BatchEditModalProps {
  selectedCount: number
  batchEditLabel: string
  batchEditCaseId: string
  batchEditAge: string
  batchEditGender: string
  batchEditSource: string
  onBatchEditLabelChange: (v: string) => void
  onBatchEditCaseIdChange: (v: string) => void
  onBatchEditAgeChange: (v: string) => void
  onBatchEditGenderChange: (v: string) => void
  onBatchEditSourceChange: (v: string) => void
  batchUpdating: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function BatchEditModal({
  selectedCount, batchEditLabel, batchEditCaseId, batchEditAge, batchEditGender, batchEditSource,
  onBatchEditLabelChange, onBatchEditCaseIdChange, onBatchEditAgeChange, onBatchEditGenderChange, onBatchEditSourceChange,
  batchUpdating, onCancel, onConfirm,
}: BatchEditModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="text-center mb-3 sm:mb-6">
          <div className="w-10 h-10 sm:w-16 sm:h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
            <Edit className="w-6 h-6 sm:w-10 sm:h-10 text-blue-600" />
          </div>
          <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2">Batch Edit Metadata</h3>
          <p className="text-xs sm:text-sm text-gray-600">Update {selectedCount} slide(s)</p>
        </div>

        {/* Info Message */}
        <div className="mb-3 sm:mb-4 p-2.5 sm:p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <p className="text-[10px] sm:text-sm text-blue-800 font-medium">
            Leave fields empty to keep existing values unchanged
          </p>
        </div>

        <div className="space-y-3 sm:space-y-4">
          {/* Label Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Label (Disease Classification)</label>
            <input type="text" value={batchEditLabel} onChange={(e) => onBatchEditLabelChange(e.target.value)}
              placeholder="Keep existing..."
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>

          {/* Case ID Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Case ID</label>
            <input type="text" value={batchEditCaseId} onChange={(e) => onBatchEditCaseIdChange(e.target.value)}
              placeholder="Keep existing..."
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            {/* Age Input */}
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Age</label>
              <input type="number" value={batchEditAge} onChange={(e) => onBatchEditAgeChange(e.target.value)}
                placeholder="Existing..."
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
            </div>
            {/* Gender Input */}
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Gender</label>
              <select value={batchEditGender} onChange={(e) => onBatchEditGenderChange(e.target.value)}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
                <option value="">Keep existing</option>
                <option value="Male">Male</option>
                <option value="Female">Female</option>
                <option value="Unspecified">Unspecified</option>
              </select>
            </div>
          </div>

          {/* Source Input */}
          <div className="mb-4 sm:mb-6">
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">Source (Organ/Tissue)</label>
            <input type="text" value={batchEditSource} onChange={(e) => onBatchEditSourceChange(e.target.value)}
              placeholder="Keep existing..."
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={batchUpdating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            Cancel
          </button>
          <button onClick={onConfirm} disabled={batchUpdating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-blue-500/10">
            {batchUpdating ? 'Updating...' : `Update ${selectedCount}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── EditDatasetModal ────────────────────────────────────────────────────────

export interface EditDatasetModalProps {
  editingDatasetName: string
  editingDatasetType: 'classification' | 'survival'
  editingDatasetOriginalType: 'classification' | 'survival'
  editingDatasetDataLevel: 'case' | 'file'
  editingDatasetOriginalDataLevel: 'case' | 'file'
  editingDatasetSaving: boolean
  isSlideDataset: boolean
  onNameChange: (v: string) => void
  onTypeChange: (v: 'classification' | 'survival') => void
  onDataLevelChange: (v: 'case' | 'file') => void
  onCancel: () => void
  onSave: () => void
}

export function EditDatasetModal({
  editingDatasetName, editingDatasetType, editingDatasetOriginalType,
  editingDatasetDataLevel, editingDatasetOriginalDataLevel, editingDatasetSaving,
  isSlideDataset, onNameChange, onTypeChange, onDataLevelChange, onCancel, onSave,
}: EditDatasetModalProps) {
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onCancel}>
      <div className="bg-white rounded-2xl sm:rounded-3xl shadow-2xl w-full max-w-md p-4 sm:p-6 animate-in zoom-in-95 fade-in duration-200" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <h3 className="text-lg sm:text-xl font-bold text-gray-900">Edit Dataset</h3>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-gray-400 hover:text-gray-600" onClick={onCancel}>
            <X className="w-5 h-5" />
          </Button>
        </div>

        {/* Dataset Name */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">Dataset Name</label>
          <input type="text" value={editingDatasetName} onChange={(e) => onNameChange(e.target.value)}
            className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="Enter dataset name" autoFocus />
        </div>

        {/* Dataset Type */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">Analysis Type</label>
          <div className="grid grid-cols-2 gap-3">
            <button type="button" onClick={() => onTypeChange('classification')}
              className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                editingDatasetType === 'classification'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}>
              <span className="font-medium">Classification</span>
            </button>
            <button type="button" onClick={() => onTypeChange('survival')}
              className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                editingDatasetType === 'survival'
                  ? 'border-amber-500 bg-amber-50 text-amber-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}>
              <span className="font-medium">Survival</span>
            </button>
          </div>
          {editingDatasetType !== editingDatasetOriginalType && (
            <p className="mt-2 text-xs text-amber-600">
              Changing type will modify metadata for all slides in this dataset
            </p>
          )}
        </div>

        {/* Data Level */}
        {isSlideDataset && (
          <div className="mb-6">
            <label className="block text-sm font-semibold text-gray-700 mb-2">Data Level</label>
            <div className="grid grid-cols-2 gap-3">
              <button type="button" onClick={() => onDataLevelChange('case')}
                className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                  editingDatasetDataLevel === 'case'
                    ? 'border-purple-500 bg-purple-50 text-purple-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                }`}>
                <Users className="w-4 h-4" />
                <span className="font-medium">Case-Level</span>
              </button>
              <button type="button" onClick={() => onDataLevelChange('file')}
                className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                  editingDatasetDataLevel === 'file'
                    ? 'border-orange-500 bg-orange-50 text-orange-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                }`}>
                <FileImage className="w-4 h-4" />
                <span className="font-medium">File-Level</span>
              </button>
            </div>
            {editingDatasetDataLevel !== editingDatasetOriginalDataLevel && (
              <p className="mt-2 text-xs text-purple-600">
                Changing data level affects how files are grouped for analysis
              </p>
            )}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={editingDatasetSaving}
            className="flex-1 px-4 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            Cancel
          </button>
          <button onClick={onSave} disabled={editingDatasetSaving || !editingDatasetName.trim()}
            className="flex-1 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed">
            {editingDatasetSaving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}


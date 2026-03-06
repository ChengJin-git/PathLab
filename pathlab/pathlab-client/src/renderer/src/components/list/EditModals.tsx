import React from 'react'
import { useTranslation } from 'react-i18next'
import { Edit, X, Users, FileImage } from 'lucide-react'
import { Button } from '../ui/button'

// ─── EditMetadataModal ───────────────────────────────────────────────────────

export interface EditMetadataModalProps {
  editingWSI: {
    wsi_id: string
    label?: string
    case_id: string
    age?: number
    gender?: string
    source?: string
    event_time?: number
    event_status?: number
  }
  editLabel: string
  editCaseId: string
  editAge: string
  editGender: string
  editSource: string
  editEventTime: string
  editEventStatus: string
  datasetType?: 'classification' | 'survival' | 'segmentation'
  onEditLabelChange: (v: string) => void
  onEditCaseIdChange: (v: string) => void
  onEditAgeChange: (v: string) => void
  onEditGenderChange: (v: string) => void
  onEditSourceChange: (v: string) => void
  onEditEventTimeChange: (v: string) => void
  onEditEventStatusChange: (v: string) => void
  updating: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function EditMetadataModal({
  editingWSI, editLabel, editCaseId, editAge, editGender, editSource, editEventTime, editEventStatus,
  datasetType,
  onEditLabelChange, onEditCaseIdChange, onEditAgeChange, onEditGenderChange, onEditSourceChange,
  onEditEventTimeChange, onEditEventStatusChange,
  updating, onCancel, onConfirm,
}: EditMetadataModalProps) {
  const { t } = useTranslation()

  // Different task types show different fields
  const isClassification = datasetType === 'classification'
  const isSurvival = datasetType === 'survival'
  const isSegmentation = datasetType === 'segmentation'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="text-center mb-3 sm:mb-6">
          <div className="w-10 h-10 sm:w-16 sm:h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
            <Edit className="w-6 h-6 sm:w-10 sm:h-10 text-blue-600" />
          </div>
          <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2">{t('listComponents.editModals.editMetadata')}</h3>
          <p className="text-xs sm:text-sm text-gray-600">{t('listComponents.editModals.updateSlideInfo')}</p>
        </div>

        {/* WSI ID (read-only) */}
        <div className="mb-3 sm:mb-4">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.slideId')}</label>
          <input type="text" value={editingWSI.wsi_id} disabled
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg bg-gray-50 text-gray-500 cursor-not-allowed text-xs sm:text-sm" />
        </div>

        {/* Label Input - Only for classification */}
        {isClassification && (
          <div className="mb-3 sm:mb-4">
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.labelDiseaseClassification')}</label>
            <input type="text" value={editLabel} onChange={(e) => onEditLabelChange(e.target.value)}
              placeholder={t('listComponents.editModals.labelPlaceholder')}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>
        )}

        {/* Event Time and Status - Only for survival */}
        {isSurvival && (
          <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-3 sm:mb-4">
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.eventTime')}</label>
              <input type="number" step="0.1" value={editEventTime} onChange={(e) => onEditEventTimeChange(e.target.value)}
                placeholder={t('listComponents.editModals.eventTimePlaceholder')}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
            </div>
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.eventStatus')}</label>
              <select value={editEventStatus} onChange={(e) => onEditEventStatusChange(e.target.value)}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
                <option value="">{t('listComponents.editModals.selectStatus')}</option>
                <option value="1">{t('listComponents.editModals.event')}</option>
                <option value="0">{t('listComponents.editModals.censored')}</option>
              </select>
            </div>
          </div>
        )}

        {/* Case ID Input */}
        <div className="mb-3 sm:mb-4">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.caseId')}</label>
          <input type="text" value={editCaseId} onChange={(e) => onEditCaseIdChange(e.target.value)}
            placeholder={t('listComponents.editModals.caseIdPlaceholder')}
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-blue-100 rounded-lg focus:ring-2 focus:ring-blue-500/10 focus:border-blue-500 text-xs sm:text-sm transition-all" />
        </div>

        <div className="grid grid-cols-2 gap-3 sm:gap-4 mb-3 sm:mb-4">
          {/* Age Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.age')}</label>
            <input type="number" value={editAge} onChange={(e) => onEditAgeChange(e.target.value)}
              placeholder={t('listComponents.editModals.agePlaceholder')}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>
          {/* Gender Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.gender')}</label>
            <select value={editGender} onChange={(e) => onEditGenderChange(e.target.value)}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
              <option value="">{t('listComponents.editModals.selectGender')}</option>
              <option value="Male">{t('listComponents.editModals.male')}</option>
              <option value="Female">{t('listComponents.editModals.female')}</option>
              <option value="Unspecified">{t('listComponents.editModals.unspecified')}</option>
            </select>
          </div>
        </div>

        {/* Source Input */}
        <div className="mb-6 sm:mb-8">
          <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.sourceOrganTissue')}</label>
          <input type="text" value={editSource} onChange={(e) => onEditSourceChange(e.target.value)}
            placeholder={t('listComponents.editModals.sourcePlaceholder')}
            className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={updating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            {t('listComponents.editModals.cancel')}
          </button>
          <button onClick={onConfirm} disabled={updating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-blue-500/10">
            {updating ? t('listComponents.editModals.saving') : t('listComponents.editModals.saveChanges')}
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
  batchEditEventTime: string
  batchEditEventStatus: string
  datasetType?: 'classification' | 'survival' | 'segmentation'
  onBatchEditLabelChange: (v: string) => void
  onBatchEditCaseIdChange: (v: string) => void
  onBatchEditAgeChange: (v: string) => void
  onBatchEditGenderChange: (v: string) => void
  onBatchEditSourceChange: (v: string) => void
  onBatchEditEventTimeChange: (v: string) => void
  onBatchEditEventStatusChange: (v: string) => void
  batchUpdating: boolean
  onCancel: () => void
  onConfirm: () => void
}

export function BatchEditModal({
  selectedCount, batchEditLabel, batchEditCaseId, batchEditAge, batchEditGender, batchEditSource,
  batchEditEventTime, batchEditEventStatus,
  datasetType,
  onBatchEditLabelChange, onBatchEditCaseIdChange, onBatchEditAgeChange, onBatchEditGenderChange, onBatchEditSourceChange,
  onBatchEditEventTimeChange, onBatchEditEventStatusChange,
  batchUpdating, onCancel, onConfirm,
}: BatchEditModalProps) {
  const { t } = useTranslation()

  // Different task types show different fields
  const isClassification = datasetType === 'classification'
  const isSurvival = datasetType === 'survival'
  const isSegmentation = datasetType === 'segmentation'

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-3 sm:p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-[95vw] p-4 sm:p-6 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="text-center mb-3 sm:mb-6">
          <div className="w-10 h-10 sm:w-16 sm:h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-2 sm:mb-4">
            <Edit className="w-6 h-6 sm:w-10 sm:h-10 text-blue-600" />
          </div>
          <h3 className="text-lg sm:text-2xl font-bold text-gray-900 mb-0.5 sm:mb-2">{t('listComponents.editModals.batchEditMetadata')}</h3>
          <p className="text-xs sm:text-sm text-gray-600">{t('listComponents.editModals.updateSlides', { count: selectedCount })}</p>
        </div>

        {/* Info Message */}
        <div className="mb-3 sm:mb-4 p-2.5 sm:p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <p className="text-[10px] sm:text-sm text-blue-800 font-medium">
            {t('listComponents.editModals.leaveFieldsEmpty')}
          </p>
        </div>

        <div className="space-y-3 sm:space-y-4">
          {/* Label Input - Only for classification */}
          {isClassification && (
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.labelDiseaseClassification')}</label>
              <input type="text" value={batchEditLabel} onChange={(e) => onBatchEditLabelChange(e.target.value)}
                placeholder={t('listComponents.editModals.keepExisting')}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
            </div>
          )}

          {/* Event Time and Status - Only for survival */}
          {isSurvival && (
            <div className="grid grid-cols-2 gap-3 sm:gap-4">
              <div>
                <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.eventTime')}</label>
                <input type="number" step="0.1" value={batchEditEventTime} onChange={(e) => onBatchEditEventTimeChange(e.target.value)}
                  placeholder={t('listComponents.editModals.keepExisting')}
                  className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
              </div>
              <div>
                <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.eventStatus')}</label>
                <select value={batchEditEventStatus} onChange={(e) => onBatchEditEventStatusChange(e.target.value)}
                  className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
                  <option value="">{t('listComponents.editModals.keepExisting')}</option>
                  <option value="1">{t('listComponents.editModals.event')}</option>
                  <option value="0">{t('listComponents.editModals.censored')}</option>
                </select>
              </div>
            </div>
          )}

          {/* Case ID Input */}
          <div>
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.caseId')}</label>
            <input type="text" value={batchEditCaseId} onChange={(e) => onBatchEditCaseIdChange(e.target.value)}
              placeholder={t('listComponents.editModals.keepExisting')}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            {/* Age Input */}
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.age')}</label>
              <input type="number" value={batchEditAge} onChange={(e) => onBatchEditAgeChange(e.target.value)}
                placeholder={t('listComponents.editModals.existingPlaceholder')}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
            </div>
            {/* Gender Input */}
            <div>
              <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.gender')}</label>
              <select value={batchEditGender} onChange={(e) => onBatchEditGenderChange(e.target.value)}
                className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm bg-white">
                <option value="">{t('listComponents.editModals.keepExisting')}</option>
                <option value="Male">{t('listComponents.editModals.male')}</option>
                <option value="Female">{t('listComponents.editModals.female')}</option>
                <option value="Unspecified">{t('listComponents.editModals.unspecified')}</option>
              </select>
            </div>
          </div>

          {/* Source Input */}
          <div className="mb-4 sm:mb-6">
            <label className="block text-[11px] sm:text-sm font-semibold text-gray-700 mb-1 sm:mb-2">{t('listComponents.editModals.sourceOrganTissue')}</label>
            <input type="text" value={batchEditSource} onChange={(e) => onBatchEditSourceChange(e.target.value)}
              placeholder={t('listComponents.editModals.keepExisting')}
              className="w-full px-3 py-1.5 sm:px-4 sm:py-2 border border-gray-200 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 text-xs sm:text-sm" />
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={batchUpdating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            {t('listComponents.editModals.cancel')}
          </button>
          <button onClick={onConfirm} disabled={batchUpdating}
            className="flex-1 px-4 py-2 sm:px-6 sm:py-2.5 text-xs sm:text-base bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed shadow-md shadow-blue-500/10">
            {batchUpdating ? t('listComponents.editModals.updating') : t('listComponents.editModals.updateCount', { count: selectedCount })}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── EditDatasetModal ────────────────────────────────────────────────────────

export interface EditDatasetModalProps {
  editingDatasetName: string
  editingDatasetType: 'classification' | 'survival' | 'segmentation'
  editingDatasetOriginalType: 'classification' | 'survival' | 'segmentation'
  editingDatasetDataLevel: 'case' | 'file'
  editingDatasetOriginalDataLevel: 'case' | 'file'
  editingDatasetSaving: boolean
  isSlideDataset: boolean
  onNameChange: (v: string) => void
  onTypeChange: (v: 'classification' | 'survival' | 'segmentation') => void
  onDataLevelChange: (v: 'case' | 'file') => void
  onCancel: () => void
  onSave: () => void
}

export function EditDatasetModal({
  editingDatasetName, editingDatasetType, editingDatasetOriginalType,
  editingDatasetDataLevel, editingDatasetOriginalDataLevel, editingDatasetSaving,
  isSlideDataset, onNameChange, onTypeChange, onDataLevelChange, onCancel, onSave,
}: EditDatasetModalProps) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4" onClick={onCancel}>
      <div className="bg-white rounded-2xl sm:rounded-3xl shadow-2xl w-full max-w-md p-4 sm:p-6 animate-in zoom-in-95 fade-in duration-200" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4 sm:mb-6">
          <h3 className="text-lg sm:text-xl font-bold text-gray-900">{t('listComponents.editModals.editDataset')}</h3>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-gray-400 hover:text-gray-600" onClick={onCancel}>
            <X className="w-5 h-5" />
          </Button>
        </div>

        {/* Dataset Name */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">{t('listComponents.editModals.datasetName')}</label>
          <input type="text" value={editingDatasetName} onChange={(e) => onNameChange(e.target.value)}
            className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder={t('listComponents.editModals.enterDatasetName')} autoFocus />
        </div>

        {/* Dataset Type */}
        <div className="mb-4">
          <label className="block text-sm font-semibold text-gray-700 mb-2">{t('listComponents.editModals.analysisType')}</label>
          <div className="grid grid-cols-3 gap-3">
            <button type="button" onClick={() => onTypeChange('classification')}
              className={`flex items-center justify-center gap-2 px-3 py-3 rounded-lg border-2 transition-all ${
                editingDatasetType === 'classification'
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}>
              <span className="font-medium text-sm">{t('listComponents.editModals.classification')}</span>
            </button>
            <button type="button" onClick={() => onTypeChange('survival')}
              className={`flex items-center justify-center gap-2 px-3 py-3 rounded-lg border-2 transition-all ${
                editingDatasetType === 'survival'
                  ? 'border-amber-500 bg-amber-50 text-amber-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}>
              <span className="font-medium text-sm">{t('listComponents.editModals.survival')}</span>
            </button>
            <button type="button" onClick={() => onTypeChange('segmentation')}
              className={`flex items-center justify-center gap-2 px-3 py-3 rounded-lg border-2 transition-all ${
                editingDatasetType === 'segmentation'
                  ? 'border-violet-500 bg-violet-50 text-violet-700'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}>
              <span className="font-medium text-sm">{t('listComponents.editModals.segmentation')}</span>
            </button>
          </div>
          {editingDatasetType !== editingDatasetOriginalType && (
            <p className="mt-2 text-xs text-amber-600">
              {t('listComponents.editModals.changingTypeWarning')}
            </p>
          )}
        </div>

        {/* Data Level */}
        {isSlideDataset && (
          <div className="mb-6">
            <label className="block text-sm font-semibold text-gray-700 mb-2">{t('listComponents.editModals.dataLevel')}</label>
            <div className="grid grid-cols-2 gap-3">
              <button type="button" onClick={() => onDataLevelChange('case')}
                className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                  editingDatasetDataLevel === 'case'
                    ? 'border-purple-500 bg-purple-50 text-purple-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                }`}>
                <Users className="w-4 h-4" />
                <span className="font-medium">{t('listComponents.editModals.caseLevel')}</span>
              </button>
              <button type="button" onClick={() => onDataLevelChange('file')}
                className={`flex items-center justify-center gap-2 px-4 py-3 rounded-lg border-2 transition-all ${
                  editingDatasetDataLevel === 'file'
                    ? 'border-orange-500 bg-orange-50 text-orange-700'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                }`}>
                <FileImage className="w-4 h-4" />
                <span className="font-medium">{t('listComponents.editModals.fileLevel')}</span>
              </button>
            </div>
            {editingDatasetDataLevel !== editingDatasetOriginalDataLevel && (
              <p className="mt-2 text-xs text-purple-600">
                {t('listComponents.editModals.changingDataLevelWarning')}
              </p>
            )}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button onClick={onCancel} disabled={editingDatasetSaving}
            className="flex-1 px-4 py-2.5 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50">
            {t('listComponents.editModals.cancel')}
          </button>
          <button onClick={onSave} disabled={editingDatasetSaving || !editingDatasetName.trim()}
            className="flex-1 px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-bold disabled:opacity-50 disabled:cursor-not-allowed">
            {editingDatasetSaving ? t('listComponents.editModals.saving') : t('listComponents.editModals.saveChanges')}
          </button>
        </div>
      </div>
    </div>
  )
}

import React from 'react'
import { useTranslation } from 'react-i18next'
import {
  CheckCircle, AlertCircle, ChevronLeft, ChevronRight, RefreshCw, Upload,
  Layers, Clock, Info, Grid3X3, FileJson, Globe, Lock
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Tooltip } from '../../ui/tooltip'
import { Label } from '../../ui/label'
import { Badge } from '../../ui/badge'
import { Checkbox } from '../../ui/checkbox'
import { ScanDirectoryResponse, DatasetSummary } from '../../../api'
import { isSegmentationTask, isSurvivalTask, type TaskType } from '../../../constants/training'
import { DataLevelSelection } from './DataLevelSelection'
import { DatasetSelection } from './DatasetSelection'

interface BatchScanResultsProps {
  batchScanResult: ScanDirectoryResponse
  batchScanStage: 'idle' | 'initial' | 'refresh' | 'segmentationRefresh'
  batchSelectedCount: number
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: TaskType
  setBatchTaskType: (type: TaskType) => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  batchIsPublic: boolean
  setBatchIsPublic: (value: boolean) => void
  handleBatchScanPageChange: (page: number) => void
  isBatchFileSelected: (path: string, valid: boolean) => boolean
  handleBatchFileToggle: (path: string, valid: boolean) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => void
  formatFileSize: (bytes: number) => string
}

export const BatchScanResults: React.FC<BatchScanResultsProps> = ({
  batchScanResult,
  batchScanStage,
  batchSelectedCount,
  batchDatasetMode,
  setBatchDatasetMode,
  batchSelectedDatasetId,
  setBatchSelectedDatasetId,
  batchNewDatasetNameRef,
  batchRegistering,
  batchImportTaskId,
  batchDatasets,
  batchTaskType,
  setBatchTaskType,
  batchDataLevel,
  setBatchDataLevel,
  batchIsPublic,
  setBatchIsPublic,
  handleBatchScanPageChange,
  isBatchFileSelected,
  handleBatchFileToggle,
  handleBatchSelectAll,
  handleBatchDeselectAll,
  handleBatchRegister,
  formatFileSize
}) => {
  const { t } = useTranslation()
  const isSegmentation = isSegmentationTask(batchTaskType)
  const isSurvival = isSurvivalTask(batchTaskType)

  return (
    <div className="space-y-4">
      {batchScanStage === 'segmentationRefresh' && (
        <div className="rounded-lg border border-violet-200 bg-violet-50 px-4 py-3">
          <p className="text-sm font-medium text-violet-900">{t('settings.storage.refreshingSegmentationAnnotations')}</p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">
          {t('settings.storage.foundFiles', {
            count: batchScanResult.total_count,
            wsi: batchScanResult.wsi_count,
            patch: batchScanResult.patch_count,
            valid: batchScanResult.valid_count,
            size: formatFileSize(batchScanResult.total_size)
          })}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleBatchSelectAll}>
            {t('settings.storage.selectAllValid')}
          </Button>
          <Button variant="outline" size="sm" onClick={handleBatchDeselectAll}>
            {t('settings.storage.deselectAll')}
          </Button>
        </div>
      </div>

      <div className="max-h-80 overflow-y-auto border border-gray-100 rounded-xl shadow-sm bg-white">
        <table className="w-full text-sm">
          <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b border-gray-100">
            <tr>
              <th className="px-3 py-3 text-left w-10"></th>
              <th className="px-3 py-3 text-left font-semibold text-gray-700">{t('settings.storage.filename')}</th>
              <th className="px-3 py-3 text-left w-16 font-semibold text-gray-700">{t('settings.storage.type')}</th>
              <th className="px-3 py-3 text-left w-20 font-semibold text-gray-700">{t('settings.storage.format')}</th>
              <th className="px-3 py-3 text-right w-24 font-semibold text-gray-700">{t('settings.storage.size')}</th>
              {isSegmentation && (
                <th className="px-3 py-3 text-left w-20 font-semibold text-gray-700" title={t('settings.storage.annotationJsonTooltip')}>JSON</th>
              )}
              <th className="px-3 py-3 text-left w-32 font-semibold text-gray-700">{t('settings.storage.status')}</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {batchScanResult.files.map((file) => (
              <tr
                key={file.path}
                className={`hover:bg-gray-50/50 transition-colors ${!file.valid ? 'opacity-60' : ''}`}
              >
                <td className="px-3 py-3">
                  <Checkbox
                    checked={isBatchFileSelected(file.path, file.valid)}
                    onCheckedChange={() => handleBatchFileToggle(file.path, file.valid)}
                    disabled={!file.valid}
                  />
                </td>
                <td className="px-3 py-3 font-medium text-xs truncate max-w-xs" title={file.path}>
                  {file.filename}
                </td>
                <td className="px-3 py-3">
                  <span className={`inline-flex px-2 py-0.5 text-xs rounded ${
                    file.data_type === 'wsi' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                  }`}>
                    {file.data_type === 'wsi' ? t('settings.storage.wsiType') : t('settings.storage.patchType')}
                  </span>
                </td>
                <td className="px-3 py-3">
                  <span className={`inline-flex px-2 py-0.5 text-xs rounded ${
                    file.format_type === 'mrxs' ? 'bg-purple-100 text-purple-700' :
                    file.format_type === 'tmap' ? 'bg-primary-100 text-primary-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {file.extension}
                  </span>
                </td>
                <td className="px-3 py-3 text-right text-gray-500">
                  {formatFileSize(file.size)}
                </td>
                {isSegmentation && (
                  <td className="px-3 py-3">
                    {file.has_annotation_json ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-teal-50 text-teal-700" title={t('settings.storage.annotationJsonFound')}>
                        <FileJson className="w-3 h-3" /> {t('settings.storage.matched')}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded bg-gray-50 text-gray-400" title={t('settings.storage.annotationJsonNotFound')}>
                        <FileJson className="w-3 h-3" /> —
                      </span>
                    )}
                  </td>
                )}
                <td className="px-3 py-3">
                  {file.valid ? (
                    <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 gap-1 py-0 px-2 font-normal">
                      <CheckCircle className="w-3 h-3" /> {t('settings.storage.valid')}
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 gap-1 py-0 px-2 font-normal" title={file.validation_message || ''}>
                      <AlertCircle className="w-3 h-3" /> {t('settings.storage.invalid')}
                    </Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="border border-gray-100 rounded-xl bg-gray-50/50 px-4 py-3 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="text-xs text-gray-500 font-medium">
          {t('settings.storage.showingRange', {
            start: batchScanResult.total_count === 0 ? 0 : (batchScanResult.page - 1) * batchScanResult.page_size + 1,
            end: Math.min(batchScanResult.page * batchScanResult.page_size, batchScanResult.total_count),
            total: batchScanResult.total_count,
          })}
        </div>
        <div className="flex items-center gap-2">
          <Tooltip content={t('settings.storage.previousPage')}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBatchScanPageChange(batchScanResult.page - 1)}
              disabled={batchScanResult.page <= 1}
              aria-label={t('settings.storage.previousPage')}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
          </Tooltip>
          <span className="text-xs font-medium text-gray-600 px-2">
            {t('settings.storage.pageIndicator', { page: batchScanResult.page, totalPages: batchScanResult.total_pages })}
          </span>
          <Tooltip content={t('settings.storage.nextPage')}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleBatchScanPageChange(batchScanResult.page + 1)}
              disabled={batchScanResult.page >= batchScanResult.total_pages}
              aria-label={t('settings.storage.nextPage')}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </Tooltip>
        </div>
      </div>

      <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
        <Label className="text-sm font-medium text-slate-900 block">{t('settings.storage.taskType')}</Label>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setBatchTaskType('wsi_classification')}
            className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              !isSurvival && !isSegmentation
                ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
                : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <Layers className={`w-4 h-4 ${!isSurvival && !isSegmentation ? 'text-primary-700' : 'text-gray-400'}`} />
              {t('settings.storage.classification')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setBatchTaskType('wsi_survival')}
            className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              isSurvival
                ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
                : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <Clock className={`w-4 h-4 ${isSurvival ? 'text-primary-700' : 'text-gray-400'}`} />
              {t('settings.storage.survivalAnalysis')}
            </div>
          </button>
          <button
            type="button"
            onClick={() => setBatchTaskType('patch_segmentation')}
            className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              isSegmentation
                ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
                : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <Grid3X3 className={`w-4 h-4 ${isSegmentation ? 'text-primary-700' : 'text-gray-400'}`} />
              {t('settings.storage.segmentation')}
            </div>
          </button>
        </div>

        <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
          <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-gray-600">
            {!isSurvival && !isSegmentation
              ? t('settings.storage.classificationInfo')
              : isSegmentation
                ? t('settings.storage.segmentationInfo')
                : t('settings.storage.survivalInfo')
            }
          </div>
        </div>
      </div>

      <DataLevelSelection batchDataLevel={batchDataLevel} setBatchDataLevel={setBatchDataLevel} taskType={batchTaskType} />

      <DatasetSelection
        batchDatasetMode={batchDatasetMode}
        setBatchDatasetMode={setBatchDatasetMode}
        batchSelectedDatasetId={batchSelectedDatasetId}
        setBatchSelectedDatasetId={setBatchSelectedDatasetId}
        batchNewDatasetNameRef={batchNewDatasetNameRef}
        batchDatasets={batchDatasets}
      />

      {batchDatasetMode === 'new' && (
        <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
          <Label className="text-sm font-medium text-slate-900 block">{t('settings.storage.datasetVisibility')}</Label>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setBatchIsPublic(false)
              }}
              className={`flex-1 flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                !batchIsPublic
                  ? 'bg-slate-200 text-slate-900 border-2 border-slate-400 shadow-sm'
                  : 'bg-white text-gray-500 border border-gray-100 hover:border-slate-300 hover:text-slate-600'
              }`}
            >
              <Lock className={`w-4 h-4 ${!batchIsPublic ? 'text-slate-700' : 'text-gray-400'}`} />
              {t('settings.storage.private')}
            </button>
            <button
              type="button"
              onClick={() => setBatchIsPublic(true)}
              className={`flex-1 flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
                batchIsPublic
                  ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
                  : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
              }`}
            >
              <Globe className={`w-4 h-4 ${batchIsPublic ? 'text-primary-700' : 'text-gray-400'}`} />
              {t('settings.storage.public')}
            </button>
          </div>

        </div>
      )}

      <div className="flex items-center justify-between">
        <div className="text-sm text-gray-600">
          {t('settings.storage.filesSelected', { count: batchSelectedCount })}
        </div>
        <Button
          onClick={handleBatchRegister}
          disabled={batchSelectedCount === 0 || batchRegistering}
          className="gap-2"
        >
          {batchRegistering ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              {t('settings.storage.registering')}
            </>
          ) : (
            <>
              <Upload className="w-4 h-4" />
              {t('settings.storage.registerSelected', { count: batchSelectedCount })}
            </>
          )}
        </Button>
      </div>

      {batchImportTaskId && (
        <div className="p-4 rounded-lg border bg-blue-50 border-blue-200">
          <div className="flex items-center gap-2 font-semibold text-blue-700">
            <CheckCircle className="w-5 h-5" />
            {t('settings.storage.importTaskSubmitted')}
          </div>
          <div className="text-sm text-blue-600 mt-1">
            {t('settings.storage.taskId')}: <span className="font-mono">{batchImportTaskId}</span>
          </div>
          <div className="text-sm text-blue-600 mt-1">
            {t('settings.storage.filesBeingRegistered')}
          </div>
        </div>
      )}
    </div>
  )
}

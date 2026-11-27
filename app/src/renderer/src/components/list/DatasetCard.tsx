import React from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Tooltip } from '../ui/tooltip'
import {
  Microscope,
  LayoutGrid,
  ChevronRight,
  CheckCircle,
  Loader2,
  Download,
  Pencil,
  Trash2,
  Users,
  FileImage,
  GitMerge,
  Database,
  User,
  Globe,
  Lock,
} from 'lucide-react'
import { formatFileSize } from '../../lib/utils/utils'
import type { DatasetSummary } from '../../api/wsi'

export interface DatasetCardProps {
  dataset: DatasetSummary
  itemType: 'slides' | 'images'
  normalizedTaskType: 'classification' | 'survival' | 'segmentation' | 'detection'
  sourceOrganLabel: string
  sourceOrganValue: string
  isDeleting: boolean
  isUnavailable?: boolean
  isAdmin: boolean
  exporting?: boolean
  exportingDatasetId?: string | null
  onClick: () => void
  onExportClick?: (e: React.MouseEvent) => void
  onEditClick?: (e: React.MouseEvent) => void
  onDeleteClick?: (e: React.MouseEvent) => void
  unknownSourceOrganFilter?: string
}

export function DatasetCard({
  dataset,
  itemType,
  normalizedTaskType,
  sourceOrganLabel,
  sourceOrganValue,
  isDeleting,
  isUnavailable,
  isAdmin,
  exporting,
  exportingDatasetId,
  onClick,
  onExportClick,
  onEditClick,
  onDeleteClick,
  unknownSourceOrganFilter = '__unknown__',
}: DatasetCardProps) {
  const { t } = useTranslation()

  return (
    <Card
      data-testid="dataset-card"
      className={`group relative overflow-hidden transition-all duration-300 border-slate-200 bg-white h-full flex flex-col ${
        isDeleting || isUnavailable ? 'pointer-events-none' : 'hover:shadow-xl hover:-translate-y-1'
      } ${isUnavailable ? 'opacity-60' : ''}`}
      onClick={isDeleting || isUnavailable ? undefined : onClick}
    >
      {isDeleting && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/75 backdrop-blur-[2px] rounded-xl">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="w-6 h-6 animate-spin text-red-400" />
            <span className="text-xs font-medium text-red-500">{t('listPage.datasetDeleting')}</span>
          </div>
        </div>
      )}

      {isUnavailable && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/60 backdrop-blur-[1px] rounded-xl">
          <div className="flex flex-col items-center gap-2">
            <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[10px] sm:text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
              {t('listPage.externalUnavailable')}
            </span>
            {dataset.availability?.reason && (
              <span className="text-[10px] sm:text-xs text-amber-600 max-w-[80%] text-center">{dataset.availability.reason}</span>
            )}
          </div>
        </div>
      )}

      <div
        className={`absolute inset-x-0 top-0 h-1 opacity-0 group-hover:opacity-100 transition-opacity bg-gradient-to-r ${
          itemType === 'slides' ? 'from-blue-500 to-indigo-500' : 'from-emerald-500 to-teal-500'
        }`}
      />

      <div className="p-4 sm:p-6 flex flex-col flex-1">
        <div className="flex items-start justify-between mb-3 sm:mb-4">
          <div
            className={`p-2 sm:p-3 rounded-2xl transition-colors ${
              itemType === 'slides'
                ? 'bg-blue-50 group-hover:bg-blue-100'
                : 'bg-emerald-50 group-hover:bg-emerald-100'
            }`}
          >
            {itemType === 'slides' ? (
              <Microscope className="w-6 h-6 sm:w-8 sm:h-8 text-blue-600" />
            ) : (
              <LayoutGrid className="w-6 h-6 sm:w-8 sm:h-8 text-emerald-600" />
            )}
          </div>
          <div className="sm:opacity-0 group-hover:opacity-100 transition-opacity -mr-1 sm:-mr-2 -mt-1 sm:-mt-2">
            <div className="flex h-8 w-8 items-center justify-center text-slate-400 group-hover:text-blue-600">
              <ChevronRight aria-hidden="true" className="w-5 h-5" />
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between mb-0.5 sm:mb-1 min-w-0 relative z-10">
          <div className="flex items-center gap-1 sm:gap-2 max-w-full group/title">
            <h3
              data-testid="dataset-card-title"
              className="text-lg sm:text-xl font-bold text-slate-900 line-clamp-2 leading-snug"
              title={dataset.dataset_name}
            >
              {dataset.dataset_name}
            </h3>
            {dataset.can_delete && (
              <div className="flex items-center sm:opacity-0 group-hover/title:opacity-100 transition-all -ml-0.5 sm:-ml-1">
                <Tooltip content={t('listPage.exportLabels')}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 sm:h-6 sm:w-6 text-slate-300 hover:text-green-600"
                    onClick={(e) => onExportClick?.(e)}
                    disabled={exporting}
                  >
                    {exporting && exportingDatasetId === dataset.dataset_id ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Download className="w-3.5 h-3.5" />
                    )}
                  </Button>
                </Tooltip>
                <Tooltip content={t('listPage.editDataset')}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 sm:h-6 sm:w-6 text-slate-300 hover:text-blue-600"
                    onClick={(e) => onEditClick?.(e)}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                </Tooltip>
                <Tooltip content={t('listPage.deleteDataset')}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 sm:h-6 sm:w-6 text-slate-300 hover:text-red-600"
                    onClick={(e) => onDeleteClick?.(e)}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </Button>
                </Tooltip>
              </div>
            )}
          </div>
        </div>

        <div
          data-testid="dataset-card-badges"
          className="dataset-card-badge-zone flex items-center gap-2 mb-3 sm:mb-4 flex-wrap max-h-20 overflow-hidden"
        >
          <p className="text-xs sm:text-sm text-slate-500 font-medium whitespace-nowrap">
            {itemType === 'slides' ? t('listPage.wholeSlideImaging') : t('listPage.patchCollection')}
          </p>
          <div className="w-1 h-1 rounded-full bg-slate-300" />
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
              normalizedTaskType === 'survival'
                ? 'bg-amber-50 text-amber-700 border border-amber-100/50'
                : normalizedTaskType === 'segmentation'
                  ? 'bg-violet-50 text-violet-700 border border-violet-100/50'
                  : 'bg-indigo-50 text-indigo-700 border border-indigo-100/50'
            }`}
          >
            {dataset.task_types.map(task => t(`training.taskSetup.${task}`)).join(' · ')}
          </span>
          {itemType === 'slides' && (
            <span
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                dataset.aggregation_level === 'case'
                  ? 'bg-purple-50 text-purple-700 border border-purple-100/50'
                  : 'bg-orange-50 text-orange-700 border border-orange-100/50'
              }`}
            >
              {dataset.aggregation_level === 'case' ? (
                <>
                  <Users className="w-3 h-3" />
                  {t('listPage.patientLevel')}
                </>
              ) : (
                <>
                  <FileImage className="w-3 h-3" />
                  {t('listPage.fileLevel')}
                </>
              )}
            </span>
          )}
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
              sourceOrganValue === unknownSourceOrganFilter
                ? 'bg-slate-50 text-slate-600 border border-slate-200/70'
                : 'bg-cyan-50 text-cyan-700 border border-cyan-100/70'
            }`}
          >
            {sourceOrganLabel}
          </span>
          {dataset.is_public ? (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-100/70">
              <Globe className="w-2.5 h-2.5" />
              {t('listComponents.editModals.public')}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold bg-slate-50 text-slate-600 border border-slate-200/70">
              <Lock className="w-2.5 h-2.5" />
              {t('listComponents.editModals.private')}
            </span>
          )}
        </div>

        {dataset.parent_dataset_name && (
          <div className="flex items-center gap-1.5 mb-3 sm:mb-4 text-[10px] sm:text-xs text-slate-500">
            <GitMerge className="w-3 h-3 text-slate-400 flex-shrink-0" />
            <span className="truncate" title={dataset.parent_dataset_name}>
              <span className="text-slate-400">{t('listPage.derivedFrom')}</span>{' '}
              <span className="font-medium text-slate-600">{dataset.parent_dataset_name}</span>
            </span>
          </div>
        )}

        <div className="mt-auto flex items-center gap-3 sm:gap-4 text-xs sm:text-sm text-slate-500/90 pt-3 sm:pt-4 border-t border-slate-100">
          <span className="flex items-center gap-1 sm:gap-1.5 font-medium whitespace-nowrap">
            <Database className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-slate-400" />
            {dataset.file_count}
            <span className="hidden sm:inline ml-1">{itemType}</span>
          </span>
          <span className="flex items-center gap-1 sm:gap-1.5 font-medium whitespace-nowrap">
            <CheckCircle className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-slate-400" />
            {formatFileSize(dataset.total_size)}
          </span>
          {isAdmin && dataset.username && (
              <span
                className="ml-auto min-w-0 pl-2 sm:pl-3 flex items-center gap-1 sm:gap-1.5 font-medium whitespace-nowrap text-slate-400"
              >
                <User className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-slate-300" />
                <span
                  data-testid="dataset-card-owner"
                  className="truncate max-w-[120px] sm:max-w-[180px]"
                  title={dataset.username}
                >
                  {dataset.username}
                </span>
              </span>
          )}
        </div>
      </div>
    </Card>
  )
}

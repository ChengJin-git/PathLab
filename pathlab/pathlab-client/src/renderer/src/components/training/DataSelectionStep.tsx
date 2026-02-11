/**
 * DataSelectionStep Component
 *
 * Step 2: Dataset and file selection for training.
 * This is a complex step with dataset grid, file table, and split configuration.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  FolderOpen,
  Plus,
  FileText,
  ArrowRight,
  CheckCircle2,
  AlertCircle,
  Layers,
  UploadCloud,
} from 'lucide-react'
import { TaskType, SplitStrategy } from '../../constants/training'
import { KFoldValidation, RandomSplitValidation, WSIItem } from '../../types/training'
import { DatasetSummary } from '../../api'
import { WSIDataTable } from './WSIDataTable'
import { DataSplitConfig } from './DataSplitConfig'
import { RegistrationProgress } from './RegistrationProgress'

export interface DataSelectionStepProps {
  // Task type
  taskType: TaskType
  dataLevel: 'wsi' | 'patch'

  // Dataset list
  datasets: DatasetSummary[]
  datasetsLoading: boolean

  // Selected dataset
  selectedDatasetId: string | null
  selectedDatasetName: string
  onSelectDataset: (id: string | null, name: string) => void
  onBackToDatasets: () => void

  // File list
  items: WSIItem[]
  loading: boolean

  // Selection
  selectedIds: Set<string>
  toggleSelection: (id: string) => void
  allPageSelected: boolean
  allFilteredSelected: boolean
  handleSelectPage: () => void
  handleSelectAllFiltered: () => void

  // Case grouping
  hasMultiSlideCases: boolean
  groupedByCaseId: [string, WSIItem[]][]
  expandedCases: Set<string>
  toggleCaseExpansion: (caseId: string) => void
  paginatedCases: [string, WSIItem[]][] | null
  isPatchDataset: boolean
  totalCases: number

  // Pagination
  currentPage: number
  setCurrentPage: (page: number) => void
  pageSize: number
  setPageSize: (size: number) => void
  totalPages: number
  pageSlides: WSIItem[]
  setSelectedIds: (ids: Set<string>) => void

  // Search
  searchQuery: string
  setSearchQuery: (query: string) => void

  // Split strategy
  splitStrategy: SplitStrategy
  setSplitStrategy: (strategy: SplitStrategy) => void
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  randomSeed: number
  setRandomSeed: (seed: number) => void
  kFoldValidation: KFoldValidation
  randomSplitValidation: RandomSplitValidation
  hasPreDefinedSplits: boolean
  predefinedSplitCounts: { train: number; val: number; test: number }
  classDistribution: Record<string, number>

  // Actions
  onEditClick: (item: WSIItem) => void
  onDeleteClick: (wsiId: string, label: string, filename?: string) => void
  onBatchEditClick: () => void
  onBatchDeleteClick: () => void

  // Helpers
  formatBytes: (bytes: number) => string
  getFileType: (fileExtension: string, size: number) => 'WSI' | 'Patch'

  // Navigation
  canProceed: boolean
  onBack: () => void
  onNext: () => void
}

export function DataSelectionStep(props: DataSelectionStepProps) {
  const navigate = useNavigate()
  const {
    taskType,
    dataLevel,
    datasets,
    datasetsLoading,
    selectedDatasetId,
    selectedDatasetName,
    onSelectDataset,
    onBackToDatasets,
    items,
    loading,
    selectedIds,
    toggleSelection,
    allPageSelected,
    allFilteredSelected,
    handleSelectPage,
    handleSelectAllFiltered,
    hasMultiSlideCases,
    groupedByCaseId,
    expandedCases,
    toggleCaseExpansion,
    paginatedCases,
    isPatchDataset,
    totalCases,
    currentPage,
    setCurrentPage,
    pageSize,
    setPageSize,
    totalPages,
    pageSlides,
    setSelectedIds,
    searchQuery,
    setSearchQuery,
    formatBytes,
    getFileType,
    splitStrategy,
    setSplitStrategy,
    kFoldSplits,
    setKFoldSplits,
    randomSeed,
    setRandomSeed,
    kFoldValidation,
    randomSplitValidation,
    hasPreDefinedSplits,
    predefinedSplitCounts,
    classDistribution,
    onEditClick,
    onDeleteClick,
    onBatchEditClick,
    onBatchDeleteClick,
    canProceed,
    onBack,
    onNext,
  } = props

  return (
    <>
      <Card className="p-3 sm:p-6 border-gray-100 shadow-sm">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4 sm:mb-6">
          <div className="flex-1 min-w-0">
            {selectedDatasetId ? (
              <DatasetSelectedHeader
                selectedDatasetName={selectedDatasetName}
                selectedCount={selectedIds.size}
                onBack={onBackToDatasets}
              />
            ) : (
              <DatasetSelectHeader selectedCount={selectedIds.size} />
            )}
          </div>
          <div className="flex shrink-0">
            <button
              onClick={() => navigate('/register')}
              className="w-full sm:w-auto px-4 py-2 sm:py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 transition-all text-xs sm:text-sm font-bold shadow-md shadow-primary-500/20 flex items-center justify-center gap-2 group"
            >
              <Plus className="w-4 h-4 group-hover:rotate-90 transition-transform duration-300" />
              Register Files
            </button>
          </div>
        </div>

        {/* Dataset Selection View (when no dataset selected) */}
        {!selectedDatasetId && (
          <DatasetGrid
            datasetsLoading={datasetsLoading}
            datasets={datasets}
            taskType={taskType}
            onSelectDataset={onSelectDataset}
            formatBytes={formatBytes}
          />
        )}

        {/* File Selection View (when dataset is selected) */}
        {selectedDatasetId && (
          <WSIDataTable
            taskType={taskType}
            loading={loading}
            filteredItems={items}
            pageSlides={pageSlides}
            selectedIds={selectedIds}
            toggleSelection={toggleSelection}
            setSelectedIds={setSelectedIds}
            allPageSelected={allPageSelected}
            allFilteredSelected={allFilteredSelected}
            handleSelectPage={handleSelectPage}
            handleSelectAllFiltered={handleSelectAllFiltered}
            hasMultiSlideCases={hasMultiSlideCases}
            paginatedCases={paginatedCases}
            expandedCases={expandedCases}
            toggleCaseExpansion={toggleCaseExpansion}
            isPatchDataset={isPatchDataset}
            totalCases={totalCases}
            currentPage={currentPage}
            setCurrentPage={setCurrentPage}
            pageSize={pageSize}
            handleEditClick={onEditClick}
            handleDeleteClick={onDeleteClick}
            getFileType={getFileType}
          />
        )}
      </Card>

      {/* Data Split Strategy */}
      {selectedDatasetId && selectedIds.size > 0 && (
        <DataSplitConfig
          splitStrategy={splitStrategy}
          setSplitStrategy={setSplitStrategy}
          kFoldSplits={kFoldSplits}
          setKFoldSplits={setKFoldSplits}
          randomSeed={randomSeed}
          setRandomSeed={setRandomSeed}
          kFoldValidation={kFoldValidation}
          randomSplitValidation={randomSplitValidation}
          hasPreDefinedSplits={hasPreDefinedSplits}
          predefinedSplitCounts={predefinedSplitCounts}
          classDistribution={classDistribution}
          selectedDatasetId={selectedDatasetId}
          selectedDatasetName={selectedDatasetName}
        />
      )}

      {/* Bottom Navigation Buttons */}
      <div className="mt-8 sm:mt-12 flex flex-col sm:flex-row items-center justify-between gap-4 pt-6 border-t border-gray-100">
        <button
          onClick={onBack}
          className="w-full sm:w-auto px-6 py-2.5 border border-gray-200 text-gray-600 rounded-xl hover:bg-gray-50 transition-all font-bold text-xs sm:text-sm flex items-center justify-center gap-2"
        >
          <ChevronLeft className="w-4 h-4" />
          Back to Parameters
        </button>
        <button
          onClick={onNext}
          disabled={!canProceed}
          className="w-full sm:w-auto px-8 py-2.5 bg-primary-600 hover:bg-primary-700 text-white rounded-xl shadow-lg shadow-primary-500/20 transition-all font-bold text-xs sm:text-sm flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {dataLevel === 'patch' ? 'Next: Model Config' : 'Next: Preprocessing'}
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </>
  )
}

/** Dataset grid for selection */
function DatasetGrid({
  datasetsLoading,
  datasets,
  taskType,
  onSelectDataset,
  formatBytes,
}: {
  datasetsLoading: boolean
  datasets: DatasetSummary[]
  taskType: TaskType
  onSelectDataset: (id: string | null, name: string) => void
  formatBytes: (bytes: number) => string
}) {
  if (datasetsLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <Loader2 className="w-8 h-8 text-primary-600 animate-spin mb-3" />
        <p className="text-sm text-gray-500 font-medium">Loading datasets...</p>
      </div>
    )
  }

  if (datasets.length === 0) {
    return (
      <div className="text-center py-12 sm:py-16 bg-gray-50/50 rounded-2xl border-2 border-dashed border-gray-200">
        <FolderOpen className="w-12 h-12 mx-auto mb-4 text-gray-300" />
        <p className="text-base sm:text-lg font-bold text-gray-700">
          {`No ${taskType === 'survival' ? 'survival' : 'classification'} datasets found`}
        </p>
        <p className="text-xs sm:text-sm text-gray-500 mt-1">
          {taskType === 'survival'
            ? 'Register datasets with event_time and event_status for survival analysis.'
            : 'Register datasets with class labels for classification tasks.'}
        </p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 px-0.5">
      {datasets.map((dataset) => (
        <div
          key={dataset.dataset_id ?? dataset.dataset_name}
          onClick={() => onSelectDataset(dataset.dataset_id, dataset.dataset_name)}
          className="p-4 sm:p-5 bg-white border border-gray-200 rounded-xl hover:border-primary-400 hover:shadow-lg hover:shadow-primary-600/5 transition-all cursor-pointer group relative overflow-hidden"
        >
          <div className="absolute top-0 right-0 p-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <ArrowRight className="w-4 h-4 text-primary-500" />
          </div>
          <div className="flex items-start gap-3 sm:gap-4">
            <div className="shrink-0 p-2 sm:p-2.5 bg-primary-50 rounded-xl group-hover:bg-primary-100 transition-colors">
              <FolderOpen className="w-5 h-5 sm:w-6 sm:h-6 text-primary-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h4 className="font-bold text-gray-900 truncate group-hover:text-primary-700 transition-colors text-sm sm:text-base">{dataset.dataset_name}</h4>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 sm:mt-2">
                <span className="text-[10px] sm:text-xs font-semibold text-gray-500 flex items-center gap-1">
                  <FileText className="w-3 h-3" />
                  {dataset.file_count} slides
                </span>
                <span className="hidden sm:inline w-1 h-1 bg-gray-300 rounded-full"></span>
                <span className="text-[10px] sm:text-xs font-semibold text-gray-500">{formatBytes(dataset.total_size)}</span>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** Header when no dataset selected */
function DatasetSelectHeader({ selectedCount }: { selectedCount: number }) {
  return (
    <>
      <h3 className="text-base sm:text-lg font-bold text-gray-900">Select Dataset</h3>
      <p className="text-[11px] sm:text-sm text-gray-500 mt-1">
        Choose a source dataset for your analysis task
        {selectedCount > 0 && <span className="ml-2 text-primary-600 font-bold">({selectedCount} files selected)</span>}
      </p>
    </>
  )
}

/** Header when dataset is selected */
function DatasetSelectedHeader({
  selectedDatasetName,
  selectedCount,
  onBack,
}: {
  selectedDatasetName: string
  selectedCount: number
  onBack: () => void
}) {
  return (
    <>
      <div className="flex items-center gap-2 mb-1.5">
        <button onClick={onBack} className="text-xs sm:text-sm text-primary-600 hover:text-primary-700 font-semibold flex items-center gap-1 transition-colors">
          <ChevronLeft className="w-3.5 h-3.5" />
          Back to Datasets
        </button>
      </div>
      <h3 className="text-base sm:text-lg font-bold text-gray-900 truncate">Dataset: {selectedDatasetName}</h3>
      <p className="text-[11px] sm:text-sm text-gray-500 mt-1">Select slides for training ({selectedCount} currently selected)</p>
    </>
  )
}


import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Database,
  HardDrive,
  Search,
  Trash2,
  CheckCircle,
  RefreshCw,
  FolderSearch,
  Upload,
  AlertCircle,
  Layers,
  Clock,
  Plus,
  Info,
  ChevronRight
} from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Select } from '../ui/select'
import { Label } from '../ui/label'
import { Badge } from '../ui/badge'
import { Checkbox } from '../ui/checkbox'
import {
  StorageStats,
  OrphanedFilesInfo,
  CleanupResult,
  OrphanedRecordsInfo,
  OrphanedRecordsCleanupResult,
  StorageConfig,
  ScanDirectoryResponse,
  CheckExternalFilesResponse,
  ExternalDatasetInfo,
  DatasetSummary,
  ExternalFileInfo
} from '../../api'

export interface StorageTabProps {
  // Storage Config
  storageConfig: StorageConfig | null
  storagePath: string
  setStoragePath: (path: string) => void
  storageSaving: boolean
  storageSaved: boolean
  storageConfigError: string | null
  handleStorageSave: (e: React.FormEvent) => Promise<void>
  handleSelectStorageDir: () => Promise<void>

  // Storage Stats
  stats: StorageStats | null
  loadingStorage: boolean
  storageError: string | null
  loadStats: () => Promise<void>

  // Orphaned Files
  orphanedFiles: OrphanedFilesInfo | null
  loadingOrphaned: boolean
  isCleaningUp: boolean
  cleanupResult: CleanupResult | null
  detectOrphaned: (clearCleanupResult?: boolean) => Promise<void>
  handleCleanup: (e: React.MouseEvent) => Promise<void>

  // Orphaned Records
  orphanedRecords: OrphanedRecordsInfo | null
  loadingOrphanedRecords: boolean
  isCleaningUpRecords: boolean
  recordsCleanupResult: OrphanedRecordsCleanupResult | null
  detectOrphanedRecordsHandler: (clearCleanupResult?: boolean) => Promise<void>
  handleRecordsCleanup: (e: React.MouseEvent) => Promise<void>

  // Batch Scan & Register
  batchScanPath: string
  setBatchScanPath: (path: string) => void
  batchScanResult: ScanDirectoryResponse | null
  batchScanning: boolean
  batchScanError: string | null
  batchSelectedFiles: Set<string>
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement | null>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: 'classification' | 'survival'
  setBatchTaskType: (type: 'classification' | 'survival') => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  handleSelectBatchScanDir: () => Promise<void>
  handleBatchScan: () => Promise<void>
  handleBatchFileToggle: (path: string) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => Promise<void>

  // External Datasets
  externalDatasets: ExternalDatasetInfo[]
  loadingExternalDatasets: boolean
  externalDatasetsLoaded: boolean
  loadExternalDatasets: (forceRefresh?: boolean) => Promise<void>
  selectedExternalDatasets: Set<string>
  unbindingDatasets: boolean
  refreshExternalDatasets: () => Promise<void>
  handleExternalDatasetToggle: (datasetId: string | null) => void
  handleExternalDatasetSelectAll: () => void
  handleUnbindDataset: (datasetId: string, datasetName: string) => Promise<void>
  handleUnbindSelectedDatasets: () => Promise<void>

  // External Files Check
  checkingExternalFiles: boolean
  externalFilesResult: CheckExternalFilesResponse | null
  selectedUnavailableFiles: Set<string>
  setSelectedUnavailableFiles: React.Dispatch<React.SetStateAction<Set<string>>>
  deletingUnavailableFiles: boolean
  externalFilesError: string | null
  handleCheckExternalFiles: () => Promise<void>
  handleDeleteUnavailableFiles: () => Promise<void>

  // Utilities
  formatBytes: (bytes: number) => string
  formatFileSize: (bytes: number) => string

  // Electron API check
  hasSelectDirectoryApi: boolean
}

// Helper function to format bytes
const formatBytesLocal = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
}

// Helper function to format file size
const formatFileSizeLocal = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export const StorageTab: React.FC<StorageTabProps> = (props) => {
  const navigate = useNavigate()
  const {
    // Storage Config
    storageConfig,
    storagePath,
    setStoragePath,
    storageSaving,
    storageSaved,
    storageConfigError,
    handleStorageSave,
    handleSelectStorageDir,

    // Storage Stats
    stats,
    loadingStorage,
    storageError,
    loadStats,

    // Orphaned Files
    orphanedFiles,
    loadingOrphaned,
    isCleaningUp,
    cleanupResult,
    detectOrphaned,
    handleCleanup,

    // Orphaned Records
    orphanedRecords,
    loadingOrphanedRecords,
    isCleaningUpRecords,
    recordsCleanupResult,
    detectOrphanedRecordsHandler,
    handleRecordsCleanup,

    // Batch Scan & Register
    batchScanPath,
    setBatchScanPath,
    batchScanResult,
    batchScanning,
    batchScanError,
    batchSelectedFiles,
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
    handleSelectBatchScanDir,
    handleBatchScan,
    handleBatchFileToggle,
    handleBatchSelectAll,
    handleBatchDeselectAll,
    handleBatchRegister,

    // External Datasets
    externalDatasets,
    loadingExternalDatasets,
    externalDatasetsLoaded,
    loadExternalDatasets,
    selectedExternalDatasets,
    unbindingDatasets,
    refreshExternalDatasets,
    handleExternalDatasetToggle,
    handleExternalDatasetSelectAll,
    handleUnbindDataset,
    handleUnbindSelectedDatasets,

    // External Files Check
    checkingExternalFiles,
    externalFilesResult,
    selectedUnavailableFiles,
    setSelectedUnavailableFiles,
    deletingUnavailableFiles,
    externalFilesError,
    handleCheckExternalFiles,
    handleDeleteUnavailableFiles,

    // Utilities
    formatBytes = formatBytesLocal,
    formatFileSize = formatFileSizeLocal,

    // Electron API check
    hasSelectDirectoryApi
  } = props

  // Mutual exclusion: disable all storage operation buttons when any operation is in progress
  const anyStorageOpInProgress = loadingStorage || loadingOrphaned || loadingOrphanedRecords

  return (
    <>
      {/* Storage Location Configuration - Always visible, doesn't depend on stats */}
      <Card className="p-4 sm:p-6 mb-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
            <Database className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
            Storage Location
          </h2>
          {storageConfig?.source && (
            <span className="text-xs text-gray-500">Source: {storageConfig.source}</span>
          )}
        </div>

        <form onSubmit={handleStorageSave} className="space-y-3">
          <div className="flex flex-col md:flex-row gap-2">
            <input
              value={storagePath}
              onChange={(e) => setStoragePath(e.target.value)}
              placeholder="/path/to/PathLab/uploads"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
            <div className="flex gap-2">
              <Button
                type="button"
                onClick={handleSelectStorageDir}
                disabled={storageSaving || !hasSelectDirectoryApi}
                className="bg-gray-100 text-gray-800 hover:bg-gray-200"
              >
                Browse
              </Button>
              <Button type="submit" disabled={storageSaving || !storagePath.trim()}>
                {storageSaving ? 'Saving...' : 'Save'}
              </Button>
            </div>
          </div>

          {storageConfigError && (
            <div className="text-sm text-red-600">{storageConfigError}</div>
          )}
          {storageSaved && (
            <div className="text-sm text-green-600">Storage location saved. Restart services to apply fully.</div>
          )}
          <p className="text-xs text-gray-500">
            This directory stores derived data (coordinates, masks, results, models, logs). Image files can remain in their original locations.
          </p>
        </form>
      </Card>

      {/* Storage Stats - Shows loading/error state inside the card */}
      <Card className="p-4 sm:p-6 mb-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
              <HardDrive className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
              Storage Overview
            </h2>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              loadStats()
            }}
            disabled={anyStorageOpInProgress}
            className="px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            <svg className={`w-4 h-4 ${loadingStorage ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {loadingStorage ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {loadingStorage ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto mb-3"></div>
              <p className="text-gray-500 text-sm">Loading storage statistics...</p>
            </div>
          </div>
        ) : storageError ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <h3 className="text-red-800 font-semibold mb-2">Error</h3>
            <p className="text-red-600 text-sm">{storageError}</p>
            <button
              type="button"
              onClick={loadStats}
              className="mt-3 px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : stats ? (
          <StorageStatsDisplay stats={stats} formatBytes={formatBytes} />
        ) : (
          <div className="text-center py-8 text-gray-500">
            <p>No storage data available.</p>
          </div>
        )}
      </Card>

      {/* Orphaned Files & Orphaned Records Management - Side by Side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Orphaned Files Card */}
        <OrphanedFilesCard
          orphanedFiles={orphanedFiles}
          loadingOrphaned={loadingOrphaned}
          isCleaningUp={isCleaningUp}
          cleanupResult={cleanupResult}
          detectOrphaned={detectOrphaned}
          handleCleanup={handleCleanup}
          formatBytes={formatBytes}
          anyStorageOpInProgress={anyStorageOpInProgress}
        />

        {/* Orphaned Records Card */}
        <OrphanedRecordsCard
          orphanedRecords={orphanedRecords}
          loadingOrphanedRecords={loadingOrphanedRecords}
          isCleaningUpRecords={isCleaningUpRecords}
          recordsCleanupResult={recordsCleanupResult}
          detectOrphanedRecordsHandler={detectOrphanedRecordsHandler}
          handleRecordsCleanup={handleRecordsCleanup}
          anyStorageOpInProgress={anyStorageOpInProgress}
        />
      </div>

      {/* Batch Scan & Register WSI Files */}
      <BatchRegisterCard
        batchScanPath={batchScanPath}
        setBatchScanPath={setBatchScanPath}
        batchScanResult={batchScanResult}
        batchScanning={batchScanning}
        batchScanError={batchScanError}
        batchSelectedFiles={batchSelectedFiles}
        batchDatasetMode={batchDatasetMode}
        setBatchDatasetMode={setBatchDatasetMode}
        batchSelectedDatasetId={batchSelectedDatasetId}
        setBatchSelectedDatasetId={setBatchSelectedDatasetId}
        batchNewDatasetNameRef={batchNewDatasetNameRef}
        batchRegistering={batchRegistering}
        batchImportTaskId={batchImportTaskId}
        batchDatasets={batchDatasets}
        batchTaskType={batchTaskType}
        setBatchTaskType={setBatchTaskType}
        batchDataLevel={batchDataLevel}
        setBatchDataLevel={setBatchDataLevel}
        handleSelectBatchScanDir={handleSelectBatchScanDir}
        handleBatchScan={handleBatchScan}
        handleBatchFileToggle={handleBatchFileToggle}
        handleBatchSelectAll={handleBatchSelectAll}
        handleBatchDeselectAll={handleBatchDeselectAll}
        handleBatchRegister={handleBatchRegister}
        formatFileSize={formatFileSize}
        hasSelectDirectoryApi={hasSelectDirectoryApi}
        externalDatasets={externalDatasets}
        loadingExternalDatasets={loadingExternalDatasets}
        externalDatasetsLoaded={externalDatasetsLoaded}
        loadExternalDatasets={loadExternalDatasets}
        selectedExternalDatasets={selectedExternalDatasets}
        unbindingDatasets={unbindingDatasets}
        refreshExternalDatasets={refreshExternalDatasets}
        handleExternalDatasetToggle={handleExternalDatasetToggle}
        handleExternalDatasetSelectAll={handleExternalDatasetSelectAll}
        handleUnbindDataset={handleUnbindDataset}
        handleUnbindSelectedDatasets={handleUnbindSelectedDatasets}
        navigate={navigate}
      />

      {/* Check External Files Card */}
      <ExternalFilesHealthCheckCard
        checkingExternalFiles={checkingExternalFiles}
        externalFilesResult={externalFilesResult}
        selectedUnavailableFiles={selectedUnavailableFiles}
        setSelectedUnavailableFiles={setSelectedUnavailableFiles}
        deletingUnavailableFiles={deletingUnavailableFiles}
        externalFilesError={externalFilesError}
        handleCheckExternalFiles={handleCheckExternalFiles}
        handleDeleteUnavailableFiles={handleDeleteUnavailableFiles}
      />
    </>
  )
}

// Sub-component: Storage Stats Display
interface StorageStatsDisplayProps {
  stats: StorageStats
  formatBytes: (bytes: number) => string
}

const StorageStatsDisplay: React.FC<StorageStatsDisplayProps> = ({ stats, formatBytes }) => {
  const labelMap: { [key: string]: string } = {
    'wsi_files': 'Original Files',
    'coordinates': 'Coordinates',
    'masks': 'Masks',
    'ai_results': 'AI Results',
    'features_cache': 'Feature',
    'training': 'Training Data',
    'models': 'Models',
    'logs': 'Logs',
  }

  return (
    <>
      {/* Total Storage Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 pb-6 border-b border-gray-200">
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Total Storage</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats.total_size_gb.toFixed(2)} <span className="text-lg text-gray-600">GB</span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {stats.total_size_mb.toFixed(2)} MB
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Total Files</div>
          <div className="text-3xl font-bold text-gray-900">
            {Object.values(stats.breakdown).reduce((sum, info) => sum + info.file_count, 0)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Across {Object.keys(stats.breakdown).length} categories
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Storage Location</div>
          <div className="text-xs font-mono text-gray-900 mt-2 break-all">
            {stats.uploads_dir}
          </div>
        </div>
      </div>

      {/* Storage Breakdown */}
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Storage Breakdown</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {Object.entries(stats.breakdown).map(([category, info]) => {
          const label = labelMap[category] || category
          return (
            <div key={category} className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors">
              <div className="text-xs text-gray-600 mb-1">{label}</div>
              <div className="text-xl font-bold text-gray-900">{info.file_count}</div>
              <div className="text-xs text-gray-500 mt-1">{formatBytes(info.size)}</div>
            </div>
          )
        })}
      </div>
    </>
  )
}

// Sub-component: Orphaned Files Card
interface OrphanedFilesCardProps {
  orphanedFiles: OrphanedFilesInfo | null
  loadingOrphaned: boolean
  isCleaningUp: boolean
  cleanupResult: CleanupResult | null
  detectOrphaned: (clearCleanupResult?: boolean) => Promise<void>
  handleCleanup: (e: React.MouseEvent) => Promise<void>
  formatBytes: (bytes: number) => string
  anyStorageOpInProgress: boolean
}

const OrphanedFilesCard: React.FC<OrphanedFilesCardProps> = ({
  orphanedFiles,
  loadingOrphaned,
  isCleaningUp,
  cleanupResult,
  detectOrphaned,
  handleCleanup,
  formatBytes,
  anyStorageOpInProgress
}) => (
  <Card className="p-4 sm:p-6">
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
      <h2 className="text-lg sm:text-lg font-semibold text-gray-900 flex items-center gap-2">
        <svg className="w-5 h-5 text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        Orphaned Files
      </h2>
      <button
        type="button"
        onClick={() => detectOrphaned()}
        disabled={anyStorageOpInProgress || isCleaningUp}
        className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
      >
        <Search className="w-4 h-4" />
        {loadingOrphaned ? 'Scanning...' : 'Scan'}
      </button>
    </div>
    <p className="text-xs text-gray-500 mb-3">Files on disk without database records</p>

    {orphanedFiles && (
      <div className="space-y-3">
        {/* Show cleanup result if available */}
        {cleanupResult ? (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-green-800 font-semibold mb-1">
              <CheckCircle className="w-5 h-5" />
              Cleanup Complete
            </div>
            <div className="text-sm text-green-700">{cleanupResult.summary}</div>
          </div>
        ) : orphanedFiles.total_orphaned_count > 0 ? (
          /* Show orphaned items warning only when no cleanup result */
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-yellow-800 mb-1">Found orphaned items</div>
                <div className="text-xl font-bold text-yellow-900">
                  {orphanedFiles.total_orphaned_file_count > 0 && (
                    <>{orphanedFiles.total_orphaned_file_count} <span className="text-sm font-normal">files</span></>
                  )}
                  {orphanedFiles.total_orphaned_file_count > 0 && orphanedFiles.total_orphaned_dir_count > 0 && ', '}
                  {orphanedFiles.total_orphaned_dir_count > 0 && (
                    <>{orphanedFiles.total_orphaned_dir_count} <span className="text-sm font-normal">dirs</span></>
                  )}
                </div>
                <div className="text-xs text-yellow-700 mt-1">
                  {formatBytes(orphanedFiles.total_orphaned_size)} can be freed
                </div>
              </div>
              <button
                type="button"
                onClick={handleCleanup}
                disabled={anyStorageOpInProgress || isCleaningUp}
                className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                {isCleaningUp ? 'Cleaning...' : 'Clean Up'}
              </button>
            </div>
          </div>
        ) : (
          /* Show no orphaned files message */
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-green-800">
              <CheckCircle className="w-5 h-5" />
              <span className="text-sm font-medium">No orphaned files found</span>
            </div>
          </div>
        )}
      </div>
    )}
  </Card>
)

// Sub-component: Orphaned Records Card
interface OrphanedRecordsCardProps {
  orphanedRecords: OrphanedRecordsInfo | null
  loadingOrphanedRecords: boolean
  isCleaningUpRecords: boolean
  recordsCleanupResult: OrphanedRecordsCleanupResult | null
  detectOrphanedRecordsHandler: (clearCleanupResult?: boolean) => Promise<void>
  handleRecordsCleanup: (e: React.MouseEvent) => Promise<void>
  anyStorageOpInProgress: boolean
}

const OrphanedRecordsCard: React.FC<OrphanedRecordsCardProps> = ({
  orphanedRecords,
  loadingOrphanedRecords,
  isCleaningUpRecords,
  recordsCleanupResult,
  detectOrphanedRecordsHandler,
  handleRecordsCleanup,
  anyStorageOpInProgress
}) => (
  <Card className="p-4 sm:p-6">
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
      <h2 className="text-lg sm:text-lg font-semibold text-gray-900 flex items-center gap-2">
        <Database className="w-5 h-5 text-gray-700" />
        Orphaned Records
      </h2>
      <button
        type="button"
        onClick={() => detectOrphanedRecordsHandler()}
        disabled={anyStorageOpInProgress || isCleaningUpRecords}
        className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
      >
        <Search className="w-4 h-4" />
        {loadingOrphanedRecords ? 'Scanning...' : 'Scan'}
      </button>
    </div>
    <p className="text-xs text-gray-500 mb-3">Database records referencing deleted entities</p>

    {orphanedRecords && (
      <div className="space-y-3">
        {orphanedRecords.total_orphaned_count > 0 ? (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-yellow-800 mb-1">Found orphaned records</div>
                <div className="text-xl font-bold text-yellow-900">
                  {orphanedRecords.total_orphaned_count} <span className="text-sm font-normal">records</span>
                </div>
                <div className="text-xs text-yellow-700 mt-1">
                  {Object.entries(orphanedRecords.summary)
                    .filter(([, count]) => count > 0)
                    .map(([cat, count]) => `${count} ${cat.replace(/_/g, ' ')}`)
                    .join(', ')}
                </div>
              </div>
              <button
                type="button"
                onClick={handleRecordsCleanup}
                disabled={anyStorageOpInProgress || isCleaningUpRecords}
                className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Trash2 className="w-4 h-4" />
                {isCleaningUpRecords ? 'Cleaning...' : 'Clean Up'}
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-green-800">
              <CheckCircle className="w-5 h-5" />
              <span className="text-sm font-medium">No orphaned records found</span>
            </div>
          </div>
        )}

        {recordsCleanupResult && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <div className="flex items-center gap-2 text-green-800 font-semibold mb-1">
              <CheckCircle className="w-5 h-5" />
              Cleanup Complete
            </div>
            <div className="text-sm text-green-700">{recordsCleanupResult.summary}</div>
          </div>
        )}
      </div>
    )}
  </Card>
)


// Sub-component: Batch Register Card (includes External Datasets Table)
interface BatchRegisterCardProps {
  batchScanPath: string
  setBatchScanPath: (path: string) => void
  batchScanResult: ScanDirectoryResponse | null
  batchScanning: boolean
  batchScanError: string | null
  batchSelectedFiles: Set<string>
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement | null>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: 'classification' | 'survival'
  setBatchTaskType: (type: 'classification' | 'survival') => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  handleSelectBatchScanDir: () => Promise<void>
  handleBatchScan: () => Promise<void>
  handleBatchFileToggle: (path: string) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => Promise<void>
  formatFileSize: (bytes: number) => string
  hasSelectDirectoryApi: boolean
  // External Datasets
  externalDatasets: ExternalDatasetInfo[]
  loadingExternalDatasets: boolean
  externalDatasetsLoaded: boolean
  loadExternalDatasets: (forceRefresh?: boolean) => Promise<void>
  selectedExternalDatasets: Set<string>
  unbindingDatasets: boolean
  refreshExternalDatasets: () => Promise<void>
  handleExternalDatasetToggle: (datasetId: string | null) => void
  handleExternalDatasetSelectAll: () => void
  handleUnbindDataset: (datasetId: string, datasetName: string) => Promise<void>
  handleUnbindSelectedDatasets: () => Promise<void>
  navigate: (path: string) => void
}

const BatchRegisterCard: React.FC<BatchRegisterCardProps> = ({
  batchScanPath,
  setBatchScanPath,
  batchScanResult,
  batchScanning,
  batchScanError,
  batchSelectedFiles,
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
  handleSelectBatchScanDir,
  handleBatchScan,
  handleBatchFileToggle,
  handleBatchSelectAll,
  handleBatchDeselectAll,
  handleBatchRegister,
  formatFileSize,
  hasSelectDirectoryApi,
  externalDatasets,
  loadingExternalDatasets,
  externalDatasetsLoaded,
  loadExternalDatasets,
  selectedExternalDatasets,
  unbindingDatasets,
  refreshExternalDatasets,
  handleExternalDatasetToggle,
  handleExternalDatasetSelectAll,
  handleUnbindDataset,
  handleUnbindSelectedDatasets,
  navigate
}) => (
  <Card className="p-4 sm:p-6 mt-6">
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
      <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center gap-2">
        <FolderSearch className="w-5 h-5 sm:w-6 sm:h-6 text-gray-700" />
        Batch Register WSI Files
      </h2>
    </div>

    <p className="text-sm text-gray-600 mb-3">
      Scan a directory for WSI files hosted on the server and register them to a dataset.
    </p>

    {/* Directory Selection */}
    <div className="flex gap-2 mb-4">
      <Input
        value={batchScanPath}
        onChange={(e) => setBatchScanPath(e.target.value)}
        placeholder="Enter directory path to scan..."
        className="flex-1"
      />
      {hasSelectDirectoryApi && (
        <Button variant="outline" onClick={handleSelectBatchScanDir}>
          Browse
        </Button>
      )}
      <Button
        onClick={handleBatchScan}
        disabled={!batchScanPath.trim() || batchScanning}
        className="gap-2"
        variant="primary"
      >
        {batchScanning ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Scanning...
          </>
        ) : (
          <>
            <Search className="w-4 h-4" />
            Scan
          </>
        )}
      </Button>
    </div>

    {batchScanError && (
      <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
        <AlertCircle className="w-4 h-4" />
        {batchScanError}
      </div>
    )}

    {/* Scan Results */}
    {batchScanResult && (
      <BatchScanResults
        batchScanResult={batchScanResult}
        batchSelectedFiles={batchSelectedFiles}
        batchDatasetMode={batchDatasetMode}
        setBatchDatasetMode={setBatchDatasetMode}
        batchSelectedDatasetId={batchSelectedDatasetId}
        setBatchSelectedDatasetId={setBatchSelectedDatasetId}
        batchNewDatasetNameRef={batchNewDatasetNameRef}
        batchRegistering={batchRegistering}
        batchImportTaskId={batchImportTaskId}
        batchDatasets={batchDatasets}
        batchTaskType={batchTaskType}
        setBatchTaskType={setBatchTaskType}
        batchDataLevel={batchDataLevel}
        setBatchDataLevel={setBatchDataLevel}
        handleBatchFileToggle={handleBatchFileToggle}
        handleBatchSelectAll={handleBatchSelectAll}
        handleBatchDeselectAll={handleBatchDeselectAll}
        handleBatchRegister={handleBatchRegister}
        formatFileSize={formatFileSize}
      />
    )}

    {/* External Datasets Table */}
    <ExternalDatasetsTable
      externalDatasets={externalDatasets}
      loadingExternalDatasets={loadingExternalDatasets}
      externalDatasetsLoaded={externalDatasetsLoaded}
      loadExternalDatasets={loadExternalDatasets}
      selectedExternalDatasets={selectedExternalDatasets}
      unbindingDatasets={unbindingDatasets}
      refreshExternalDatasets={refreshExternalDatasets}
      handleExternalDatasetToggle={handleExternalDatasetToggle}
      handleExternalDatasetSelectAll={handleExternalDatasetSelectAll}
      handleUnbindDataset={handleUnbindDataset}
      handleUnbindSelectedDatasets={handleUnbindSelectedDatasets}
      navigate={navigate}
    />
  </Card>
)


// Sub-component: Batch Scan Results
interface BatchScanResultsProps {
  batchScanResult: ScanDirectoryResponse
  batchSelectedFiles: Set<string>
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement | null>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: 'classification' | 'survival'
  setBatchTaskType: (type: 'classification' | 'survival') => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  handleBatchFileToggle: (path: string) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => Promise<void>
  formatFileSize: (bytes: number) => string
}

const BatchScanResults: React.FC<BatchScanResultsProps> = ({
  batchScanResult,
  batchSelectedFiles,
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
  handleBatchFileToggle,
  handleBatchSelectAll,
  handleBatchDeselectAll,
  handleBatchRegister,
  formatFileSize
}) => (
  <div className="space-y-4">
    <div className="flex items-center justify-between">
      <div className="text-sm text-gray-600">
        Found <span className="font-semibold text-gray-900">{batchScanResult.total_count}</span> files
        ({batchScanResult.files.filter(f => f.data_type === 'wsi').length} WSI, {batchScanResult.files.filter(f => f.data_type === 'patch').length} patch, {batchScanResult.valid_count} valid, {formatFileSize(batchScanResult.total_size)} total)
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={handleBatchSelectAll}>
          Select All Valid
        </Button>
        <Button variant="outline" size="sm" onClick={handleBatchDeselectAll}>
          Deselect All
        </Button>
      </div>
    </div>

    {/* File List */}
    <div className="max-h-80 overflow-y-auto border border-gray-100 rounded-xl shadow-sm bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b border-gray-100">
          <tr>
            <th className="px-3 py-3 text-left w-10"></th>
            <th className="px-3 py-3 text-left font-semibold text-gray-700">Filename</th>
            <th className="px-3 py-3 text-left w-16 font-semibold text-gray-700">Type</th>
            <th className="px-3 py-3 text-left w-20 font-semibold text-gray-700">Format</th>
            <th className="px-3 py-3 text-right w-24 font-semibold text-gray-700">Size</th>
            <th className="px-3 py-3 text-left w-32 font-semibold text-gray-700">Status</th>
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
                  checked={batchSelectedFiles.has(file.path)}
                  onCheckedChange={() => handleBatchFileToggle(file.path)}
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
                  {file.data_type === 'wsi' ? 'WSI' : 'Patch'}
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
              <td className="px-3 py-3">
                {file.valid ? (
                  <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 gap-1 py-0 px-2 font-normal">
                    <CheckCircle className="w-3 h-3" /> Valid
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 gap-1 py-0 px-2 font-normal" title={file.validation_message || ''}>
                    <AlertCircle className="w-3 h-3" /> Invalid
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>

    {/* Task Type Selection */}
    <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
      <Label className="text-sm font-medium text-slate-900 block">Task Type</Label>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setBatchTaskType('classification')}
          className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
            batchTaskType === 'classification'
              ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
              : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Layers className={`w-4 h-4 ${batchTaskType === 'classification' ? 'text-primary-700' : 'text-gray-400'}`} />
            Classification
          </div>
        </button>
        <button
          type="button"
          onClick={() => setBatchTaskType('survival')}
          className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
            batchTaskType === 'survival'
              ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
              : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Clock className={`w-4 h-4 ${batchTaskType === 'survival' ? 'text-primary-700' : 'text-gray-400'}`} />
            Survival Analysis
          </div>
        </button>
      </div>

      {/* Info message based on task type */}
      <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
        <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-gray-600">
          {batchTaskType === 'classification' ? (
            <>
              Files will be registered with default label: <span className="font-medium text-gray-800">"External Import"</span>
              <br />
              You can modify labels later in the <span className="font-medium text-primary-600">Data Repository</span> page.
            </>
          ) : (
            <>
              Files will be registered with <span className="font-medium text-gray-800">no event time/status</span> set.
              <br />
              You can set survival data later in the <span className="font-medium text-primary-600">Data Repository</span> page.
            </>
          )}
        </div>
      </div>
    </div>

    {/* Data Level Selection */}
    <DataLevelSelection batchDataLevel={batchDataLevel} setBatchDataLevel={setBatchDataLevel} />

    {/* Dataset Selection */}
    <DatasetSelection
      batchDatasetMode={batchDatasetMode}
      setBatchDatasetMode={setBatchDatasetMode}
      batchSelectedDatasetId={batchSelectedDatasetId}
      setBatchSelectedDatasetId={setBatchSelectedDatasetId}
      batchNewDatasetNameRef={batchNewDatasetNameRef}
      batchDatasets={batchDatasets}
    />

    {/* Register Button */}
    <div className="flex items-center justify-between">
      <div className="text-sm text-gray-600">
        {batchSelectedFiles.size} file(s) selected
      </div>
      <Button
        onClick={handleBatchRegister}
        disabled={batchSelectedFiles.size === 0 || batchRegistering}
        className="gap-2"
      >
        {batchRegistering ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Registering...
          </>
        ) : (
          <>
            <Upload className="w-4 h-4" />
            Register Selected ({batchSelectedFiles.size})
          </>
        )}
      </Button>
    </div>

    {/* Task Submitted Message */}
    {batchImportTaskId && (
      <div className="p-4 rounded-lg border bg-blue-50 border-blue-200">
        <div className="flex items-center gap-2 font-semibold text-blue-700">
          <CheckCircle className="w-5 h-5" />
          Import Task Submitted
        </div>
        <div className="text-sm text-blue-600 mt-1">
          Task ID: <span className="font-mono">{batchImportTaskId}</span>
        </div>
        <div className="text-sm text-blue-600 mt-1">
          Files are being registered in the background. Check the notification center for progress.
        </div>
      </div>
    )}
  </div>
)

// Sub-component: Data Level Selection
interface DataLevelSelectionProps {
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
}

const DataLevelSelection: React.FC<DataLevelSelectionProps> = ({ batchDataLevel, setBatchDataLevel }) => (
  <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
    <Label className="text-sm font-medium text-slate-900 block">Data Level</Label>
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => setBatchDataLevel('file')}
        className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
          batchDataLevel === 'file'
            ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
            : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Layers className={`w-4 h-4 ${batchDataLevel === 'file' ? 'text-primary-700' : 'text-gray-400'}`} />
          File-Level
        </div>
      </button>
      <button
        type="button"
        onClick={() => setBatchDataLevel('case')}
        className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
          batchDataLevel === 'case'
            ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
            : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Database className={`w-4 h-4 ${batchDataLevel === 'case' ? 'text-primary-700' : 'text-gray-400'}`} />
          Case-Level
        </div>
      </button>
    </div>

    {/* Info message based on data level */}
    <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
      <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
      <div className="text-xs text-gray-600">
        {batchDataLevel === 'file' ? (
          <>
            Each file is treated as an <span className="font-medium text-gray-800">independent sample</span>.
            <br />
            Suitable for file-level classification or survival analysis.
          </>
        ) : (
          <>
            Files are grouped by <span className="font-medium text-gray-800">case ID</span> (extracted from filename).
            <br />
            Suitable for case-level survival analysis where multiple files share the same outcome.
          </>
        )}
      </div>
    </div>
  </div>
)

// Sub-component: Dataset Selection
interface DatasetSelectionProps {
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement | null>
  batchDatasets: DatasetSummary[]
}

const DatasetSelection: React.FC<DatasetSelectionProps> = ({
  batchDatasetMode,
  setBatchDatasetMode,
  batchSelectedDatasetId,
  setBatchSelectedDatasetId,
  batchNewDatasetNameRef,
  batchDatasets
}) => (
  <div className="bg-gray-50 rounded-lg p-4 space-y-3">
    <Label className="text-sm font-medium text-gray-700 block">Dataset</Label>
    <div className="flex gap-2">
      <button
        type="button"
        onClick={() => setBatchDatasetMode('new')}
        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
          batchDatasetMode === 'new'
            ? 'bg-primary-600 text-white shadow-md'
            : 'bg-white text-gray-600 border border-gray-200 hover:border-primary-300 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Plus className="w-4 h-4" />
          Create New
        </div>
      </button>
      <button
        type="button"
        onClick={() => setBatchDatasetMode('existing')}
        className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-all ${
          batchDatasetMode === 'existing'
            ? 'bg-primary-600 text-white shadow-md'
            : 'bg-white text-gray-600 border border-gray-200 hover:border-primary-300 hover:text-primary-600'
        }`}
      >
        <div className="flex items-center justify-center gap-2">
          <Database className="w-4 h-4" />
          Add to Existing
        </div>
      </button>
    </div>

    {batchDatasetMode === 'new' ? (
      <Input
        ref={batchNewDatasetNameRef}
        placeholder="Enter new dataset name..."
      />
    ) : (
      <Select
        value={batchSelectedDatasetId}
        onChange={(value) => setBatchSelectedDatasetId(value)}
        options={[
          { value: '', label: 'Select a dataset...' },
          ...batchDatasets.filter(d => d.dataset_id !== null).map(d => ({ value: d.dataset_id!, label: d.dataset_name }))
        ]}
      />
    )}
  </div>
)

// Sub-component: External Datasets Table
interface ExternalDatasetsTableProps {
  externalDatasets: ExternalDatasetInfo[]
  loadingExternalDatasets: boolean
  externalDatasetsLoaded: boolean
  loadExternalDatasets: (forceRefresh?: boolean) => Promise<void>
  selectedExternalDatasets: Set<string>
  unbindingDatasets: boolean
  refreshExternalDatasets: () => Promise<void>
  handleExternalDatasetToggle: (datasetId: string | null) => void
  handleExternalDatasetSelectAll: () => void
  handleUnbindDataset: (datasetId: string, datasetName: string) => Promise<void>
  handleUnbindSelectedDatasets: () => Promise<void>
  navigate: (path: string) => void
}

const ExternalDatasetsTable: React.FC<ExternalDatasetsTableProps> = ({
  externalDatasets,
  loadingExternalDatasets,
  externalDatasetsLoaded,
  loadExternalDatasets,
  selectedExternalDatasets,
  unbindingDatasets,
  refreshExternalDatasets,
  handleExternalDatasetToggle,
  handleExternalDatasetSelectAll,
  handleUnbindDataset,
  handleUnbindSelectedDatasets,
  navigate
}) => (
  <div className="border rounded-lg mt-4">
    <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
      <h3 className="font-medium text-gray-900 flex items-center gap-2">
        <HardDrive className="w-4 h-4" />
        Externally Imported Datasets ({externalDatasetsLoaded ? externalDatasets.length : '—'})
      </h3>
      <div className="flex items-center gap-2">
        {externalDatasets.length > 0 && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleExternalDatasetSelectAll}
              className="text-xs"
            >
              {selectedExternalDatasets.size === externalDatasets.filter(d => d.dataset_id).length ? 'Deselect All' : 'Select All'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleUnbindSelectedDatasets}
              disabled={selectedExternalDatasets.size === 0 || unbindingDatasets}
              className="gap-1 text-red-600 border-red-100 hover:bg-red-50 hover:text-red-700 hover:border-red-200"
            >
              {unbindingDatasets ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Trash2 className="w-3 h-3" />
              )}
              Unbind Selected ({selectedExternalDatasets.size})
            </Button>
          </>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={externalDatasetsLoaded ? refreshExternalDatasets : () => loadExternalDatasets()}
          disabled={loadingExternalDatasets}
          className="gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${loadingExternalDatasets ? 'animate-spin' : ''}`} />
          {externalDatasetsLoaded ? 'Refresh' : 'Load'}
        </Button>
      </div>
    </div>
    {loadingExternalDatasets ? (
      <div className="p-8 text-center text-gray-500">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
        Loading external datasets...
      </div>
    ) : !externalDatasetsLoaded ? (
      <div className="p-8 text-center text-gray-500">
        <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p className="mb-2">External datasets have not been loaded yet.</p>
        <p className="text-xs text-gray-400 mb-3">Load dataset names and file counts from the database.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => loadExternalDatasets()}
          className="gap-1"
        >
          <Search className="w-3 h-3" />
          Load External Datasets
        </Button>
      </div>
    ) : externalDatasets.length === 0 ? (
      <div className="p-8 text-center text-gray-500">
        <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p>No externally imported datasets found.</p>
        <p className="text-xs mt-1">Use the form above to scan and register WSI files from external drives.</p>
      </div>
    ) : (
      <>
        <div className="max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b">
              <tr>
                <th className="px-3 py-3 text-left w-10"></th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700 min-w-[200px]">Dataset Name</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">Files Count</th>
                <th className="px-4 py-3 text-center w-32 font-semibold text-gray-700">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {externalDatasets.map((dataset) => (
                <tr key={dataset.dataset_id || 'uncategorized'} className="hover:bg-gray-50/50 transition-colors group">
                  <td className="px-3 py-3">
                    {dataset.dataset_id && (
                      <Checkbox
                        checked={selectedExternalDatasets.has(dataset.dataset_id)}
                        onCheckedChange={() => handleExternalDatasetToggle(dataset.dataset_id!)}
                      />
                    )}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {dataset.dataset_name}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    <span className="font-mono bg-gray-100 px-2 py-0.5 rounded text-xs">{dataset.total_files} files</span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    {dataset.dataset_id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleUnbindDataset(dataset.dataset_id!, dataset.dataset_name)}
                        disabled={unbindingDatasets}
                        className="text-red-500 hover:text-red-700 hover:bg-red-50 gap-1.5 h-8 px-3 transition-all rounded-md border border-transparent hover:border-red-100"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        <span className="text-xs font-semibold">Unbind</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 bg-gray-50 border-t text-xs text-gray-500">
          <strong>Unbind</strong> removes database records only. Files on external drives are NOT deleted.
          To manage individual files, go to <button onClick={() => navigate('/wsi-list')} className="font-medium text-primary-600 hover:underline inline-flex items-center gap-0.5">Data Repository <ChevronRight className="w-3 h-3" /></button>.
        </div>
      </>
    )}
  </div>
)

// Sub-component: External Files Health Check Card
interface ExternalFilesHealthCheckCardProps {
  checkingExternalFiles: boolean
  externalFilesResult: CheckExternalFilesResponse | null
  selectedUnavailableFiles: Set<string>
  setSelectedUnavailableFiles: React.Dispatch<React.SetStateAction<Set<string>>>
  deletingUnavailableFiles: boolean
  externalFilesError: string | null
  handleCheckExternalFiles: () => Promise<void>
  handleDeleteUnavailableFiles: () => Promise<void>
}

const ExternalFilesHealthCheckCard: React.FC<ExternalFilesHealthCheckCardProps> = ({
  checkingExternalFiles,
  externalFilesResult,
  selectedUnavailableFiles,
  setSelectedUnavailableFiles,
  deletingUnavailableFiles,
  externalFilesError,
  handleCheckExternalFiles,
  handleDeleteUnavailableFiles
}) => (
  <Card className="overflow-hidden border-none shadow-xl bg-white/80 backdrop-blur-sm">
    <div className="bg-gradient-to-r from-slate-50 to-white px-6 py-5 border-b border-slate-100 flex items-center justify-between">
      <div>
        <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2.5">
          <HardDrive className="w-5 h-5 text-primary-600" />
          External Files Health Check
        </h2>
        <p className="text-xs text-slate-500 mt-1 font-medium">
          Verify accessibility of files imported from external storage devices
        </p>
      </div>
      <Button
        onClick={handleCheckExternalFiles}
        disabled={checkingExternalFiles}
        variant={externalFilesResult ? "outline" : "default"}
        className={`gap-2.5 px-5 h-10 font-bold transition-all shadow-sm ${!externalFilesResult ? 'bg-primary-600 hover:bg-primary-700 hover:shadow-md text-white' : 'hover:bg-slate-50'}`}
      >
        {checkingExternalFiles ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Checking...
          </>
        ) : (
          <>
            <Search className="w-4 h-4" />
            Check Files
          </>
        )}
      </Button>
    </div>

    <div className="p-6 pt-4">
      {externalFilesError && (
        <div className="mb-4 p-4 bg-rose-50 border border-rose-200 rounded-xl text-rose-700 flex items-center gap-3 animate-fadeIn">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span className="text-sm font-semibold">{externalFilesError}</span>
        </div>
      )}

      {externalFilesResult && (
        <div className="space-y-6 animate-fadeIn">
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4 mb-8">
            <div className="relative overflow-hidden bg-slate-50 p-5 rounded-2xl border border-slate-200/60 shadow-sm transition-all hover:shadow-md">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-slate-500 text-[10px] uppercase tracking-widest font-bold mb-1">Total External</p>
                  <p className="text-3xl font-extrabold text-slate-900 tracking-tight">{externalFilesResult.total_external.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-slate-200/50 rounded-lg">
                  <Database className="w-5 h-5 text-slate-600" />
                </div>
              </div>
              <div className="mt-4 h-1 w-full bg-slate-200 rounded-full overflow-hidden">
                <div className="h-full bg-slate-500 w-full opacity-30"></div>
              </div>
            </div>

            <div className="relative overflow-hidden bg-emerald-50/40 p-5 rounded-2xl border border-emerald-100 shadow-sm transition-all hover:shadow-md">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-emerald-700/70 text-[10px] uppercase tracking-widest font-bold mb-1">Available</p>
                  <p className="text-3xl font-extrabold text-emerald-700 tracking-tight">{externalFilesResult.available_count.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-emerald-100/80 rounded-lg">
                  <CheckCircle className="w-5 h-5 text-emerald-600" />
                </div>
              </div>
              <div className="mt-4 h-1 w-full bg-emerald-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 transition-all duration-1000"
                  style={{ width: `${externalFilesResult.total_external > 0 ? (externalFilesResult.available_count / externalFilesResult.total_external) * 100 : 0}%` }}
                ></div>
              </div>
            </div>

            <div className="relative overflow-hidden bg-rose-50/40 p-5 rounded-2xl border border-rose-100 shadow-sm transition-all hover:shadow-md">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-rose-700/70 text-[10px] uppercase tracking-widest font-bold mb-1">Unavailable</p>
                  <p className="text-3xl font-extrabold text-rose-700 tracking-tight">{externalFilesResult.unavailable_count.toLocaleString()}</p>
                </div>
                <div className="p-2 bg-rose-100/80 rounded-lg">
                  <AlertCircle className="w-5 h-5 text-rose-600" />
                </div>
              </div>
              <div className="mt-4 h-1 w-full bg-rose-100 rounded-full overflow-hidden">
                <div
                  className="h-full bg-rose-500 transition-all duration-1000"
                  style={{ width: `${externalFilesResult.total_external > 0 ? (externalFilesResult.unavailable_count / externalFilesResult.total_external) * 100 : 0}%` }}
                ></div>
              </div>
            </div>
          </div>

          {/* Unavailable files list */}
          {externalFilesResult.unavailable.length > 0 && (
            <UnavailableFilesList
              unavailableFiles={externalFilesResult.unavailable}
              selectedUnavailableFiles={selectedUnavailableFiles}
              setSelectedUnavailableFiles={setSelectedUnavailableFiles}
              deletingUnavailableFiles={deletingUnavailableFiles}
              handleDeleteUnavailableFiles={handleDeleteUnavailableFiles}
            />
          )}

          {/* All files available message */}
          {externalFilesResult.unavailable.length === 0 && externalFilesResult.total_external > 0 && (
            <div className="relative overflow-hidden p-8 bg-gradient-to-br from-emerald-50 to-teal-50/30 border border-emerald-100 rounded-3xl flex flex-col items-center text-center gap-4 animate-fadeIn shadow-inner">
              <div className="w-16 h-16 bg-white shadow-xl shadow-emerald-200/50 flex items-center justify-center rounded-2xl transform rotate-3 transition-transform hover:rotate-0 duration-500">
                <CheckCircle className="w-8 h-8 text-emerald-500" />
              </div>
              <div className="space-y-1">
                <h3 className="text-emerald-900 font-black text-xl tracking-tight">System Fully Synchronized</h3>
                <p className="text-emerald-700/70 text-sm max-w-md mx-auto leading-relaxed font-medium">
                  All <span className="text-emerald-800 font-bold">{externalFilesResult.total_external}</span> external files are currently mapped and accessible. No action required.
                </p>
              </div>
              <div className="absolute top-0 right-0 p-8 opacity-[0.03] pointer-events-none transform translate-x-1/4 -translate-y-1/4 scale-150">
                <CheckCircle className="w-48 h-48" />
              </div>
            </div>
          )}

          {/* No external files message */}
          {externalFilesResult.total_external === 0 && (
            <div className="p-10 bg-slate-50/50 border border-dashed border-slate-200 rounded-3xl flex flex-col items-center text-center gap-4">
              <div className="p-4 bg-white rounded-2xl shadow-sm border border-slate-100">
                <HardDrive className="w-8 h-8 text-slate-300" />
              </div>
              <div className="space-y-1">
                <h3 className="text-slate-900 font-bold">No External Files Detected</h3>
                <p className="text-slate-500 text-sm max-w-xs">You haven't imported any files from external or removable drives yet.</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  </Card>
)



// Sub-component: Unavailable Files List
interface UnavailableFilesListProps {
  unavailableFiles: ExternalFileInfo[]
  selectedUnavailableFiles: Set<string>
  setSelectedUnavailableFiles: React.Dispatch<React.SetStateAction<Set<string>>>
  deletingUnavailableFiles: boolean
  handleDeleteUnavailableFiles: () => Promise<void>
}

const UnavailableFilesList: React.FC<UnavailableFilesListProps> = ({
  unavailableFiles,
  selectedUnavailableFiles,
  setSelectedUnavailableFiles,
  deletingUnavailableFiles,
  handleDeleteUnavailableFiles
}) => {
  const handleToggle = (wsiId: string) => {
    setSelectedUnavailableFiles((prev) => {
      const next = new Set(prev)
      if (next.has(wsiId)) {
        next.delete(wsiId)
      } else {
        next.add(wsiId)
      }
      return next
    })
  }

  const handleSelectAll = () => {
    if (selectedUnavailableFiles.size === unavailableFiles.length) {
      setSelectedUnavailableFiles(new Set())
    } else {
      setSelectedUnavailableFiles(new Set(unavailableFiles.map((f) => f.wsi_id)))
    }
  }

  return (
    <div className="border border-rose-100 rounded-2xl overflow-hidden shadow-sm">
      <div className="bg-rose-50/50 px-5 py-4 border-b border-rose-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-rose-100 rounded-lg">
            <AlertCircle className="w-4 h-4 text-rose-600" />
          </div>
          <div>
            <h3 className="font-bold text-rose-900 text-sm">
              Unavailable Files ({unavailableFiles.length})
            </h3>
            <p className="text-xs text-rose-600/70 mt-0.5">
              These files are registered but no longer accessible at their original location
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSelectAll}
            className="text-xs text-rose-700 hover:bg-rose-100"
          >
            {selectedUnavailableFiles.size === unavailableFiles.length ? 'Deselect All' : 'Select All'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDeleteUnavailableFiles}
            disabled={selectedUnavailableFiles.size === 0 || deletingUnavailableFiles}
            className="gap-1.5 text-rose-600 border-rose-200 hover:bg-rose-50 hover:text-rose-700 hover:border-rose-300 font-semibold"
          >
            {deletingUnavailableFiles ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Deleting...
              </>
            ) : (
              <>
                <Trash2 className="w-3.5 h-3.5" />
                Delete Selected ({selectedUnavailableFiles.size})
              </>
            )}
          </Button>
        </div>
      </div>

      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-rose-50/30 backdrop-blur-sm sticky top-0 border-b border-rose-100">
            <tr>
              <th className="px-4 py-3 text-left w-10"></th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider">Filename</th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider">Dataset</th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider max-w-xs">Path</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rose-50">
            {unavailableFiles.map((file) => (
              <tr
                key={file.wsi_id}
                className="hover:bg-rose-50/50 transition-colors"
              >
                <td className="px-4 py-3">
                  <Checkbox
                    checked={selectedUnavailableFiles.has(file.wsi_id)}
                    onCheckedChange={() => handleToggle(file.wsi_id)}
                  />
                </td>
                <td className="px-4 py-3 font-medium text-rose-900">
                  {file.original_filename}
                </td>
                <td className="px-4 py-3 text-rose-700/80">
                  {file.dataset_name || <span className="text-rose-400 italic">Uncategorized</span>}
                </td>
                <td className="px-4 py-3 text-rose-600/70 text-xs font-mono truncate max-w-xs" title={file.wsi_path}>
                  {file.wsi_path}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 bg-rose-50/30 border-t border-rose-100 text-xs text-rose-600/80">
        <strong>Delete</strong> removes database records only. Original files (if they exist elsewhere) are not affected.
      </div>
    </div>
  )
}

import React from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Database,
  HardDrive,
  Trash2,
  AlertCircle,
  ChevronDown,
  ChevronUp
} from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
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
  DatasetSummary
} from '../../api'
import { formatBytes as formatBytesDefault, formatFileSize as formatFileSizeDefault } from '../../lib/utils'
import {
  StorageStatsDisplay,
  OrphanedFilesCard,
  OrphanedRecordsCard,
  BatchRegisterCard,
  ExternalFilesHealthCheckCard
} from './storage'

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

  // Reset Derived Data
  handleResetDerivedData: () => Promise<void>

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
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement>
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

export const StorageTab: React.FC<StorageTabProps> = (props) => {
  const navigate = useNavigate()
  const [isDangerZoneOpen, setIsDangerZoneOpen] = React.useState(false)
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

    // Reset Derived Data
    handleResetDerivedData,

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
    formatBytes = formatBytesDefault,
    formatFileSize = formatFileSizeDefault,

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

      {/* Reset Derived Data - Dangerous Operation */}
      <Card className="p-4 sm:p-6 mb-6 border-2 border-red-200 bg-red-50/30">
        <div 
          className="flex items-center justify-between cursor-pointer" 
          onClick={() => setIsDangerZoneOpen(!isDangerZoneOpen)}
        >
          <h2 className="text-lg sm:text-lg font-semibold text-red-900 flex items-center gap-2">
            <AlertCircle className="w-5 h-5 text-red-700" />
            Danger Zone
          </h2>
          <button type="button" className="text-red-700 transition-transform duration-200">
            {isDangerZoneOpen ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
          </button>
        </div>

        {isDangerZoneOpen && (
          <div className="mt-4 animate-in fade-in slide-in-from-top-2 duration-200">
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
              <div>
                <h3 className="text-md font-medium text-red-800 mb-1">
                  Reset All Derived Data
                </h3>
                <p className="text-xs text-red-700">
                  Warning: This will delete ALL processed data while keeping original WSI files.
                </p>
              </div>
              <button
                type="button"
                onClick={handleResetDerivedData}
                disabled={anyStorageOpInProgress}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-end sm:self-auto"
              >
                <Trash2 className="w-4 h-4" />
                Reset All Data
              </button>
            </div>

            <div className="bg-white rounded-lg p-4 border border-red-200">
              <div className="text-sm text-gray-700 space-y-2">
                <p className="font-medium text-red-900">This operation will DELETE:</p>
                <ul className="list-disc list-inside space-y-1 text-xs ml-2">
                  <li>All coordinates files</li>
                  <li>All mask files</li>
                  <li>All feature caches</li>
                  <li>All AI analysis results</li>
                  <li>All training data and tasks</li>
                  <li>All trained models</li>
                  <li>All logs and metadata</li>
                </ul>
                <p className="font-medium text-green-900 mt-3">This operation will PRESERVE:</p>
                <ul className="list-disc list-inside space-y-1 text-xs ml-2">
                  <li>Original WSI files (in wsi_files/)</li>
                </ul>
                <p className="text-xs text-red-700 mt-3 font-medium">
                  This operation CANNOT be undone. Check Background Tasks panel for progress.
                </p>
              </div>
            </div>
          </div>
        )}
      </Card>

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


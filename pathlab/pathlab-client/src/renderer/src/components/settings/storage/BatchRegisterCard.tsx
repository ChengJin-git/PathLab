import React from 'react'
import { FolderSearch, Search, RefreshCw, AlertCircle } from 'lucide-react'
import { Card } from '../../ui/card'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import {
  ScanDirectoryResponse, DatasetSummary,
  ExternalDatasetInfo
} from '../../../api'
import { BatchScanResults } from './BatchScanResults'
import { ExternalDatasetsTable } from './ExternalDatasetsTable'

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

export const BatchRegisterCard: React.FC<BatchRegisterCardProps> = ({
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


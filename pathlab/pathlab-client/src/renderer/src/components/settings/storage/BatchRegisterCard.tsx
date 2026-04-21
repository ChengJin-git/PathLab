import React from 'react'
import { useTranslation } from 'react-i18next'
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
  batchScanStage: 'idle' | 'initial' | 'refresh' | 'segmentationRefresh'
  batchScanError: string | null
  batchSelectedCount: number
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: 'classification' | 'survival' | 'segmentation'
  setBatchTaskType: (type: 'classification' | 'survival' | 'segmentation') => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  batchIsPublic: boolean
  setBatchIsPublic: (value: boolean) => void
  handleSelectBatchScanDir: () => Promise<void>
  handleBatchScan: () => void
  handleBatchScanPageChange: (page: number) => void
  isBatchFileSelected: (path: string, valid: boolean) => boolean
  handleBatchFileToggle: (path: string, valid: boolean) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => void
  formatFileSize: (bytes: number) => string
  hasSelectDirectoryApi: boolean
  externalDatasets: ExternalDatasetInfo[]
  loadingExternalDatasets: boolean
  externalDatasetsLoaded: boolean
  loadExternalDatasets: (forceRefresh?: boolean) => Promise<void>
  selectedExternalDatasets: Set<string>
  unbindingDatasets: boolean
  refreshExternalDatasets: () => void | Promise<void>
  handleExternalDatasetToggle: (datasetId: string | null) => void
  handleExternalDatasetSelectAll: () => void
  handleUnbindDataset: (datasetId: string, datasetName: string) => void | Promise<void>
  handleUnbindSelectedDatasets: () => void | Promise<void>
  navigate: (path: string) => void
}

export const BatchRegisterCard: React.FC<BatchRegisterCardProps> = ({
  batchScanPath,
  setBatchScanPath,
  batchScanResult,
  batchScanning,
  batchScanStage,
  batchScanError,
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
  handleSelectBatchScanDir,
  handleBatchScan,
  handleBatchScanPageChange,
  isBatchFileSelected,
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
}) => {
  const { t } = useTranslation()

  return (
    <Card className="p-4 sm:p-6 mt-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
        <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center gap-2">
          <FolderSearch className="w-5 h-5 sm:w-6 sm:h-6 text-gray-700" />
          {t('settings.storage.batchRegisterTitle')}
        </h2>
      </div>

      <p className="text-sm text-gray-600 mb-3">
        {t('settings.storage.batchRegisterDescription')}
      </p>

      <div className="flex gap-2 mb-4">
        <Input
          value={batchScanPath}
          onChange={(e) => setBatchScanPath(e.target.value)}
          placeholder={t('settings.storage.enterDirectoryPath')}
          className="flex-1"
        />
        {hasSelectDirectoryApi && (
          <Button variant="outline" onClick={handleSelectBatchScanDir}>
            {t('settings.storage.browse')}
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
              {t('settings.storage.scanning')}
            </>
          ) : (
            <>
              <Search className="w-4 h-4" />
              {t('settings.storage.scan')}
            </>
          )}
        </Button>
      </div>

      {batchScanning && batchScanStage === 'initial' && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3">
          <p className="text-sm font-medium text-blue-900">{t('settings.storage.scanInProgressTitle')}</p>
          <p className="mt-1 text-xs text-blue-700">{t('settings.storage.scanInProgressDescription')}</p>
        </div>
      )}

      {batchScanning && batchScanStage !== 'initial' && batchScanResult && (
        <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <p className="text-sm font-medium text-slate-900">{t('settings.storage.refreshingScanResults')}</p>
        </div>
      )}

      {batchScanError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          {batchScanError}
        </div>
      )}

      {batchScanResult && (
        <BatchScanResults
          batchScanResult={batchScanResult}
          batchScanStage={batchScanStage}
          batchSelectedCount={batchSelectedCount}
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
          batchIsPublic={batchIsPublic}
          setBatchIsPublic={setBatchIsPublic}
          handleBatchScanPageChange={handleBatchScanPageChange}
          isBatchFileSelected={isBatchFileSelected}
          handleBatchFileToggle={handleBatchFileToggle}
          handleBatchSelectAll={handleBatchSelectAll}
          handleBatchDeselectAll={handleBatchDeselectAll}
          handleBatchRegister={handleBatchRegister}
          formatFileSize={formatFileSize}
        />
      )}

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
}

import React, { useState, useEffect, useRef } from 'react'
import { useAsyncAction } from '../../lib/hooks/useAsyncAction'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Database,
} from 'lucide-react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import {
  getStorageConfig,
  updateStorageConfig,
  scanDirectory,
  checkExternalFiles,
  startScanDirectoryTask,
  startBatchImportTask,
  startDeleteExternalTask,
  startUnbindDatasetTask,
  getStorageTaskStatus,
  getExternalDatasets,
  getExternalDatasetsCachedSync,
  invalidateExternalDatasetsCache,
  cancelStorageTask,
  getStorageInspection, awaitInspection, cancelStorageInspection, type StorageInspection, type InspectionKind,
} from '../../api/storage'
import type {
  StorageConfig,
  ScanDirectoryResponse,
  ScanDirectoryTaskResult,
  CheckExternalFilesResponse,
  ExternalDatasetInfo,
} from '../../api/storage'
import { fetchAllDatasets } from '../../api/wsi'
import { formatFileSize } from '../../lib/utils/utils'
import type { DatasetSummary } from '../../api/wsi'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'
import { isAnnotationTask, type TaskType } from '../../constants/training'
import { ShowConfirmDialog } from './ConfirmDialog'
import { MigrationModal } from './MigrationModal'
import {InspectionProgress} from './storage/InspectionProgress'
import {
  BatchRegisterCard,
  ExternalFilesHealthCheckCard
} from './storage'
import { StorageInventoryPanel } from './storage/StorageInventoryPanel'

const SCAN_TASK_POLL_INTERVAL_MS = 2000

export interface StorageTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export const StorageTab: React.FC<StorageTabProps> = ({ showConfirmDialog, closeConfirmDialog }) => {
  const BATCH_SCAN_PAGE_SIZE = 100
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { addMigrationTask, openPanel } = useBackgroundTask()
  const [inspections,setInspections]=useState<Partial<Record<InspectionKind,StorageInspection>>>({})
  const inspectionController=useRef(new AbortController())
  const externalLock=useRef(false)
  const [scanTaskProgress,setScanTaskProgress]=useState<StorageInspection>()
  const progressFor=(kind:InspectionKind)=>(value:StorageInspection)=>setInspections(previous=>({...previous,[kind]:value}))

  const [storageConfig, setStorageConfig] = useState<StorageConfig | null>(null)
  const [storagePath, setStoragePath] = useState('')
  const [storageSaving, runStorageSaving] = useAsyncAction<void>({ onError: (err) => setStorageConfigError(err instanceof Error ? err.message : t('settings.storageTab.failedToUpdateConfig')) })
  const [storageSaved, setStorageSaved] = useState(false)
  const [storageConfigError, setStorageConfigError] = useState<string | null>(null)
  const [showMigrationPrompt, setShowMigrationPrompt] = useState(false)
  const [migrationTarget, setMigrationTarget] = useState('')
  const [deleteSource, setDeleteSource] = useState(false)
  const [batchScanPath, setBatchScanPath] = useState('')
  const [batchScanResult, setBatchScanResult] = useState<ScanDirectoryResponse | null>(null)
  const [batchScanning, runBatchScanning] = useAsyncAction<void>({ onError: (err) => setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToScanDir')) })
  const [batchScanStage, setBatchScanStage] = useState<'idle' | 'initial' | 'refresh' | 'segmentationRefresh'>('idle')
  const [batchScanError, setBatchScanError] = useState<string | null>(null)
  const [batchSelectedFiles, setBatchSelectedFiles] = useState<Set<string>>(new Set())
  const [batchExcludedFiles, setBatchExcludedFiles] = useState<Set<string>>(new Set())
  const [batchSelectAllValid, setBatchSelectAllValid] = useState(false)
  const [batchDatasetMode, setBatchDatasetMode] = useState<'existing' | 'new'>('new')
  const [batchSelectedDatasetId, setBatchSelectedDatasetId] = useState<string>('')
  const batchNewDatasetNameRef = useRef<HTMLInputElement>(null)
  const [batchRegistering, runBatchRegistering] = useAsyncAction<void>({ onError: (err) => setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToStartImport')) })
  const [batchImportTaskId, setBatchImportTaskId] = useState<string | null>(null)
  const [activeScanTaskId, setActiveScanTaskId] = useState<string | null>(null)
  const activeScanTaskIdRef = useRef<string | null>(null)
  const [batchDatasets, setBatchDatasets] = useState<DatasetSummary[]>([])
  const [batchTaskType, setBatchTaskTypeRaw] = useState<TaskType>('wsi_classification')
  const [batchDataLevel, setBatchDataLevel] = useState<'case' | 'file'>('file')
  const [batchIsPublic, setBatchIsPublic] = useState(false)
  const setBatchTaskType = (type: TaskType) => {
    setBatchTaskTypeRaw(type)
    if (isAnnotationTask(type)) setBatchDataLevel('file')
  }
  const resolveBatchTaskTypeForScan = (scanResult?: ScanDirectoryResponse | null): TaskType => {
    if (batchTaskType !== 'wsi_classification') return batchTaskType
    if (scanResult && scanResult.patch_count > 0 && scanResult.wsi_count === 0) return 'patch_classification'
    return 'wsi_classification'
  }
  const resolveBatchDataLevelForTask = (taskType: TaskType): 'case' | 'file' => {
    return taskType.startsWith('patch_') ? 'file' : batchDataLevel
  }
  const waitForScanDirectoryTask = async (taskId: string): Promise<ScanDirectoryTaskResult> => {
    while (true) {
      if(inspectionController.current.signal.aborted)throw new DOMException('Aborted','AbortError')
      const task = await getStorageTaskStatus(taskId)
      setScanTaskProgress({kind:'external-health',status:task.status==='processing'?'running':task.status==='pending'?'queued':task.status as 'completed',processed:task.processed_items,total:task.total_items||null,stage:'directory'})

      if (task.status === 'completed') {
        const results = task.results as ScanDirectoryTaskResult | null
        if (!results?.scan_id) {
          throw new Error('Directory scan completed without a scan session')
        }
        return results
      }

      if (task.status === 'failed') {
        throw new Error(task.error_message || t('settings.storageTab.failedToScanDir'))
      }

      if (task.status === 'cancelled') {
        throw new Error('Directory scan was cancelled')
      }

      await new Promise(resolve => setTimeout(resolve, SCAN_TASK_POLL_INTERVAL_MS))
    }
  }

  const [externalDatasets, setExternalDatasets] = useState<ExternalDatasetInfo[]>(() => {
    const cached = getExternalDatasetsCachedSync()
    return cached?.datasets ?? []
  })
  const [externalDatasetsLoaded, setExternalDatasetsLoaded] = useState<boolean>(() => {
    return getExternalDatasetsCachedSync() !== null
  })
  const [loadingExternalDatasets, setLoadingExternalDatasets] = useState(false)
  const [selectedExternalDatasets, setSelectedExternalDatasets] = useState<Set<string>>(new Set())
  const [unbindingDatasets, runUnbindingDatasets] = useAsyncAction<void>()
  const [checkingExternalFiles, runCheckingExternalFiles] = useAsyncAction<void>({ onError: (err) => setExternalFilesError(err instanceof Error ? err.message : t('settings.storageTab.failedToCheckFiles')) })
  const [externalFilesResult, setExternalFilesResult] = useState<CheckExternalFilesResponse | null>(null)
  const [selectedUnavailableFiles, setSelectedUnavailableFiles] = useState<Set<string>>(new Set())
  const [deletingUnavailableFiles, runDeletingUnavailableFiles] = useAsyncAction<void>({ onError: (err) => setExternalFilesError(err instanceof Error ? err.message : t('settings.storageTab.failedToStartDelete')) })
  const [externalFilesError, setExternalFilesError] = useState<string | null>(null)

  const loadBatchDatasets = async () => {
    try {
      const response = await fetchAllDatasets()
      setBatchDatasets(response.items)
    } catch (err) {
      console.error('Failed to load datasets for batch registration:', err)
    }
  }

  const loadExternalDatasetsFunc = async (forceRefresh = false) => {
    if(externalLock.current)return
    externalLock.current=true
    setLoadingExternalDatasets(true)
    try {
      const response = await getExternalDatasets(forceRefresh)
      setExternalDatasets(response.datasets)
      setExternalDatasetsLoaded(true)
    } catch (err) {
      console.error('Failed to load external datasets:', err)
    } finally {
      externalLock.current=false
      setLoadingExternalDatasets(false)
    }
  }

  const refreshExternalDatasets = async () => {
    invalidateExternalDatasetsCache()
    setExternalDatasetsLoaded(false)
    await loadExternalDatasetsFunc(true)
  }

  const loadStorageConfig = async () => {
    setStorageConfigError(null)
    try {
      const config = await getStorageConfig()
      setStorageConfig(config)
      setStoragePath(config.uploads_dir)
    } catch (err) {
      console.error('Failed to load storage config:', err)
      setStorageConfigError(err instanceof Error ? err.message : t('settings.storageTab.failedToLoadConfig'))
    }
  }

  const handleCancelBatchScan = () => {
    const activeId = activeScanTaskIdRef.current
    if (activeId) {
      cancelStorageTask(activeId).catch(() => {})
      activeScanTaskIdRef.current = null
      setActiveScanTaskId(null)
    }
    setBatchScanStage('idle')
  }

  const handleBatchScan = () => {
    if (!batchScanPath.trim()) return
    setBatchScanError(null)
    setBatchScanResult(null)
    setBatchScanStage('initial')
    setBatchSelectedFiles(new Set())
    setBatchExcludedFiles(new Set())
    setBatchSelectAllValid(false)
    setBatchImportTaskId(null)
    void runBatchScanning(async () => {
      if(batchDatasets.length===0)void loadBatchDatasets()
      const scanTaskType = resolveBatchTaskTypeForScan()
      const task = await startScanDirectoryTask(batchScanPath.trim(), {
        taskType: scanTaskType,
        pageSize: BATCH_SCAN_PAGE_SIZE,
      })
      activeScanTaskIdRef.current = task.task_id
      setActiveScanTaskId(task.task_id)
      try {
        const scanTaskResult = await waitForScanDirectoryTask(task.task_id)
        const result = await scanDirectory(scanTaskResult.directory, {
          scanId: scanTaskResult.scan_id,
          taskType: scanTaskType,
          page: 1,
          pageSize: scanTaskResult.page_size || BATCH_SCAN_PAGE_SIZE,
        })
        setBatchScanResult(result)
        setBatchSelectAllValid(true)
        setBatchScanStage('idle')
      } finally {
        activeScanTaskIdRef.current = null
        setActiveScanTaskId(null)
      }
    }).catch((err: unknown) => {
      setBatchScanStage('idle')
      console.error('Failed to scan directory:', err)
      setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToScanDir'))
    })
  }

  const handleBatchScanPageChange = (page: number) => {
    if (!batchScanResult) return
    setBatchScanError(null)
    setBatchScanStage('refresh')
    void runBatchScanning(async () => {
      const scanTaskType = resolveBatchTaskTypeForScan(batchScanResult)
      const result = await scanDirectory(batchScanResult.directory, {
        scanId: batchScanResult.scan_id,
        taskType: scanTaskType,
        page,
        pageSize: batchScanResult.page_size || BATCH_SCAN_PAGE_SIZE,
      })
      setBatchScanResult(result)
      setBatchScanStage('idle')
    }).catch((err: unknown) => {
      setBatchScanStage('idle')
      console.error('Failed to load scan page:', err)
      setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToScanDir'))
    })
  }

  useEffect(() => {
    if (!isAnnotationTask(batchTaskType) || !batchScanResult?.directory || batchScanResult.annotation_scan_enabled) {
      return
    }

    let cancelled = false

    setBatchScanError(null)
    setBatchScanStage('segmentationRefresh')
    void runBatchScanning(async () => {
      const task=await startScanDirectoryTask(batchScanResult.directory,{taskType:batchTaskType,pageSize:batchScanResult.page_size||BATCH_SCAN_PAGE_SIZE})
      activeScanTaskIdRef.current=task.task_id;setActiveScanTaskId(task.task_id)
      let scanned:ScanDirectoryTaskResult
      try{scanned=await waitForScanDirectoryTask(task.task_id)}finally{activeScanTaskIdRef.current=null;setActiveScanTaskId(null)}
      const result = await scanDirectory(batchScanResult.directory, {
        scanId:scanned.scan_id,
        taskType: batchTaskType,
        page: batchScanResult.page,
        pageSize: batchScanResult.page_size || BATCH_SCAN_PAGE_SIZE,
      })
      if (!cancelled) {
        setBatchScanResult(result)
        setBatchScanStage('idle')
      }
    }).catch((err: unknown) => {
      if (!cancelled) {
        setBatchScanStage('idle')
        console.error('Failed to reload segmentation scan:', err)
        setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToScanDir'))
      }
    })

    return () => {
      cancelled = true
    }
  }, [batchScanResult, batchTaskType, t])

  const isBatchFileSelected = (path: string, valid: boolean) => {
    if (!valid) return false
    return batchSelectAllValid ? !batchExcludedFiles.has(path) : batchSelectedFiles.has(path)
  }

  const batchSelectedCount = batchSelectAllValid
    ? Math.max(0, (batchScanResult?.valid_count || 0) - batchExcludedFiles.size)
    : batchSelectedFiles.size

  const handleBatchFileToggle = (path: string, valid: boolean) => {
    if (!valid) return
    if (batchSelectAllValid) {
      setBatchExcludedFiles(prev => {
        const next = new Set(prev)
        if (next.has(path)) { next.delete(path) } else { next.add(path) }
        return next
      })
      return
    }
    setBatchSelectedFiles(prev => {
      const next = new Set(prev)
      if (next.has(path)) { next.delete(path) } else { next.add(path) }
      return next
    })
  }

  const handleBatchSelectAll = () => {
    setBatchSelectAllValid(true)
    setBatchSelectedFiles(new Set())
    setBatchExcludedFiles(new Set())
  }

  const handleBatchDeselectAll = () => {
    setBatchSelectAllValid(false)
    setBatchSelectedFiles(new Set())
    setBatchExcludedFiles(new Set())
  }

  const handleBatchRegister = () => {
    if (batchSelectedCount === 0) return
    if (batchDatasetMode === 'existing' && !batchSelectedDatasetId) {
      setBatchScanError(t('settings.storageTab.pleaseSelectDataset'))
      return
    }
    const datasetNameToUse = batchNewDatasetNameRef.current?.value.trim() || ''
    if (batchDatasetMode === 'new' && !datasetNameToUse) {
      setBatchScanError(t('settings.storageTab.pleaseEnterDatasetName'))
      return
    }
    setBatchScanError(null)
    setBatchImportTaskId(null)
    void runBatchRegistering(async () => {
      const importTaskType = resolveBatchTaskTypeForScan(batchScanResult)
      const result = await startBatchImportTask({
        scan_id: batchScanResult?.scan_id,
        select_all_valid: batchSelectAllValid,
        selected_paths: Array.from(batchSelectedFiles),
        excluded_paths: Array.from(batchExcludedFiles),
        dataset_id: batchDatasetMode === 'existing' ? batchSelectedDatasetId : undefined,
        dataset_name: batchDatasetMode === 'new' ? datasetNameToUse : undefined,
        scan_root: batchScanResult?.directory,
        aggregation_level: resolveBatchDataLevelForTask(importTaskType),
        task_type: importTaskType,
        is_public: batchDatasetMode === 'new' ? batchIsPublic : undefined,
      })
      setBatchImportTaskId(result.task_id)
      openPanel()
      setBatchSelectedFiles(new Set())
      setBatchExcludedFiles(new Set())
      setBatchSelectAllValid(false)
      if (batchNewDatasetNameRef.current) { batchNewDatasetNameRef.current.value = '' }
      setTimeout(() => { loadBatchDatasets(); refreshExternalDatasets() }, 2000)
    }).catch((err: unknown) => {
      console.error('Failed to start batch import task:', err)
      setBatchScanError(err instanceof Error ? err.message : t('settings.storageTab.failedToStartImport'))
    })
  }

  const handleCheckExternalFiles = () => {
    setExternalFilesError(null)
    setSelectedUnavailableFiles(new Set())
    void runCheckingExternalFiles(async () => {
      const result = await checkExternalFiles(undefined,progressFor('external-health'),inspectionController.current.signal)
      setExternalFilesResult(result)
      if (result.unavailable.length > 0) {
        setSelectedUnavailableFiles(new Set(result.unavailable.map(f => f.wsi_id)))
      }
    }).catch((err: unknown) => {
      console.error('Failed to check external files:', err)
      setExternalFilesError(err instanceof Error ? err.message : t('settings.storageTab.failedToCheckFiles'))
    })
  }

  const handleDeleteUnavailableFiles = async () => {
    if (selectedUnavailableFiles.size === 0) return
    showConfirmDialog({
      title: t('settings.storageTab.deleteRecords'),
      message: t('settings.storageTab.deleteRecordsConfirm', { count: selectedUnavailableFiles.size }),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        setExternalFilesError(null)
        void runDeletingUnavailableFiles(async () => {
          await startDeleteExternalTask(Array.from(selectedUnavailableFiles))
          setSelectedUnavailableFiles(new Set())
          setTimeout(() => handleCheckExternalFiles(), 2000)
        }).catch((err: unknown) => {
          console.error('Failed to start delete external task:', err)
          setExternalFilesError(err instanceof Error ? err.message : t('settings.storageTab.failedToStartDelete'))
        })
      }
    })
  }

  const handleExternalDatasetToggle = (datasetId: string | null) => {
    if (!datasetId) return
    setSelectedExternalDatasets(prev => {
      const next = new Set(prev)
      if (next.has(datasetId)) { next.delete(datasetId) } else { next.add(datasetId) }
      return next
    })
  }

  const handleExternalDatasetSelectAll = () => {
    if (selectedExternalDatasets.size === externalDatasets.filter(d => d.dataset_id).length) {
      setSelectedExternalDatasets(new Set())
    } else {
      setSelectedExternalDatasets(new Set(externalDatasets.filter(d => d.dataset_id).map(d => d.dataset_id!)))
    }
  }

  const handleUnbindDataset = async (datasetId: string, datasetName: string) => {
    showConfirmDialog({
      title: t('settings.storageTab.unbindDataset'),
      message: t('settings.storageTab.unbindDatasetConfirm', { name: datasetName }),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        void runUnbindingDatasets(async () => {
          await startUnbindDatasetTask(datasetId)
          setTimeout(() => refreshExternalDatasets(), 2000)
        }).catch((err: unknown) => {
          console.error('Failed to start unbind dataset task:', err)
          showConfirmDialog({
            title: t('settings.storageTab.unbindFailed'),
            message: err instanceof Error ? err.message : t('settings.storageTab.failedToStartUnbind'),
            confirmVariant: 'info',
            showCancel: false,
            onConfirm: () => closeConfirmDialog()
          })
        })
      }
    })
  }

  const handleUnbindSelectedDatasets = async () => {
    if (selectedExternalDatasets.size === 0) return
    const datasetNames = externalDatasets
      .filter(d => d.dataset_id && selectedExternalDatasets.has(d.dataset_id))
      .map(d => d.dataset_name)
      .join(', ')
    showConfirmDialog({
      title: t('settings.storageTab.unbindDatasets'),
      message: t('settings.storageTab.unbindDatasetsConfirm', { count: selectedExternalDatasets.size, names: datasetNames }),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        void runUnbindingDatasets(async () => {
          for (const datasetId of selectedExternalDatasets) {
            await startUnbindDatasetTask(datasetId)
          }
          setSelectedExternalDatasets(new Set())
          setTimeout(() => refreshExternalDatasets(), 2000)
        }).catch((err: unknown) => {
          console.error('Failed to start unbind dataset tasks:', err)
          showConfirmDialog({
            title: t('settings.storageTab.unbindFailed'),
            message: err instanceof Error ? err.message : t('settings.storageTab.failedToStartUnbind'),
            confirmVariant: 'info',
            showCancel: false,
            onConfirm: () => closeConfirmDialog()
          })
        })
      }
    })
  }

  const performStorageUpdate = (path: string) => {
    setStorageConfigError(null)
    return runStorageSaving(async () => {
      const result = await updateStorageConfig(path)
      setStorageConfig({ uploads_dir: result.uploads_dir, source: 'config' })
      setStoragePath(result.uploads_dir)
      setStorageSaved(true)
      setTimeout(() => setStorageSaved(false), 3000)
    }).catch((err: unknown) => {
      console.error('Failed to update storage config:', err)
      setStorageConfigError(err instanceof Error ? err.message : t('settings.storageTab.failedToUpdateConfig'))
    })
  }

  const handleStorageSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!storagePath.trim()) return
    if (storageConfig && storagePath.trim() !== storageConfig.uploads_dir) {
      setMigrationTarget(storagePath.trim())
      setShowMigrationPrompt(true)
      return
    }
    await performStorageUpdate(storagePath.trim())
  }

  const handleConfirmMigration = () => {
    setShowMigrationPrompt(false)
    void runStorageSaving(async () => {
      await addMigrationTask(migrationTarget, deleteSource)
      setStorageSaved(true)
      setTimeout(() => setStorageSaved(false), 3000)
    }).catch((err: unknown) => {
      console.error('Failed to start migration:', err)
      setStorageConfigError(err instanceof Error ? err.message : t('settings.storageTab.failedToStartMigration'))
    })
  }

  const handleSkipMigration = async () => {
    setShowMigrationPrompt(false)
    await performStorageUpdate(migrationTarget)
  }

  useEffect(() => {
    const controller=new AbortController();inspectionController.current=controller
    for(const kind of ['external-health'] as InspectionKind[]){
      getStorageInspection(kind,'',false,controller.signal).then(value=>{
        if(controller.signal.aborted||!['queued','running','completed'].includes(value.status))return
        void runCheckingExternalFiles(async()=>{const result=await awaitInspection<CheckExternalFilesResponse>(kind,progressFor(kind),controller.signal,'',true);setExternalFilesResult(result)}).catch(()=>{})
      }).catch(()=>{})
    }
    if (!storageConfig) loadStorageConfig()
    if (!externalDatasetsLoaded && !loadingExternalDatasets && getExternalDatasetsCachedSync() !== null) {
      loadExternalDatasetsFunc()
    }
    return()=>controller.abort()
  }, [])

  const anyStorageOpInProgress = batchScanning || checkingExternalFiles

  return (
    <>
      <Card className="p-4 sm:p-6 mb-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-4">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
            <Database className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
            {t('settings.storageTab.storageLocation')}
          </h2>
          {storageConfig?.source && (
            <span className="text-xs text-gray-500">{t('settings.storageTab.source')}: {storageConfig.source}</span>
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
              <Button type="submit" disabled={storageSaving || !storagePath.trim()}>
                {storageSaving ? t('settings.storageTab.saving') : t('settings.storageTab.save')}
              </Button>
            </div>
          </div>
          {storageConfigError && <div className="text-sm text-red-600">{storageConfigError}</div>}
          {storageSaved && <div className="text-sm text-green-600">{t('settings.storageTab.savedMessage')}</div>}
          <p className="text-xs text-gray-500">
            {t('settings.storageTab.storageLocationDescription')}
          </p>
        </form>
      </Card>

      <StorageInventoryPanel key={storageConfig?.uploads_dir} showConfirmDialog={showConfirmDialog} closeConfirmDialog={closeConfirmDialog} />

      {batchScanning&&<InspectionProgress value={scanTaskProgress} onCancel={handleCancelBatchScan}/>}
      <BatchRegisterCard
        batchScanPath={batchScanPath}
        setBatchScanPath={setBatchScanPath}
        batchScanResult={batchScanResult}
        batchScanning={batchScanning}
        batchScanStage={batchScanStage}
        batchScanError={batchScanError}
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
        handleBatchScan={handleBatchScan}
        handleCancelBatchScan={handleCancelBatchScan}
        canCancelBatchScan={Boolean(activeScanTaskId)}
        handleBatchScanPageChange={handleBatchScanPageChange}
          isBatchFileSelected={isBatchFileSelected}
          handleBatchFileToggle={handleBatchFileToggle}
        handleBatchSelectAll={handleBatchSelectAll}
        handleBatchDeselectAll={handleBatchDeselectAll}
        handleBatchRegister={handleBatchRegister}
        formatFileSize={formatFileSize}
        externalDatasets={externalDatasets}
        loadingExternalDatasets={loadingExternalDatasets}
        externalDatasetsLoaded={externalDatasetsLoaded}
        loadExternalDatasets={loadExternalDatasetsFunc}
        selectedExternalDatasets={selectedExternalDatasets}
        unbindingDatasets={unbindingDatasets}
        refreshExternalDatasets={refreshExternalDatasets}
        handleExternalDatasetToggle={handleExternalDatasetToggle}
        handleExternalDatasetSelectAll={handleExternalDatasetSelectAll}
        handleUnbindDataset={handleUnbindDataset}
        handleUnbindSelectedDatasets={handleUnbindSelectedDatasets}
        navigate={navigate}
      />

        <InspectionProgress value={inspections['external-health']} onCancel={()=>void cancelStorageInspection('external-health')}/>
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

      <MigrationModal
        isOpen={showMigrationPrompt}
        currentPath={storageConfig?.uploads_dir}
        targetPath={migrationTarget}
        deleteSource={deleteSource}
        onDeleteSourceChange={setDeleteSource}
        onCancel={() => setShowMigrationPrompt(false)}
        onSkipMigration={handleSkipMigration}
        onConfirmMigration={handleConfirmMigration}
      />
    </>
  )
}

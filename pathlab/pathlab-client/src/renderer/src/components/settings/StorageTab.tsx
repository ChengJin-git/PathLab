import React, { useState, useEffect, useRef } from 'react'
import { useAsyncAction } from '../../lib/useAsyncAction'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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
  getStorageStats,
  detectOrphanedFiles,
  cleanupOrphanedFiles,
  detectOrphanedRecords,
  cleanupOrphanedRecords,
  resetDerivedData,
  getStorageConfig,
  updateStorageConfig,
  scanDirectory,
  checkExternalFiles,
  startBatchImportTask,
  startDeleteExternalTask,
  startUnbindDatasetTask,
  getExternalDatasets,
  getExternalDatasetsCachedSync,
  invalidateExternalDatasetsCache,
} from '../../api/storage'
import type {
  StorageStats,
  OrphanedFilesInfo,
  CleanupResult,
  OrphanedRecordsInfo,
  OrphanedRecordsCleanupResult,
  StorageConfig,
  ScanDirectoryResponse,
  CheckExternalFilesResponse,
  ExternalDatasetInfo,
} from '../../api/storage'
import { fetchDatasets } from '../../api/wsi'
import type { DatasetSummary } from '../../api/wsi'
import { formatFileSize } from '../../lib/utils'
import { useBackgroundTask } from '../../contexts/BackgroundTaskContext'
import { isSegmentationTask, type TaskType } from '../../constants/training'
import { ShowConfirmDialog } from './ConfirmDialog'
import { MigrationModal } from './MigrationModal'
import {
  StorageStatsDisplay,
  OrphanedFilesCard,
  OrphanedRecordsCard,
  BatchRegisterCard,
  ExternalFilesHealthCheckCard
} from './storage'

interface ElectronFilesApi {
  selectDirectory?: (options?: { title?: string }) => Promise<string | null>
}
interface ElectronApi {
  files?: ElectronFilesApi
}
declare const window: Window & { api?: ElectronApi }

export interface StorageTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export const StorageTab: React.FC<StorageTabProps> = ({ showConfirmDialog, closeConfirmDialog }) => {
  const BATCH_SCAN_PAGE_SIZE = 100
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { addMigrationTask } = useBackgroundTask()
  const [isDangerZoneOpen, setIsDangerZoneOpen] = React.useState(false)
  const hasSelectDirectoryApi = !!window.api?.files?.selectDirectory

  const [stats, setStats] = useState<StorageStats | null>(null)
  const [loadingStorage, setLoadingStorage] = useState(false)
  const [storageError, setStorageError] = useState<string | null>(null)
  const [orphanedFiles, setOrphanedFiles] = useState<OrphanedFilesInfo | null>(null)
  const [loadingOrphaned, runLoadingOrphaned] = useAsyncAction<void>({ onError: (err) => setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToDetectOrphanedFiles')) })
  const [isCleaningUp, runCleaningUp] = useAsyncAction<void>({ onError: (err) => setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToCleanupFiles')) })
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null)
  const [selectedCategories] = useState<Set<string>>(new Set())
  const [orphanedRecords, setOrphanedRecords] = useState<OrphanedRecordsInfo | null>(null)
  const [loadingOrphanedRecords, runLoadingOrphanedRecords] = useAsyncAction<void>({ onError: (err) => setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToDetectOrphanedRecords')) })
  const [isCleaningUpRecords, runCleaningUpRecords] = useAsyncAction<void>({ onError: (err) => setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToCleanupRecords')) })
  const [recordsCleanupResult, setRecordsCleanupResult] = useState<OrphanedRecordsCleanupResult | null>(null)
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
  const [batchDatasets, setBatchDatasets] = useState<DatasetSummary[]>([])
  const [batchTaskType, setBatchTaskTypeRaw] = useState<TaskType>('wsi_classification')
  const [batchDataLevel, setBatchDataLevel] = useState<'case' | 'file'>('file')
  const [batchIsPublic, setBatchIsPublic] = useState(false)
  const setBatchTaskType = (type: TaskType) => {
    setBatchTaskTypeRaw(type)
    if (isSegmentationTask(type)) setBatchDataLevel('file')
  }
  const resolveBatchTaskTypeForScan = (scanResult?: ScanDirectoryResponse | null): TaskType => {
    if (batchTaskType !== 'wsi_classification') return batchTaskType
    if (scanResult && scanResult.patch_count > 0 && scanResult.wsi_count === 0) return 'patch_classification'
    return 'wsi_classification'
  }
  const resolveBatchDataLevelForTask = (taskType: TaskType): 'case' | 'file' => {
    return taskType.startsWith('patch_') ? 'file' : batchDataLevel
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
      const response = await fetchDatasets()
      setBatchDatasets(response.items)
    } catch (err) {
      console.error('Failed to load datasets for batch registration:', err)
    }
  }

  const loadExternalDatasetsFunc = async (forceRefresh = false) => {
    setLoadingExternalDatasets(true)
    try {
      const response = await getExternalDatasets(forceRefresh)
      setExternalDatasets(response.datasets)
      setExternalDatasetsLoaded(true)
    } catch (err) {
      console.error('Failed to load external datasets:', err)
    } finally {
      setLoadingExternalDatasets(false)
    }
  }

  const refreshExternalDatasets = async () => {
    invalidateExternalDatasetsCache()
    setExternalDatasetsLoaded(false)
    await loadExternalDatasetsFunc(true)
  }

  const loadStats = async () => {
    setLoadingStorage(true)
    setStorageError(null)
    try {
      const data = await getStorageStats()
      setStats(data)
    } catch (err) {
      console.error('Failed to load storage stats:', err)
      setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToLoadStats'))
    } finally {
      setLoadingStorage(false)
    }
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

  const handleSelectBatchScanDir = async () => {
    if (!window.api?.files?.selectDirectory) return
    const selected = await window.api.files.selectDirectory({ title: t('settings.storageTab.selectDirToScan') })
    if (selected) {
      setBatchScanPath(selected)
      setBatchScanResult(null)
      setBatchScanError(null)
      setBatchScanStage('idle')
      setBatchSelectedFiles(new Set())
      setBatchExcludedFiles(new Set())
      setBatchSelectAllValid(false)
      setBatchImportTaskId(null)
    }
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
      const scanTaskType = resolveBatchTaskTypeForScan()
      const result = await scanDirectory(batchScanPath.trim(), {
        taskType: scanTaskType,
        page: 1,
        pageSize: BATCH_SCAN_PAGE_SIZE,
      })
      setBatchScanResult(result)
      setBatchSelectAllValid(true)
      setBatchScanStage('idle')
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
    if (!isSegmentationTask(batchTaskType) || !batchScanResult?.directory || batchScanResult.annotation_scan_enabled) {
      return
    }

    let cancelled = false

    setBatchScanError(null)
    setBatchScanStage('segmentationRefresh')
    void runBatchScanning(async () => {
      const result = await scanDirectory(batchScanResult.directory, {
        taskType: 'patch_segmentation',
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
    setExternalFilesResult(null)
    setExternalFilesError(null)
    setSelectedUnavailableFiles(new Set())
    void runCheckingExternalFiles(async () => {
      const result = await checkExternalFiles()
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

  const handleSelectStorageDir = async () => {
    if (!window.api?.files?.selectDirectory) return
    const selected = await window.api.files.selectDirectory({ title: t('settings.storageTab.selectStorageLocation') })
    if (selected) { setStoragePath(selected) }
  }

  const performStorageUpdate = (path: string) => {
    setStorageConfigError(null)
    return runStorageSaving(async () => {
      const result = await updateStorageConfig(path)
      setStorageConfig({ uploads_dir: result.uploads_dir, source: 'config' })
      setStoragePath(result.uploads_dir)
      await loadStats()
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

  const detectOrphaned = (clearCleanupResult: boolean = true) => {
    setStorageError(null)
    if (clearCleanupResult) { setCleanupResult(null) }
    return runLoadingOrphaned(async () => {
      const data = await detectOrphanedFiles()
      setOrphanedFiles(data)
    }).catch((err: unknown) => {
      console.error('Failed to detect orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToDetectOrphanedFiles'))
    })
  }

  const handleCleanup = (e: React.MouseEvent) => {
    e.preventDefault()
    if (!orphanedFiles) return
    const categories = selectedCategories.size > 0 ? Array.from(selectedCategories) : undefined
    setStorageError(null)
    void runCleaningUp(async () => {
      const result = await cleanupOrphanedFiles(categories)
      setCleanupResult(result)
      loadStats()
    }).catch((err: unknown) => {
      console.error('Failed to cleanup orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToCleanupFiles'))
    })
  }

  const detectOrphanedRecordsHandler = (clearCleanupResult: boolean = true) => {
    setStorageError(null)
    if (clearCleanupResult) { setRecordsCleanupResult(null) }
    return runLoadingOrphanedRecords(async () => {
      const data = await detectOrphanedRecords()
      setOrphanedRecords(data)
    }).catch((err: unknown) => {
      console.error('Failed to detect orphaned records:', err)
      setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToDetectOrphanedRecords'))
    })
  }

  const handleRecordsCleanup = (e: React.MouseEvent) => {
    e.preventDefault()
    if (!orphanedRecords) return
    setStorageError(null)
    void runCleaningUpRecords(async () => {
      const result = await cleanupOrphanedRecords()
      setRecordsCleanupResult(result)
      await detectOrphanedRecordsHandler(false)
    }).catch((err: unknown) => {
      console.error('Failed to cleanup orphaned records:', err)
      setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToCleanupRecords'))
    })
  }

  const handleResetDerivedData = async () => {
    showConfirmDialog({
      title: t('settings.storageTab.resetDerivedDataTitle'),
      message: t('settings.storageTab.resetDerivedDataConfirm'),
      confirmText: t('settings.storageTab.resetDerivedDataButton'),
      confirmVariant: 'danger',
      onConfirm: async () => {
        closeConfirmDialog()
        setStorageError(null)
        try {
          const response = await resetDerivedData()
          console.log('Reset derived data task started:', response.task_id)
        } catch (err) {
          console.error('Failed to start reset derived data task:', err)
          setStorageError(err instanceof Error ? err.message : t('settings.storageTab.failedToResetDerivedData'))
        }
      }
    })
  }

  useEffect(() => {
    if (!stats) loadStats()
    if (!storageConfig) loadStorageConfig()
    if (batchDatasets.length === 0) loadBatchDatasets()
    if (!externalDatasetsLoaded && !loadingExternalDatasets && getExternalDatasetsCachedSync() !== null) {
      loadExternalDatasetsFunc()
    }
  }, [])

  const anyStorageOpInProgress = loadingStorage || loadingOrphaned || loadingOrphanedRecords

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
              <Button type="button" onClick={handleSelectStorageDir} disabled={storageSaving || !hasSelectDirectoryApi} className="bg-gray-100 text-gray-800 hover:bg-gray-200">
                {t('settings.storageTab.browse')}
              </Button>
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

      <Card className="p-4 sm:p-6 mb-6">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-center">
              <HardDrive className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 font-shrink-0" />
              {t('settings.storageTab.storageOverview')}
            </h2>
          </div>
          <button
            type="button"
            onClick={(e) => { e.preventDefault(); loadStats() }}
            disabled={anyStorageOpInProgress}
            className="px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50"
          >
            <svg className={`w-4 h-4 ${loadingStorage ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {loadingStorage ? t('settings.storageTab.loading') : t('settings.storageTab.refresh')}
          </button>
        </div>
        {loadingStorage ? (
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600 mx-auto mb-3"></div>
              <p className="text-gray-500 text-sm">{t('settings.storageTab.loadingStorageStats')}</p>
            </div>
          </div>
        ) : storageError ? (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <h3 className="text-red-800 font-semibold mb-2">{t('settings.storageTab.error')}</h3>
            <p className="text-red-600 text-sm">{storageError}</p>
            <button type="button" onClick={loadStats} className="mt-3 px-3 py-1.5 text-sm bg-red-600 text-white rounded hover:bg-red-700">{t('settings.storageTab.retry')}</button>
          </div>
        ) : stats ? (
          <StorageStatsDisplay stats={stats} formatFileSize={formatFileSize} />
        ) : (
          <div className="text-center py-8 text-gray-500"><p>{t('settings.storageTab.noStorageData')}</p></div>
        )}
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <OrphanedFilesCard
          orphanedFiles={orphanedFiles}
          loadingOrphaned={loadingOrphaned}
          isCleaningUp={isCleaningUp}
          cleanupResult={cleanupResult}
          detectOrphaned={detectOrphaned}
          handleCleanup={handleCleanup}
          formatFileSize={formatFileSize}
          anyStorageOpInProgress={anyStorageOpInProgress}
        />
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

      <Card className="p-4 sm:p-6 mb-6 border-2 border-red-200 bg-red-50/30">
        <button
          type="button"
          onClick={() => setIsDangerZoneOpen(!isDangerZoneOpen)}
          className="w-full flex items-center justify-between"
        >
          <h2 className="text-lg sm:text-xl font-semibold text-red-800 flex items-center">
            <AlertCircle className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-red-600 flex-shrink-0" />
            {t('settings.storageTab.dangerZone')}
          </h2>
          {isDangerZoneOpen ? (
            <ChevronUp className="w-5 h-5 text-red-600" />
          ) : (
            <ChevronDown className="w-5 h-5 text-red-600" />
          )}
        </button>
        {isDangerZoneOpen && (
          <div className="mt-4 space-y-4">
            <div className="bg-red-50 border border-red-200 rounded-lg p-4">
              <h3 className="text-red-800 font-semibold mb-2 flex items-center">
                <Trash2 className="w-4 h-4 mr-2" />
                {t('settings.storageTab.resetDerivedData')}
              </h3>
              <p className="text-sm text-red-700 mb-3">
                {t('settings.storageTab.resetDerivedDataDescription')}
              </p>
              <Button
                type="button"
                onClick={handleResetDerivedData}
                className="bg-red-600 text-white hover:bg-red-700"
              >
                <Trash2 className="w-4 h-4 mr-2" />
                {t('settings.storageTab.resetDerivedData')}
              </Button>
            </div>
          </div>
        )}
      </Card>

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
        handleSelectBatchScanDir={handleSelectBatchScanDir}
        handleBatchScan={handleBatchScan}
          handleBatchScanPageChange={handleBatchScanPageChange}
          isBatchFileSelected={isBatchFileSelected}
          handleBatchFileToggle={handleBatchFileToggle}
        handleBatchSelectAll={handleBatchSelectAll}
        handleBatchDeselectAll={handleBatchDeselectAll}
        handleBatchRegister={handleBatchRegister}
        formatFileSize={formatFileSize}
        hasSelectDirectoryApi={hasSelectDirectoryApi}
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

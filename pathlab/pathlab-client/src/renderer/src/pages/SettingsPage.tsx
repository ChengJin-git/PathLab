import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, ClipboardList, Database, Info, BookOpen, HardDrive, RefreshCw, ArrowLeft, Users, MessageSquare } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, OrphanedFilesInfo, CleanupResult, detectOrphanedRecords, cleanupOrphanedRecords, OrphanedRecordsInfo, OrphanedRecordsCleanupResult, getStorageConfig, updateStorageConfig, StorageConfig, getTrainedModels, TrainedModel, updateTrainedModel, deleteTrainedModel, TrainingTask, getQueueStatus, QueueStatus, updateQueueConfig, getQueueConfig, listUsers, updateUser, deleteUser, UserListItem, UserUpdateRequest, revokeUserAgreement, registerUser, RegisterRequest, fetchDatasets, DatasetSummary, getUserDatasetPermissions, grantDatasetPermission, revokeDatasetPermission, DatasetPermission, getAuthToken, getGlobalSettings, updateGlobalSettings, getAdminFeedbacks, getFeedbackStats, exportFeedbacks, resetAllFeedbacks, MessageFeedback, FeedbackStats, startAsyncExport, getExportTaskStatus, downloadExportFile, ExportTaskStatus, scanDirectory, ScanDirectoryResponse, checkExternalFiles, CheckExternalFilesResponse, startBatchImportTask, startDeleteExternalTask, startUnbindDatasetTask, getExternalDatasets, getExternalDatasetsCachedSync, invalidateExternalDatasetsCache, ExternalDatasetInfo } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE, PREPROCESSING_BASE, AI_BASE } from '../config'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import {
  ConfirmDialog,
  EditUserModal,
  CreateUserModal,
  PermissionModal,
  MigrationModal,
  GeneralTab,
  TasksTab,
  ModelsTab,
  StorageTab,
  UsersTab,
  FeedbackTab
} from '../components/settings'

type TabType = 'general' | 'tasks' | 'models' | 'storage' | 'users' | 'feedback'

type ServiceStatus = 'online' | 'offline' | 'checking'

interface ServiceHealth {
  gateway: ServiceStatus
  wsi: ServiceStatus
  ai: ServiceStatus
}

interface ElectronFilesApi {
  selectDirectory?: (options?: { title?: string }) => Promise<string | null>
}

interface ElectronApi {
  files?: ElectronFilesApi
}

declare const window: Window & { api?: ElectronApi }

export default function SettingsPage() {
  const navigate = useNavigate()
  const { isAdmin, isLoading: authLoading, user: currentUser } = useAuth()

  // Redirect non-admin users to dashboard
  useEffect(() => {
    if (!authLoading && !isAdmin) {
      navigate('/dashboard')
    }
  }, [isAdmin, authLoading, navigate])

  // Active Tab
  const [activeTab, setActiveTab] = useState<TabType>(() => {
    const savedTab = localStorage.getItem('settingsActiveTab')
    const validTabs: TabType[] = ['general', 'tasks', 'models', 'storage', 'users', 'feedback']
    return (validTabs.includes(savedTab as TabType) ? savedTab as TabType : 'general')
  })

  // Persist active tab to localStorage
  useEffect(() => {
    localStorage.setItem('settingsActiveTab', activeTab)
  }, [activeTab])

  // Service Health Status
  const [serviceHealth, setServiceHealth] = useState<ServiceHealth>({
    gateway: 'checking',
    wsi: 'checking',
    ai: 'checking'
  })

  // User Management State
  const [users, setUsers] = useState<UserListItem[]>([])
  const [loadingUsers, setLoadingUsers] = useState(false)
  const [usersError, setUsersError] = useState<string | null>(null)
  const [editingUser, setEditingUser] = useState<UserListItem | null>(null)
  const [editForm, setEditForm] = useState<{ nickname: string; role: string; password: string }>({ nickname: '', role: '', password: '' })
  const [showCreateUser, setShowCreateUser] = useState(false)
  const [createForm, setCreateForm] = useState<{ username: string; password: string; nickname: string; role: string }>({ username: '', password: '', nickname: '', role: 'pathologist' })
  const [creatingUser, setCreatingUser] = useState(false)

  // Dataset Permission Management State
  const [permissionUser, setPermissionUser] = useState<UserListItem | null>(null)  // User being managed
  const [userPermissions, setUserPermissions] = useState<DatasetPermission[]>([])
  const [loadingPermissions, setLoadingPermissions] = useState(false)
  const [datasets, setDatasets] = useState<{ dataset_id: string; dataset_name: string }[]>([])
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('')
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([])
  const [expiresInHours, setExpiresInHours] = useState<string>('')
  const [grantingPermission, setGrantingPermission] = useState(false)

  // Confirmation/Alert Dialog State
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean
    title: string
    message: string
    onConfirm: () => void
    confirmText?: string
    confirmVariant?: 'danger' | 'warning' | 'info' // added 'info' for alerts
    showCancel?: boolean // added to hide cancel button for alerts
  }>({ isOpen: false, title: '', message: '', onConfirm: () => { }, showCancel: true })

  // AI Configuration (loaded from backend - global settings)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [model, setModel] = useState('qwen/qwen3-vl-235b-a22b-instruct')
  const [huggingfaceToken, setHuggingfaceToken] = useState('')
  const [dashscopeApiKey, setDashscopeApiKey] = useState('')
  const [aiSaved, setAiSaved] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)
  const [aiLoading, setAiLoading] = useState(true)

  // Local vLLM Configuration
  const [localVllmEnabled, setLocalVllmEnabled] = useState(false)
  const [localVllmBaseUrl, setLocalVllmBaseUrl] = useState('http://127.0.0.1:8000/v1')
  const [localVllmModel, setLocalVllmModel] = useState('')
  const [localVllmApiKey, setLocalVllmApiKey] = useState('')
  const [localVllmStatus, setLocalVllmStatus] = useState<'checking' | 'online' | 'offline'>('offline')
  const [localVllmDetectedModel, setLocalVllmDetectedModel] = useState<string | null>(null)

  // Slide Task Settings (task_timeout is loaded from backend)
  const [taskTimeout, setTaskTimeout] = useState('259200')  // Default: 3 days
  const [taskSaved, setTaskSaved] = useState(false)
  const [taskSaving, setTaskSaving] = useState(false)

  // GPU Queue Status
  const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null)
  const [loadingQueue, setLoadingQueue] = useState(false)
  const [queueError, setQueueError] = useState<string | null>(null)

  // Trained Models State
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [modelsError, setModelsError] = useState<string | null>(null)
  const [modelsTotal, setModelsTotal] = useState(0)
  const [tasks, setTasks] = useState<TrainingTask[]>([])

  // Storage Management State
  const [stats, setStats] = useState<StorageStats | null>(null)
  const [loadingStorage, setLoadingStorage] = useState(false)
  const [storageError, setStorageError] = useState<string | null>(null)
  const [orphanedFiles, setOrphanedFiles] = useState<OrphanedFilesInfo | null>(null)
  const [loadingOrphaned, setLoadingOrphaned] = useState(false)
  const [isCleaningUp, setIsCleaningUp] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null)
  const [selectedCategories] = useState<Set<string>>(new Set())
  // Orphaned Records (zombie database records) state
  const [orphanedRecords, setOrphanedRecords] = useState<OrphanedRecordsInfo | null>(null)
  const [loadingOrphanedRecords, setLoadingOrphanedRecords] = useState(false)
  const [isCleaningUpRecords, setIsCleaningUpRecords] = useState(false)
  const [recordsCleanupResult, setRecordsCleanupResult] = useState<OrphanedRecordsCleanupResult | null>(null)
  const [storageConfig, setStorageConfig] = useState<StorageConfig | null>(null)
  const [storagePath, setStoragePath] = useState('')
  const [storageSaving, setStorageSaving] = useState(false)
  const [storageSaved, setStorageSaved] = useState(false)
  const [storageConfigError, setStorageConfigError] = useState<string | null>(null)

  // Migration Prompt State
  const [showMigrationPrompt, setShowMigrationPrompt] = useState(false)
  const [migrationTarget, setMigrationTarget] = useState('')
  const [deleteSource, setDeleteSource] = useState(false)
  const { addMigrationTask } = useBackgroundTask()

  // Batch Scan & Register State
  const [batchScanPath, setBatchScanPath] = useState('')
  const [batchScanResult, setBatchScanResult] = useState<ScanDirectoryResponse | null>(null)
  const [batchScanning, setBatchScanning] = useState(false)
  const [batchScanError, setBatchScanError] = useState<string | null>(null)
  const [batchSelectedFiles, setBatchSelectedFiles] = useState<Set<string>>(new Set())
  const [batchDatasetMode, setBatchDatasetMode] = useState<'existing' | 'new'>('new')
  const [batchSelectedDatasetId, setBatchSelectedDatasetId] = useState<string>('')
  // Use ref for dataset name input to avoid re-rendering on every keystroke
  const batchNewDatasetNameRef = useRef<HTMLInputElement>(null)
  const [batchRegistering, setBatchRegistering] = useState(false)
  // Result now stores just the task submission result (task is processed in background)
  const [batchImportTaskId, setBatchImportTaskId] = useState<string | null>(null)
  const [batchDatasets, setBatchDatasets] = useState<DatasetSummary[]>([])
  // Task type and data level for batch import
  const [batchTaskType, setBatchTaskType] = useState<'classification' | 'survival'>('classification')
  const [batchDataLevel, setBatchDataLevel] = useState<'case' | 'slide'>('slide')
  // External datasets state (datasets containing externally imported files)
  // Initialize from localStorage cache for instant display after login
  // Also track if we have valid cache to avoid unnecessary API calls
  const [externalDatasets, setExternalDatasets] = useState<ExternalDatasetInfo[]>(() => {
    const cached = getExternalDatasetsCachedSync()
    return cached?.datasets ?? []
  })
  const [externalDatasetsLoaded, setExternalDatasetsLoaded] = useState<boolean>(() => {
    // If we have valid cache (even if empty), consider it loaded
    return getExternalDatasetsCachedSync() !== null
  })
  const [loadingExternalDatasets, setLoadingExternalDatasets] = useState(false)
  const [selectedExternalDatasets, setSelectedExternalDatasets] = useState<Set<string>>(new Set())
  const [unbindingDatasets, setUnbindingDatasets] = useState(false)
  // External files check state
  const [checkingExternalFiles, setCheckingExternalFiles] = useState(false)
  const [externalFilesResult, setExternalFilesResult] = useState<CheckExternalFilesResponse | null>(null)
  const [selectedUnavailableFiles, setSelectedUnavailableFiles] = useState<Set<string>>(new Set())
  const [deletingUnavailableFiles, setDeletingUnavailableFiles] = useState(false)
  const [externalFilesError, setExternalFilesError] = useState<string | null>(null)

  // Feedback Management State
  const [feedbacks, setFeedbacks] = useState<MessageFeedback[]>([])
  const [feedbackStats, setFeedbackStats] = useState<FeedbackStats | null>(null)
  const [feedbackTotal, setFeedbackTotal] = useState(0)
  const [feedbackPage, setFeedbackPage] = useState(0)
  const [feedbackLimit] = useState(20)
  const [loadingFeedbacks, setLoadingFeedbacks] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)
  const [feedbackTypeFilter, setFeedbackTypeFilter] = useState<'thumbs_up' | 'thumbs_down' | null>(null)
  const [helpfulnessFilter, setHelpfulnessFilter] = useState<'helpful' | 'not_helpful' | null>(null)
  const [exportingFeedbacks, setExportingFeedbacks] = useState(false)
  const [resettingFeedbacks, setResettingFeedbacks] = useState(false)
  // Date range filters for export
  const [exportDateFrom, setExportDateFrom] = useState<string>(() => {
    const d = new Date()
    d.setMonth(d.getMonth() - 3)
    return d.toISOString().split('T')[0]
  })
  const [exportDateTo, setExportDateTo] = useState<string>(() => new Date().toISOString().split('T')[0])
  // Async export task state
  const [exportTaskId, setExportTaskId] = useState<string | null>(null)
  const [exportTaskStatus, setExportTaskStatus] = useState<ExportTaskStatus | null>(null)
  const [exportPollingInterval, setExportPollingInterval] = useState<NodeJS.Timeout | null>(null)

  // Check local vLLM status with given parameters (used after loading settings)
  const checkLocalVllmStatusWithParams = async (baseUrl: string, apiKey: string) => {
    if (!baseUrl) {
      setLocalVllmStatus('offline')
      setLocalVllmDetectedModel(null)
      return
    }
    setLocalVllmStatus('checking')
    setLocalVllmDetectedModel(null)
    try {
      const token = getAuthToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }
      const res = await fetch(`${API_BASE}/settings/check-vllm`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          base_url: baseUrl,
          api_key: apiKey || null
        })
      })
      if (res.ok) {
        const data = await res.json()
        setLocalVllmStatus(data.online ? 'online' : 'offline')
        if (data.online && data.model) {
          setLocalVllmDetectedModel(data.model)
        }
      } else {
        setLocalVllmStatus('offline')
      }
    } catch {
      setLocalVllmStatus('offline')
    }
  }

  // Load global settings from backend on mount
  const loadGlobalSettings = useCallback(async () => {
    setAiLoading(true)
    try {
      const settings = await getGlobalSettings()
      setApiKey(settings.openrouter_api_key)
      setBaseUrl(settings.openrouter_base_url)
      setModel(settings.openrouter_model)
      setHuggingfaceToken(settings.huggingface_token)
      setDashscopeApiKey(settings.dashscope_api_key)
      // Local vLLM settings
      setLocalVllmEnabled(settings.local_vllm_enabled)
      setLocalVllmBaseUrl(settings.local_vllm_base_url)
      setLocalVllmModel(settings.local_vllm_model)
      setLocalVllmApiKey(settings.local_vllm_api_key)
      // Auto-check local vLLM status if enabled
      if (settings.local_vllm_enabled && settings.local_vllm_base_url) {
        checkLocalVllmStatusWithParams(settings.local_vllm_base_url, settings.local_vllm_api_key)
      }
    } catch (err) {
      console.error('Failed to load global settings:', err)
      // Keep default values
    } finally {
      setAiLoading(false)
    }
  }, [])

  // Load feedback data (admin only)
  const loadFeedbacks = useCallback(async () => {
    setLoadingFeedbacks(true)
    setFeedbackError(null)
    try {
      const [feedbackResponse, statsResponse] = await Promise.all([
        getAdminFeedbacks(
          feedbackPage * feedbackLimit,
          feedbackLimit,
          feedbackTypeFilter,
          helpfulnessFilter
        ),
        getFeedbackStats()
      ])
      setFeedbacks(feedbackResponse.feedbacks)
      setFeedbackTotal(feedbackResponse.total)
      setFeedbackStats(statsResponse)
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to load feedbacks')
    } finally {
      setLoadingFeedbacks(false)
    }
  }, [feedbackPage, feedbackLimit, feedbackTypeFilter, helpfulnessFilter])

  // Async export feedbacks handler (for large datasets)
  const handleAsyncExport = async (format: 'json' | 'csv') => {
    // Clear previous export state
    if (exportPollingInterval) {
      clearInterval(exportPollingInterval)
      setExportPollingInterval(null)
    }
    setExportTaskId(null)
    setExportTaskStatus(null)
    setExportingFeedbacks(true)
    setFeedbackError(null)

    try {
      // Start async export
      const result = await startAsyncExport(
        format,
        exportDateFrom || null,
        exportDateTo || null,
        feedbackTypeFilter,
        helpfulnessFilter
      )

      setExportTaskId(result.task_id)

      // Start polling for status
      const pollStatus = async () => {
        try {
          const status = await getExportTaskStatus(result.task_id)
          setExportTaskStatus(status)

          if (status.status === 'completed') {
            // Stop polling
            if (exportPollingInterval) {
              clearInterval(exportPollingInterval)
              setExportPollingInterval(null)
            }
            setExportingFeedbacks(false)

            // Auto-download the file
            const blob = await downloadExportFile(result.task_id)
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.${format}`
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
            URL.revokeObjectURL(url)
          } else if (status.status === 'failed') {
            // Stop polling
            if (exportPollingInterval) {
              clearInterval(exportPollingInterval)
              setExportPollingInterval(null)
            }
            setExportingFeedbacks(false)
            setFeedbackError(status.error_message || 'Export failed')
          }
        } catch {
          // Continue polling even if one request fails
        }
      }

      // Poll every 2 seconds
      const interval = setInterval(pollStatus, 2000)
      setExportPollingInterval(interval)

      // Also poll immediately
      await pollStatus()
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to start export')
      setExportingFeedbacks(false)
    }
  }

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (exportPollingInterval) {
        clearInterval(exportPollingInterval)
      }
    }
  }, [exportPollingInterval])

  // Legacy sync export for small datasets (keep as fallback)
  const handleExportFeedbacks = async (format: 'json' | 'csv') => {
    // Use async export for better performance with large datasets
    if (feedbackStats && feedbackStats.total_feedbacks > 1000) {
      await handleAsyncExport(format)
      return
    }

    // For small datasets, use sync export
    setExportingFeedbacks(true)
    try {
      const result = await exportFeedbacks(format)
      if (format === 'csv' && result instanceof Blob) {
        const url = URL.createObjectURL(result)
        const a = document.createElement('a')
        a.href = url
        a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.csv`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      } else if (format === 'json' && !(result instanceof Blob)) {
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `feedbacks_${new Date().toISOString().split('T')[0]}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      setFeedbackError(err instanceof Error ? err.message : 'Failed to export feedbacks')
    } finally {
      setExportingFeedbacks(false)
    }
  }

  // Reset all feedbacks handler
  const handleResetFeedbacks = () => {
    setConfirmDialog({
      isOpen: true,
      title: 'Reset All Feedbacks',
      message: 'Are you sure you want to delete ALL feedback data? This action cannot be undone.',
      confirmText: 'Delete All',
      confirmVariant: 'danger',
      showCancel: true,
      onConfirm: async () => {
        // Close the confirmation dialog
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))

        // Execute reset
        setResettingFeedbacks(true)
        try {
          const result = await resetAllFeedbacks()
          // Show success dialog
          setTimeout(() => {
            setConfirmDialog({
              isOpen: true,
              title: 'Success',
              message: `Successfully deleted ${result.deleted_count} feedbacks.`,
              confirmText: 'OK',
              confirmVariant: 'info',
              showCancel: false,
              onConfirm: () => setConfirmDialog(prev => ({ ...prev, isOpen: false }))
            })
          }, 100) // Small delay to allow the first dialog to close smoothly or just transition

          // Reload feedbacks after reset
          await loadFeedbacks()
        } catch (err) {
          setFeedbackError(err instanceof Error ? err.message : 'Failed to reset feedbacks')
        } finally {
          setResettingFeedbacks(false)
        }
      }
    })
  }

  // Load saved settings on mount
  useEffect(() => {
    // Load AI configuration from backend (global settings)
    loadGlobalSettings()

    // Load task timeout from backend
    loadTaskConfig()
  }, [loadGlobalSettings])

  // Load feedbacks when feedback tab is active
  useEffect(() => {
    if (activeTab === 'feedback') {
      loadFeedbacks()
    }
  }, [activeTab, loadFeedbacks])

  // Load task configuration from backend
  const loadTaskConfig = async () => {
    try {
      const config = await getQueueConfig()
      setTaskTimeout(String(config.task_timeout))
    } catch (err) {
      console.error('Failed to load task config:', err)
      // Keep default value
    }
  }

  const checkServiceHealth = useCallback(async () => {
    // Check Gateway
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) })
      setServiceHealth(prev => ({ ...prev, gateway: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, gateway: 'offline' }))
    }

    // Check WSI Service (Preprocessing)
    try {
      const res = await fetch(`${PREPROCESSING_BASE}/health`, { signal: AbortSignal.timeout(3000) })
      setServiceHealth(prev => ({ ...prev, wsi: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, wsi: 'offline' }))
    }

    // Check AI Service
    try {
      const res = await fetch(`${AI_BASE.replace('/api/ai', '')}/health`, { signal: AbortSignal.timeout(3000) })
      setServiceHealth(prev => ({ ...prev, ai: res.ok ? 'online' : 'offline' }))
    } catch {
      setServiceHealth(prev => ({ ...prev, ai: 'offline' }))
    }
  }, [])

  // Check service health on mount and periodically
  useEffect(() => {
    checkServiceHealth()
    const interval = setInterval(checkServiceHealth, 10000) // Check every 10 seconds
    return () => clearInterval(interval)
  }, [checkServiceHealth])

  // Check local vLLM server status via backend proxy (to avoid CORS issues)
  // Triggered by Test button, uses current state values
  const checkLocalVllmStatus = () => {
    checkLocalVllmStatusWithParams(localVllmBaseUrl, localVllmApiKey)
  }

  // When not enabled, show offline
  useEffect(() => {
    if (!localVllmEnabled) {
      setLocalVllmStatus('offline')
      setLocalVllmDetectedModel(null)
    }
  }, [localVllmEnabled])

  // Load storage stats and datasets when storage tab is active (with caching)
  useEffect(() => {
    if (activeTab === 'storage') {
      // Only load if not already loaded (caching)
      if (!stats) loadStats()
      if (!storageConfig) loadStorageConfig()
      if (batchDatasets.length === 0) loadBatchDatasets()
      // Only load external datasets if not already loaded from cache
      // This prevents expensive API calls on every page visit
      if (!externalDatasetsLoaded && !loadingExternalDatasets) loadExternalDatasets()
    }
  }, [activeTab])

  // Load datasets for batch registration (for dropdown selection)
  const loadBatchDatasets = async () => {
    try {
      const response = await fetchDatasets()
      setBatchDatasets(response.items)
    } catch (err) {
      console.error('Failed to load datasets for batch registration:', err)
    }
  }

  // Load external datasets (datasets containing externally imported files)
  // Uses persistent cache - will return cached data instantly if available
  // For large file systems, manual refresh is recommended
  const loadExternalDatasets = async (forceRefresh = false) => {
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

  // Refresh external datasets (invalidate cache and force reload)
  const refreshExternalDatasets = async () => {
    invalidateExternalDatasetsCache()
    setExternalDatasetsLoaded(false)
    await loadExternalDatasets(true)
  }

  // Storage Management Functions
  const loadStats = async () => {
    setLoadingStorage(true)
    setStorageError(null)
    try {
      const data = await getStorageStats()
      setStats(data)
    } catch (err) {
      console.error('Failed to load storage stats:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to load storage stats')
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
      setStorageConfigError(err instanceof Error ? err.message : 'Failed to load storage config')
    }
  }

  // Batch Scan & Register Functions
  const handleSelectBatchScanDir = async () => {
    if (!window.api?.files?.selectDirectory) return
    const selected = await window.api.files.selectDirectory({ title: 'Select directory to scan for WSI files' })
    if (selected) {
      setBatchScanPath(selected)
      setBatchScanResult(null)
      setBatchScanError(null)
      setBatchSelectedFiles(new Set())
      setBatchImportTaskId(null)
    }
  }

  const handleBatchScan = async () => {
    if (!batchScanPath.trim()) return
    setBatchScanning(true)
    setBatchScanError(null)
    setBatchScanResult(null)
    setBatchSelectedFiles(new Set())
    setBatchImportTaskId(null)
    try {
      const result = await scanDirectory(batchScanPath.trim())
      setBatchScanResult(result)
      // Auto-select all valid files
      const validFiles = new Set(result.files.filter(f => f.valid).map(f => f.path))
      setBatchSelectedFiles(validFiles)
    } catch (err) {
      console.error('Failed to scan directory:', err)
      setBatchScanError(err instanceof Error ? err.message : 'Failed to scan directory')
    } finally {
      setBatchScanning(false)
    }
  }

  const handleBatchFileToggle = (path: string) => {
    setBatchSelectedFiles(prev => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const handleBatchSelectAll = () => {
    if (!batchScanResult) return
    const validFiles = new Set(batchScanResult.files.filter(f => f.valid).map(f => f.path))
    setBatchSelectedFiles(validFiles)
  }

  const handleBatchDeselectAll = () => {
    setBatchSelectedFiles(new Set())
  }

  const handleBatchRegister = async () => {
    if (batchSelectedFiles.size === 0) return
    if (batchDatasetMode === 'existing' && !batchSelectedDatasetId) {
      setBatchScanError('Please select an existing dataset')
      return
    }
    // Use ref value to avoid re-rendering on every keystroke
    const datasetNameToUse = batchNewDatasetNameRef.current?.value.trim() || ''
    if (batchDatasetMode === 'new' && !datasetNameToUse) {
      setBatchScanError('Please enter a name for the new dataset')
      return
    }

    setBatchRegistering(true)
    setBatchScanError(null)
    setBatchImportTaskId(null)
    try {
      // Build file info array with format_type and associated_data from scan result
      const selectedFilesInfo = batchScanResult?.files
        .filter(f => batchSelectedFiles.has(f.path))
        .map(f => ({
          path: f.path,
          format_type: f.format_type,
          associated_data: f.associated_data
        })) || []

      // For classification: use default label "External Import"
      // For survival: leave event_time/event_status as null (user sets later in Data Repository)
      // Start background task - processing continues in background with progress in notification center
      const result = await startBatchImportTask({
        files: selectedFilesInfo,
        dataset_id: batchDatasetMode === 'existing' ? batchSelectedDatasetId : undefined,
        dataset_name: batchDatasetMode === 'new' ? datasetNameToUse : undefined,
        data_level: batchDataLevel,
        task_type: batchTaskType,
        default_label: batchTaskType === 'classification' ? 'External Import' : undefined
      })
      setBatchImportTaskId(result.task_id)
      // Clear selection after task is submitted
      setBatchSelectedFiles(new Set())
      // Clear the input field via ref
      if (batchNewDatasetNameRef.current) {
        batchNewDatasetNameRef.current.value = ''
      }
      // Refresh datasets lists after a short delay (task is running in background)
      setTimeout(() => {
        loadBatchDatasets()
        refreshExternalDatasets()
      }, 2000)
    } catch (err) {
      console.error('Failed to start batch import task:', err)
      setBatchScanError(err instanceof Error ? err.message : 'Failed to start batch import task')
    } finally {
      setBatchRegistering(false)
    }
  }

  // Check external files availability
  const handleCheckExternalFiles = async () => {
    setCheckingExternalFiles(true)
    setExternalFilesResult(null)
    setExternalFilesError(null)
    setSelectedUnavailableFiles(new Set())
    try {
      const result = await checkExternalFiles()
      setExternalFilesResult(result)
      // Auto-select all unavailable files
      if (result.unavailable.length > 0) {
        setSelectedUnavailableFiles(new Set(result.unavailable.map(f => f.wsi_id)))
      }
    } catch (err) {
      console.error('Failed to check external files:', err)
      setExternalFilesError(err instanceof Error ? err.message : 'Failed to check external files')
    } finally {
      setCheckingExternalFiles(false)
    }
  }

  // Delete selected unavailable files - starts background task
  const handleDeleteUnavailableFiles = async () => {
    if (selectedUnavailableFiles.size === 0) return

    setConfirmDialog({
      isOpen: true,
      title: 'Delete records',
      message: `Are you sure you want to delete ${selectedUnavailableFiles.size} unavailable file record(s)? This action cannot be undone. Progress will be shown in the notification center.`,
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        setDeletingUnavailableFiles(true)
        setExternalFilesError(null)
        try {
          // Start background task - processing continues in background with progress in notification center
          await startDeleteExternalTask(Array.from(selectedUnavailableFiles))
          // Clear selection and show success message
          setSelectedUnavailableFiles(new Set())
          // Refresh the check results after a short delay (task is running in background)
          setTimeout(() => handleCheckExternalFiles(), 2000)
        } catch (err) {
          console.error('Failed to start delete external task:', err)
          setExternalFilesError(err instanceof Error ? err.message : 'Failed to start delete task')
        } finally {
          setDeletingUnavailableFiles(false)
        }
      }
    })
  }

  // Toggle selection of an external dataset
  const handleExternalDatasetToggle = (datasetId: string | null) => {
    if (!datasetId) return
    setSelectedExternalDatasets(prev => {
      const next = new Set(prev)
      if (next.has(datasetId)) {
        next.delete(datasetId)
      } else {
        next.add(datasetId)
      }
      return next
    })
  }

  // Select/deselect all external datasets
  const handleExternalDatasetSelectAll = () => {
    if (selectedExternalDatasets.size === externalDatasets.filter(d => d.dataset_id).length) {
      setSelectedExternalDatasets(new Set())
    } else {
      setSelectedExternalDatasets(new Set(externalDatasets.filter(d => d.dataset_id).map(d => d.dataset_id!)))
    }
  }

  // Unbind a single dataset
  const handleUnbindDataset = async (datasetId: string, datasetName: string) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Unbind dataset',
      message: `Are you sure you want to unbind dataset "${datasetName}"? This will remove all external file records from this dataset. The actual files on the external drive will NOT be deleted. Progress will be shown in the notification center.`,
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        setUnbindingDatasets(true)
        try {
          await startUnbindDatasetTask(datasetId)
          // Refresh after a short delay
          setTimeout(() => refreshExternalDatasets(), 2000)
        } catch (err) {
          console.error('Failed to start unbind dataset task:', err)
          setConfirmDialog({
            isOpen: true,
            title: 'Unbind Failed',
            message: err instanceof Error ? err.message : 'Failed to start unbind task',
            confirmVariant: 'info',
            showCancel: false,
            onConfirm: () => setConfirmDialog(prev => ({ ...prev, isOpen: false }))
          })
        } finally {
          setUnbindingDatasets(false)
        }
      }
    })
  }

  // Unbind selected datasets
  const handleUnbindSelectedDatasets = async () => {
    if (selectedExternalDatasets.size === 0) return
    const datasetNames = externalDatasets
      .filter(d => d.dataset_id && selectedExternalDatasets.has(d.dataset_id))
      .map(d => d.dataset_name)
      .join(', ')

    setConfirmDialog({
      isOpen: true,
      title: 'Unbind datasets',
      message: `Are you sure you want to unbind ${selectedExternalDatasets.size} dataset(s): ${datasetNames}? This will remove all external file records from these datasets. The actual files on the external drive will NOT be deleted. Progress will be shown in the notification center.`,
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        setUnbindingDatasets(true)
        try {
          // Start unbind tasks for each selected dataset
          for (const datasetId of selectedExternalDatasets) {
            await startUnbindDatasetTask(datasetId)
          }
          setSelectedExternalDatasets(new Set())
          // Refresh after a short delay
          setTimeout(() => refreshExternalDatasets(), 2000)
        } catch (err) {
          console.error('Failed to start unbind dataset tasks:', err)
          setConfirmDialog({
            isOpen: true,
            title: 'Unbind Failed',
            message: err instanceof Error ? err.message : 'Failed to start unbind tasks',
            confirmVariant: 'info',
            showCancel: false,
            onConfirm: () => setConfirmDialog(prev => ({ ...prev, isOpen: false }))
          })
        } finally {
          setUnbindingDatasets(false)
        }
      }
    })
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const handleSelectStorageDir = async () => {
    if (!window.api?.files?.selectDirectory) return
    const selected = await window.api.files.selectDirectory({ title: 'Select storage location' })
    if (selected) {
      setStoragePath(selected)
    }
  }

  const handleStorageSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!storagePath.trim()) return

    // Check if path changed is actually different and valid (simple string check)
    // Also ensuring storageConfig is loaded to compare
    if (storageConfig && storagePath.trim() !== storageConfig.uploads_dir) {
      // Path changed, prompt for migration
      setMigrationTarget(storagePath.trim())
      setShowMigrationPrompt(true)
      return
    }

    // No change, just verify/save (though usually we wouldn't even enable save if no change)
    await performStorageUpdate(storagePath.trim())
  }

  const performStorageUpdate = async (path: string) => {
    setStorageSaving(true)
    setStorageConfigError(null)
    try {
      const result = await updateStorageConfig(path)
      setStorageConfig({ uploads_dir: result.uploads_dir, source: 'config' })
      setStoragePath(result.uploads_dir)
      await loadStats()
      setStorageSaved(true)
      setTimeout(() => setStorageSaved(false), 3000)
    } catch (err) {
      console.error('Failed to update storage config:', err)
      setStorageConfigError(err instanceof Error ? err.message : 'Failed to update storage config')
    } finally {
      setStorageSaving(false)
    }
  }

  const handleConfirmMigration = async () => {
    setShowMigrationPrompt(false)
    setStorageSaving(true)
    try {
      // Trigger migration task
      await addMigrationTask(migrationTarget, deleteSource)

      // We don't update config immediately here, the backend migration task completion will eventually trigger it
      // or we can refresh stats later. But user should see the task running.
      // However, usually we want to update the config AFTER migration.
      // Our backend GET /migration/status handles the config update on completion.
      // So here we just start the task.

      setStorageSaved(true) // Indicate "started" via saved message or maybe different message
      setTimeout(() => setStorageSaved(false), 3000)

      // Force reload stats to see "migration in progress" or just wait for background task context
    } catch (err) {
      console.error('Failed to start migration:', err)
      setStorageConfigError(err instanceof Error ? err.message : 'Failed to start migration')
    } finally {
      setStorageSaving(false)
    }
  }

  const handleSkipMigration = async () => {
    setShowMigrationPrompt(false)
    await performStorageUpdate(migrationTarget)
  }

  const detectOrphaned = async (clearCleanupResult: boolean = true) => {
    setLoadingOrphaned(true)
    setStorageError(null)
    // Only clear cleanup result when manually scanning, not after cleanup
    if (clearCleanupResult) {
      setCleanupResult(null)
    }
    try {
      const data = await detectOrphanedFiles()
      setOrphanedFiles(data)
    } catch (err) {
      console.error('Failed to detect orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to detect orphaned files')
    } finally {
      setLoadingOrphaned(false)
    }
  }

  const handleCleanup = async (e: React.MouseEvent) => {
    e.preventDefault()
    if (!orphanedFiles) return

    const categories = selectedCategories.size > 0
      ? Array.from(selectedCategories)
      : undefined

    setIsCleaningUp(true)
    setStorageError(null)
    try {
      const result = await cleanupOrphanedFiles(categories)
      setCleanupResult(result)
      // Refresh stats in background
      loadStats()
      // Don't re-scan here - cleanup result is shown instead, user can manually re-scan via Scan button
    } catch (err) {
      console.error('Failed to cleanup orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to cleanup orphaned files')
    } finally {
      setIsCleaningUp(false)
    }
  }

  // Orphaned Records (zombie database records) handlers
  const detectOrphanedRecordsHandler = async (clearCleanupResult: boolean = true) => {
    setLoadingOrphanedRecords(true)
    setStorageError(null)
    if (clearCleanupResult) {
      setRecordsCleanupResult(null)
    }
    try {
      const data = await detectOrphanedRecords()
      setOrphanedRecords(data)
    } catch (err) {
      console.error('Failed to detect orphaned records:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to detect orphaned records')
    } finally {
      setLoadingOrphanedRecords(false)
    }
  }

  const handleRecordsCleanup = async (e: React.MouseEvent) => {
    e.preventDefault()
    if (!orphanedRecords) return

    setIsCleaningUpRecords(true)
    setStorageError(null)
    try {
      const result = await cleanupOrphanedRecords()
      setRecordsCleanupResult(result)
      // Re-scan orphaned records but don't clear the cleanup result
      await detectOrphanedRecordsHandler(false)
    } catch (err) {
      console.error('Failed to cleanup orphaned records:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to cleanup orphaned records')
    } finally {
      setIsCleaningUpRecords(false)
    }
  }

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  const handleAISave = async (e: React.FormEvent) => {
    e.preventDefault()
    setAiSaving(true)
    try {
      await updateGlobalSettings({
        openrouter_api_key: apiKey,
        openrouter_base_url: baseUrl,
        openrouter_model: model,
        huggingface_token: huggingfaceToken,
        dashscope_api_key: dashscopeApiKey,
        // Local vLLM settings
        local_vllm_enabled: localVllmEnabled,
        local_vllm_base_url: localVllmBaseUrl,
        local_vllm_model: localVllmModel,
        local_vllm_api_key: localVllmApiKey,
      })
      setAiSaved(true)
      setTimeout(() => setAiSaved(false), 3000)
    } catch (err) {
      console.error('Failed to save AI settings:', err)
      // Use custom alert
      setConfirmDialog({
        isOpen: true,
        title: 'Error',
        message: err instanceof Error ? err.message : 'Failed to save AI configuration',
        confirmText: 'OK',
        confirmVariant: 'danger',
        showCancel: false,
        onConfirm: () => setConfirmDialog(prev => ({ ...prev, isOpen: false }))
      })
    } finally {
      setAiSaving(false)
    }
  }

  const handleTaskSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setTaskSaving(true)
    try {
      const timeout = parseInt(taskTimeout, 10)
      if (isNaN(timeout) || timeout < 60 || timeout > 259200) {
        throw new Error('Task timeout must be between 60 and 259200 seconds')
      }
      await updateQueueConfig({ task_timeout: timeout })
      setTaskSaved(true)
      setTimeout(() => setTaskSaved(false), 3000)
    } catch (err) {
      console.error('Failed to save task config:', err)
      // Use custom alert
      setConfirmDialog({
        isOpen: true,
        title: 'Error',
        message: err instanceof Error ? err.message : 'Failed to save task configuration',
        confirmText: 'OK',
        confirmVariant: 'danger',
        showCancel: false,
        onConfirm: () => setConfirmDialog(prev => ({ ...prev, isOpen: false }))
      })
    } finally {
      setTaskSaving(false)
    }
  }

  // Load trained models
  const loadTasks = useCallback(async () => {
    try {
      const token = getAuthToken()
      const response = await fetch(`${API_BASE}/results/tasks`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      })
      if (response.ok) {
        const data = await response.json()
        setTasks(data.items || [])
      }
    } catch (error) {
      console.error('Failed to load tasks:', error)
    }
  }, [])

  // Load GPU queue status
  const loadQueueStatus = useCallback(async () => {
    setLoadingQueue(true)
    setQueueError(null)
    try {
      const status = await getQueueStatus()
      setQueueStatus(status)
    } catch (err) {
      console.error('Failed to load queue status:', err)
      setQueueError(err instanceof Error ? err.message : 'Failed to load queue status')
    } finally {
      setLoadingQueue(false)
    }
  }, [])

  // Update max concurrent GPU tasks
  const handleUpdateMaxConcurrent = useCallback(async (newValue: number) => {
    try {
      await updateQueueConfig({ max_concurrent: newValue })
      // Reload queue status to get updated values
      const status = await getQueueStatus()
      setQueueStatus(status)
    } catch (err) {
      console.error('Failed to update queue config:', err)
      setQueueError(err instanceof Error ? err.message : 'Failed to update queue config')
    }
  }, [])

  const loadTrainedModels = useCallback(async () => {
    setLoadingModels(true)
    setModelsError(null)
    try {
      const response = await getTrainedModels(0, 100)
      setTrainedModels(response.items)
      setModelsTotal(response.total)
    } catch (err) {
      console.error('Failed to load trained models:', err)
      setModelsError(err instanceof Error ? err.message : 'Failed to load models')
    } finally {
      setLoadingModels(false)
    }
  }, [])

  // Handler functions for model operations
  const handleSetDefaultModel = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_default: true })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to set default')
    }
  }, [loadTrainedModels])

  const handleToggleModelActive = useCallback(async (model: TrainedModel) => {
    try {
      await updateTrainedModel(model.model_id, { is_active: !model.is_active })
      await loadTrainedModels()
    } catch (err) {
      setModelsError(err instanceof Error ? err.message : 'Failed to update status')
    }
  }, [loadTrainedModels])

  const handleDeleteModel = useCallback((model: TrainedModel) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete Model',
      message: `Are you sure you want to delete "${model.model_name}"? This cannot be undone.`,
      confirmText: 'Delete',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          await deleteTrainedModel(model.model_id)
          await loadTrainedModels()
        } catch (err) {
          setModelsError(err instanceof Error ? err.message : 'Failed to delete')
        }
      }
    })
  }, [loadTrainedModels])

  // Load models when models tab is active
  useEffect(() => {
    if (activeTab === 'models') {
      loadTrainedModels()
      loadTasks()
    }
  }, [activeTab, loadTrainedModels, loadTasks])

  // Load and auto-refresh queue status when tasks tab is active
  useEffect(() => {
    if (activeTab === 'tasks') {
      loadQueueStatus()
      // Auto-refresh every 3 seconds
      const interval = setInterval(loadQueueStatus, 3000)
      return () => clearInterval(interval)
    }
  }, [activeTab, loadQueueStatus])

  // User Management Functions
  const loadUsers = useCallback(async () => {
    setLoadingUsers(true)
    setUsersError(null)
    try {
      const userList = await listUsers()
      setUsers(userList)
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setLoadingUsers(false)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'users') {
      loadUsers()
    }
  }, [activeTab, loadUsers])

  const handleSaveUser = async () => {
    if (!editingUser) return
    // Validate password if provided
    if (editForm.password && editForm.password.length < 6) {
      setUsersError('Password must be at least 6 characters')
      return
    }
    try {
      const updateData: UserUpdateRequest = {}
      if (editForm.nickname !== (editingUser.nickname || '')) {
        updateData.nickname = editForm.nickname
      }
      if (editForm.role !== editingUser.role) {
        updateData.role = editForm.role as 'admin' | 'pathologist' | 'guest'
      }
      if (editForm.password) {
        updateData.password = editForm.password
      }
      await updateUser(editingUser.id, updateData)
      setEditingUser(null)
      setUsersError(null)
      loadUsers()
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to update user')
    }
  }

  const handleCreateUser = async () => {
    if (!createForm.username || !createForm.password) {
      setUsersError('Username and password are required')
      return
    }
    if (createForm.password.length < 6) {
      setUsersError('Password must be at least 6 characters')
      return
    }
    try {
      setCreatingUser(true)
      setUsersError(null)
      const data: RegisterRequest = {
        email: createForm.username, // FastAPI-Users uses email field for username
        password: createForm.password,
        nickname: createForm.nickname || undefined,
        role: createForm.role as 'pathologist' | 'guest'
      }
      await registerUser(data)
      setShowCreateUser(false)
      setCreateForm({ username: '', password: '', nickname: '', role: 'pathologist' })
      loadUsers()
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to create user')
    } finally {
      setCreatingUser(false)
    }
  }

  // Dataset Permission Management Functions
  const openPermissionModal = async (user: UserListItem) => {
    setPermissionUser(user)
    setLoadingPermissions(true)
    setSelectedDatasetId('')
    setSelectedDatasetIds([])
    setExpiresInHours('')
    try {
      // Load user's current permissions
      const permResponse = await getUserDatasetPermissions(user.id)
      setUserPermissions(permResponse.permissions)
      // Load available datasets
      const datasetResponse = await fetchDatasets()
      setDatasets(datasetResponse.items.filter(d => d.dataset_id !== null).map(d => ({
        dataset_id: d.dataset_id!,
        dataset_name: d.dataset_name
      })))
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to load permissions')
    } finally {
      setLoadingPermissions(false)
    }
  }

  const handleGrantPermission = async () => {
    if (!permissionUser || (selectedDatasetIds.length === 0 && !selectedDatasetId)) return
    try {
      setGrantingPermission(true)
      const hours = expiresInHours ? parseInt(expiresInHours, 10) : undefined

      // Support both single (legacy) and batch selection
      const idsToGrant = selectedDatasetIds.length > 0 ? selectedDatasetIds : [selectedDatasetId]

      for (const dsId of idsToGrant) {
        if (dsId) {
          await grantDatasetPermission(dsId, permissionUser.id, hours)
        }
      }
      
      // Refresh permissions
      const permResponse = await getUserDatasetPermissions(permissionUser.id)
      setUserPermissions(permResponse.permissions)
      setSelectedDatasetId('')
      setSelectedDatasetIds([])
      setExpiresInHours('')
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : 'Failed to grant permission')
    } finally {
      setGrantingPermission(false)
    }
  }

  const handleRevokePermission = (datasetId: string) => {
    if (!permissionUser) return
    const datasetName = datasets.find(d => d.dataset_id === datasetId)?.dataset_name || datasetId
    setConfirmDialog({
      isOpen: true,
      title: 'Revoke Permission',
      message: `Revoke access to dataset "${datasetName}" for this user?`,
      confirmText: 'Revoke',
      confirmVariant: 'warning',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          await revokeDatasetPermission(datasetId, permissionUser.id)
          // Refresh permissions
          const permResponse = await getUserDatasetPermissions(permissionUser.id)
          setUserPermissions(permResponse.permissions)
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : 'Failed to revoke permission')
        }
      }
    })
  }

  const handleRevokeAllPermissions = () => {
    if (!permissionUser || userPermissions.length === 0) return
    setConfirmDialog({
      isOpen: true,
      title: 'Revoke All Permissions',
      message: `Are you sure you want to revoke ALL dataset permissions for ${permissionUser.nickname || permissionUser.email}?`,
      confirmText: 'Revoke All',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          const promises = userPermissions.map(perm => 
            revokeDatasetPermission(perm.dataset_id, permissionUser.id)
          )
          
          await Promise.allSettled(promises)
          
          // Refresh permissions
          const permResponse = await getUserDatasetPermissions(permissionUser.id)
          setUserPermissions(permResponse.permissions)
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : 'Failed to revoke permissions')
        }
      }
    })
  }

  const closePermissionModal = () => {
    setPermissionUser(null)
    setUserPermissions([])
    setSelectedDatasetId('')
    setExpiresInHours('')
  }

  const tabs = [
    { id: 'general' as TabType, name: 'General', icon: Bot, description: 'AI & API Configuration' },
    { id: 'tasks' as TabType, name: 'Tasks', icon: ClipboardList, description: 'Task Management' },
    { id: 'models' as TabType, name: 'Models', icon: Database, description: 'Model Management' },
    { id: 'storage' as TabType, name: 'Storage', icon: HardDrive, description: 'Storage & Cleanup' },
    { id: 'users' as TabType, name: 'Users', icon: Users, description: 'User Management' },
    { id: 'feedback' as TabType, name: 'Feedback', icon: MessageSquare, description: 'User Feedback Analytics' },
  ]

  return (
    <div className="w-full">
      <PageHeader
        title="Settings"
        description="Configure your PathLab platform"
      >
        <Button
          variant="outline"
          onClick={() => navigate('/dashboard')}
          className="gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Button>
      </PageHeader>

      {/* Tab Navigation */}
      <Card className="mb-6">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px overflow-x-auto w-full" aria-label="Tabs">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`
                    group inline-flex items-center justify-center px-4 py-3 sm:px-6 sm:py-4 border-b-2 font-medium text-sm whitespace-nowrap flex-1 transition-colors
                    ${isActive
                      ? 'border-primary-500 text-primary-600 bg-primary-50/10'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 hover:bg-gray-50/50'
                    }
                  `}
                >
                  <Icon className={`mr-2 h-5 w-5 ${isActive ? 'text-primary-600' : 'text-gray-400 group-hover:text-gray-500'}`} />
                  <div className="text-left">
                    <div>{tab.name}</div>
                    <div className="text-xs text-gray-400 font-normal">{tab.description}</div>
                  </div>
                </button>
              )
            })}
          </nav>
        </div>
      </Card>

      {/* Tab Content */}
      <div className="space-y-6">
        {/* General Tab - AI Configuration */}
        {activeTab === 'general' && (
          <GeneralTab
            apiKey={apiKey}
            baseUrl={baseUrl}
            model={model}
            huggingfaceToken={huggingfaceToken}
            dashscopeApiKey={dashscopeApiKey}
            localVllmEnabled={localVllmEnabled}
            localVllmBaseUrl={localVllmBaseUrl}
            localVllmModel={localVllmModel}
            localVllmApiKey={localVllmApiKey}
            localVllmStatus={localVllmStatus}
            localVllmDetectedModel={localVllmDetectedModel}
            aiSaving={aiSaving}
            aiSaved={aiSaved}
            onApiKeyChange={setApiKey}
            onBaseUrlChange={setBaseUrl}
            onModelChange={setModel}
            onHuggingfaceTokenChange={setHuggingfaceToken}
            onDashscopeApiKeyChange={setDashscopeApiKey}
            onLocalVllmEnabledChange={setLocalVllmEnabled}
            onLocalVllmBaseUrlChange={setLocalVllmBaseUrl}
            onLocalVllmModelChange={setLocalVllmModel}
            onLocalVllmApiKeyChange={setLocalVllmApiKey}
            onCheckLocalVllmStatus={checkLocalVllmStatus}
            onSave={handleAISave}
          />
        )}

        {/* Tasks Tab - Slide Task Settings and GPU Queue Status */}
        {activeTab === 'tasks' && (
          <TasksTab
            queueStatus={queueStatus}
            loadingQueue={loadingQueue}
            queueError={queueError}
            taskTimeout={taskTimeout}
            taskSaving={taskSaving}
            taskSaved={taskSaved}
            onLoadQueueStatus={loadQueueStatus}
            onUpdateMaxConcurrent={handleUpdateMaxConcurrent}
            onTaskTimeoutChange={setTaskTimeout}
            onTaskSave={handleTaskSave}
          />
        )}

        {/* Models Tab - Trained Models Management */}
        {activeTab === 'models' && (
          <ModelsTab
            trainedModels={trainedModels}
            loadingModels={loadingModels}
            modelsError={modelsError}
            modelsTotal={modelsTotal}
            tasks={tasks}
            onLoadModels={loadTrainedModels}
            onSetDefault={handleSetDefaultModel}
            onToggleActive={handleToggleModelActive}
            onDeleteModel={handleDeleteModel}
          />
        )}

        {/* Storage Tab - Storage Management */}
        {activeTab === 'storage' && (
          <StorageTab
            storageConfig={storageConfig}
            storagePath={storagePath}
            setStoragePath={setStoragePath}
            storageSaving={storageSaving}
            storageSaved={storageSaved}
            storageConfigError={storageConfigError}
            handleStorageSave={handleStorageSave}
            handleSelectStorageDir={handleSelectStorageDir}
            stats={stats}
            loadingStorage={loadingStorage}
            storageError={storageError}
            loadStats={loadStats}
            orphanedFiles={orphanedFiles}
            loadingOrphaned={loadingOrphaned}
            isCleaningUp={isCleaningUp}
            cleanupResult={cleanupResult}
            detectOrphaned={detectOrphaned}
            handleCleanup={handleCleanup}
            orphanedRecords={orphanedRecords}
            loadingOrphanedRecords={loadingOrphanedRecords}
            isCleaningUpRecords={isCleaningUpRecords}
            recordsCleanupResult={recordsCleanupResult}
            detectOrphanedRecordsHandler={detectOrphanedRecordsHandler}
            handleRecordsCleanup={handleRecordsCleanup}
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
            externalDatasets={externalDatasets}
            loadingExternalDatasets={loadingExternalDatasets}
            selectedExternalDatasets={selectedExternalDatasets}
            unbindingDatasets={unbindingDatasets}
            refreshExternalDatasets={refreshExternalDatasets}
            handleExternalDatasetToggle={handleExternalDatasetToggle}
            handleExternalDatasetSelectAll={handleExternalDatasetSelectAll}
            handleUnbindDataset={handleUnbindDataset}
            handleUnbindSelectedDatasets={handleUnbindSelectedDatasets}
            checkingExternalFiles={checkingExternalFiles}
            externalFilesResult={externalFilesResult}
            selectedUnavailableFiles={selectedUnavailableFiles}
            setSelectedUnavailableFiles={setSelectedUnavailableFiles}
            deletingUnavailableFiles={deletingUnavailableFiles}
            externalFilesError={externalFilesError}
            handleCheckExternalFiles={handleCheckExternalFiles}
            handleDeleteUnavailableFiles={handleDeleteUnavailableFiles}
            formatBytes={formatBytes}
            formatFileSize={formatFileSize}
            hasSelectDirectoryApi={!!window.api?.files?.selectDirectory}
          />
        )}

        {/* Users Tab - User Management */}
        {activeTab === 'users' && (
          <UsersTab
            users={users}
            loadingUsers={loadingUsers}
            usersError={usersError}
            currentUserId={currentUser?.id}
            onShowCreateUser={() => setShowCreateUser(true)}
            onLoadUsers={loadUsers}
            onEditUser={(user) => {
              setEditingUser(user)
              setEditForm({ nickname: user.nickname || '', role: user.role, password: '' })
            }}
            onOpenPermissionModal={openPermissionModal}
            onToggleUserActive={async (user) => {
              try {
                await updateUser(user.id, { is_active: !user.is_active })
                loadUsers()
              } catch {
                // Error handled by the component
              }
            }}
            onRevokeAgreement={async (userId) => {
              try {
                await revokeUserAgreement(userId)
                loadUsers()
              } catch {
                // Error handled by the component
              }
            }}
            onDeleteUser={async (userId) => {
              if (confirm('Are you sure you want to delete this user?')) {
                try {
                  await deleteUser(userId)
                  loadUsers()
                } catch {
                  // Error handled by the component
                }
              }
            }}
          />
        )}

        {/* Feedback Tab - User Feedback Analytics */}
        {activeTab === 'feedback' && (
          <FeedbackTab
            feedbacks={feedbacks}
            feedbackTotal={feedbackTotal}
            feedbackPage={feedbackPage}
            feedbackLimit={feedbackLimit}
            loadingFeedbacks={loadingFeedbacks}
            resettingFeedbacks={resettingFeedbacks}
            exportingFeedbacks={exportingFeedbacks}
            feedbackTypeFilter={feedbackTypeFilter}
            helpfulnessFilter={helpfulnessFilter}
            exportDateFrom={exportDateFrom}
            exportDateTo={exportDateTo}
            onLoadFeedbacks={loadFeedbacks}
            onResetFeedbacks={handleResetFeedbacks}
            onExportFeedbacks={handleExportFeedbacks}
            onFeedbackTypeFilterChange={(val) => {
              setFeedbackTypeFilter(val)
              setFeedbackPage(0)
            }}
            onHelpfulnessFilterChange={(val) => {
              setHelpfulnessFilter(val)
              setFeedbackPage(0)
            }}
            onExportDateFromChange={setExportDateFrom}
            onExportDateToChange={setExportDateTo}
            onPageChange={setFeedbackPage}
          />
        )}

        {/* System Information - Show on all tabs except storage and feedback */}
        {activeTab !== 'storage' && activeTab !== 'feedback' && (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                <Info className="w-6 h-6 mr-3 text-gray-700" />
                System Information
              </h2>
              <button
                onClick={checkServiceHealth}
                className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                title="Refresh status"
              >
                <RefreshCw className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">Platform Version</span>
                <span className="text-sm text-gray-600">v1.0.0</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">Gateway Service</span>
                <span className={`text-sm flex items-center ${serviceHealth.gateway === 'online' ? 'text-green-600' :
                  serviceHealth.gateway === 'checking' ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                  <div className={`w-2 h-2 rounded-full mr-2 ${serviceHealth.gateway === 'online' ? 'bg-green-500' :
                    serviceHealth.gateway === 'checking' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
                    }`}></div>
                  {serviceHealth.gateway === 'online' ? 'Online' :
                    serviceHealth.gateway === 'checking' ? 'Checking...' : 'Offline'}
                </span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">WSI Service</span>
                <span className={`text-sm flex items-center ${serviceHealth.wsi === 'online' ? 'text-green-600' :
                  serviceHealth.wsi === 'checking' ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                  <div className={`w-2 h-2 rounded-full mr-2 ${serviceHealth.wsi === 'online' ? 'bg-green-500' :
                    serviceHealth.wsi === 'checking' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
                    }`}></div>
                  {serviceHealth.wsi === 'online' ? 'Online' :
                    serviceHealth.wsi === 'checking' ? 'Checking...' : 'Offline'}
                </span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-sm font-medium text-gray-700">AI Service</span>
                <span className={`text-sm flex items-center ${serviceHealth.ai === 'online' ? 'text-green-600' :
                  serviceHealth.ai === 'checking' ? 'text-yellow-600' : 'text-red-600'
                  }`}>
                  <div className={`w-2 h-2 rounded-full mr-2 ${serviceHealth.ai === 'online' ? 'bg-green-500' :
                    serviceHealth.ai === 'checking' ? 'bg-yellow-500 animate-pulse' : 'bg-red-500'
                    }`}></div>
                  {serviceHealth.ai === 'online' ? 'Online' :
                    serviceHealth.ai === 'checking' ? 'Checking...' : 'Offline'}
                </span>
              </div>
            </div>
          </Card>
        )}

        {/* Edit User Modal */}
        {editingUser && (
          <EditUserModal
            user={editingUser}
            editForm={editForm}
            onEditFormChange={setEditForm}
            onSave={handleSaveUser}
            onClose={() => setEditingUser(null)}
          />
        )}

        {/* Create User Modal */}
        {showCreateUser && (
          <CreateUserModal
            createForm={createForm}
            onCreateFormChange={setCreateForm}
            onSubmit={handleCreateUser}
            onClose={() => {
              setShowCreateUser(false)
              setCreateForm({ username: '', password: '', nickname: '', role: 'pathologist' })
              setUsersError(null)
            }}
            isCreating={creatingUser}
          />
        )}

        {/* Dataset Permission Management Modal */}
        {permissionUser && (
          <PermissionModal
            user={permissionUser}
            permissions={userPermissions}
            datasets={datasets}
            selectedDatasetIds={selectedDatasetIds}
            expiresInHours={expiresInHours}
            loadingPermissions={loadingPermissions}
            grantingPermission={grantingPermission}
            onSelectedDatasetIdsChange={setSelectedDatasetIds}
            onExpiresInHoursChange={setExpiresInHours}
            onGrantPermission={handleGrantPermission}
            onRevokePermission={handleRevokePermission}
            onRevokeAllPermissions={handleRevokeAllPermissions}
            onClose={closePermissionModal}
          />
        )}

        {/* Confirmation Dialog */}
        <ConfirmDialog
          dialog={confirmDialog}
          onClose={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
        />

        {/* About - Show on all tabs except storage, users, and feedback */}
        {activeTab !== 'storage' && activeTab !== 'users' && activeTab !== 'feedback' && (
          <Card className="p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <BookOpen className="w-6 h-6 mr-3 text-gray-700" />
              About
            </h2>

            <div className="space-y-3 text-sm text-gray-600">
              <p>
                <strong className="text-gray-900">PathLab</strong> is an AI-powered pathology analysis platform
                for whole slide image (WSI) classification and analysis.
              </p>
              <p>
                The platform integrates state-of-the-art deep learning models with an intuitive
                AI assistant to help researchers set up and run pathology analysis tasks.
              </p>
            </div>
          </Card>
        )}
      </div>

      {/* Migration Confirmation Modal */}
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
    </div>
  )
}


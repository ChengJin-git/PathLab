import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Layers, ClipboardList, Database, Info, BookOpen, CheckCircle, HardDrive, RefreshCw, Search, ArrowLeft, ChevronRight, Trash2, Star, ToggleLeft, ToggleRight, MoreVertical, Calendar, Minus, Plus, Users, Shield, UserCog, User, Edit, UserPlus, RotateCcw, Key, X, Clock, MessageSquare, ThumbsUp, ThumbsDown, Download, Cloud, Server, FolderSearch, Upload, AlertCircle } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, OrphanedFilesInfo, CleanupResult, getStorageConfig, updateStorageConfig, StorageConfig, getTrainedModels, TrainedModel, updateTrainedModel, deleteTrainedModel, TrainingTask, getQueueStatus, QueueStatus, updateQueueConfig, getQueueConfig, listUsers, updateUser, deleteUser, UserListItem, UserUpdateRequest, revokeUserAgreement, registerUser, RegisterRequest, fetchDatasets, DatasetSummary, getUserDatasetPermissions, grantDatasetPermission, revokeDatasetPermission, DatasetPermission, getAuthToken, getGlobalSettings, updateGlobalSettings, GlobalSettings, getAdminFeedbacks, getFeedbackStats, exportFeedbacks, resetAllFeedbacks, MessageFeedback, FeedbackStats, AdminFeedbackListResponse, startAsyncExport, getExportTaskStatus, downloadExportFile, ExportTaskStatus, scanDirectory, batchRegisterWSI, ScanDirectoryResponse, ScannedWSIFile, BatchRegisterResponse } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE, PREPROCESSING_BASE, AI_BASE } from '../config'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Select } from '../components/ui/select'
import { Label } from '../components/ui/label'

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
  const [activeTab, setActiveTab] = useState<TabType>('general')

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
  const [batchNewDatasetName, setBatchNewDatasetName] = useState('')
  const [batchDefaultLabel, setBatchDefaultLabel] = useState('')
  const [batchRegistering, setBatchRegistering] = useState(false)
  const [batchRegisterResult, setBatchRegisterResult] = useState<BatchRegisterResponse | null>(null)
  const [batchDatasets, setBatchDatasets] = useState<DatasetSummary[]>([])

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

  // Load storage stats and datasets when storage tab is active
  useEffect(() => {
    if (activeTab === 'storage') {
      loadStats()
      loadStorageConfig()
      loadBatchDatasets()
    }
  }, [activeTab])

  // Load datasets for batch registration
  const loadBatchDatasets = async () => {
    try {
      const data = await fetchDatasets()
      setBatchDatasets(data)
    } catch (err) {
      console.error('Failed to load datasets for batch registration:', err)
    }
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
      setBatchRegisterResult(null)
    }
  }

  const handleBatchScan = async () => {
    if (!batchScanPath.trim()) return
    setBatchScanning(true)
    setBatchScanError(null)
    setBatchScanResult(null)
    setBatchSelectedFiles(new Set())
    setBatchRegisterResult(null)
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
    if (batchDatasetMode === 'new' && !batchNewDatasetName.trim()) {
      setBatchScanError('Please enter a name for the new dataset')
      return
    }

    setBatchRegistering(true)
    setBatchScanError(null)
    setBatchRegisterResult(null)
    try {
      const result = await batchRegisterWSI({
        files: Array.from(batchSelectedFiles),
        dataset_id: batchDatasetMode === 'existing' ? batchSelectedDatasetId : undefined,
        dataset_name: batchDatasetMode === 'new' ? batchNewDatasetName.trim() : undefined,
        default_label: batchDefaultLabel.trim() || undefined
      })
      setBatchRegisterResult(result)
      // Refresh datasets list
      loadBatchDatasets()
      // Clear selection after success
      if (result.success > 0) {
        setBatchSelectedFiles(new Set())
        setBatchNewDatasetName('')
        setBatchDefaultLabel('')
      }
    } catch (err) {
      console.error('Failed to batch register:', err)
      setBatchScanError(err instanceof Error ? err.message : 'Failed to batch register WSI files')
    } finally {
      setBatchRegistering(false)
    }
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
      // Re-scan orphaned files but don't clear the cleanup result
      await detectOrphaned(false)
    } catch (err) {
      console.error('Failed to cleanup orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to cleanup orphaned files')
    } finally {
      setIsCleaningUp(false)
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

  const SaveButton = ({ saved, loading }: { saved: boolean; loading?: boolean }) => (
    <div className="flex items-center space-x-3">
      {saved && (
        <span className="text-sm text-green-600 flex items-center">
          <CheckCircle className="w-5 h-5 mr-1" />
          Settings saved!
        </span>
      )}
      <button
        type="submit"
        disabled={loading}
        className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all shadow-sm disabled:opacity-50"
      >
        {loading ? 'Saving...' : 'Save Settings'}
      </button>
    </div>
  )

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

  const handleEditUser = (user: UserListItem) => {
    setEditingUser(user)
    setEditForm({ nickname: user.nickname || '', role: user.role, password: '' })
  }

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

  const handleDeleteUser = (userId: string) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Delete User',
      message: 'Are you sure you want to delete this user? This action cannot be undone.',
      confirmText: 'Delete',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          await deleteUser(userId)
          loadUsers()
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : 'Failed to delete user')
        }
      }
    })
  }

  const handleRevokeAgreement = (userId: string) => {
    setConfirmDialog({
      isOpen: true,
      title: 'Revoke Agreement',
      message: 'Revoke this user\'s agreement? They will need to accept again on next login.',
      confirmText: 'Revoke',
      confirmVariant: 'warning',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          await revokeUserAgreement(userId)
          loadUsers()
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : 'Failed to revoke agreement')
        }
      }
    })
  }

  const handleToggleUserActive = (user: UserListItem) => {
    // Prevent deactivating the super admin (username "admin")
    if (user.email === 'admin' && user.is_active) {
      setUsersError('Cannot deactivate the super admin account')
      return
    }

    // Prevent deactivating yourself
    if (currentUser && user.id === currentUser.id) {
      setUsersError('You cannot deactivate your own account')
      return
    }

    const isActivating = !user.is_active
    setConfirmDialog({
      isOpen: true,
      title: isActivating ? 'Activate User' : 'Deactivate User',
      message: isActivating
        ? `Activate user "${user.email}"? They will be able to log in again.`
        : `Deactivate user "${user.email}"? They will not be able to log in until reactivated.`,
      confirmText: isActivating ? 'Activate' : 'Deactivate',
      confirmVariant: isActivating ? 'warning' : 'danger',
      onConfirm: async () => {
        setConfirmDialog(prev => ({ ...prev, isOpen: false }))
        try {
          await updateUser(user.id, { is_active: isActivating })
          loadUsers()
        } catch (err) {
          setUsersError(err instanceof Error ? err.message : `Failed to ${isActivating ? 'activate' : 'deactivate'} user`)
        }
      }
    })
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

  const getRoleBadgeColor = (role: string) => {
    switch (role) {
      case 'admin': return 'bg-red-100 text-red-800 border-red-200'
      case 'pathologist': return 'bg-blue-100 text-blue-800 border-blue-200'
      case 'guest': return 'bg-gray-100 text-gray-800 border-gray-200'
      default: return 'bg-gray-100 text-gray-800 border-gray-200'
    }
  }

  // Dataset Permission Management Functions
  const openPermissionModal = async (user: UserListItem) => {
    setPermissionUser(user)
    setLoadingPermissions(true)
    setSelectedDatasetId('')
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
    if (!permissionUser || !selectedDatasetId) return
    try {
      setGrantingPermission(true)
      const hours = expiresInHours ? parseInt(expiresInHours, 10) : undefined
      await grantDatasetPermission(selectedDatasetId, permissionUser.id, hours)
      // Refresh permissions
      const permResponse = await getUserDatasetPermissions(permissionUser.id)
      setUserPermissions(permResponse.permissions)
      setSelectedDatasetId('')
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
                      ? 'border-blue-500 text-blue-600 bg-blue-50/10'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 hover:bg-gray-50/50'
                    }
                  `}
                >
                  <Icon className={`mr-2 h-5 w-5 ${isActive ? 'text-blue-600' : 'text-gray-400 group-hover:text-gray-500'}`} />
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
          <div className="space-y-6">
            <form onSubmit={handleAISave} className="space-y-6">
              {/* Remote Model Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Cloud className="w-5 h-5 mr-2 text-blue-600" />
                    Remote Model Settings
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  {/* Remote Provider Config */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label>OpenRouter API Key</Label>
                      <Input
                        type="password"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder="sk-..."
                      />
                      <p className="text-xs text-gray-500">
                        Get key from <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">OpenRouter Console</a>
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label>Base URL</Label>
                      <Input
                        value={baseUrl}
                        onChange={(e) => setBaseUrl(e.target.value)}
                        placeholder="https://openrouter.ai/api/v1"
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label>Model</Label>
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      className="flex h-9 w-full rounded-lg border border-gray-200 bg-white px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <optgroup label="Multimodal Models">
                        <option value="qwen/qwen3-vl-235b-a22b-instruct">Qwen3-VL-235B-A22B-Instruct (Recommended)</option>
                        <option value="qwen/qwen3-vl-235b-a22b-thinking">Qwen3-VL-235B-A22B-Thinking (Deep Reasoning)</option>
                        <option value="z-ai/glm-4.6v">GLM-4.6V</option>
                        <option value="moonshotai/kimi-k2.5">Kimi-K2.5</option>
                      </optgroup>
                      <optgroup label="Text Models">
                        <option value="qwen/qwen3-235b-a22b-instruct-2507">Qwen3-235B-A22B-Instruct-2507</option>
                        <option value="z-ai/glm-4.7-flash">GLM-4.7-Flash</option>
                        <option value="moonshotai/kimi-k2-0905">Kimi-K2-Instruct-0905</option>
                      </optgroup>
                    </select>
                  </div>
                </CardContent>
              </Card>

              {/* Local Model Settings */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center text-lg">
                      <Server className="w-5 h-5 mr-2 text-green-600" />
                      Local Inference Settings
                    </CardTitle>
                    <div className="flex items-center space-x-4">
                      <div className={`flex items-center space-x-2 px-3 py-1 rounded-full text-sm font-medium border ${localVllmStatus === 'online'
                        ? 'bg-green-50 text-green-700 border-green-200'
                        : localVllmStatus === 'checking'
                          ? 'bg-yellow-50 text-yellow-700 border-yellow-200'
                          : 'bg-gray-100 text-gray-600 border-gray-200'
                        }`}>
                        <div className={`w-2 h-2 rounded-full ${localVllmStatus === 'online' ? 'bg-green-500' : localVllmStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'
                          }`} />
                        <span>{localVllmStatus === 'online' ? 'Online' : localVllmStatus === 'checking' ? 'Checking...' : 'Offline'}</span>
                      </div>
                      <div className="flex items-center space-x-3">
                        <Label htmlFor="local-vllm-toggle" className="text-sm font-medium cursor-pointer select-none" onClick={() => setLocalVllmEnabled(!localVllmEnabled)}>
                          Enable
                        </Label>
                        <div
                          id="local-vllm-toggle"
                          className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors duration-300 ${localVllmEnabled ? 'bg-blue-600' : 'bg-gray-200'}`}
                          onClick={() => setLocalVllmEnabled(!localVllmEnabled)}
                        >
                          <div className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-300 ${localVllmEnabled ? 'translate-x-5' : ''}`} />
                        </div>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                {localVllmEnabled && (
                  <CardContent className="pt-2"> 
                    <div className="space-y-6">
                      <div className="space-y-2">
                        <Label>Base URL</Label>
                        <div className="flex gap-3">
                          <Input
                            value={localVllmBaseUrl}
                            onChange={(e) => setLocalVllmBaseUrl(e.target.value)}
                            placeholder="http://127.0.0.1:8000/v1"
                            className="font-mono text-sm"
                          />
                          <Button
                            type="button"
                            variant="outline"
                            onClick={checkLocalVllmStatus}
                            className="bg-white"
                          >
                            Test Connection
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="space-y-2">
                          <div className="flex justify-between">
                            <Label>Model Name</Label>
                            {localVllmDetectedModel && (
                              <span className="text-xs font-mono bg-blue-100 text-blue-800 px-2 py-0.5 rounded">
                                Detected: {localVllmDetectedModel}
                              </span>
                            )}
                          </div>
                          <Input
                            value={localVllmModel}
                            onChange={(e) => setLocalVllmModel(e.target.value)}
                            placeholder={localVllmDetectedModel || "Qwen/Qwen2.5-VL-7B-Instruct"}
                          />
                          <p className="text-xs text-gray-500">Leave empty to use auto-detected model</p>
                        </div>
                        <div className="space-y-2">
                          <Label>API Key <span className="text-gray-400 font-normal ml-2">(Optional)</span></Label>
                          <Input
                            type="password"
                            value={localVllmApiKey}
                            onChange={(e) => setLocalVllmApiKey(e.target.value)}
                            placeholder="token-..."
                          />
                        </div>
                      </div>
                    </div>
                  </CardContent>
                )}
              </Card>

              {/* Additional Service Credentials Settings */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center text-lg">
                    <Key className="w-5 h-5 mr-2 text-purple-600" />
                    Shared Service Credentials
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label>HuggingFace Token</Label>
                      <Input
                        type="password"
                        value={huggingfaceToken}
                        onChange={(e) => setHuggingfaceToken(e.target.value)}
                        placeholder="hf_..."
                      />
                      <p className="text-xs text-gray-500">
                        For downloading gated models. <a href="https://huggingface.co/settings/tokens" target="_blank" className="text-blue-600 hover:underline">Get Token</a>
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label>DashScope API Key</Label>
                      <Input
                        type="password"
                        value={dashscopeApiKey}
                        onChange={(e) => setDashscopeApiKey(e.target.value)}
                        placeholder="sk-..."
                      />
                      <p className="text-xs text-gray-500">
                        For Qwen3-ASR voice. <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" className="text-blue-600 hover:underline">Get Key</a>
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Save Action Bar */}
              <div className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
                <div className="flex items-center gap-2 text-sm text-gray-500">
                  <Info className="w-4 h-4" />
                  <span>Settings apply to all AI services globally.</span>
                </div>
                <SaveButton saved={aiSaved} loading={aiSaving} />
              </div>
            </form>
          </div>
        )}

        {/* Tasks Tab - Slide Task Settings and GPU Queue Status */}
        {activeTab === 'tasks' && (
          <div className="space-y-6">
            <Card className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                  <Layers className="w-6 h-6 mr-3 text-gray-700" />
                  Task Processing Configuration
                </h2>
                <button
                  onClick={loadQueueStatus}
                  disabled={loadingQueue}
                  className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                  title="Refresh queue status"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingQueue ? 'animate-spin' : ''}`} />
                </button>
              </div>

              {queueError && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                  {queueError}
                </div>
              )}

              {queueStatus ? (
                <div className="space-y-6">
                  {/* Compact Status Bar */}
                  <div className="p-4 bg-gray-50 rounded-xl border border-gray-100">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-8 items-center">
                      {/* Left Column: Queue State + Running Tasks */}
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 w-full">
                        {/* Queue State - Fixed Width Anchor */}
                        <div className="flex items-center gap-3 min-w-fit flex-shrink-0 justify-between sm:justify-start">
                          <div className="flex items-center gap-3">
                            <div className={`w-3 h-3 rounded-full flex-shrink-0 ${queueStatus.is_running ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.5)]' : 'bg-red-500'}`} />
                            <span className="text-sm font-bold text-gray-700 whitespace-nowrap">
                              {queueStatus.is_running ? 'Queue Active' : 'Queue Stopped'}
                            </span>
                          </div>
                        </div>

                        <div className="hidden sm:block w-px h-6 bg-gray-300 mx-1" />

                        {/* Running Tasks Metric */}
                        <div className="flex-1 flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm min-w-0">
                          <span className="text-sm font-medium text-gray-500 truncate mr-2">Running Tasks</span>
                          <span className="text-base font-bold text-gray-900">{queueStatus.running_count}</span>
                        </div>
                      </div>

                      {/* Right Column: Pending Tasks */}
                      <div className="w-full">
                        <div className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200 shadow-sm w-full">
                          <span className="text-sm font-medium text-gray-500 truncate">Pending Tasks</span>
                          <span className="text-base font-bold text-gray-900">{queueStatus.pending_count}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Settings Grid */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
                    {/* Max Concurrent */}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Max Concurrent Tasks
                      </label>
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center w-full">
                          <div className="flex items-center bg-white border border-gray-300 rounded-lg overflow-hidden shadow-sm hover:border-blue-400 transition-colors w-full">
                            <button
                              onClick={() => handleUpdateMaxConcurrent(Math.max(1, queueStatus.max_concurrent - 1))}
                              className="p-2.5 hover:bg-gray-50 text-gray-600 transition-colors border-r border-gray-200 active:bg-gray-100 flex-shrink-0"
                              title="Decrease"
                            >
                              <Minus className="w-4 h-4" />
                            </button>

                            <input
                              type="number"
                              min="1"
                              max="10"
                              value={queueStatus.max_concurrent}
                              onChange={(e) => {
                                const val = parseInt(e.target.value);
                                if (!isNaN(val)) {
                                  handleUpdateMaxConcurrent(Math.min(10, Math.max(1, val)));
                                }
                              }}
                              className="flex-1 py-1.5 text-center font-bold text-gray-900 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none bg-transparent text-sm"
                            />

                            <button
                              onClick={() => handleUpdateMaxConcurrent(Math.min(10, queueStatus.max_concurrent + 1))}
                              className="p-2.5 hover:bg-gray-50 text-gray-600 transition-colors border-l border-gray-200 active:bg-gray-100 flex-shrink-0"
                              title="Increase"
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        <p className="text-xs text-gray-500 leading-tight">
                          Controls how many GPU tasks run in parallel. High values need more VRAM.
                        </p>
                      </div>
                    </div>

                    {/* Timeout */}
                    <div>
                      <form onSubmit={handleTaskSave} className="flex flex-col gap-2 h-full justify-between">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">
                            Task Timeout (seconds)
                          </label>
                          <div className="flex items-center gap-0 w-full rounded-lg shadow-sm overflow-hidden border border-gray-300 focus-within:ring-2 focus-within:ring-blue-500 focus-within:border-transparent transition-all">
                            <input
                              type="number"
                              value={taskTimeout}
                              onChange={(e) => setTaskTimeout(e.target.value)}
                              min="60"
                              max="259200"
                              className="flex-1 px-3 py-2 border-none focus:ring-0 text-sm font-medium"
                              placeholder="86400"
                            />
                            <button
                              type="submit"
                              disabled={taskSaving}
                              className={`flex-shrink-0 px-4 py-2 text-sm font-bold text-white transition-all active:scale-95 border-l border-gray-300 ${taskSaved
                                ? 'bg-green-600 hover:bg-green-700'
                                : taskSaving
                                  ? 'bg-gray-400 cursor-not-allowed'
                                  : 'bg-blue-600 hover:bg-blue-700'
                                } focus:outline-none`}
                            >
                              {taskSaved ? (
                                <span className="flex items-center">
                                  <CheckCircle className="w-3.5 h-3.5 mr-1.5" />
                                  Saved
                                </span>
                              ) : taskSaving ? (
                                'Saving...'
                              ) : (
                                'Save'
                              )}
                            </button>
                          </div>
                        </div>
                        <p className="text-xs text-gray-500 italic">
                          Tasks auto-cancel after this limit (Max: 3 days).
                        </p>
                      </form>
                    </div>
                  </div>

                  {/* Task List (if active) */}
                  {(queueStatus.running_task_ids.length > 0 || queueStatus.pending_task_ids.length > 0) && (
                    <div className="pt-4 border-t border-gray-100 space-y-3">
                      {queueStatus.running_task_ids.length > 0 && (
                        <div className="flex items-start gap-3">
                          <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">Running:</span>
                          <div className="flex flex-wrap gap-2">
                            {queueStatus.running_task_ids.map((taskId) => (
                              <span key={taskId} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-green-50 text-green-700 border border-green-100">
                                {taskId.length > 8 ? `${taskId.slice(0, 8)}...` : taskId}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {queueStatus.pending_task_ids.length > 0 && (
                        <div className="flex items-start gap-3">
                          <span className="text-xs font-bold text-gray-500 uppercase tracking-wider py-0.5 min-w-[60px]">Pending:</span>
                          <div className="flex flex-wrap gap-2">
                            {queueStatus.pending_task_ids.map((taskId) => (
                              <span key={taskId} className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-100">
                                {taskId.length > 8 ? `${taskId.slice(0, 8)}...` : taskId}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : loadingQueue ? (
                <div className="flex items-center justify-center py-12">
                  <RefreshCw className="w-8 h-8 animate-spin text-blue-500 opacity-50" />
                </div>
              ) : (
                <div className="text-center py-12 bg-gray-50 rounded-xl border border-dashed border-gray-200 text-gray-500">
                  Unable to load queue status. Please check service connectivity.
                </div>
              )}
            </Card>
          </div>
        )}

        {/* Models Tab - Trained Models Management */}
        {activeTab === 'models' && (
          <Card className="p-4 sm:p-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h2 className="text-lg sm:text-xl font-semibold text-gray-900 flex items-start">
                <Database className="w-5 h-5 sm:w-6 sm:h-6 mr-2 sm:mr-3 text-gray-700 mt-1" />
                <div className="flex flex-col">
                  <span>Model Management</span>
                  <span className="text-gray-500 font-normal text-sm mt-0.5">(for External Validation)</span>
                </div>
              </h2>
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">{modelsTotal} model{modelsTotal !== 1 ? 's' : ''}</span>
                <button
                  onClick={loadTrainedModels}
                  disabled={loadingModels}
                  className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                  title="Refresh models"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingModels ? 'animate-spin' : ''}`} />
                </button>
              </div>
            </div>

            {modelsError && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                {modelsError}
              </div>
            )}

            {loadingModels ? (
              <div className="flex items-center justify-center py-12">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
                  <p className="text-gray-500 text-sm">Loading models...</p>
                </div>
              </div>
            ) : trainedModels.length === 0 ? (
              <div className="text-center py-12">
                <Database className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-500">No trained models yet</p>
                <p className="text-gray-400 text-sm mt-1">
                  Complete a training task to see models here
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto -mx-4 sm:mx-0">
                <table className="w-full min-w-[600px]">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-base font-semibold text-gray-900 tracking-wide bg-gray-50/50">
                      <th className="px-5 py-4">Model</th>
                      <th className="px-5 py-4 hidden md:table-cell">Classes</th>
                      <th className="px-5 py-4 hidden lg:table-cell">Metrics</th>
                      <th className="px-5 py-4">Status</th>
                      <th className="px-5 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {trainedModels.map((model) => {
                      // Lookup the task name from our tasks state
                      const task = tasks.find(t => t.task_id === model.task_id)
                      const taskName = (task as any)?.name || (task as any)?.task_name || 'Unknown Task'

                      const metrics = model.val_metrics || {}
                      const isSurvival = metrics.c_index !== undefined

                      let primaryMetric = { label: 'Loss', value: metrics.loss }
                      let secondaryMetric = { label: 'Accuracy', value: metrics.accuracy }

                      if (isSurvival) {
                        primaryMetric = { label: 'C-Index', value: metrics.c_index }
                        secondaryMetric = { label: 'Loss', value: metrics.loss }
                      } else if (metrics.auc !== undefined || metrics.macro_auc !== undefined) {
                        primaryMetric = { label: 'AUC', value: metrics.auc || metrics.macro_auc }
                        secondaryMetric = { label: 'Accuracy', value: metrics.accuracy }
                      }

                      const formatValue = (v: any) => (typeof v === 'number' ? v.toFixed(3) : (v || '—'))

                      return (
                        <tr key={model.model_id} className="hover:bg-gray-50 transition-colors group border-b last:border-0 border-gray-100">
                          <td className="px-6 py-4 align-middle">
                            <div className="min-w-0 flex flex-col gap-1.5">
                              <div className="flex items-center gap-2">
                                {/* Task Badge in Chip style */}
                                <div className="flex items-center gap-1.5 bg-gray-100 px-2.5 py-0.5 rounded-full text-xs font-semibold text-gray-600">
                                  <Layers className="w-3 h-3 text-gray-500" />
                                  <span className="truncate max-w-[120px]" title={taskName}>{taskName}</span>
                                </div>
                                <span className="text-gray-300">|</span>
                                <span className="text-xs text-gray-400 flex items-center gap-1">
                                  <Calendar className="w-3 h-3" />
                                  {model.created_at && new Date(model.created_at).toLocaleDateString()}
                                </span>
                              </div>

                              <div className="text-lg font-bold text-gray-900 truncate max-w-[200px] sm:max-w-[320px]" title={model.model_name}>
                                {model.model_name}
                              </div>

                              <div className="flex items-center gap-2 text-xs text-gray-500">
                                <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">{model.feature_extractor}</span>
                                {model.aggregator && (
                                  <>
                                    <span className="text-gray-300">+</span>
                                    <span className="font-mono bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">{model.aggregator}</span>
                                  </>
                                )}
                              </div>
                            </div>
                          </td>

                          <td className="px-6 py-4 hidden md:table-cell align-middle">
                            <div className="flex flex-wrap gap-1.5 max-w-[240px]">
                              {isSurvival ? (
                                // For survival models, show time intervals count instead of bin labels
                                <span className="inline-flex items-center bg-emerald-50 text-emerald-700 px-2.5 py-1 rounded text-xs font-medium border border-emerald-100">
                                  {model.classes?.length || 4} Time Intervals
                                </span>
                              ) : (
                                // For classification models, show class labels
                                <>
                                  {model.classes?.slice(0, 4).map((cls, idx) => (
                                    <span key={idx} className="inline-flex items-center bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-medium border border-indigo-100">
                                      {cls}
                                    </span>
                                  ))}
                                  {model.classes && model.classes.length > 4 && (
                                    <span className="text-gray-400 font-medium text-xs flex items-center px-1">+{model.classes.length - 4}</span>
                                  )}
                                </>
                              )}
                            </div>
                          </td>

                          <td className="px-6 py-4 hidden lg:table-cell align-middle">
                            {Object.keys(metrics).length > 0 ? (
                              <div className="flex flex-col gap-2">
                                {/* Primary Metric Large */}
                                <div className="flex items-center justify-between gap-4 max-w-[160px]">
                                  <span className="text-gray-500 text-xs font-bold uppercase tracking-wider">{primaryMetric.label}</span>
                                  <span className="font-mono font-bold text-gray-900 text-xl tracking-tight">
                                    {formatValue(primaryMetric.value)}
                                  </span>
                                </div>

                                {/* Secondary Metric Small */}
                                {secondaryMetric.value !== undefined && (
                                  <div className="flex items-center justify-between gap-4 max-w-[160px] opacity-75">
                                    <span className="text-gray-400 text-[10px] font-semibold uppercase tracking-wider">{secondaryMetric.label}</span>
                                    <span className="font-mono font-medium text-gray-600 text-sm">
                                      {formatValue(secondaryMetric.value)}
                                    </span>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-sm text-gray-300 italic">No metrics</span>
                            )}
                          </td>

                          <td className="px-6 py-4 align-middle">
                            <div className="flex flex-col gap-2 items-start">
                              {model.is_default && (
                                <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-bold uppercase tracking-wide shadow-sm">
                                  <Star className="w-3 h-3 fill-current" />
                                  Default
                                </div>
                              )}

                              <div className={`
                              inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full text-xs font-medium border shadow-sm transition-colors
                              ${model.is_active
                                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                  : 'bg-gray-50 text-gray-500 border-gray-200'}
                            `}>
                                <div className={`w-1.5 h-1.5 rounded-full ${model.is_active ? 'bg-emerald-500' : 'bg-gray-400'}`} />
                                {model.is_active ? 'Active' : 'Inactive'}
                              </div>
                            </div>
                          </td>

                          <td className="px-6 py-4 align-middle text-right">
                            <div className="flex items-center justify-end gap-2">
                              {!model.is_default && model.is_active && (
                                <button
                                  onClick={async () => {
                                    try {
                                      await updateTrainedModel(model.model_id, { is_default: true })
                                      await loadTrainedModels()
                                    } catch (err) {
                                      setModelsError(err instanceof Error ? err.message : 'Failed to set default')
                                    }
                                  }}
                                  className="p-2 text-gray-400 hover:text-amber-500 hover:bg-amber-50 rounded-lg transition-all"
                                  title="Set as default"
                                >
                                  <Star className="w-5 h-5" />
                                </button>
                              )}
                              <button
                                onClick={async () => {
                                  try {
                                    await updateTrainedModel(model.model_id, { is_active: !model.is_active })
                                    await loadTrainedModels()
                                  } catch (err) {
                                    setModelsError(err instanceof Error ? err.message : 'Failed to update status')
                                  }
                                }}
                                className={`p-2 rounded-lg transition-all ${model.is_active
                                  ? 'text-emerald-600 hover:bg-emerald-50'
                                  : 'text-gray-400 hover:text-emerald-600 hover:bg-gray-100'
                                  }`}
                                title={model.is_active ? 'Deactivate' : 'Activate'}
                              >
                                {model.is_active ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
                              </button>
                              <button
                                onClick={() => {
                                  setConfirmDialog({
                                    isOpen: true,
                                    title: 'Delete Model',
                                    message: `Delete model "${model.model_name}"? This action cannot be undone.`,
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
                                }}
                                className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                                title="Delete model"
                              >
                                <Trash2 className="w-5 h-5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {/* Storage Tab - Storage Management */}
        {activeTab === 'storage' && (
          <>
            {loadingStorage ? (
              <div className="flex items-center justify-center py-12">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                  <p className="text-gray-600">Loading storage statistics...</p>
                </div>
              </div>
            ) : storageError ? (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <h3 className="text-red-800 font-semibold mb-2">Error</h3>
                <p className="text-red-600">{storageError}</p>
                <button
                  type="button"
                  onClick={loadStats}
                  className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
                >
                  Retry
                </button>
              </div>
            ) : stats ? (
              <>
                {/* Storage Location Configuration */}
                <Card className="p-6 mb-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                      <Database className="w-6 h-6 mr-3 text-gray-700" />
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
                        className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          onClick={handleSelectStorageDir}
                          disabled={storageSaving || !window.api?.files?.selectDirectory}
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

                {/* Storage Stats */}
                <Card className="p-6 mb-6">
                  <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                      <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                        <HardDrive className="w-6 h-6 mr-3 text-gray-700" />
                        Storage Overview
                      </h2>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.preventDefault()
                        loadStats()
                      }}
                      className="px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                      Refresh
                    </button>
                  </div>

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
                </Card>

                {/* Orphaned Files Management */}
                <Card className="p-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                      <svg className="w-6 h-6 text-gray-700" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      Orphaned Files
                    </h2>
                    <button
                      type="button"
                      onClick={() => detectOrphaned()}
                      disabled={loadingOrphaned || isCleaningUp}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                      </svg>
                      {loadingOrphaned ? 'Scanning...' : 'Scan'}
                    </button>
                  </div>

                  {orphanedFiles && (
                    <div className="space-y-3">
                      {/* Summary */}
                      {orphanedFiles.total_orphaned_count > 0 ? (
                        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                          <div className="flex items-center justify-between">
                            <div>
                              <div className="text-sm text-yellow-800 mb-1 flex items-center gap-2">
                                Found orphaned files
                              </div>
                              <div className="text-2xl font-bold text-yellow-900">
                                {orphanedFiles.total_orphaned_count} <span className="text-sm font-normal">files</span>
                              </div>
                              <div className="text-xs text-yellow-700 mt-1">
                                {formatBytes(orphanedFiles.total_orphaned_size)} can be freed
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={handleCleanup}
                              disabled={loadingOrphaned || isCleaningUp}
                              className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                              {isCleaningUp ? 'Cleaning...' : 'Clean Up'}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <div className="flex items-center gap-2 text-green-800">
                            <CheckCircle className="w-5 h-5" />
                            <span className="text-sm font-medium">
                              No orphaned files found
                            </span>
                          </div>
                        </div>
                      )}

                      {cleanupResult && (
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <div className="flex items-center gap-2 text-green-800 font-semibold mb-1">
                            <CheckCircle className="w-5 h-5" />
                            Cleanup Complete
                          </div>
                          <div className="text-sm text-green-700">
                            {cleanupResult.summary}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </Card>

                {/* Batch Scan & Register WSI Files */}
                <Card className="p-6 mt-6">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
                      <FolderSearch className="w-6 h-6 text-gray-700" />
                      Batch Register WSI Files
                    </h2>
                  </div>

                  <p className="text-sm text-gray-600 mb-4">
                    Scan a directory for WSI files copied via hard drive and register them to a dataset.
                  </p>

                  {/* Directory Selection */}
                  <div className="flex gap-2 mb-4">
                    <Input
                      value={batchScanPath}
                      onChange={(e) => setBatchScanPath(e.target.value)}
                      placeholder="Enter directory path to scan..."
                      className="flex-1"
                    />
                    {window.api?.files?.selectDirectory && (
                      <Button variant="outline" onClick={handleSelectBatchScanDir}>
                        Browse
                      </Button>
                    )}
                    <Button
                      onClick={handleBatchScan}
                      disabled={!batchScanPath.trim() || batchScanning}
                      className="gap-2"
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
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <div className="text-sm text-gray-600">
                          Found <span className="font-semibold text-gray-900">{batchScanResult.total_count}</span> WSI files
                          ({batchScanResult.valid_count} valid, {formatFileSize(batchScanResult.total_size)} total)
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
                      <div className="max-h-64 overflow-y-auto border rounded-lg">
                        <table className="w-full text-sm">
                          <thead className="bg-gray-50 sticky top-0">
                            <tr>
                              <th className="px-3 py-2 text-left w-10"></th>
                              <th className="px-3 py-2 text-left">Filename</th>
                              <th className="px-3 py-2 text-left w-20">Format</th>
                              <th className="px-3 py-2 text-right w-24">Size</th>
                              <th className="px-3 py-2 text-left w-32">Status</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y">
                            {batchScanResult.files.map((file) => (
                              <tr
                                key={file.path}
                                className={`hover:bg-gray-50 ${!file.valid ? 'opacity-60' : ''}`}
                              >
                                <td className="px-3 py-2">
                                  <input
                                    type="checkbox"
                                    checked={batchSelectedFiles.has(file.path)}
                                    onChange={() => handleBatchFileToggle(file.path)}
                                    disabled={!file.valid}
                                    className="rounded"
                                  />
                                </td>
                                <td className="px-3 py-2 font-mono text-xs truncate max-w-xs" title={file.path}>
                                  {file.filename}
                                </td>
                                <td className="px-3 py-2">
                                  <span className={`inline-flex px-2 py-0.5 text-xs rounded ${
                                    file.format_type === 'mrxs' ? 'bg-purple-100 text-purple-700' :
                                    file.format_type === 'tmap' ? 'bg-blue-100 text-blue-700' :
                                    'bg-gray-100 text-gray-700'
                                  }`}>
                                    {file.extension}
                                  </span>
                                </td>
                                <td className="px-3 py-2 text-right text-gray-600">
                                  {formatFileSize(file.size)}
                                </td>
                                <td className="px-3 py-2">
                                  {file.valid ? (
                                    <span className="text-green-600 flex items-center gap-1">
                                      <CheckCircle className="w-3 h-3" /> Valid
                                    </span>
                                  ) : (
                                    <span className="text-red-600 flex items-center gap-1" title={file.validation_message || ''}>
                                      <AlertCircle className="w-3 h-3" /> {file.validation_message}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Dataset Selection */}
                      <div className="bg-gray-50 rounded-lg p-4 space-y-3">
                        <div className="flex items-center gap-4">
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="radio"
                              checked={batchDatasetMode === 'new'}
                              onChange={() => setBatchDatasetMode('new')}
                              className="text-blue-600"
                            />
                            <span className="text-sm">Create new dataset</span>
                          </label>
                          <label className="flex items-center gap-2 cursor-pointer">
                            <input
                              type="radio"
                              checked={batchDatasetMode === 'existing'}
                              onChange={() => setBatchDatasetMode('existing')}
                              className="text-blue-600"
                            />
                            <span className="text-sm">Add to existing dataset</span>
                          </label>
                        </div>

                        {batchDatasetMode === 'new' ? (
                          <Input
                            value={batchNewDatasetName}
                            onChange={(e) => setBatchNewDatasetName(e.target.value)}
                            placeholder="Enter new dataset name..."
                          />
                        ) : (
                          <Select
                            value={batchSelectedDatasetId}
                            onChange={(value) => setBatchSelectedDatasetId(value)}
                            options={[
                              { value: '', label: 'Select a dataset...' },
                              ...batchDatasets.map(d => ({ value: d.dataset_id, label: d.dataset_name }))
                            ]}
                          />
                        )}

                        <div>
                          <Label className="text-sm text-gray-600 mb-1 block">Default Label (optional)</Label>
                          <Input
                            value={batchDefaultLabel}
                            onChange={(e) => setBatchDefaultLabel(e.target.value)}
                            placeholder="e.g., Unknown, Unlabeled..."
                          />
                        </div>
                      </div>

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

                      {/* Registration Result */}
                      {batchRegisterResult && (
                        <div className={`p-4 rounded-lg border ${
                          batchRegisterResult.failed > 0
                            ? 'bg-yellow-50 border-yellow-200'
                            : 'bg-green-50 border-green-200'
                        }`}>
                          <div className="flex items-center gap-2 font-semibold mb-2">
                            <CheckCircle className={`w-5 h-5 ${batchRegisterResult.failed > 0 ? 'text-yellow-600' : 'text-green-600'}`} />
                            Registration Complete
                          </div>
                          <div className="text-sm space-y-1">
                            <div>Dataset: <span className="font-medium">{batchRegisterResult.dataset_name}</span></div>
                            <div className="flex gap-4">
                              <span className="text-green-700">✓ {batchRegisterResult.success} succeeded</span>
                              {batchRegisterResult.skipped > 0 && (
                                <span className="text-gray-600">⊘ {batchRegisterResult.skipped} skipped (already registered)</span>
                              )}
                              {batchRegisterResult.failed > 0 && (
                                <span className="text-red-600">✗ {batchRegisterResult.failed} failed</span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              </>
            ) : null}
          </>
        )}

        {/* Users Tab - User Management */}
        {activeTab === 'users' && (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                <Users className="w-6 h-6 mr-3 text-gray-700" />
                User Management
              </h2>
              <div className="flex gap-2">
                <Button
                  onClick={() => setShowCreateUser(true)}
                  className="gap-2"
                >
                  <UserPlus className="w-4 h-4" />
                  Create User
                </Button>
                <Button
                  variant="outline"
                  onClick={loadUsers}
                  disabled={loadingUsers}
                  className="gap-2"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingUsers ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
              </div>
            </div>

            {usersError && (
              <div className="mb-4 p-4 bg-red-100 border border-red-300 rounded-lg text-red-600 text-sm">
                {usersError}
              </div>
            )}

            {loadingUsers ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Username</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Nickname</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Role</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Status</th>
                      <th className="text-left py-3 px-4 font-medium text-gray-600">Agreement</th>
                      <th className="text-right py-3 px-4 font-medium text-gray-600">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((user) => (
                      <tr key={user.id} className="border-b border-gray-100 hover:bg-gray-50">
                        <td className="py-3 px-4 text-gray-900">{user.email}</td>
                        <td className="py-3 px-4 text-gray-600">{user.nickname || '-'}</td>
                        <td className="py-3 px-4">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${getRoleBadgeColor(user.role)}`}>
                            {user.role === 'admin' && <Shield className="w-3 h-3 mr-1" />}
                            {user.role === 'pathologist' && <UserCog className="w-3 h-3 mr-1" />}
                            {user.role === 'guest' && <User className="w-3 h-3 mr-1" />}
                            {user.role.charAt(0).toUpperCase() + user.role.slice(1)}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                            {user.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="py-3 px-4">
                          {user.role === 'admin' ? (
                            <span className="text-xs text-gray-500 italic">Auto accepted</span>
                          ) : user.agreement_accepted_at ? (
                            <span className="text-xs text-green-600">
                              {new Date(user.agreement_accepted_at).toLocaleDateString()}
                            </span>
                          ) : (
                            <span className="text-xs text-gray-400">Not accepted</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleEditUser(user)}
                              className="h-8 w-8 p-0"
                              title="Edit user"
                            >
                              <Edit className="w-4 h-4" />
                            </Button>
                            {/* Dataset Permission button - for guest and pathologist users (not admin) */}
                            {user.role !== 'admin' && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => openPermissionModal(user)}
                                className="h-8 w-8 p-0 text-purple-600 hover:text-purple-700 hover:bg-purple-50"
                                title="Manage dataset permissions"
                              >
                                <Key className="w-4 h-4" />
                              </Button>
                            )}
                            {/* Toggle active status - hidden for current user and super admin "admin" */}
                            {(!currentUser || user.id !== currentUser.id) && user.email !== 'admin' && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleToggleUserActive(user)}
                                className={`h-8 w-8 p-0 ${user.is_active
                                  ? 'text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50'
                                  : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                                  }`}
                                title={user.is_active ? 'Deactivate user' : 'Activate user'}
                              >
                                {user.is_active ? <ToggleRight className="w-4 h-4" /> : <ToggleLeft className="w-4 h-4" />}
                              </Button>
                            )}
                            {user.agreement_accepted_at && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleRevokeAgreement(user.id)}
                                className="h-8 w-8 p-0 text-orange-600 hover:text-orange-700 hover:bg-orange-50"
                                title="Revoke agreement"
                              >
                                <RotateCcw className="w-4 h-4" />
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDeleteUser(user.id)}
                              className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                              title="Delete user"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </td>
                      </tr>
                    ))}
                    {users.length === 0 && (
                      <tr>
                        <td colSpan={6} className="py-8 text-center text-gray-500">
                          No users found
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}

        {/* Feedback Tab - User Feedback Analytics */}
        {activeTab === 'feedback' && (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                <MessageSquare className="w-6 h-6 mr-3 text-gray-700" />
                User Feedback Analytics
              </h2>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={loadFeedbacks}
                  disabled={loadingFeedbacks}
                  className="gap-2"
                >
                  <RefreshCw className={`w-4 h-4 ${loadingFeedbacks ? 'animate-spin' : ''}`} />
                  Refresh
                </Button>
                <Button
                  variant="outline"
                  onClick={handleResetFeedbacks}
                  disabled={loadingFeedbacks || resettingFeedbacks}
                  className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
                >
                  <Trash2 className={`w-4 h-4 ${resettingFeedbacks ? 'animate-pulse' : ''}`} />
                  Reset All
                </Button>
              </div>
            </div>

            {/* Export Section & Filters - Compact Layout */}
            <div className="mb-6 p-4 bg-gray-50/50 border border-gray-200/60 rounded-xl space-y-4">

              {/* Top Row: Export Setup + Filters */}
              <div className="flex flex-col xl:flex-row gap-4 items-end xl:items-center justify-between">

                {/* Left: Filters - Using New Select */}
                <div className="flex flex-wrap gap-3 items-center w-full xl:w-auto">
                  <div className="w-full sm:w-48">
                    <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Feedback Type</Label>
                    <Select
                      value={feedbackTypeFilter || ''}
                      onChange={(val) => {
                        setFeedbackTypeFilter(val ? val as 'thumbs_up' | 'thumbs_down' : null)
                        setFeedbackPage(0)
                      }}
                      options={[
                        { value: '', label: 'All Types' },
                        { value: 'thumbs_up', label: 'Thumbs Up' },
                        { value: 'thumbs_down', label: 'Thumbs Down' }
                      ]}
                    />
                  </div>

                  <div className="w-full sm:w-48">
                    <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Helpfulness</Label>
                    <Select
                      value={helpfulnessFilter || ''}
                      onChange={(val) => {
                        setHelpfulnessFilter(val ? val as 'helpful' | 'not_helpful' : null)
                        setFeedbackPage(0)
                      }}
                      options={[
                        { value: '', label: 'All Ratings' },
                        { value: 'helpful', label: 'Helpful' },
                        { value: 'not_helpful', label: 'Not Helpful' }
                      ]}
                    />
                  </div>
                </div>

                {/* Vertical Divider (Desktop) */}
                <div className="hidden xl:block w-px h-10 bg-gray-200 mx-2"></div>

                {/* Right: Date Range + Actions */}
                <div className="flex flex-col sm:flex-row gap-3 items-end w-full xl:w-auto">
                  <div>
                    <Label className="text-xs font-semibold text-gray-500 mb-1.5 block">Date Range</Label>
                    <div className="flex items-center gap-2">
                      <input
                        type="date"
                        value={exportDateFrom}
                        onChange={(e) => setExportDateFrom(e.target.value)}
                        className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                      />
                      <span className="text-gray-400">-</span>
                      <input
                        type="date"
                        value={exportDateTo}
                        onChange={(e) => setExportDateTo(e.target.value)}
                        className="h-9 px-3 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                      />
                      {(exportDateFrom || exportDateTo) && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            setExportDateFrom('')
                            setExportDateTo('')
                          }}
                          className="h-9 w-9 p-0 text-gray-400 hover:text-gray-600"
                          title="Clear dates"
                        >
                          <X className="w-4 h-4" />
                        </Button>
                      )}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      onClick={() => handleExportFeedbacks('csv')}
                      disabled={exportingFeedbacks || loadingFeedbacks}
                      className="h-9 gap-2 bg-white"
                    >
                      <Download className="w-4 h-4" />
                      CSV
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => handleExportFeedbacks('json')}
                      disabled={exportingFeedbacks || loadingFeedbacks}
                      className="h-9 gap-2 bg-white"
                    >
                      <Download className="w-4 h-4" />
                      JSON
                    </Button>
                  </div>
                </div>
              </div>
            </div>

            {loadingFeedbacks ? (
              <div className="flex items-center justify-center py-12">
                <RefreshCw className="w-6 h-6 animate-spin text-gray-400 mr-2" />
                <span className="text-gray-500">Loading feedbacks...</span>
              </div>
            ) : feedbacks.length === 0 ? (
              <div className="text-center py-12 text-gray-500">
                <MessageSquare className="w-12 h-12 mx-auto mb-4 text-gray-300" />
                <p>No feedbacks found</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Message Content</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Username</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Feedback</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Helpfulness</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Task</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time to Action</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Created At</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {feedbacks.map((feedback) => (
                      <tr key={feedback.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-900 font-mono text-xs">{feedback.id}</td>
                        <td className="px-4 py-3 text-gray-600 text-xs max-w-[200px] truncate" title={feedback.message_content || ''}>
                          {feedback.message_content
                            ? feedback.message_content.length > 50
                              ? feedback.message_content.slice(0, 50) + '...'
                              : feedback.message_content
                            : '-'}
                        </td>
                        <td className="px-4 py-3 text-gray-900 text-sm">
                          {feedback.username || feedback.user_id.slice(0, 8) + '...'}
                        </td>
                        <td className="px-4 py-3">
                          {feedback.feedback_type === 'thumbs_up' && (
                            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
                              <ThumbsUp className="w-3 h-3" /> Up
                            </span>
                          )}
                          {feedback.feedback_type === 'thumbs_down' && (
                            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-700">
                              <ThumbsDown className="w-3 h-3" /> Down
                            </span>
                          )}
                          {!feedback.feedback_type && (
                            <span className="text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {feedback.task_helpfulness === 'helpful' && (
                            <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
                              Helpful
                            </span>
                          )}
                          {feedback.task_helpfulness === 'not_helpful' && (
                            <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-700">
                              Not Helpful
                            </span>
                          )}
                          {!feedback.task_helpfulness && (
                            <span className="text-gray-400">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs max-w-[150px]">
                          {feedback.task_title ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-purple-50 text-purple-700 truncate capitalize" title={`${feedback.task_type?.replace(/_/g, ' ')}: ${feedback.task_title}`}>
                              {feedback.task_type && <span className="font-medium">{feedback.task_type.replace(/_/g, ' ')}:</span>}
                              <span className="truncate max-w-[80px]">{feedback.task_title}</span>
                            </span>
                          ) : '-'}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs">
                          {feedback.time_to_action_seconds != null ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full bg-cyan-50 text-cyan-700">
                              <Clock className="w-3 h-3" />
                              {feedback.time_to_action_seconds.toFixed(1)}s
                            </span>
                          ) : '-'}
                        </td>
                        <td className="px-4 py-3 text-gray-600 text-xs">
                          {new Date(feedback.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {feedbackTotal > feedbackLimit && (
              <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-200">
                <div className="text-sm text-gray-600">
                  Showing {feedbackPage * feedbackLimit + 1} - {Math.min((feedbackPage + 1) * feedbackLimit, feedbackTotal)} of {feedbackTotal}
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setFeedbackPage(Math.max(0, feedbackPage - 1))}
                    disabled={feedbackPage === 0 || loadingFeedbacks}
                  >
                    Previous
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setFeedbackPage(feedbackPage + 1)}
                    disabled={(feedbackPage + 1) * feedbackLimit >= feedbackTotal || loadingFeedbacks}
                  >
                    Next
                  </Button>
                </div>
              </div>
            )}
          </Card>
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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Edit User</h3>
              <div className="space-y-4">
                <div>
                  <Label className="text-sm text-gray-600">Username</Label>
                  <Input value={editingUser.email} disabled className="mt-1 bg-gray-50" />
                </div>
                <div>
                  <Label className="text-sm text-gray-600">Nickname</Label>
                  <Input
                    value={editForm.nickname}
                    onChange={(e) => setEditForm({ ...editForm, nickname: e.target.value })}
                    className="mt-1"
                    placeholder="Enter nickname"
                  />
                </div>
                <div>
                  <Label className="text-sm text-gray-600">New Password</Label>
                  <Input
                    type="password"
                    value={editForm.password}
                    onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                    className="mt-1"
                    placeholder="Leave empty to keep current password"
                  />
                  <p className="text-xs text-gray-400 mt-1">Minimum 6 characters. Leave empty to keep current password.</p>
                </div>
                <div>
                  <Label className="text-sm text-gray-600">Role</Label>
                  <select
                    value={editForm.role}
                    onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                    className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                  >
                    <option value="admin">Admin</option>
                    <option value="pathologist">Pathologist</option>
                    <option value="guest">Guest</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <Button variant="outline" onClick={() => setEditingUser(null)}>
                  Cancel
                </Button>
                <Button onClick={handleSaveUser}>
                  Save Changes
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Create User Modal */}
        {showCreateUser && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center">
                <UserPlus className="w-5 h-5 mr-2 text-blue-600" />
                Create New User
              </h3>
              <div className="space-y-4">
                <div>
                  <Label className="text-sm text-gray-600">Username *</Label>
                  <Input
                    value={createForm.username}
                    onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
                    className="mt-1"
                    placeholder="Enter username"
                    disabled={creatingUser}
                  />
                </div>
                <div>
                  <Label className="text-sm text-gray-600">Password *</Label>
                  <Input
                    type="password"
                    value={createForm.password}
                    onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                    className="mt-1"
                    placeholder="Minimum 6 characters"
                    disabled={creatingUser}
                  />
                </div>
                <div>
                  <Label className="text-sm text-gray-600">Nickname</Label>
                  <Input
                    value={createForm.nickname}
                    onChange={(e) => setCreateForm({ ...createForm, nickname: e.target.value })}
                    className="mt-1"
                    placeholder="Display name (optional)"
                    disabled={creatingUser}
                  />
                </div>
                <div>
                  <Label className="text-sm text-gray-600">Role</Label>
                  <select
                    value={createForm.role}
                    onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })}
                    className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    disabled={creatingUser}
                  >
                    <option value="admin">Admin</option>
                    <option value="pathologist">Pathologist</option>
                    <option value="guest">Guest</option>
                  </select>
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <Button variant="outline" onClick={() => {
                  setShowCreateUser(false)
                  setCreateForm({ username: '', password: '', nickname: '', role: 'pathologist' })
                  setUsersError(null)
                }} disabled={creatingUser}>
                  Cancel
                </Button>
                <Button onClick={handleCreateUser} disabled={creatingUser}>
                  {creatingUser ? 'Creating...' : 'Create User'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Dataset Permission Management Modal */}
        {permissionUser && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6 max-h-[80vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-lg font-semibold text-gray-900 flex items-center">
                  <Key className="w-5 h-5 mr-2 text-purple-600" />
                  Dataset Permissions - {permissionUser.nickname || permissionUser.email}
                </h3>
                <button
                  onClick={closePermissionModal}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Current Permissions */}
              <div className="mb-6">
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-medium text-gray-700">Current Permissions</h4>
                  {!loadingPermissions && userPermissions.length > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleRevokeAllPermissions}
                      className="h-auto py-1 px-2 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                      title="Revoke all permissions"
                    >
                      <Trash2 className="w-3 h-3 mr-1" />
                      Batch Revoke
                    </Button>
                  )}
                </div>
                {loadingPermissions ? (
                  <div className="text-sm text-gray-500">Loading permissions...</div>
                ) : userPermissions.length === 0 ? (
                  <div className="text-sm text-gray-500 italic py-4 text-center border border-dashed border-gray-200 rounded-lg">
                    No dataset permissions granted
                  </div>
                ) : (
                  <div className="space-y-2">
                    {userPermissions.map(perm => (
                      <div
                        key={perm.id}
                        className={`flex items-center justify-between p-3 rounded-lg border ${perm.is_valid ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200 opacity-60'
                          }`}
                      >
                        <div className="flex-1">
                          <div className="font-medium text-gray-900">
                            {datasets.find(d => d.dataset_id === perm.dataset_id)?.dataset_name || perm.dataset_id}
                          </div>
                          <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {perm.expires_at
                                ? `Expires: ${new Date(perm.expires_at).toLocaleString()}`
                                : 'No expiration'}
                            </span>
                            {perm.is_expired && (
                              <span className="text-red-600 font-medium">Expired</span>
                            )}
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRevokePermission(perm.dataset_id)}
                          className="h-8 w-8 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                          title="Revoke permission"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Grant New Permission */}
              <div className="border-t border-gray-200 pt-6">
                <h4 className="text-sm font-medium text-gray-700 mb-3">Grant New Permission</h4>
                <div className="flex gap-3">
                  <div className="flex-1">
                    <select
                      value={selectedDatasetId}
                      onChange={(e) => setSelectedDatasetId(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
                      disabled={grantingPermission}
                    >
                      <option value="">Select a dataset...</option>
                      {datasets
                        .filter(d => !userPermissions.some(p => p.dataset_id === d.dataset_id && p.is_valid))
                        .map(d => (
                          <option key={d.dataset_id} value={d.dataset_id}>
                            {d.dataset_name}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div className="w-32">
                    <Input
                      type="number"
                      value={expiresInHours}
                      onChange={(e) => setExpiresInHours(e.target.value)}
                      placeholder="Hours"
                      className="w-full"
                      min="1"
                      disabled={grantingPermission}
                      title="Expiration time in hours (leave empty for no expiration)"
                    />
                  </div>
                  <Button
                    onClick={handleGrantPermission}
                    disabled={!selectedDatasetId || grantingPermission}
                    className="bg-purple-600 hover:bg-purple-700"
                  >
                    {grantingPermission ? 'Granting...' : 'Grant'}
                  </Button>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Hours field is optional. Leave empty for permanent permission.
                </p>
              </div>

              {/* Close Button */}
              <div className="flex justify-end mt-6 pt-4 border-t border-gray-200">
                <Button variant="outline" onClick={closePermissionModal}>
                  Close
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Confirmation Dialog */}
        {confirmDialog.isOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
            <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6">
              <div className="text-center mb-6">
                <div className={`w-14 h-14 rounded-full flex items-center justify-center mx-auto mb-4 ${confirmDialog.confirmVariant === 'danger' ? 'bg-red-100' :
                  confirmDialog.confirmVariant === 'info' ? 'bg-blue-100' : 'bg-amber-100'
                  }`}>
                  {confirmDialog.confirmVariant === 'danger' ? (
                    <Trash2 className="w-7 h-7 text-red-600" />
                  ) : confirmDialog.confirmVariant === 'info' ? (
                    <Info className="w-7 h-7 text-blue-600" />
                  ) : (
                    <Trash2 className="w-7 h-7 text-amber-600" />
                  )}
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">{confirmDialog.title}</h3>
                <p className="text-gray-600 text-sm">{confirmDialog.message}</p>
              </div>
              <div className="flex gap-3">
                {confirmDialog.showCancel !== false && (
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => setConfirmDialog(prev => ({ ...prev, isOpen: false }))}
                  >
                    Cancel
                  </Button>
                )}
                <Button
                  className={`flex-1 ${confirmDialog.confirmVariant === 'danger'
                    ? 'bg-red-600 hover:bg-red-700 text-white'
                    : confirmDialog.confirmVariant === 'info'
                      ? 'bg-blue-600 hover:bg-blue-700 text-white'
                      : 'bg-amber-600 hover:bg-amber-700 text-white'
                    }`}
                  onClick={confirmDialog.onConfirm}
                >
                  {confirmDialog.confirmText || 'Confirm'}
                </Button>
              </div>
            </div>
          </div>
        )}

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
      {showMigrationPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/60 backdrop-blur-md p-4 animate-in fade-in duration-300">
          <div className="bg-white rounded-3xl shadow-2xl max-w-lg w-full overflow-hidden animate-in zoom-in-95 duration-300 border border-gray-100">
            {/* Soft Header */}
            <div className="p-8 pb-4 text-center">
              <div className="w-20 h-20 bg-blue-50 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-sm border border-blue-100/50">
                <RefreshCw className="w-10 h-10 text-blue-500 animate-spin-slow" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900">Data Migration</h3>
              <p className="text-gray-500 mt-3 text-sm leading-relaxed max-w-sm mx-auto">
                You've selected a new storage location. Would you like to move your existing slides and models to the new path?
              </p>
            </div>

            <div className="px-8 py-6">
              {/* Path Comparison Visualization - Softer style */}
              <div className="bg-gray-50/80 rounded-2xl p-6 mb-6 border border-gray-100/50">
                <div className="flex items-center justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-6 h-6 rounded-md bg-gray-200 flex items-center justify-center">
                        <Database className="w-3.5 h-3.5 text-gray-500" />
                      </div>
                      <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">From</span>
                    </div>
                    <div className="text-xs text-gray-600 font-mono break-all truncate-2" title={storageConfig?.uploads_dir}>
                      {storageConfig?.uploads_dir}
                    </div>
                  </div>

                  <div className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-white shadow-sm border border-gray-100">
                    <ChevronRight className="w-4 h-4 text-blue-400" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-6 h-6 rounded-md bg-blue-100 flex items-center justify-center">
                        <HardDrive className="w-3.5 h-3.5 text-blue-500" />
                      </div>
                      <span className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">To</span>
                    </div>
                    <div className="text-xs text-blue-900 font-mono font-medium break-all truncate-2" title={migrationTarget}>
                      {migrationTarget}
                    </div>
                  </div>
                </div>
              </div>

              {/* Cleanup Option - More subtle */}
              <div className={`p-4 rounded-xl border transition-all duration-300 ${deleteSource ? 'bg-red-50 border-red-100' : 'bg-white border-gray-100 shadow-sm'}`}>
                <label className="flex items-center gap-4 cursor-pointer group">
                  <div className="relative flex items-center justify-center">
                    <input
                      type="checkbox"
                      id="deleteSource"
                      checked={deleteSource}
                      onChange={(e) => setDeleteSource(e.target.checked)}
                      className="w-5 h-5 text-blue-500 border-gray-200 rounded-lg focus:ring-blue-500 focus:ring-offset-0 transition-all cursor-pointer"
                    />
                  </div>
                  <div className="flex-1">
                    <span className={`text-sm font-semibold block ${deleteSource ? 'text-red-700' : 'text-gray-700'}`}>
                      Cleanup original files
                    </span>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Delete from source after successful transfer
                    </p>
                  </div>
                </label>
              </div>
            </div>

            {/* Actions - Clean Layout */}
            <div className="p-8 pt-0 flex flex-col sm:flex-row gap-3">
              <Button
                variant="outline"
                className="flex-1 py-6 border-gray-100 hover:bg-gray-50 hover:text-gray-900 rounded-xl font-medium text-gray-500"
                onClick={() => setShowMigrationPrompt(false)}
              >
                Cancel
              </Button>
              <div className="flex-[2] flex gap-2">
                <Button
                  variant="outline"
                  className="flex-1 py-6 border-transparent bg-gray-50 hover:bg-gray-100 rounded-xl font-medium text-gray-600 transition-colors"
                  onClick={handleSkipMigration}
                >
                  Skip Move
                </Button>
                <Button
                  variant="primary"
                  className="flex-[1.5] py-6 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-500/20 rounded-xl font-bold border-none transition-all active:scale-[0.98]"
                  onClick={handleConfirmMigration}
                >
                  Start Move
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}


import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, Square, Layers, ClipboardList, Database, Info, BookOpen, CheckCircle, HardDrive, RefreshCw, Search, ArrowLeft, ChevronRight } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, OrphanedFilesInfo, CleanupResult, getStorageConfig, updateStorageConfig, StorageConfig, fetchExtractors } from '../api'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { API_BASE, PREPROCESSING_BASE, AI_BASE } from '../config'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'

type TabType = 'general' | 'processing' | 'tasks' | 'models' | 'storage'

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
  // Active Tab
  const [activeTab, setActiveTab] = useState<TabType>('general')

  // Service Health Status
  const [serviceHealth, setServiceHealth] = useState<ServiceHealth>({
    gateway: 'checking',
    wsi: 'checking',
    ai: 'checking'
  })

  // AI Configuration
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [model, setModel] = useState('qwen/qwen3-vl-235b-a22b-thinking')
  const [huggingfaceToken, setHuggingfaceToken] = useState('')
  const [aiSaved, setAiSaved] = useState(false)

  // Patch Extraction Settings
  const [patchSize, setPatchSize] = useState('512')
  const [patchStride, setPatchStride] = useState('0')
  const [patchLevel, setPatchLevel] = useState('0')
  // Tissue Segmentation Settings
  const [segSthresh, setSegSthresh] = useState('5')  // Very low threshold for maximum detection
  const [segMthresh, setSegMthresh] = useState('7')
  const [segClose, setSegClose] = useState('4')
  const [segUseOtsu, setSegUseOtsu] = useState(false)
  const [segContourFn, setSegContourFn] = useState('four_pt')
  const [patchSaved, setPatchSaved] = useState(false)

  // Feature Extraction Settings
  const [featureExtractor, setFeatureExtractor] = useState('resnet50')
  const [featureBatchSize, setFeatureBatchSize] = useState('32')
  const [featureDevice, setFeatureDevice] = useState('cuda')
  const [featureNormalize, setFeatureNormalize] = useState(true)
  const [featureSaved, setFeatureSaved] = useState(false)
  const [availableExtractors, setAvailableExtractors] = useState<{ id: string; name: string; description: string }[]>([])
  const [loadingExtractors, setLoadingExtractors] = useState(false)

  // Slide Task Settings
  const [taskTimeout, setTaskTimeout] = useState('3600')
  const [taskMaxRetries, setTaskMaxRetries] = useState('3')
  const [taskAutoCleanup, setTaskAutoCleanup] = useState(true)
  const [taskNotifications, setTaskNotifications] = useState(true)
  const [taskSaved, setTaskSaved] = useState(false)

  // Checkpoint Manager Settings
  const [ckptAutoLoad, setCkptAutoLoad] = useState(true)
  const [ckptMaxStorage, setCkptMaxStorage] = useState('10')
  const [ckptBackupEnabled, setCkptBackupEnabled] = useState(false)
  const [ckptDefaultPath, setCkptDefaultPath] = useState('/models/checkpoints')
  const [ckptSaved, setCkptSaved] = useState(false)

  // Storage Management State
  const [stats, setStats] = useState<StorageStats | null>(null)
  const [loadingStorage, setLoadingStorage] = useState(false)
  const [storageError, setStorageError] = useState<string | null>(null)
  const [orphanedFiles, setOrphanedFiles] = useState<OrphanedFilesInfo | null>(null)
  const [loadingOrphaned, setLoadingOrphaned] = useState(false)
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

  // Load saved settings on mount
  useEffect(() => {
    // AI Configuration
    setApiKey(localStorage.getItem('openrouter_api_key') || '')
    setBaseUrl(localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1')
    setModel(localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-thinking')
    setHuggingfaceToken(localStorage.getItem('huggingface_token') || '')

    // Patch Extraction
    setPatchSize(localStorage.getItem('patch_size') || '512')
    setPatchStride(localStorage.getItem('patch_stride') || '0')
    setPatchLevel(localStorage.getItem('patch_level') || '0')
    // Tissue Segmentation
    setSegSthresh(localStorage.getItem('seg_sthresh') || '5')  // Low threshold for maximum tissue detection
    setSegMthresh(localStorage.getItem('seg_mthresh') || '7')
    setSegClose(localStorage.getItem('seg_close') || '4')
    setSegUseOtsu(localStorage.getItem('seg_use_otsu') === 'true')
    setSegContourFn(localStorage.getItem('seg_contour_fn') || 'four_pt')

    // Feature Extraction
    setFeatureExtractor(localStorage.getItem('feature_extractor') || 'resnet50')
    setFeatureBatchSize(localStorage.getItem('feature_batch_size') || '32')
    setFeatureDevice(localStorage.getItem('feature_device') || 'cuda')
    setFeatureNormalize(localStorage.getItem('feature_normalize') === 'true')

    // Slide Task
    setTaskTimeout(localStorage.getItem('task_timeout') || '3600')
    setTaskMaxRetries(localStorage.getItem('task_max_retries') || '3')
    setTaskAutoCleanup(localStorage.getItem('task_auto_cleanup') === 'true')
    setTaskNotifications(localStorage.getItem('task_notifications') !== 'false')

    // Checkpoint Manager
    setCkptAutoLoad(localStorage.getItem('ckpt_auto_load') !== 'false')
    setCkptMaxStorage(localStorage.getItem('ckpt_max_storage') || '10')
    setCkptBackupEnabled(localStorage.getItem('ckpt_backup_enabled') === 'true')
    setCkptDefaultPath(localStorage.getItem('ckpt_default_path') || '/models/checkpoints')

    loadExtractors()
  }, [])

  const loadExtractors = async () => {
    setLoadingExtractors(true)
    try {
      const data = await fetchExtractors()
      // Fallback defined here if list is incomplete
      const merged = [...data]
      const defaultList = [
        { id: 'resnet50', name: 'ResNet50', description: 'ImageNet' },
        { id: 'uni', name: 'UNI', description: 'Mahmood Lab' },
        { id: 'conch', name: 'CONCH', description: 'Mahmood Lab' },
        { id: 'virchow2', name: 'Virchow2', description: 'Paige AI' }
      ]
      defaultList.forEach(fallback => {
        if (!merged.find(m => m.id === fallback.id)) {
          merged.push(fallback)
        }
      })
      setAvailableExtractors(merged)
    } catch (e) {
      console.error('Failed to load extractors:', e)
    } finally {
      setLoadingExtractors(false)
    }
  }

  // Check service health
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

  // Load storage stats when storage tab is active
  useEffect(() => {
    if (activeTab === 'storage') {
      loadStats()
      loadStorageConfig()
    }
  }, [activeTab])

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

  const detectOrphaned = async () => {
    setLoadingOrphaned(true)
    setStorageError(null)
    setCleanupResult(null)
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

  const handleCleanup = async () => {
    if (!orphanedFiles) return

    const categories = selectedCategories.size > 0
      ? Array.from(selectedCategories)
      : undefined

    setLoadingOrphaned(true)
    setStorageError(null)
    try {
      const result = await cleanupOrphanedFiles(categories)
      setCleanupResult(result)
      await loadStats()
      await detectOrphaned()
    } catch (err) {
      console.error('Failed to cleanup orphaned files:', err)
      setStorageError(err instanceof Error ? err.message : 'Failed to cleanup orphaned files')
    } finally {
      setLoadingOrphaned(false)
    }
  }

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes'
    const k = 1024
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round((bytes / Math.pow(k, i)) * 100) / 100 + ' ' + sizes[i]
  }

  const handleAISave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('openrouter_api_key', apiKey)
    localStorage.setItem('openrouter_base_url', baseUrl)
    localStorage.setItem('openrouter_model', model)
    localStorage.setItem('huggingface_token', huggingfaceToken)
    setAiSaved(true)
    setTimeout(() => setAiSaved(false), 3000)
  }

  const handlePatchSave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('patch_size', patchSize)
    localStorage.setItem('patch_stride', patchStride)
    localStorage.setItem('patch_level', patchLevel)
    // Tissue Segmentation
    localStorage.setItem('seg_sthresh', segSthresh)
    localStorage.setItem('seg_mthresh', segMthresh)
    localStorage.setItem('seg_close', segClose)
    localStorage.setItem('seg_use_otsu', String(segUseOtsu))
    localStorage.setItem('seg_contour_fn', segContourFn)
    setPatchSaved(true)
    setTimeout(() => setPatchSaved(false), 3000)
  }

  const handleFeatureSave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('feature_extractor', featureExtractor)
    localStorage.setItem('feature_batch_size', featureBatchSize)
    localStorage.setItem('feature_device', featureDevice)
    localStorage.setItem('feature_normalize', String(featureNormalize))
    setFeatureSaved(true)
    setTimeout(() => setFeatureSaved(false), 3000)
  }

  const handleTaskSave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('task_timeout', taskTimeout)
    localStorage.setItem('task_max_retries', taskMaxRetries)
    localStorage.setItem('task_auto_cleanup', String(taskAutoCleanup))
    localStorage.setItem('task_notifications', String(taskNotifications))
    setTaskSaved(true)
    setTimeout(() => setTaskSaved(false), 3000)
  }

  const handleCkptSave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('ckpt_auto_load', String(ckptAutoLoad))
    localStorage.setItem('ckpt_max_storage', ckptMaxStorage)
    localStorage.setItem('ckpt_backup_enabled', String(ckptBackupEnabled))
    localStorage.setItem('ckpt_default_path', ckptDefaultPath)
    setCkptSaved(true)
    setTimeout(() => setCkptSaved(false), 3000)
  }

  const SaveButton = ({ saved, loading }: { saved: boolean; loading?: boolean }) => (
    <div className="flex items-center space-x-3 pt-2">
      <button
        type="submit"
        disabled={loading}
        className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all shadow-sm disabled:opacity-50"
      >
        {loading ? 'Saving...' : 'Save Settings'}
      </button>
      {saved && (
        <span className="text-sm text-green-600 flex items-center">
          <CheckCircle className="w-5 h-5 mr-1" />
          Settings saved!
        </span>
      )}
    </div>
  )

  const tabs = [
    { id: 'general' as TabType, name: 'General', icon: Bot, description: 'AI & API Configuration' },
    { id: 'processing' as TabType, name: 'Processing', icon: Layers, description: 'Patch & Feature Extraction' },
    { id: 'tasks' as TabType, name: 'Tasks', icon: ClipboardList, description: 'Task Management' },
    { id: 'models' as TabType, name: 'Models', icon: Database, description: 'Checkpoint Manager' },
    { id: 'storage' as TabType, name: 'Storage', icon: HardDrive, description: 'Storage & Cleanup' },
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
                    group inline-flex items-center justify-center px-6 py-4 border-b-2 font-medium text-sm whitespace-nowrap flex-1 transition-colors
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
          <Card>
            <CardContent className="p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
                <Bot className="w-6 h-6 mr-3 text-gray-700" />
                AI Configuration
              </h2>

              <form onSubmit={handleAISave} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    OpenRouter API Key
                  </label>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="sk-..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Get your API key from <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">OpenRouter Console</a>
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    API Base URL
                  </label>
                  <input
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://openrouter.ai/api/v1"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    OpenRouter API endpoint (default: https://openrouter.ai/api/v1)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Model
                  </label>
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    <optgroup label="Vision Multimodal (Pathology Image Analysis)">

                      <option value="qwen/qwen3-vl-235b-a22b-instruct">Qwen3-VL-235B-A22B-Instruct (Recommended)</option>
                      <option value="qwen/qwen3-vl-235b-a22b-thinking">Qwen3-VL-235B-A22B-Thinking (Deep Reasoning)</option>
                      <option value="z-ai/glm-4.5v">GLM-4.5V (Vision)</option>
                    </optgroup>
                    <optgroup label="Text Flagship (Report Generation & Chat)">
                      <option value="qwen/qwen3-235b-a22b-instruct-2507">Qwen3-235B-A22B-Instruct-2507</option>
                      <option value="z-ai/glm-4.6">GLM-4.6</option>
                      <option value="moonshotai/kimi-k2-0905">Kimi-K2-Instruct-0905</option>
                    </optgroup>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    Choose a model for pathology analysis. Qwen3-VL-235B-A22B-Instruct is recommended for image analysis tasks.
                  </p>
                </div>

                <div className="border-t border-gray-200 pt-4 mt-4">
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    HuggingFace Token
                  </label>
                  <input
                    type="password"
                    value={huggingfaceToken}
                    onChange={(e) => setHuggingfaceToken(e.target.value)}
                    placeholder="hf_..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Required for downloading gated models. Get your token from{' '}
                    <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                      HuggingFace Settings
                    </a>
                  </p>
                </div>

                <SaveButton saved={aiSaved} />
              </form>
            </CardContent>
          </Card>
        )}

        {/* Processing Tab - Patch Extraction + Feature Extraction */}
        {activeTab === 'processing' && (
          <>
            {/* Patch Extraction Settings */}
            <Card className="p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
                <Square className="w-6 h-6 mr-3 text-gray-700" />
                Patch Extraction
              </h2>

              <form onSubmit={handlePatchSave} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Patch Size (pixels)
                    </label>
                    <input
                      type="number"
                      value={patchSize}
                      onChange={(e) => setPatchSize(e.target.value)}
                      min="64"
                      max="1024"
                      step="64"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Size of extracted patches (e.g., 256, 512)
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Stride (0 = no overlap)
                    </label>
                    <input
                      type="number"
                      value={patchStride}
                      onChange={(e) => setPatchStride(e.target.value)}
                      min="0"
                      max="1024"
                      step="64"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Step size between patches (0 = no overlap)
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Pyramid Level
                    </label>
                    <select
                      value={patchLevel}
                      onChange={(e) => setPatchLevel(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      <option value="0">Level 0 (Highest Resolution)</option>
                      <option value="1">Level 1</option>
                      <option value="2">Level 2</option>
                      <option value="3">Level 3</option>
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      WSI pyramid level to extract from
                    </p>
                  </div>
                </div>

                {/* Tissue Segmentation Settings */}
                <div className="mt-6 pt-6 border-t border-gray-200">
                  <h3 className="text-lg font-medium text-gray-900 mb-4">Tissue Segmentation</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Saturation Threshold
                      </label>
                      <input
                        type="number"
                        value={segSthresh}
                        onChange={(e) => setSegSthresh(e.target.value)}
                        min="1"
                        max="255"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        HSV saturation threshold (default: 5, lower = more tissue detected)
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Median Filter Size
                      </label>
                      <input
                        type="number"
                        value={segMthresh}
                        onChange={(e) => setSegMthresh(e.target.value)}
                        min="1"
                        max="15"
                        step="2"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        Median filter kernel size (must be odd, default: 7)
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Morphological Closing
                      </label>
                      <input
                        type="number"
                        value={segClose}
                        onChange={(e) => setSegClose(e.target.value)}
                        min="0"
                        max="20"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      <p className="text-xs text-gray-500 mt-1">
                        Closing kernel size (default: 4)
                      </p>
                    </div>

                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Contour Check Function
                      </label>
                      <select
                        value={segContourFn}
                        onChange={(e) => setSegContourFn(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      >
                        <option value="four_pt">Four Point (Most Strict)</option>
                        <option value="center">Center Point</option>
                        <option value="basic">Basic (Top-Left Only)</option>
                      </select>
                      <p className="text-xs text-gray-500 mt-1">
                        How to check if patch is in tissue
                      </p>
                    </div>

                    <div className="md:col-span-2">
                      <label className="flex items-center space-x-2">
                        <input
                          type="checkbox"
                          checked={segUseOtsu}
                          onChange={(e) => setSegUseOtsu(e.target.checked)}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                        <span className="text-sm font-medium text-gray-700">
                          Use Otsu Auto-Thresholding
                        </span>
                      </label>
                      <p className="text-xs text-gray-500 mt-1 ml-6">
                        Automatically determine threshold (overrides saturation threshold)
                      </p>
                    </div>
                  </div>
                </div>

                <SaveButton saved={patchSaved} />
              </form>
            </Card>
            <Card className="p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
                <Layers className="w-6 h-6 mr-3 text-gray-700" />
                Feature Extraction
              </h2>

              <form onSubmit={handleFeatureSave} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Feature Extractor Model
                    </label>
                    <select
                      value={featureExtractor}
                      onChange={(e) => setFeatureExtractor(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      {availableExtractors.length > 0 ? (
                        <>
                          <optgroup label="Pathology Foundation Models">
                            {availableExtractors
                              .filter(e => !e.id.toLowerCase().includes('resnet') && !e.id.toLowerCase().includes('vit'))
                              .map(e => (
                                <option key={e.id} value={e.id}>{e.name}</option>
                              ))
                            }
                          </optgroup>
                          <optgroup label="General Purpose Models">
                            {availableExtractors
                              .filter(e => e.id.toLowerCase().includes('resnet') || e.id.toLowerCase().includes('vit'))
                              .map(e => (
                                <option key={e.id} value={e.id}>{e.name}</option>
                              ))
                            }
                          </optgroup>
                        </>
                      ) : (
                        <>
                          <optgroup label="Standard Models">
                            <option value="resnet50">ResNet50 (ImageNet)</option>
                            <option value="vit_l_16">ViT-Large (ImageNet)</option>
                          </optgroup>
                          <optgroup label="Pathology Foundation Models">
                            <option value="uni">UNI (Mahmood Lab)</option>
                            <option value="conch">CONCH (Mahmood Lab)</option>
                            <option value="virchow2">Virchow2 (Paige AI)</option>
                            <option value="plip">PLIP (Pathology-Language)</option>
                          </optgroup>
                        </>
                      )}
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      Pre-trained model for feature extraction
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Batch Size
                    </label>
                    <input
                      type="number"
                      value={featureBatchSize}
                      onChange={(e) => setFeatureBatchSize(e.target.value)}
                      min="1"
                      max="256"
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">
                      Number of patches processed simultaneously
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Device
                    </label>
                    <select
                      value={featureDevice}
                      onChange={(e) => setFeatureDevice(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      <option value="cuda">GPU (CUDA)</option>
                      <option value="cpu">CPU</option>
                      <option value="mps">Apple Silicon (MPS)</option>
                    </select>
                    <p className="text-xs text-gray-500 mt-1">
                      Hardware device for computation
                    </p>
                  </div>

                  <div className="flex items-center">
                    <label className="flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={featureNormalize}
                        onChange={(e) => setFeatureNormalize(e.target.checked)}
                        className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      />
                      <span className="ml-2 text-sm font-medium text-gray-700">
                        Normalize Features
                      </span>
                    </label>
                    <p className="text-xs text-gray-500 ml-6 mt-1">
                      Apply L2 normalization to extracted features
                    </p>
                  </div>
                </div>

                <SaveButton saved={featureSaved} />
              </form>
            </Card>
          </>
        )}

        {/* Tasks Tab - Slide Task Settings */}
        {activeTab === 'tasks' && (
          <Card className="p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <ClipboardList className="w-6 h-6 mr-3 text-gray-700" />
              Slide Task Configuration
            </h2>

            <form onSubmit={handleTaskSave} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Task Timeout (seconds)
                  </label>
                  <input
                    type="number"
                    value={taskTimeout}
                    onChange={(e) => setTaskTimeout(e.target.value)}
                    min="60"
                    max="86400"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Maximum time for task execution (default: 3600s = 1 hour)
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Max Retries
                  </label>
                  <input
                    type="number"
                    value={taskMaxRetries}
                    onChange={(e) => setTaskMaxRetries(e.target.value)}
                    min="0"
                    max="10"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Number of retry attempts for failed tasks
                  </p>
                </div>

                <div className="flex items-center">
                  <label className="flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={taskAutoCleanup}
                      onChange={(e) => setTaskAutoCleanup(e.target.checked)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="ml-2 text-sm font-medium text-gray-700">
                      Auto Cleanup Completed Tasks
                    </span>
                  </label>
                  <p className="text-xs text-gray-500 ml-6 mt-1">
                    Automatically remove old task records after 30 days
                  </p>
                </div>

                <div className="flex items-center">
                  <label className="flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={taskNotifications}
                      onChange={(e) => setTaskNotifications(e.target.checked)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="ml-2 text-sm font-medium text-gray-700">
                      Enable Task Notifications
                    </span>
                  </label>
                  <p className="text-xs text-gray-500 ml-6 mt-1">
                    Show notifications when tasks complete or fail
                  </p>
                </div>
              </div>

              <SaveButton saved={taskSaved} />
            </form>
          </Card>
        )}

        {/* Models Tab - Checkpoint Manager */}
        {activeTab === 'models' && (
          <Card className="p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <Database className="w-6 h-6 mr-3 text-gray-700" />
              Checkpoint Manager
            </h2>

            <form onSubmit={handleCkptSave} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Default Checkpoint Path
                  </label>
                  <input
                    type="text"
                    value={ckptDefaultPath}
                    onChange={(e) => setCkptDefaultPath(e.target.value)}
                    placeholder="/models/checkpoints"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Default directory for storing model checkpoints
                  </p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Max Storage (GB)
                  </label>
                  <input
                    type="number"
                    value={ckptMaxStorage}
                    onChange={(e) => setCkptMaxStorage(e.target.value)}
                    min="1"
                    max="1000"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Maximum storage space for checkpoints
                  </p>
                </div>

                <div className="flex items-center">
                  <label className="flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ckptAutoLoad}
                      onChange={(e) => setCkptAutoLoad(e.target.checked)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="ml-2 text-sm font-medium text-gray-700">
                      Auto-load Last Active Checkpoint
                    </span>
                  </label>
                  <p className="text-xs text-gray-500 ml-6 mt-1">
                    Automatically load the last active checkpoint on startup
                  </p>
                </div>

                <div className="flex items-center">
                  <label className="flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ckptBackupEnabled}
                      onChange={(e) => setCkptBackupEnabled(e.target.checked)}
                      className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                    />
                    <span className="ml-2 text-sm font-medium text-gray-700">
                      Enable Automatic Backup
                    </span>
                  </label>
                  <p className="text-xs text-gray-500 ml-6 mt-1">
                    Create backup copies of checkpoints before deletion
                  </p>
                </div>
              </div>

              <SaveButton saved={ckptSaved} />
            </form>
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
                    <h2 className="text-xl font-semibold text-gray-900 flex items-center">
                      <HardDrive className="w-6 h-6 mr-3 text-gray-700" />
                      Storage Overview
                    </h2>
                    <button
                      onClick={loadStats}
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
                      onClick={detectOrphaned}
                      disabled={loadingOrphaned}
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
                              <div className="text-sm text-yellow-800 mb-1">Found orphaned files</div>
                              <div className="text-2xl font-bold text-yellow-900">
                                {orphanedFiles.total_orphaned_count} <span className="text-sm font-normal">files</span>
                              </div>
                              <div className="text-xs text-yellow-700 mt-1">
                                {formatBytes(orphanedFiles.total_orphaned_size)} can be freed
                              </div>
                            </div>
                            <button
                              onClick={handleCleanup}
                              disabled={loadingOrphaned}
                              className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                              Clean Up
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                          <div className="flex items-center gap-2 text-green-800">
                            <CheckCircle className="w-5 h-5" />
                            <span className="text-sm font-medium">No orphaned files found</span>
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
              </>
            ) : null}
          </>
        )}

        {/* System Information - Show on all tabs except storage */}
        {activeTab !== 'storage' && (
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

        {/* About - Show on all tabs except storage */}
        {activeTab !== 'storage' && (
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


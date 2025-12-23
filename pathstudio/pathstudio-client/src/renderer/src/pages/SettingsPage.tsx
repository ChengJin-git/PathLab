import { useState, useEffect } from 'react'
import { Bot, Square, Layers, ClipboardList, Database, Info, BookOpen, CheckCircle, HardDrive } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, OrphanedFilesInfo, CleanupResult } from '../api'

type TabType = 'general' | 'processing' | 'tasks' | 'models' | 'storage'

export default function SettingsPage() {
  // Active Tab
  const [activeTab, setActiveTab] = useState<TabType>('general')

  // AI Configuration
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [model, setModel] = useState('qwen/qwen3-vl-235b-a22b-thinking')
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

  // Load saved settings on mount
  useEffect(() => {
    // AI Configuration
    setApiKey(localStorage.getItem('openrouter_api_key') || '')
    setBaseUrl(localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1')
    setModel(localStorage.getItem('openrouter_model') || 'qwen/qwen3-vl-235b-a22b-thinking')

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
  }, [])

  // Load storage stats when storage tab is active
  useEffect(() => {
    if (activeTab === 'storage') {
      loadStats()
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
    <div className="max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-600 mt-2">Configure your PathStudio platform</p>
      </div>

      {/* Tab Navigation */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 mb-6">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px overflow-x-auto" aria-label="Tabs">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`
                    group inline-flex items-center px-6 py-4 border-b-2 font-medium text-sm whitespace-nowrap
                    ${isActive
                      ? 'border-blue-500 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
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
      </div>

      {/* Tab Content */}
      <div className="space-y-6">
        {/* General Tab - AI Configuration */}
        {activeTab === 'general' && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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

            <SaveButton saved={aiSaved} />
          </form>
          </div>
        )}

        {/* Processing Tab - Patch Extraction + Feature Extraction */}
        {activeTab === 'processing' && (
          <>
            {/* Patch Extraction Settings */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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
            </div>

            {/* Feature Extraction Settings */}
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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
                  <optgroup label="Standard Models">
                    <option value="resnet50">ResNet50 (ImageNet)</option>
                    <option value="resnet101">ResNet101 (ImageNet)</option>
                    <option value="vit_base">ViT-Base (ImageNet)</option>
                    <option value="vit_large">ViT-Large (ImageNet)</option>
                  </optgroup>
                  <optgroup label="Pathology-Specific">
                    <option value="ctranspath">CTransPath (Pathology)</option>
                    <option value="uni">UNI (Pathology Foundation)</option>
                    <option value="plip">PLIP (Pathology-Language)</option>
                  </optgroup>
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
            </div>
          </>
        )}

        {/* Tasks Tab - Slide Task Settings */}
        {activeTab === 'tasks' && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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
          </div>
        )}

        {/* Models Tab - Checkpoint Manager */}
        {activeTab === 'models' && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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
          </div>
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
                {/* Storage Stats */}
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
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
                        'wsi_files': 'WSI Files',
                        'coordinates': 'Coordinates',
                        'thumbnails': 'Thumbnails',
                        'masks': 'Masks',
                        'ai_results': 'AI Results',
                        'training': 'Training Data',
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
                </div>

                {/* Orphaned Files Management */}
                <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
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
                </div>
              </>
            ) : null}
          </>
        )}

        {/* System Information - Show on all tabs except storage */}
        {activeTab !== 'storage' && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <Info className="w-6 h-6 mr-3 text-gray-700" />
              System Information
            </h2>

            <div className="space-y-3">
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">Platform Version</span>
                <span className="text-sm text-gray-600">v1.0.0</span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">Gateway Service</span>
                <span className="text-sm text-green-600 flex items-center">
                  <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
                  Online
                </span>
              </div>
              <div className="flex justify-between py-2 border-b border-gray-100">
                <span className="text-sm font-medium text-gray-700">WSI Service</span>
                <span className="text-sm text-green-600 flex items-center">
                  <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
                  Online
                </span>
              </div>
              <div className="flex justify-between py-2">
                <span className="text-sm font-medium text-gray-700">AI Service</span>
                <span className="text-sm text-green-600 flex items-center">
                  <div className="w-2 h-2 bg-green-500 rounded-full mr-2"></div>
                  Online
                </span>
              </div>
            </div>
          </div>
        )}

        {/* About - Show on all tabs except storage */}
        {activeTab !== 'storage' && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
              <BookOpen className="w-6 h-6 mr-3 text-gray-700" />
              About
            </h2>

            <div className="space-y-3 text-sm text-gray-600">
              <p>
                <strong className="text-gray-900">PathStudio</strong> is an AI-powered pathology analysis platform
                for whole slide image (WSI) classification and analysis.
              </p>
              <p>
                The platform integrates state-of-the-art deep learning models with an intuitive
                AI assistant to help researchers set up and run pathology analysis tasks.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}


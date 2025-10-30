import { useState, useEffect } from 'react'

export default function SettingsPage() {
  // AI Configuration
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://api.siliconflow.cn/v1')
  const [model, setModel] = useState('Qwen/Qwen3-VL-235B-A22B-Instruct')
  const [aiSaved, setAiSaved] = useState(false)

  // Patch Extraction Settings
  const [patchSize, setPatchSize] = useState('512')
  const [patchStride, setPatchStride] = useState('0')
  const [patchLevel, setPatchLevel] = useState('0')
  const [patchFormat, setPatchFormat] = useState('jpeg')
  const [patchQuality, setPatchQuality] = useState('95')
  // Tissue Segmentation Settings
  const [segSthresh, setSegSthresh] = useState('20')
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

  // Load saved settings on mount
  useEffect(() => {
    // AI Configuration
    setApiKey(localStorage.getItem('siliconflow_api_key') || '')
    setBaseUrl(localStorage.getItem('siliconflow_base_url') || 'https://api.siliconflow.cn/v1')
    setModel(localStorage.getItem('siliconflow_model') || 'Qwen/Qwen3-VL-235B-A22B-Instruct')

    // Patch Extraction
    setPatchSize(localStorage.getItem('patch_size') || '512')
    setPatchStride(localStorage.getItem('patch_stride') || '0')
    setPatchLevel(localStorage.getItem('patch_level') || '0')
    setPatchFormat(localStorage.getItem('patch_format') || 'jpeg')
    setPatchQuality(localStorage.getItem('patch_quality') || '95')
    // Tissue Segmentation
    setSegSthresh(localStorage.getItem('seg_sthresh') || '20')
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

  const handleAISave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('siliconflow_api_key', apiKey)
    localStorage.setItem('siliconflow_base_url', baseUrl)
    localStorage.setItem('siliconflow_model', model)
    setAiSaved(true)
    setTimeout(() => setAiSaved(false), 3000)
  }

  const handlePatchSave = (e: React.FormEvent) => {
    e.preventDefault()
    localStorage.setItem('patch_size', patchSize)
    localStorage.setItem('patch_stride', patchStride)
    localStorage.setItem('patch_level', patchLevel)
    localStorage.setItem('patch_format', patchFormat)
    localStorage.setItem('patch_quality', patchQuality)
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
          <svg className="w-5 h-5 mr-1" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          Settings saved!
        </span>
      )}
    </div>
  )

  return (
    <div className="max-w-7xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-600 mt-2">Configure your SmartResearch platform</p>
      </div>

      <div className="space-y-6">
        {/* AI Configuration */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">🤖</span>
            AI Configuration (SiliconFlow)
          </h2>

          <form onSubmit={handleAISave} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                SiliconFlow API Key
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-500 mt-1">
                Get your API key from <a href="https://cloud.siliconflow.cn/account/ak" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">SiliconFlow Console</a>
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
                placeholder="https://api.siliconflow.cn/v1"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <p className="text-xs text-gray-500 mt-1">
                SiliconFlow API endpoint (default: https://api.siliconflow.cn/v1)
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
                  <option value="Qwen/Qwen3-VL-235B-A22B-Instruct">Qwen3-VL-235B-A22B-Instruct (Recommended)</option>
                  <option value="Qwen/Qwen3-VL-235B-A22B-Thinking">Qwen3-VL-235B-A22B-Thinking (Deep Reasoning)</option>
                  <option value="Qwen/Qwen3-VL-32B-Instruct">Qwen3-VL-32B-Instruct</option>
                  <option value="zai-org/GLM-4.5V">GLM-4.5V (Vision)</option>
                </optgroup>
                <optgroup label="Text Flagship (Report Generation & Chat)">
                  <option value="Qwen/Qwen3-235B-A22B-Instruct-2507">Qwen3-235B-A22B-Instruct-2507</option>
                  <option value="Qwen/Qwen3-30B-A3B-Instruct-2507">Qwen3-30B-A3B-Instruct-2507</option>
                  <option value="deepseek-ai/DeepSeek-V3">DeepSeek-V3</option>
                  <option value="zai-org/GLM-4.6">GLM-4.6 (200K Context)</option>
                  <option value="moonshotai/Kimi-K2-Instruct-0905">Kimi-K2-Instruct-0905</option>
                </optgroup>
              </select>
              <p className="text-xs text-gray-500 mt-1">
                Choose a model for pathology analysis. Qwen3-VL-235B-A22B-Instruct is recommended for image analysis tasks.
              </p>
            </div>

            <SaveButton saved={aiSaved} />
          </form>
        </div>

        {/* Patch Extraction Settings */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">🔲</span>
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

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Image Format
                </label>
                <select
                  value={patchFormat}
                  onChange={(e) => setPatchFormat(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="jpeg">JPEG</option>
                  <option value="png">PNG</option>
                  <option value="webp">WebP</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  Output format for extracted patches
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  JPEG Quality
                </label>
                <input
                  type="number"
                  value={patchQuality}
                  onChange={(e) => setPatchQuality(e.target.value)}
                  min="1"
                  max="100"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Quality for JPEG compression (1-100)
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
                    HSV saturation threshold (default: 20)
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
            <span className="text-2xl mr-3">🧬</span>
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

        {/* Slide Task Settings */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">📋</span>
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

        {/* Checkpoint Manager Settings */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">💾</span>
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

        {/* System Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">ℹ️</span>
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

        {/* About */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center">
            <span className="text-2xl mr-3">📖</span>
            About
          </h2>
          
          <div className="space-y-3 text-sm text-gray-600">
            <p>
              <strong className="text-gray-900">SmartResearch</strong> is an AI-powered pathology analysis platform
              for whole slide image (WSI) classification and analysis.
            </p>
            <p>
              The platform integrates state-of-the-art deep learning models with an intuitive
              AI assistant to help researchers set up and run pathology analysis tasks.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}


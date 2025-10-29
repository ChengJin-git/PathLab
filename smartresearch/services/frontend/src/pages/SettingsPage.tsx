import { useState, useEffect } from 'react'

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://api.siliconflow.cn/v1')
  const [model, setModel] = useState('Qwen/Qwen3-VL-235B-A22B-Instruct')
  const [saved, setSaved] = useState(false)

  // Load saved settings on mount
  useEffect(() => {
    const savedApiKey = localStorage.getItem('siliconflow_api_key') || ''
    const savedBaseUrl = localStorage.getItem('siliconflow_base_url') || 'https://api.siliconflow.cn/v1'
    const savedModel = localStorage.getItem('siliconflow_model') || 'Qwen/Qwen3-VL-235B-A22B-Instruct'

    setApiKey(savedApiKey)
    setBaseUrl(savedBaseUrl)
    setModel(savedModel)
  }, [])

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault()
    // Save settings to localStorage
    localStorage.setItem('siliconflow_api_key', apiKey)
    localStorage.setItem('siliconflow_base_url', baseUrl)
    localStorage.setItem('siliconflow_model', model)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

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

          <form onSubmit={handleSave} className="space-y-4">
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

            <div className="flex items-center space-x-3 pt-2">
              <button
                type="submit"
                className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all shadow-sm"
              >
                Save Settings
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


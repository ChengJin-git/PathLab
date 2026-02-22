import { useState, useEffect, useCallback } from 'react'
import { Cloud, Server, Key, Info, CheckCircle, Mic } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { getGlobalSettings, updateGlobalSettings, getAuthToken } from '../../api'
import { API_BASE } from '../../config'
import { ShowConfirmDialog } from './ConfirmDialog'
import { useTranslation } from 'react-i18next'

export interface GeneralTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

  const { t } = useTranslation()
export function GeneralTab({ showConfirmDialog, closeConfirmDialog }: GeneralTabProps) {
  // Remote LLM state
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [model, setModel] = useState('qwen/qwen3.5-plus-02-15')
  const [huggingfaceToken, setHuggingfaceToken] = useState('')
  const [dashscopeApiKey, setDashscopeApiKey] = useState('')
  const [aiSaved, setAiSaved] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)

  // Local vLLM state
  const [localVllmEnabled, setLocalVllmEnabled] = useState(false)
  const [localVllmBaseUrl, setLocalVllmBaseUrl] = useState('http://127.0.0.1:8000/v1')
  const [localVllmModel, setLocalVllmModel] = useState('')
  const [localVllmApiKey, setLocalVllmApiKey] = useState('')
  const [localVllmStatus, setLocalVllmStatus] = useState<'checking' | 'online' | 'offline'>('offline')
  const [localVllmDetectedModel, setLocalVllmDetectedModel] = useState<string | null>(null)

  // Local ASR state
  const [localAsrEnabled, setLocalAsrEnabled] = useState(false)
  const [localAsrBaseUrl, setLocalAsrBaseUrl] = useState('http://127.0.0.1:8001/v1')
  const [localAsrModel, setLocalAsrModel] = useState('')
  const [localAsrApiKey, setLocalAsrApiKey] = useState('')
  const [localAsrStatus, setLocalAsrStatus] = useState<'checking' | 'online' | 'offline'>('offline')
  const [localAsrDetectedModel, setLocalAsrDetectedModel] = useState<string | null>(null)

  // Check local vLLM status
  const checkLocalVllmStatusWithParams = async (bUrl: string, aKey: string) => {
    if (!bUrl) { setLocalVllmStatus('offline'); setLocalVllmDetectedModel(null); return }
    setLocalVllmStatus('checking')
    setLocalVllmDetectedModel(null)
    try {
      const token = getAuthToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`${API_BASE}/settings/check-vllm`, {
        method: 'POST', headers,
        body: JSON.stringify({ base_url: bUrl, api_key: aKey || null })
      })
      if (res.ok) {
        const data = await res.json()
        setLocalVllmStatus(data.online ? 'online' : 'offline')
        if (data.online && data.model) setLocalVllmDetectedModel(data.model)
      } else { setLocalVllmStatus('offline') }
    } catch { setLocalVllmStatus('offline') }
  }

  // Check local ASR status
  const checkLocalAsrStatusWithParams = async (bUrl: string, aKey: string, m?: string) => {
    if (!bUrl) { setLocalAsrStatus('offline'); setLocalAsrDetectedModel(null); return }
    setLocalAsrStatus('checking')
    setLocalAsrDetectedModel(null)
    try {
      const token = getAuthToken()
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`
      const res = await fetch(`${API_BASE}/settings/check-asr`, {
        method: 'POST', headers,
        body: JSON.stringify({ base_url: bUrl, model: m || null, api_key: aKey || null })
      })
      if (res.ok) {
        const data = await res.json()
        setLocalAsrStatus(data.online ? 'online' : 'offline')
        if (data.online && data.model) setLocalAsrDetectedModel(data.model)
      } else { setLocalAsrStatus('offline') }
    } catch { setLocalAsrStatus('offline') }
  }

  // Load global settings
  const loadGlobalSettings = useCallback(async () => {
    try {
      const s = await getGlobalSettings()
      setApiKey(s.openrouter_api_key); setBaseUrl(s.openrouter_base_url); setModel(s.openrouter_model)
      setHuggingfaceToken(s.huggingface_token); setDashscopeApiKey(s.dashscope_api_key)
      setLocalVllmEnabled(s.local_vllm_enabled); setLocalVllmBaseUrl(s.local_vllm_base_url)
      setLocalVllmModel(s.local_vllm_model); setLocalVllmApiKey(s.local_vllm_api_key)
      setLocalAsrEnabled(s.local_asr_enabled); setLocalAsrBaseUrl(s.local_asr_base_url)
      setLocalAsrModel(s.local_asr_model); setLocalAsrApiKey(s.local_asr_api_key)
      if (s.local_vllm_enabled && s.local_vllm_base_url) {
        checkLocalVllmStatusWithParams(s.local_vllm_base_url, s.local_vllm_api_key)
      }
      if (s.local_asr_enabled && s.local_asr_base_url) {
        checkLocalAsrStatusWithParams(s.local_asr_base_url, s.local_asr_api_key, s.local_asr_model)
      }
    } catch (err) { console.error('Failed to load global settings:', err) }
  }, [])

  useEffect(() => { loadGlobalSettings() }, [loadGlobalSettings])

  // When disabled, show offline
  useEffect(() => { if (!localVllmEnabled) { setLocalVllmStatus('offline'); setLocalVllmDetectedModel(null) } }, [localVllmEnabled])
  useEffect(() => { if (!localAsrEnabled) { setLocalAsrStatus('offline'); setLocalAsrDetectedModel(null) } }, [localAsrEnabled])

  const checkLocalVllmStatus = () => checkLocalVllmStatusWithParams(localVllmBaseUrl, localVllmApiKey)
  const checkLocalAsrStatus = () => checkLocalAsrStatusWithParams(localAsrBaseUrl, localAsrApiKey, localAsrModel)

  const handleAISave = async (e: React.FormEvent) => {
    e.preventDefault()
    setAiSaving(true)
    try {
      await updateGlobalSettings({
        openrouter_api_key: apiKey, openrouter_base_url: baseUrl, openrouter_model: model,
        huggingface_token: huggingfaceToken, dashscope_api_key: dashscopeApiKey,
        local_vllm_enabled: localVllmEnabled, local_vllm_base_url: localVllmBaseUrl,
        local_vllm_model: localVllmModel, local_vllm_api_key: localVllmApiKey,
        local_asr_enabled: localAsrEnabled, local_asr_base_url: localAsrBaseUrl,
        local_asr_model: localAsrModel, local_asr_api_key: localAsrApiKey,
      })
      setAiSaved(true)
      setTimeout(() => setAiSaved(false), 3000)
    } catch (err) {
      console.error('Failed to save AI settings:', err)
      showConfirmDialog({
        title: 'Error',
        message: err instanceof Error ? err.message : 'Failed to save AI configuration',
        confirmText: 'OK', confirmVariant: 'danger', showCancel: false,
        onConfirm: () => closeConfirmDialog()
      })
    } finally { setAiSaving(false) }
  }
  return (
    <div className="space-y-6">
      <form onSubmit={handleAISave} className="space-y-6">

        {/* Stacked Layout: Remote Services then Local Services */}
        <div className="space-y-8">
          {/* Remote Services Section */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-700 flex items-center">
              <Cloud className="w-5 h-5 mr-2 text-blue-600" />
              {t('settings.remoteServices')}
            </h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Left Column: Remote LLM Settings (OpenRouter) */}
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center text-base">
                    <Server className="w-4 h-4 mr-2 text-primary-600" />
                    {t('settings.general.llmOpenRouter')}
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label>{t('settings.general.apiKey')}</Label>
                    <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-..." />
                    <p className="text-xs text-gray-500">
                      <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">{t('common.getKey')}</a>
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>{t('settings.general.baseUrl')}</Label>
                    <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://openrouter.ai/api/v1" className="font-mono text-sm" />
                  </div>
                  <div className="space-y-2">
                    <Label>{t('settings.general.model')}</Label>
                    <select
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      className="flex h-9 w-full rounded-lg border border-gray-200 bg-white px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950"
                    >
                      <optgroup label={t('settings.general.multimodalModels')}>
                        <option value="qwen/qwen3.5-plus-02-15">Qwen3.5-Plus-02-15</option>
                        <option value="z-ai/glm-5">GLM-5</option>
                        <option value="moonshotai/kimi-k2.5">Kimi-K2.5</option>
                      </optgroup>
                      <optgroup label={t('settings.general.textModels')}>
                        <option value="qwen/qwen3-235b-a22b-instruct-2507">Qwen3-235B-A22B-Instruct-2507</option>
                        <option value="stepfun/step-3.5-flash:free">Step-3.5-Flash</option>
                        <option value="z-ai/glm-4.7-flash">GLM-4.7-Flash</option>
                        <option value="moonshotai/kimi-k2-0905">Kimi-K2-Instruct-0905</option>
                      </optgroup>
                    </select>
                  </div>
                </CardContent>
              </Card>

              {/* Right Column: Remote ASR + Shared Credentials */}
              <div className="space-y-6">
                {/* Remote ASR Settings (DashScope) */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center text-base">
                      <Mic className="w-4 h-4 mr-2 text-orange-600" />
                      {t('settings.general.asrDashScope')}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label>{t('settings.general.dashscopeApiKey')}</Label>
                      <Input type="password" value={dashscopeApiKey} onChange={(e) => setDashscopeApiKey(e.target.value)} placeholder="sk-..." />
                      <p className="text-xs text-gray-500">
                        {t('settings.general.forQwen3Asr')} <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" className="text-primary-600 hover:underline">{t('common.getKey')}</a>
                      </p>
                    </div>
                  </CardContent>
                </Card>

                {/* Shared Service Credentials */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center text-base">
                      <Key className="w-4 h-4 mr-2 text-amber-600" />
                      {t('settings.general.sharedCredentials')}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      <Label>{t('settings.general.huggingfaceToken')}</Label>
                      <Input type="password" value={huggingfaceToken} onChange={(e) => setHuggingfaceToken(e.target.value)} placeholder="hf_..." />
                      <p className="text-xs text-gray-500">
                        {t('settings.general.forDownloadingGated')} <a href="https://huggingface.co/settings/tokens" target="_blank" className="text-primary-600 hover:underline">{t('common.getToken')}</a>
                      </p>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>
          </div>

          {/* Local Services Section */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-700 flex items-center">
              <Server className="w-5 h-5 mr-2 text-green-600" />
              {t('settings.localServices')}
            </h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Local LLM Settings */}
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center text-base">
                      <Server className="w-4 h-4 mr-2 text-green-600" />
                      {t('settings.general.llmVllm')}
                    </CardTitle>
                    <div className="flex items-center space-x-3">
                      <div className={`flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${localVllmStatus === 'online' ? 'bg-green-50 text-green-700 border-green-200' :
                        localVllmStatus === 'checking' ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                          'bg-gray-100 text-gray-600 border-gray-200'
                        }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${localVllmStatus === 'online' ? 'bg-green-500' : localVllmStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'}`} />
                        <span>{localVllmStatus === 'online' ? t('common.online') : localVllmStatus === 'checking' ? '...' : t('common.offline')}</span>
                      </div>
                      <div
                        className={`w-10 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-300 ${localVllmEnabled ? 'bg-green-600' : 'bg-gray-200'}`}
                        onClick={() => setLocalVllmEnabled(!localVllmEnabled)}
                      >
                        <div className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-300 ${localVllmEnabled ? 'translate-x-5' : ''}`} />
                      </div>
                    </div>
                  </div>
                </CardHeader>
                {localVllmEnabled && (
                  <CardContent className="pt-2 space-y-4">
                    <div className="space-y-2">
                      <Label>{t('settings.general.baseUrl')}</Label>
                      <div className="flex gap-2">
                        <Input value={localVllmBaseUrl} onChange={(e) => setLocalVllmBaseUrl(e.target.value)} placeholder="http://127.0.0.1:8000/v1" className="font-mono text-sm" />
                        <Button type="button" variant="outline" size="sm" onClick={checkLocalVllmStatus} className="bg-white whitespace-nowrap">
                          {t('common.test')}
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <Label>{t('settings.general.model')}</Label>
                        {localVllmDetectedModel && (
                          <span className="text-xs font-mono bg-green-100 text-green-800 px-1.5 py-0.5 rounded">
                            {localVllmDetectedModel}
                          </span>
                        )}
                      </div>
                      <Input value={localVllmModel} onChange={(e) => setLocalVllmModel(e.target.value)} placeholder={localVllmDetectedModel || "Qwen/Qwen3.5-Plus-02-15"} />
                    </div>
                    <div className="space-y-2">
                      <Label>{t('settings.general.apiKeyOptional')}</Label>
                      <Input type="password" value={localVllmApiKey} onChange={(e) => setLocalVllmApiKey(e.target.value)} placeholder="token-..." />
                    </div>
                  </CardContent>
                )}
              </Card>

              {/* Local ASR Settings */}
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center text-base">
                      <Mic className="w-4 h-4 mr-2 text-purple-600" />
                      {t('settings.general.asrWebSocket')}
                    </CardTitle>
                    <div className="flex items-center space-x-3">
                      <div className={`flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${localAsrStatus === 'online' ? 'bg-green-50 text-green-700 border-green-200' :
                        localAsrStatus === 'checking' ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                          'bg-gray-100 text-gray-600 border-gray-200'
                        }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${localAsrStatus === 'online' ? 'bg-green-500' : localAsrStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'}`} />
                        <span>{localAsrStatus === 'online' ? t('common.online') : localAsrStatus === 'checking' ? '...' : t('common.offline')}</span>
                      </div>
                      <div
                        className={`w-10 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-300 ${localAsrEnabled ? 'bg-purple-600' : 'bg-gray-200'}`}
                        onClick={() => setLocalAsrEnabled(!localAsrEnabled)}
                      >
                        <div className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-300 ${localAsrEnabled ? 'translate-x-5' : ''}`} />
                      </div>
                    </div>
                  </div>
                </CardHeader>
                {localAsrEnabled && (
                  <CardContent className="pt-2 space-y-4">
                    <div className="space-y-2">
                      <Label>{t('settings.general.webSocketUrl')}</Label>
                      <div className="flex gap-2">
                        <Input value={localAsrBaseUrl} onChange={(e) => setLocalAsrBaseUrl(e.target.value)} placeholder="ws://127.0.0.1:8001/api-ws/v1/realtime" className="font-mono text-sm" />
                        <Button type="button" variant="outline" size="sm" onClick={checkLocalAsrStatus} className="bg-white whitespace-nowrap">
                          {t('common.test')}
                        </Button>
                      </div>
                      <p className="text-xs text-gray-500">
                        {t('settings.general.webSocketEndpointInfo')}
                      </p>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <Label>{t('settings.general.model')}</Label>
                        {localAsrDetectedModel && (
                          <span className="text-xs font-mono bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">
                            {localAsrDetectedModel}
                          </span>
                        )}
                      </div>
                      <Input value={localAsrModel} onChange={(e) => setLocalAsrModel(e.target.value)} placeholder={localAsrDetectedModel || "Qwen/Qwen3-ASR-1.7B"} />
                      <p className="text-xs text-gray-500">
                        {t('settings.general.modelNameWillBeAppended')}
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label>{t('settings.general.apiKeyOptional')}</Label>
                      <Input type="password" value={localAsrApiKey} onChange={(e) => setLocalAsrApiKey(e.target.value)} placeholder="token-..." />
                    </div>
                  </CardContent>
                )}
              </Card>
            </div>
          </div>
        </div>



        {/* Save Action Bar */}
        <div className="flex items-center justify-between p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Info className="w-4 h-4" />
            <span>{t('common.localServicePriority')}</span>
          </div>
          <div className="flex items-center space-x-3">
            {aiSaved && (
              <span className="text-sm text-green-600 flex items-center">
                <CheckCircle className="w-5 h-5 mr-1" />
                {t('common.savedSuccess')}
              </span>
            )}
            <button
              type="submit"
              disabled={aiSaving}
              className="px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-700 text-white text-sm font-medium rounded-lg hover:from-primary-700 hover:to-primary-800 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 transition-all shadow-sm disabled:opacity-50"
            >
              {aiSaving ? t('common.savingText') : t('common.saveSettings')}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

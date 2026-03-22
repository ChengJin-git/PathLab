import { useState, useEffect, useCallback } from 'react'
import { Cloud, Server, Key, Info, CheckCircle, Mic, Globe, Mail } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { getGlobalSettings, updateGlobalSettings, buildAuthRequestInit } from '../../api'
import { API_BASE } from '../../config'
import { ShowConfirmDialog } from './ConfirmDialog'
import { useTranslation } from 'react-i18next'

// Status Badge Component
function StatusBadge({ status }: { status: 'online' | 'offline' | 'checking' }) {
  const { t } = useTranslation()
  const statusConfig = {
    online: { bg: 'bg-emerald-50', text: 'text-emerald-700', border: 'border-emerald-200', dot: 'bg-emerald-500' },
    checking: { bg: 'bg-amber-50', text: 'text-amber-700', border: 'border-amber-200', dot: 'bg-amber-500' },
    offline: { bg: 'bg-slate-100', text: 'text-slate-600', border: 'border-slate-200', dot: 'bg-slate-400' }
  }
  const config = statusConfig[status]
  const statusText = status === 'online' ? t('common.online') : status === 'checking' ? t('common.checking') : t('common.offline')
  return (
    <div className={`flex items-center space-x-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border ${config.bg} ${config.text} ${config.border}`}>
      <div className={`w-2 h-2 rounded-full ${config.dot} animate-pulse`} />
      <span>{statusText}</span>
    </div>
  )
}

// Toggle Switch Component
function ToggleSwitch({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
        enabled ? 'bg-emerald-600 ring-emerald-500' : 'bg-slate-300 ring-slate-400'
      }`}
      role="switch"
      aria-checked={enabled}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-lg transition-transform ${enabled ? 'translate-x-6' : 'translate-x-1'}`}
      />
    </button>
  )
}

/**
 * Single source of truth for all available AI models.
 * Used by GeneralTab (<select>) and AIChatPage (multimodal upload validation).
 */
export interface ModelOption {
  id: string
  label: string
  multimodal: boolean
  closedSource?: boolean
}

export const MODEL_OPTIONS: ModelOption[] = [
  // Multimodal models (support image input)
  { id: 'qwen/qwen3.5-plus-02-15', label: 'Qwen3.5-Plus-02-15', multimodal: true },
  { id: 'moonshotai/kimi-k2.5', label: 'Kimi-K2.5', multimodal: true },
  { id: 'openai/gpt-5.3-codex', label: 'GPT-5.3-Codex', multimodal: true, closedSource: true },
  { id: 'anthropic/claude-sonnet-4-6', label: 'Claude Sonnet 4.6', multimodal: true, closedSource: true },
  // Text-only models
  { id: 'z-ai/glm-5', label: 'GLM-5', multimodal: false },
  { id: 'qwen/qwen3-235b-a22b-instruct-2507', label: 'Qwen3-235B-A22B-Instruct-2507', multimodal: false },
  { id: 'stepfun/step-3.5-flash:free', label: 'Step-3.5-Flash', multimodal: false },
  { id: 'minimax/minimax-m2.7', label: 'Minimax-M2.7', multimodal: false },
  { id: 'xiaomi/mimo-v2-pro', label: 'MIMO-V2-Pro', multimodal: false },
]

export const CUSTOM_MODEL_SENTINEL = '__custom__'

export const MULTIMODAL_MODELS = new Set(
  MODEL_OPTIONS.filter(m => m.multimodal).map(m => m.id)
)

function isCustomModelId(id: string): boolean {
  return !!id && id !== CUSTOM_MODEL_SENTINEL && !MODEL_OPTIONS.some(m => m.id === id)
}

export interface GeneralTabProps {
  showConfirmDialog: ShowConfirmDialog
  closeConfirmDialog: () => void
}

export function GeneralTab({ showConfirmDialog, closeConfirmDialog }: GeneralTabProps) {
  const { t } = useTranslation()
  // Remote LLM state
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('https://openrouter.ai/api/v1')
  const [model, setModel] = useState('qwen/qwen3.5-plus-02-15')
  const [isCustomMode, setIsCustomMode] = useState(false)
  const [huggingfaceToken, setHuggingfaceToken] = useState('')
  const [dashscopeApiKey, setDashscopeApiKey] = useState('')
  // Kaggle credentials
  const [kaggleUsername, setKaggleUsername] = useState('')
  const [kaggleKey, setKaggleKey] = useState('')
  // Web Search
  const [exaApiKey, setExaApiKey] = useState('')
  const [tavilyApiKey, setTavilyApiKey] = useState('')
  const [aiSaved, setAiSaved] = useState(false)
  const [aiSaving, setAiSaving] = useState(false)

  // Local vLLM state
  const [localVllmEnabled, setLocalVllmEnabled] = useState(false)
  const [localVllmBaseUrl, setLocalVllmBaseUrl] = useState('http://127.0.0.1:8000/v1')
  const [localVllmModel, setLocalVllmModel] = useState('')
  const [localVllmApiKey, setLocalVllmApiKey] = useState('')
  const [localVllmStatus, setLocalVllmStatus] = useState<'checking' | 'online' | 'offline'>('offline')
  const [localVllmDetectedModel, setLocalVllmDetectedModel] = useState<string | null>(null)

  const [resendEnabled, setResendEnabled] = useState(false)
  const [resendApiKey, setResendApiKey] = useState('')

  const [localAsrEnabled, setLocalAsrEnabled] = useState(false)
  const [localAsrBaseUrl, setLocalAsrBaseUrl] = useState('ws://127.0.0.1:8001/api-ws/v1/realtime')
  const [localAsrModel, setLocalAsrModel] = useState('')
  const [localAsrApiKey, setLocalAsrApiKey] = useState('')
  const [localAsrStatus, setLocalAsrStatus] = useState<'checking' | 'online' | 'offline'>('offline')
  const [localAsrDetectedModel, setLocalAsrDetectedModel] = useState<string | null>(null)

  // Check local vLLM status
  const checkLocalVllmStatusWithParams = useCallback(async (bUrl: string, aKey: string) => {
    if (!bUrl) { setLocalVllmStatus('offline'); setLocalVllmDetectedModel(null); return }
    setLocalVllmStatus('checking')
    setLocalVllmDetectedModel(null)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const res = await fetch(`${API_BASE}/settings/check-vllm`, buildAuthRequestInit({
        method: 'POST', headers,
        body: JSON.stringify({ base_url: bUrl, api_key: aKey || null })
      }))
      if (res.ok) {
        const data = await res.json()
        setLocalVllmStatus(data.online ? 'online' : 'offline')
        if (data.online && data.model) setLocalVllmDetectedModel(data.model)
      } else { setLocalVllmStatus('offline') }
    } catch { setLocalVllmStatus('offline') }
  }, [])

  // Check local ASR status
  const checkLocalAsrStatusWithParams = useCallback(async (bUrl: string, aKey: string, m?: string) => {
    if (!bUrl) { setLocalAsrStatus('offline'); setLocalAsrDetectedModel(null); return }
    setLocalAsrStatus('checking')
    setLocalAsrDetectedModel(null)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      const res = await fetch(`${API_BASE}/settings/check-asr`, buildAuthRequestInit({
        method: 'POST', headers,
        body: JSON.stringify({ base_url: bUrl, model: m || null, api_key: aKey || null })
      }))
      if (res.ok) {
        const data = await res.json()
        setLocalAsrStatus(data.online ? 'online' : 'offline')
        if (data.online && data.model) setLocalAsrDetectedModel(data.model)
      } else { setLocalAsrStatus('offline') }
    } catch { setLocalAsrStatus('offline') }
  }, [])

  // Load global settings
  const loadGlobalSettings = useCallback(async () => {
    try {
      const s = await getGlobalSettings()
      setApiKey(s.openrouter_api_key); setBaseUrl(s.openrouter_base_url); setModel(s.openrouter_model)
      setIsCustomMode(isCustomModelId(s.openrouter_model))
      localStorage.setItem('openrouter_api_key', s.openrouter_api_key)
      localStorage.setItem('openrouter_base_url', s.openrouter_base_url)
      localStorage.setItem('openrouter_model', s.openrouter_model)
      setHuggingfaceToken(s.huggingface_token); setDashscopeApiKey(s.dashscope_api_key)
      setKaggleUsername(s.kaggle_username || ''); setKaggleKey(s.kaggle_key || '')
      setExaApiKey(s.exa_api_key || '')
      setTavilyApiKey(s.tavily_api_key || '')
      setLocalVllmEnabled(s.local_vllm_enabled); setLocalVllmBaseUrl(s.local_vllm_base_url)
      setLocalVllmModel(s.local_vllm_model); setLocalVllmApiKey(s.local_vllm_api_key)
      setResendEnabled(s.resend_enabled || false)
      setResendApiKey(s.resend_api_key || '')
      setLocalAsrEnabled(s.local_asr_enabled); setLocalAsrBaseUrl(s.local_asr_base_url)
      setLocalAsrModel(s.local_asr_model); setLocalAsrApiKey(s.local_asr_api_key)
      if (s.local_vllm_enabled && s.local_vllm_base_url) {
        checkLocalVllmStatusWithParams(s.local_vllm_base_url, s.local_vllm_api_key)
      }
      if (s.local_asr_enabled && s.local_asr_base_url) {
        checkLocalAsrStatusWithParams(s.local_asr_base_url, s.local_asr_api_key, s.local_asr_model)
      }
    } catch (err) { console.error('Failed to load global settings:', err) }
  }, [checkLocalAsrStatusWithParams, checkLocalVllmStatusWithParams])

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
        kaggle_username: kaggleUsername, kaggle_key: kaggleKey,
        exa_api_key: exaApiKey, tavily_api_key: tavilyApiKey,
        local_vllm_enabled: localVllmEnabled, local_vllm_base_url: localVllmBaseUrl,
        local_vllm_model: localVllmModel, local_vllm_api_key: localVllmApiKey,
        local_asr_enabled: localAsrEnabled, local_asr_base_url: localAsrBaseUrl,
        local_asr_model: localAsrModel, local_asr_api_key: localAsrApiKey,
        resend_enabled: resendEnabled, resend_api_key: resendApiKey,
      })
      localStorage.setItem('openrouter_api_key', apiKey)
      localStorage.setItem('openrouter_base_url', baseUrl)
      localStorage.setItem('openrouter_model', model)
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
    <div className="space-y-6 pb-6">
      <form onSubmit={handleAISave} className="space-y-6">
        {/* Remote Services Section */}
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-blue-100 rounded-lg">
              <Cloud className="w-5 h-5 text-blue-600" />
            </div>
            <h2 className="text-lg font-bold text-slate-900">{t('settings.remoteServices')}</h2>
          </div>

          <Card className="border border-slate-200 shadow-sm overflow-hidden">
            <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-slate-100">
              {/* Left Column: LLM Settings (Primary) + Web Search */}
              <div className="flex flex-col divide-y divide-slate-100">
                <div className="p-5 space-y-4 bg-slate-50/30">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-1.5 bg-blue-100 rounded-md">
                      <Server className="w-4 h-4 text-blue-600" />
                    </div>
                    <h3 className="font-semibold text-slate-900">{t('settings.general.llmOpenRouter')}</h3>
                  </div>
                  
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.apiKey')}</Label>
                      <div className="relative">
                        <Input
                          type="password"
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          placeholder="sk-..."
                          className="h-9 text-sm border-slate-300 focus:border-blue-500 focus:ring-blue-500 pr-20"
                        />
                        <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 hover:text-blue-700 font-medium hover:underline">
                            {t('common.getKey')}
                          </a>
                        </div>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.baseUrl')}</Label>
                        <Input
                          value={baseUrl}
                          onChange={(e) => setBaseUrl(e.target.value)}
                          placeholder="https://openrouter.ai/api/v1"
                          className="h-9 font-mono text-xs border-slate-300 focus:border-blue-500 focus:ring-blue-500"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.model')}</Label>
                        <Select
                          value={isCustomMode ? CUSTOM_MODEL_SENTINEL : model}
                          onChange={(val) => {
                            if (val === CUSTOM_MODEL_SENTINEL) {
                              setIsCustomMode(true)
                              if (!isCustomMode) setModel('')
                            } else {
                              setIsCustomMode(false)
                              setModel(val)
                            }
                          }}
                          options={[
                            {
                              group: t('settings.general.multimodalModels'),
                              options: MODEL_OPTIONS.filter(m => m.multimodal && !m.closedSource).map(m => ({ value: m.id, label: m.label })),
                            },
                            {
                              group: t('settings.general.textModels'),
                              options: MODEL_OPTIONS.filter(m => !m.multimodal && !m.closedSource).map(m => ({ value: m.id, label: m.label })),
                            },
                            {
                              group: t('settings.general.closedSourceModels'),
                              options: MODEL_OPTIONS.filter(m => m.closedSource).map(m => ({ value: m.id, label: m.label })),
                            },
                            {
                              group: t('settings.general.customModel'),
                              options: [{ value: CUSTOM_MODEL_SENTINEL, label: `${t('settings.general.customModel')}...` }],
                            },
                          ]}
                        />
                        {isCustomMode && (
                          <Input
                            value={model}
                            onChange={(e) => setModel(e.target.value)}
                            placeholder={t('settings.general.customModelPlaceholder')}
                            className="h-9 font-mono text-xs border-slate-300 focus:border-blue-500 focus:ring-blue-500"
                            autoFocus
                          />
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Web Search */}
                <div className="p-5 space-y-4">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-1.5 bg-indigo-100 rounded-md">
                      <Globe className="w-4 h-4 text-indigo-600" />
                    </div>
                    <div className="flex flex-col">
                      <h3 className="font-semibold text-slate-900">{t('settings.general.webSearchCard')}</h3>
                      <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Deep Research</span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    {/* Exa API Key */}
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.exaApiKey')}</Label>
                      <div className="relative">
                        <Input
                          type="password"
                          value={exaApiKey}
                          onChange={(e) => setExaApiKey(e.target.value)}
                          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                          className="h-9 text-sm border-slate-300 focus:border-indigo-500 focus:ring-indigo-500 pr-16"
                        />
                        <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://exa.ai" target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-600 hover:text-indigo-700 font-medium hover:underline">
                            {t('common.getKey')}
                          </a>
                        </div>
                      </div>
                    </div>

                    {/* Tavily API Key */}
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.tavilyApiKey')}</Label>
                      <div className="relative">
                        <Input
                          type="password"
                          value={tavilyApiKey}
                          onChange={(e) => setTavilyApiKey(e.target.value)}
                          placeholder="tvly-..."
                          className="h-9 text-sm border-slate-300 focus:border-indigo-500 focus:ring-indigo-500 pr-16"
                        />
                        <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://tavily.com" target="_blank" rel="noopener noreferrer" className="text-xs text-indigo-600 hover:text-indigo-700 font-medium hover:underline">
                            {t('common.getKey')}
                          </a>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Column: Other Services (Stacked) */}
              <div className="flex flex-col divide-y divide-slate-100">
                {/* DashScope ASR */}
                <div className="p-5 space-y-4">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-1.5 bg-orange-100 rounded-md">
                      <Mic className="w-4 h-4 text-orange-600" />
                    </div>
                    <h3 className="font-semibold text-slate-900">{t('settings.general.asrDashScope')}</h3>
                  </div>
                  
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.dashscopeApiKey')}</Label>
                      <span className="text-xs text-slate-500">
                        {t('settings.general.forQwen3Asr')}
                      </span>
                    </div>
                    <div className="relative">
                      <Input

                        type="password"
                        value={dashscopeApiKey}
                        onChange={(e) => setDashscopeApiKey(e.target.value)}
                        placeholder="sk-..."
                        className="h-9 text-sm border-slate-300 focus:border-orange-500 focus:ring-orange-500 pr-20"
                      />
                      <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" rel="noopener noreferrer" className="text-xs text-orange-600 hover:text-orange-700 font-medium hover:underline">
                          {t('common.getKey')}
                        </a>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Shared Credentials */}
                <div className="p-5 space-y-4">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-1.5 bg-amber-100 rounded-md">
                      <Key className="w-4 h-4 text-amber-600" />
                    </div>
                    <h3 className="font-semibold text-slate-900">{t('settings.general.sharedCredentials')}</h3>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">HF TOKEN</Label>
                    <div className="relative">
                      <Input
                        type="password"
                        value={huggingfaceToken}
                        onChange={(e) => setHuggingfaceToken(e.target.value)}
                        placeholder="hf_..."
                        className="h-9 text-sm border-slate-300 focus:border-amber-500 focus:ring-amber-500 pr-20"
                      />
                      <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer" className="text-xs text-amber-600 hover:text-amber-700 font-medium hover:underline">
                          {t('common.getToken')}
                        </a>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">KAGGLE USERNAME</Label>
                      <Input
                        value={kaggleUsername}
                        onChange={(e) => setKaggleUsername(e.target.value)}
                        placeholder="your_username"
                        className="h-9 text-sm border-slate-300 focus:border-amber-500 focus:ring-amber-500"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">KAGGLE KEY</Label>
                      <div className="relative">
                        <Input
                          type="password"
                          value={kaggleKey}
                          onChange={(e) => setKaggleKey(e.target.value)}
                          placeholder="xxxxxxxxxxxxxxxx"
                          className="h-9 text-sm border-slate-300 focus:border-amber-500 focus:ring-amber-500 pr-16"
                        />
                        <div className="absolute right-2 top-1/2 -translate-y-1/2">
                          <a href="https://www.kaggle.com/settings" target="_blank" rel="noopener noreferrer" className="text-xs text-amber-600 hover:text-amber-700 font-medium hover:underline">
                            {t('common.getKey')}
                          </a>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="p-5 space-y-4">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <div className="p-1.5 bg-violet-100 rounded-md">
                        <Mail className="w-4 h-4 text-violet-600" />
                      </div>
                      <div className="flex flex-col">
                        <h3 className="font-semibold text-slate-900">{t('settings.general.resendEmailCard')}</h3>
                        <span className="text-[10px] text-slate-500 font-medium uppercase tracking-wide">Resend</span>
                      </div>
                    </div>
                    <ToggleSwitch enabled={resendEnabled} onChange={() => setResendEnabled(!resendEnabled)} />
                  </div>

                  {resendEnabled && (
                    <div className="space-y-3">
                      <div className="space-y-2">
                        <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.resendApiKey')}</Label>
                        <div className="relative">
                          <Input
                            type="password"
                            value={resendApiKey}
                            onChange={(e) => setResendApiKey(e.target.value)}
                            placeholder="re_..."
                            className="h-9 text-sm border-slate-300 focus:border-violet-500 focus:ring-violet-500 pr-20"
                          />
                          <div className="absolute right-2 top-1/2 -translate-y-1/2">
                            <a href="https://resend.com/api-keys" target="_blank" rel="noopener noreferrer" className="text-xs text-violet-600 hover:text-violet-700 font-medium hover:underline">
                              {t('common.getKey')}
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </Card>
        </section>

        {/* Removed Separate Web Search Section, now integrated above */}

        {/* Local Services Section */}
        <section className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-100 rounded-lg">
              <Server className="w-5 h-5 text-emerald-600" />
            </div>
            <h2 className="text-lg font-bold text-slate-900">{t('settings.localServices')}</h2>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Local vLLM Card */}
            <Card className="border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
              <CardHeader className="pb-1 p-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base text-slate-900">
                    <div className="p-1 bg-emerald-100 rounded">
                      <Server className="w-3.5 h-3.5 text-emerald-600" />
                    </div>
                    {t('settings.general.llmVllm')}
                  </CardTitle>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <StatusBadge status={localVllmStatus} />
                    <ToggleSwitch enabled={localVllmEnabled} onChange={() => setLocalVllmEnabled(!localVllmEnabled)} />
                  </div>
                </div>
              </CardHeader>
              {localVllmEnabled && (
                <CardContent className="space-y-2.5 border-t border-slate-100 p-3 pt-2.5">
                  <div className="space-y-1">
                    <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.baseUrl')}</Label>
                    <div className="flex gap-2">
                      <Input
                        value={localVllmBaseUrl}
                        onChange={(e) => setLocalVllmBaseUrl(e.target.value)}
                        placeholder="http://127.0.0.1:8000/v1"
                        className="h-8 font-mono text-xs border-slate-300 focus:border-emerald-500 focus:ring-emerald-500"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={checkLocalVllmStatus}
                        className="h-8 px-2.5 whitespace-nowrap text-xs border-slate-300 text-slate-700 hover:bg-slate-50"
                      >
                        {t('common.test')}
                      </Button>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between items-center">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.model')}</Label>
                      {localVllmDetectedModel && (
                        <span className="text-xs font-mono bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded border border-emerald-200">
                          {localVllmDetectedModel}
                        </span>
                      )}
                    </div>
                    <Input
                      value={localVllmModel}
                      onChange={(e) => setLocalVllmModel(e.target.value)}
                      placeholder={localVllmDetectedModel || 'Qwen/Qwen3.5-Plus-02-15'}
                      className="h-8 text-sm border-slate-300 focus:border-emerald-500 focus:ring-emerald-500"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">
                      {t('settings.general.apiKey')} <span className="text-slate-400 font-normal">({t('common.optional')})</span>
                    </Label>
                    <Input
                      type="password"
                      value={localVllmApiKey}
                      onChange={(e) => setLocalVllmApiKey(e.target.value)}
                      placeholder="token-..."
                      className="h-8 text-sm border-slate-300 focus:border-emerald-500 focus:ring-emerald-500"
                    />
                  </div>
                </CardContent>
              )}
            </Card>

            {/* Local ASR Card */}
            <Card className="border border-slate-200 shadow-sm hover:shadow-md transition-shadow">
              <CardHeader className="pb-1 p-3">
                <div className="flex items-center justify-between gap-2">
                  <CardTitle className="flex items-center gap-2 text-base text-slate-900">
                    <div className="p-1 bg-purple-100 rounded">
                      <Mic className="w-3.5 h-3.5 text-purple-600" />
                    </div>
                    {t('settings.general.asrWebSocket')}
                  </CardTitle>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <StatusBadge status={localAsrStatus} />
                    <ToggleSwitch enabled={localAsrEnabled} onChange={() => setLocalAsrEnabled(!localAsrEnabled)} />
                  </div>
                </div>
              </CardHeader>
              {localAsrEnabled && (
                <CardContent className="space-y-2.5 border-t border-slate-100 p-3 pt-2.5">
                  <div className="space-y-1">
                    <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">WEBSOCKET URL</Label>
                    <div className="flex gap-2">
                      <Input
                        value={localAsrBaseUrl}
                        onChange={(e) => setLocalAsrBaseUrl(e.target.value)}
                        placeholder="ws://127.0.0.1:8001/api-ws/v1/realtime"
                        className="h-8 font-mono text-xs border-slate-300 focus:border-purple-500 focus:ring-purple-500"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={checkLocalAsrStatus}
                        className="h-8 px-2.5 whitespace-nowrap text-xs border-slate-300 text-slate-700 hover:bg-slate-50"
                      >
                        {t('common.test')}
                      </Button>
                    </div>
                    <p className="text-xs text-slate-500">{t('settings.general.webSocketHint')}</p>
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between items-center">
                      <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">{t('settings.general.model')}</Label>
                      {localAsrDetectedModel && (
                        <span className="text-xs font-mono bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded border border-purple-200">
                          {localAsrDetectedModel}
                        </span>
                      )}
                    </div>
                    <Input
                      value={localAsrModel}
                      onChange={(e) => setLocalAsrModel(e.target.value)}
                      placeholder={localAsrDetectedModel || 'Qwen/Qwen3-ASR-1.7B'}
                      className="h-8 text-sm border-slate-300 focus:border-purple-500 focus:ring-purple-500"
                    />
                    <p className="text-xs text-slate-500">{t('settings.general.modelNameHint')}</p>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs text-slate-700 font-semibold uppercase tracking-wide">
                      {t('settings.general.apiKey')} <span className="text-slate-400 font-normal">({t('common.optional')})</span>
                    </Label>
                    <Input
                      type="password"
                      value={localAsrApiKey}
                      onChange={(e) => setLocalAsrApiKey(e.target.value)}
                      placeholder="token-..."
                      className="h-8 text-sm border-slate-300 focus:border-purple-500 focus:ring-purple-500"
                    />
                  </div>
                </CardContent>
              )}
            </Card>
          </div>
        </section>

        {/* Save Action Bar */}
        <div className="flex items-center justify-between p-4 bg-gradient-to-r from-slate-50 to-slate-100 border border-slate-200 rounded-lg sticky bottom-0 shadow-lg">
          <div className="flex items-center gap-2 text-xs text-slate-600 font-medium">
            <Info className="w-4 h-4 flex-shrink-0" />
            <span>{t('common.localServicePriority')}</span>
          </div>
          <div className="flex items-center gap-3">
            {aiSaved && (
              <span className="text-xs text-emerald-600 font-semibold flex items-center gap-1.5 animate-pulse">
                <CheckCircle className="w-4 h-4" />
                {t('common.savedSuccess')}
              </span>
            )}
            <button
              type="submit"
              disabled={aiSaving}
              className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-xs font-semibold rounded-lg hover:from-blue-700 hover:to-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {aiSaving ? t('common.savingText') : t('common.saveSettings')}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

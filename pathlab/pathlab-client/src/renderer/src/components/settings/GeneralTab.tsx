import { Cloud, Server, Key, Info, CheckCircle, Mic } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

export interface GeneralTabProps {
  // Remote LLM Settings (OpenRouter)
  apiKey: string
  baseUrl: string
  model: string
  huggingfaceToken: string
  dashscopeApiKey: string
  // Local LLM Settings (vLLM)
  localVllmEnabled: boolean
  localVllmBaseUrl: string
  localVllmModel: string
  localVllmApiKey: string
  localVllmStatus: 'checking' | 'online' | 'offline'
  localVllmDetectedModel: string | null
  // Local ASR Settings
  localAsrEnabled: boolean
  localAsrBaseUrl: string
  localAsrModel: string
  localAsrApiKey: string
  localAsrStatus: 'checking' | 'online' | 'offline'
  localAsrDetectedModel: string | null
  // Save state
  aiSaving: boolean
  aiSaved: boolean
  // LLM Callbacks
  onApiKeyChange: (value: string) => void
  onBaseUrlChange: (value: string) => void
  onModelChange: (value: string) => void
  onHuggingfaceTokenChange: (value: string) => void
  onDashscopeApiKeyChange: (value: string) => void
  onLocalVllmEnabledChange: (value: boolean) => void
  onLocalVllmBaseUrlChange: (value: string) => void
  onLocalVllmModelChange: (value: string) => void
  onLocalVllmApiKeyChange: (value: string) => void
  onCheckLocalVllmStatus: () => void
  // ASR Callbacks
  onLocalAsrEnabledChange: (value: boolean) => void
  onLocalAsrBaseUrlChange: (value: string) => void
  onLocalAsrModelChange: (value: string) => void
  onLocalAsrApiKeyChange: (value: string) => void
  onCheckLocalAsrStatus: () => void
  onSave: (e: React.FormEvent) => void
}

export function GeneralTab({
  apiKey, baseUrl, model, huggingfaceToken, dashscopeApiKey,
  localVllmEnabled, localVllmBaseUrl, localVllmModel, localVllmApiKey,
  localVllmStatus, localVllmDetectedModel,
  localAsrEnabled, localAsrBaseUrl, localAsrModel, localAsrApiKey,
  localAsrStatus, localAsrDetectedModel,
  aiSaving, aiSaved,
  onApiKeyChange, onBaseUrlChange, onModelChange, onHuggingfaceTokenChange, onDashscopeApiKeyChange,
  onLocalVllmEnabledChange, onLocalVllmBaseUrlChange, onLocalVllmModelChange, onLocalVllmApiKeyChange,
  onCheckLocalVllmStatus,
  onLocalAsrEnabledChange, onLocalAsrBaseUrlChange, onLocalAsrModelChange, onLocalAsrApiKeyChange,
  onCheckLocalAsrStatus,
  onSave
}: GeneralTabProps) {
  return (
    <div className="space-y-6">
      <form onSubmit={onSave} className="space-y-6">
        {/* Stacked Layout: Remote Services then Local Services */}
        <div className="space-y-8">
          {/* Remote Services Section */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-700 flex items-center">
              <Cloud className="w-5 h-5 mr-2 text-blue-600" />
              Remote Services
            </h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
              {/* Left Column: Remote LLM Settings (OpenRouter) */}
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <CardTitle className="flex items-center text-base">
                    <Server className="w-4 h-4 mr-2 text-primary-600" />
                    LLM (OpenRouter)
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <Label>API Key</Label>
                    <Input type="password" value={apiKey} onChange={(e) => onApiKeyChange(e.target.value)} placeholder="sk-..." />
                    <p className="text-xs text-gray-500">
                      <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">Get Key</a>
                    </p>
                  </div>
                  <div className="space-y-2">
                    <Label>Base URL</Label>
                    <Input value={baseUrl} onChange={(e) => onBaseUrlChange(e.target.value)} placeholder="https://openrouter.ai/api/v1" className="font-mono text-sm" />
                  </div>
                  <div className="space-y-2">
                    <Label>Model</Label>
                    <select
                      value={model}
                      onChange={(e) => onModelChange(e.target.value)}
                      className="flex h-9 w-full rounded-lg border border-gray-200 bg-white px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-gray-950"
                    >
                      <optgroup label="Multimodal Models">
                        <option value="qwen/qwen3-vl-235b-a22b-instruct">Qwen3-VL-235B-A22B-Instruct</option>
                        <option value="qwen/qwen3-vl-235b-a22b-thinking">Qwen3-VL-235B-A22B-Thinking</option>
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

              {/* Right Column: Remote ASR + Shared Credentials */}
              <div className="space-y-6">
                {/* Remote ASR Settings (DashScope) */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center text-base">
                      <Mic className="w-4 h-4 mr-2 text-orange-600" />
                      ASR (DashScope)
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="space-y-2">
                      <Label>DashScope API Key</Label>
                      <Input type="password" value={dashscopeApiKey} onChange={(e) => onDashscopeApiKeyChange(e.target.value)} placeholder="sk-..." />
                      <p className="text-xs text-gray-500">
                        For Qwen3-ASR realtime. <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" className="text-primary-600 hover:underline">Get Key</a>
                      </p>
                    </div>
                  </CardContent>
                </Card>

                {/* Shared Service Credentials */}
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="flex items-center text-base">
                      <Key className="w-4 h-4 mr-2 text-amber-600" />
                      Shared Credentials
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      <Label>HuggingFace Token</Label>
                      <Input type="password" value={huggingfaceToken} onChange={(e) => onHuggingfaceTokenChange(e.target.value)} placeholder="hf_..." />
                      <p className="text-xs text-gray-500">
                        For downloading gated models. <a href="https://huggingface.co/settings/tokens" target="_blank" className="text-primary-600 hover:underline">Get Token</a>
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
              Local Services
            </h2>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Local LLM Settings */}
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="flex items-center text-base">
                      <Server className="w-4 h-4 mr-2 text-green-600" />
                      LLM (vLLM)
                    </CardTitle>
                    <div className="flex items-center space-x-3">
                      <div className={`flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${localVllmStatus === 'online' ? 'bg-green-50 text-green-700 border-green-200' :
                        localVllmStatus === 'checking' ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                          'bg-gray-100 text-gray-600 border-gray-200'
                        }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${localVllmStatus === 'online' ? 'bg-green-500' : localVllmStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'}`} />
                        <span>{localVllmStatus === 'online' ? 'Online' : localVllmStatus === 'checking' ? '...' : 'Offline'}</span>
                      </div>
                      <div
                        className={`w-10 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-300 ${localVllmEnabled ? 'bg-green-600' : 'bg-gray-200'}`}
                        onClick={() => onLocalVllmEnabledChange(!localVllmEnabled)}
                      >
                        <div className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-300 ${localVllmEnabled ? 'translate-x-5' : ''}`} />
                      </div>
                    </div>
                  </div>
                </CardHeader>
                {localVllmEnabled && (
                  <CardContent className="pt-2 space-y-4">
                    <div className="space-y-2">
                      <Label>Base URL</Label>
                      <div className="flex gap-2">
                        <Input value={localVllmBaseUrl} onChange={(e) => onLocalVllmBaseUrlChange(e.target.value)} placeholder="http://127.0.0.1:8000/v1" className="font-mono text-sm" />
                        <Button type="button" variant="outline" size="sm" onClick={onCheckLocalVllmStatus} className="bg-white whitespace-nowrap">
                          Test
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <Label>Model</Label>
                        {localVllmDetectedModel && (
                          <span className="text-xs font-mono bg-green-100 text-green-800 px-1.5 py-0.5 rounded">
                            {localVllmDetectedModel}
                          </span>
                        )}
                      </div>
                      <Input value={localVllmModel} onChange={(e) => onLocalVllmModelChange(e.target.value)} placeholder={localVllmDetectedModel || "Qwen/Qwen3-ASR-1.7B"} />
                    </div>
                    <div className="space-y-2">
                      <Label>API Key <span className="text-gray-400 font-normal">(Optional)</span></Label>
                      <Input type="password" value={localVllmApiKey} onChange={(e) => onLocalVllmApiKeyChange(e.target.value)} placeholder="token-..." />
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
                      ASR (vLLM)
                    </CardTitle>
                    <div className="flex items-center space-x-3">
                      <div className={`flex items-center space-x-1.5 px-2 py-0.5 rounded-full text-xs font-medium border ${localAsrStatus === 'online' ? 'bg-green-50 text-green-700 border-green-200' :
                        localAsrStatus === 'checking' ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                          'bg-gray-100 text-gray-600 border-gray-200'
                        }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${localAsrStatus === 'online' ? 'bg-green-500' : localAsrStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'}`} />
                        <span>{localAsrStatus === 'online' ? 'Online' : localAsrStatus === 'checking' ? '...' : 'Offline'}</span>
                      </div>
                      <div
                        className={`w-10 h-5 flex items-center rounded-full p-0.5 cursor-pointer transition-colors duration-300 ${localAsrEnabled ? 'bg-purple-600' : 'bg-gray-200'}`}
                        onClick={() => onLocalAsrEnabledChange(!localAsrEnabled)}
                      >
                        <div className={`bg-white w-4 h-4 rounded-full shadow-sm transform transition-transform duration-300 ${localAsrEnabled ? 'translate-x-5' : ''}`} />
                      </div>
                    </div>
                  </div>
                </CardHeader>
                {localAsrEnabled && (
                  <CardContent className="pt-2 space-y-4">
                    <div className="space-y-2">
                      <Label>Base URL</Label>
                      <div className="flex gap-2">
                        <Input value={localAsrBaseUrl} onChange={(e) => onLocalAsrBaseUrlChange(e.target.value)} placeholder="http://127.0.0.1:8001/v1" className="font-mono text-sm" />
                        <Button type="button" variant="outline" size="sm" onClick={onCheckLocalAsrStatus} className="bg-white whitespace-nowrap">
                          Test
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <Label>Model</Label>
                        {localAsrDetectedModel && (
                          <span className="text-xs font-mono bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">
                            {localAsrDetectedModel}
                          </span>
                        )}
                      </div>
                      <Input value={localAsrModel} onChange={(e) => onLocalAsrModelChange(e.target.value)} placeholder={localAsrDetectedModel || "Qwen/Qwen3-ASR-1.7B"} />
                    </div>
                    <div className="space-y-2">
                      <Label>API Key <span className="text-gray-400 font-normal">(Optional)</span></Label>
                      <Input type="password" value={localAsrApiKey} onChange={(e) => onLocalAsrApiKeyChange(e.target.value)} placeholder="token-..." />
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
            <span>Local services have priority. Falls back to remote if unavailable.</span>
          </div>
          <div className="flex items-center space-x-3">
            {aiSaved && (
              <span className="text-sm text-green-600 flex items-center">
                <CheckCircle className="w-5 h-5 mr-1" />
                Saved!
              </span>
            )}
            <button
              type="submit"
              disabled={aiSaving}
              className="px-4 py-2 bg-gradient-to-r from-primary-600 to-primary-700 text-white text-sm font-medium rounded-lg hover:from-primary-700 hover:to-primary-800 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2 transition-all shadow-sm disabled:opacity-50"
            >
              {aiSaving ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}

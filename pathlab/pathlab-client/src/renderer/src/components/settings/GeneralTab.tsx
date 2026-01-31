import { Cloud, Server, Key, Info, CheckCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

export interface GeneralTabProps {
  // Remote Model Settings
  apiKey: string
  baseUrl: string
  model: string
  huggingfaceToken: string
  dashscopeApiKey: string
  // Local vLLM Settings
  localVllmEnabled: boolean
  localVllmBaseUrl: string
  localVllmModel: string
  localVllmApiKey: string
  localVllmStatus: 'checking' | 'online' | 'offline'
  localVllmDetectedModel: string | null
  // Save state
  aiSaving: boolean
  aiSaved: boolean
  // Callbacks
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
  onSave: (e: React.FormEvent) => void
}

export function GeneralTab({
  apiKey, baseUrl, model, huggingfaceToken, dashscopeApiKey,
  localVllmEnabled, localVllmBaseUrl, localVllmModel, localVllmApiKey,
  localVllmStatus, localVllmDetectedModel,
  aiSaving, aiSaved,
  onApiKeyChange, onBaseUrlChange, onModelChange, onHuggingfaceTokenChange, onDashscopeApiKeyChange,
  onLocalVllmEnabledChange, onLocalVllmBaseUrlChange, onLocalVllmModelChange, onLocalVllmApiKeyChange,
  onCheckLocalVllmStatus, onSave
}: GeneralTabProps) {
  return (
    <div className="space-y-6">
      <form onSubmit={onSave} className="space-y-6">
        {/* Remote Model Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center text-lg">
              <Cloud className="w-5 h-5 mr-2 text-primary-600" />
              Remote Model Settings
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-2">
                <Label>OpenRouter API Key</Label>
                <Input type="password" value={apiKey} onChange={(e) => onApiKeyChange(e.target.value)} placeholder="sk-..." />
                <p className="text-xs text-gray-500">
                  Get key from <a href="https://openrouter.ai/keys" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:underline">OpenRouter Console</a>
                </p>
              </div>
              <div className="space-y-2">
                <Label>Base URL</Label>
                <Input value={baseUrl} onChange={(e) => onBaseUrlChange(e.target.value)} placeholder="https://openrouter.ai/api/v1" />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Model</Label>
              <select
                value={model}
                onChange={(e) => onModelChange(e.target.value)}
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
                <div className={`flex items-center space-x-2 px-3 py-1 rounded-full text-sm font-medium border ${
                  localVllmStatus === 'online' ? 'bg-green-50 text-green-700 border-green-200' :
                  localVllmStatus === 'checking' ? 'bg-yellow-50 text-yellow-700 border-yellow-200' :
                  'bg-gray-100 text-gray-600 border-gray-200'
                }`}>
                  <div className={`w-2 h-2 rounded-full ${localVllmStatus === 'online' ? 'bg-green-500' : localVllmStatus === 'checking' ? 'bg-yellow-500' : 'bg-gray-400'}`} />
                  <span>{localVllmStatus === 'online' ? 'Online' : localVllmStatus === 'checking' ? 'Checking...' : 'Offline'}</span>
                </div>
                <div className="flex items-center space-x-3">
                  <Label htmlFor="local-vllm-toggle" className="text-sm font-medium cursor-pointer select-none" onClick={() => onLocalVllmEnabledChange(!localVllmEnabled)}>
                    Enable
                  </Label>
                  <div
                    id="local-vllm-toggle"
                    className={`w-11 h-6 flex items-center rounded-full p-1 cursor-pointer transition-colors duration-300 ${localVllmEnabled ? 'bg-primary-600' : 'bg-gray-200'}`}
                    onClick={() => onLocalVllmEnabledChange(!localVllmEnabled)}
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
                    <Input value={localVllmBaseUrl} onChange={(e) => onLocalVllmBaseUrlChange(e.target.value)} placeholder="http://127.0.0.1:8000/v1" className="font-mono text-sm" />
                    <Button type="button" variant="outline" onClick={onCheckLocalVllmStatus} className="bg-white">
                      Test Connection
                    </Button>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <Label>Model Name</Label>
                      {localVllmDetectedModel && (
                        <span className="text-xs font-mono bg-primary-100 text-primary-800 px-2 py-0.5 rounded">
                          Detected: {localVllmDetectedModel}
                        </span>
                      )}
                    </div>
                    <Input value={localVllmModel} onChange={(e) => onLocalVllmModelChange(e.target.value)} placeholder={localVllmDetectedModel || "Qwen/Qwen2.5-VL-7B-Instruct"} />
                    <p className="text-xs text-gray-500">Leave empty to use auto-detected model</p>
                  </div>
                  <div className="space-y-2">
                    <Label>API Key <span className="text-gray-400 font-normal ml-2">(Optional)</span></Label>
                    <Input type="password" value={localVllmApiKey} onChange={(e) => onLocalVllmApiKeyChange(e.target.value)} placeholder="token-..." />
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
                <Input type="password" value={huggingfaceToken} onChange={(e) => onHuggingfaceTokenChange(e.target.value)} placeholder="hf_..." />
                <p className="text-xs text-gray-500">
                  For downloading gated models. <a href="https://huggingface.co/settings/tokens" target="_blank" className="text-primary-600 hover:underline">Get Token</a>
                </p>
              </div>
              <div className="space-y-2">
                <Label>DashScope API Key</Label>
                <Input type="password" value={dashscopeApiKey} onChange={(e) => onDashscopeApiKeyChange(e.target.value)} placeholder="sk-..." />
                <p className="text-xs text-gray-500">
                  For Qwen3-ASR voice. <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank" className="text-primary-600 hover:underline">Get Key</a>
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
          <div className="flex items-center space-x-3">
            {aiSaved && (
              <span className="text-sm text-green-600 flex items-center">
                <CheckCircle className="w-5 h-5 mr-1" />
                Settings saved!
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

export interface ModelOption {
  id: string
  label: string
  multimodal: boolean
  closedSource?: boolean
}

export const MODEL_OPTIONS: ModelOption[] = [
  { id: 'qwen/qwen3.6-plus:free', label: 'Qwen3.6-Plus', multimodal: true },
  { id: 'qwen/qwen3.5-plus-02-15', label: 'Qwen3.5-Plus-02-15', multimodal: true },
  { id: 'moonshotai/kimi-k2.5', label: 'Kimi-K2.5', multimodal: true },
  { id: 'openai/gpt-5.3-codex', label: 'GPT-5.3-Codex', multimodal: true, closedSource: true },
  { id: 'anthropic/claude-sonnet-4-6', label: 'Claude Sonnet 4.6', multimodal: true, closedSource: true },
  { id: 'z-ai/glm-5.1', label: 'GLM-5.1', multimodal: false },
  { id: 'qwen/qwen3-235b-a22b-instruct-2507', label: 'Qwen3-235B-A22B-Instruct-2507', multimodal: false },
  { id: 'stepfun/step-3.5-flash:free', label: 'Step-3.5-Flash', multimodal: false },
  { id: 'minimax/minimax-m2.7', label: 'Minimax-M2.7', multimodal: false },
  { id: 'xiaomi/mimo-v2-pro', label: 'MIMO-V2-Pro', multimodal: false },
]

export const CUSTOM_MODEL_SENTINEL = '__custom__'

export const MULTIMODAL_MODELS = new Set(
  MODEL_OPTIONS.filter(model => model.multimodal).map(model => model.id)
)

export function isCustomModelId(id: string): boolean {
  return !!id && id !== CUSTOM_MODEL_SENTINEL && !MODEL_OPTIONS.some(model => model.id === id)
}

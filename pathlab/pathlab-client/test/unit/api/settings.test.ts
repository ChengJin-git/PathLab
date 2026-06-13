import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  getPublicSettings,
  getGlobalSettings,
  updateGlobalSettings,
  type GlobalSettings,
  type PublicSettings,
} from '@renderer/api/settings'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_PUBLIC_SETTINGS: PublicSettings = {
  turnstile_enabled: true,
  turnstile_site_key: 'site_key_abc',
}

const MOCK_GLOBAL_SETTINGS: GlobalSettings = {
  openrouter_api_key: 'sk-or-test',
  openrouter_base_url: 'https://openrouter.ai/api/v1',
  openrouter_model: 'qwen/qwen3-plus',
  huggingface_token: 'hf_test_token',
  dashscope_api_key: 'ds_test_key',
  exa_api_key: 'exa_test_key',
  local_vllm_enabled: false,
  local_vllm_base_url: 'http://localhost:8000/v1',
  local_vllm_model: 'Qwen/Qwen2.5-7B-Instruct',
  local_vllm_api_key: '',
  local_asr_enabled: false,
  local_asr_base_url: 'http://localhost:8001/v1',
  local_asr_model: 'whisper-1',
  local_asr_api_key: '',
  turnstile_enabled: true,
  turnstile_site_key: 'site_key_abc',
  turnstile_secret_key: 'secret_key_xyz',
  resend_enabled: false,
  resend_api_key: '',
  email_templates: {
    new_user_registration_notice: { subject: 'Welcome', html: '<p>Welcome</p>' },
    account_activated: { subject: 'Account Activated', html: '<p>Activated</p>' },
    task_completed_notice: { subject: 'Task Completed', html: '<p>Done</p>' },
    admin_new_user_registration_notice: { subject: 'New User', html: '<p>New user registered</p>' },
  },
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('getPublicSettings', () => {
  it('fetches from GET /settings/public without auth', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_PUBLIC_SETTINGS))
    await getPublicSettings()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/settings/public')
    expect(new Headers(opts?.headers as HeadersInit).get('Authorization')).toBeNull()
  })

  it('returns turnstile config', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_PUBLIC_SETTINGS))
    const result = await getPublicSettings()
    expect(result.turnstile_enabled).toBe(true)
    expect(result.turnstile_site_key).toBe('site_key_abc')
  })

  it('throws on API error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Service unavailable' }, 503))
    await expect(getPublicSettings()).rejects.toMatchObject({ status: 503 })
  })
})

describe('getGlobalSettings', () => {
  it('fetches from GET /settings with auth', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_GLOBAL_SETTINGS))
    await getGlobalSettings()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/settings')
    expect(String(url)).not.toContain('/settings/public')
  })

  it('returns all AI model provider fields', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_GLOBAL_SETTINGS))
    const result = await getGlobalSettings()
    expect(result.openrouter_api_key).toBe('sk-or-test')
    expect(result.openrouter_base_url).toBe('https://openrouter.ai/api/v1')
    expect(result.openrouter_model).toBe('qwen/qwen3-plus')
    expect(result.huggingface_token).toBe('hf_test_token')
    expect(result.dashscope_api_key).toBe('ds_test_key')
    expect(result.exa_api_key).toBe('exa_test_key')
  })

  it('returns local vLLM configuration', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_GLOBAL_SETTINGS))
    const result = await getGlobalSettings()
    expect(result.local_vllm_enabled).toBe(false)
    expect(result.local_vllm_base_url).toBe('http://localhost:8000/v1')
    expect(result.local_vllm_model).toBe('Qwen/Qwen2.5-7B-Instruct')
    expect(result.local_vllm_api_key).toBe('')
  })

  it('returns local ASR configuration', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_GLOBAL_SETTINGS))
    const result = await getGlobalSettings()
    expect(result.local_asr_enabled).toBe(false)
    expect(result.local_asr_base_url).toBe('http://localhost:8001/v1')
    expect(result.local_asr_model).toBe('whisper-1')
  })

  it('throws 403 when non-admin accesses settings', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Forbidden' }, 403))
    await expect(getGlobalSettings()).rejects.toMatchObject({ status: 403, code: 'AUTH_ERROR' })
  })
})

describe('updateGlobalSettings', () => {
  it('sends POST to /settings with partial update', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_GLOBAL_SETTINGS, openrouter_model: 'anthropic/claude-3.5-sonnet' }))
    await updateGlobalSettings({ openrouter_model: 'anthropic/claude-3.5-sonnet' })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/settings')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.openrouter_model).toBe('anthropic/claude-3.5-sonnet')
  })

  it('updates OpenRouter model only', async () => {
    const updated = { ...MOCK_GLOBAL_SETTINGS, openrouter_model: 'google/gemini-2.5-flash' }
    mockFetch.mockResolvedValueOnce(ok(updated))
    const result = await updateGlobalSettings({ openrouter_model: 'google/gemini-2.5-flash' })
    expect(result.openrouter_model).toBe('google/gemini-2.5-flash')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(Object.keys(body)).toEqual(['openrouter_model'])
  })

  it('enables local vLLM with base URL and model', async () => {
    const updated = { ...MOCK_GLOBAL_SETTINGS, local_vllm_enabled: true, local_vllm_model: 'mistral-7b' }
    mockFetch.mockResolvedValueOnce(ok(updated))
    await updateGlobalSettings({ local_vllm_enabled: true, local_vllm_model: 'mistral-7b' })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.local_vllm_enabled).toBe(true)
    expect(body.local_vllm_model).toBe('mistral-7b')
  })

  it('enables local ASR', async () => {
    const updated = { ...MOCK_GLOBAL_SETTINGS, local_asr_enabled: true }
    mockFetch.mockResolvedValueOnce(ok(updated))
    await updateGlobalSettings({ local_asr_enabled: true })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.local_asr_enabled).toBe(true)
  })

  it('updates HuggingFace token', async () => {
    const updated = { ...MOCK_GLOBAL_SETTINGS, huggingface_token: 'hf_new_token' }
    mockFetch.mockResolvedValueOnce(ok(updated))
    await updateGlobalSettings({ huggingface_token: 'hf_new_token' })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.huggingface_token).toBe('hf_new_token')
  })

  it('throws on error', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Validation error' }, 422))
    await expect(updateGlobalSettings({ openrouter_model: '' })).rejects.toMatchObject({ status: 422 })
  })
})

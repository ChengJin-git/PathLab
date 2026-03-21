import { API_BASE } from '../config'
import { apiFetch } from './client'

// ========== Global Settings API ==========

export interface EmailTemplateItem {
  subject: string
  html: string
}

export interface EmailTemplatesConfig {
  new_user_registration_notice: EmailTemplateItem
  account_activated: EmailTemplateItem
  task_completed_notice: EmailTemplateItem
  admin_new_user_registration_notice: EmailTemplateItem
}

/**
 * Global settings interface
 */
export interface GlobalSettings {
  openrouter_api_key: string
  openrouter_base_url: string
  openrouter_model: string
  huggingface_token: string
  dashscope_api_key: string
  // Exa Search API key for web search functionality
  exa_api_key: string
  // Local vLLM settings (OpenAI-compatible server for LLM)
  local_vllm_enabled: boolean
  local_vllm_base_url: string
  local_vllm_model: string
  local_vllm_api_key: string
  // Local ASR settings (OpenAI-compatible server for ASR)
  local_asr_enabled: boolean
  local_asr_base_url: string
  local_asr_model: string
  local_asr_api_key: string
  // Cloudflare Turnstile settings
  turnstile_enabled: boolean
  turnstile_site_key: string
  turnstile_secret_key: string
  resend_enabled: boolean
  resend_api_key: string
  resend_admin_email: string
  email_templates: EmailTemplatesConfig
}

/**
 * Public settings interface (no authentication required)
 */
export interface PublicSettings {
  turnstile_enabled: boolean
  turnstile_site_key: string
}

/**
 * Get public settings (no authentication required)
 * @returns Public settings including Turnstile configuration
 */
export async function getPublicSettings(): Promise<PublicSettings> {
  return apiFetch<PublicSettings>(
    `${API_BASE}/settings/public`,
    undefined,
    'Failed to get public settings',
    true  // skipAuth - this endpoint doesn't require authentication
  )
}

/**
 * Get global settings
 * @returns Global settings
 * @throws {ApiError} If the request fails
 */
export async function getGlobalSettings(): Promise<GlobalSettings> {
  return apiFetch<GlobalSettings>(
    `${API_BASE}/settings`,
    undefined,
    'Failed to get global settings'
  )
}

/**
 * Update global settings (admin only)
 * @param settings - Settings to update (only provided fields will be updated)
 * @returns Updated global settings
 * @throws {ApiError} If the request fails
 */
export async function updateGlobalSettings(
  settings: Partial<GlobalSettings>
): Promise<GlobalSettings> {
  return apiFetch<GlobalSettings>(
    `${API_BASE}/settings`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    },
    'Failed to update global settings'
  )
}

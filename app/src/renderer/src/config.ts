/**
 * API configuration for the PathLab web client.
 *
 * Service URLs come from Vite environment variables (VITE_API_BASE,
 * VITE_PREPROCESSING_BASE, VITE_AI_BASE) or default to the page host with the
 * standard ports 6100 (Gateway), 6101 (Preprocessing) and 6102 (AI).
 */

// Get hostname safely
function getHostname(): string {
  try {
    return window.location?.hostname || '127.0.0.1'
  } catch {
    return '127.0.0.1'
  }
}

const hostname = getHostname()

// Default fixed ports for debug mode
const DEFAULT_GATEWAY_PORT = 6100
const DEFAULT_PREPROCESSING_PORT = 6101
const DEFAULT_AI_PORT = 6102

/** Kept for callers that initialise configuration at start-up; URLs are static. */
export async function initializeApiConfig(): Promise<void> {}

/**
 * Get the current API base URL
 * Priority: environment variable > default
 */
export function getApiBase(): string {
  // Environment variable takes precedence
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE
  }

  // Default fallback (debug mode uses fixed ports)
  return `http://${hostname}:${DEFAULT_GATEWAY_PORT}`
}

/**
 * Get the Preprocessing service URL
 */
export function getPreprocessingBase(): string {
  if (import.meta.env.VITE_PREPROCESSING_BASE) {
    return import.meta.env.VITE_PREPROCESSING_BASE
  }

  return `http://${hostname}:${DEFAULT_PREPROCESSING_PORT}`
}

/**
 * Get the AI service URL
 */
export function getAiBase(): string {
  if (import.meta.env.VITE_AI_BASE) {
    return import.meta.env.VITE_AI_BASE
  }

  return `http://${hostname}:${DEFAULT_AI_PORT}/api/ai`
}

// Exported URLs; updateApiBase() recomputes them from the environment
export let API_BASE = import.meta.env.VITE_API_BASE || `http://${hostname}:${DEFAULT_GATEWAY_PORT}`
export let PREPROCESSING_BASE = import.meta.env.VITE_PREPROCESSING_BASE || `http://${hostname}:${DEFAULT_PREPROCESSING_PORT}`
export let AI_BASE = import.meta.env.VITE_AI_BASE || `http://${hostname}:${DEFAULT_AI_PORT}/api/ai`

/**
 * Recompute the API base URLs
 */
export function updateApiBase(): void {
  API_BASE = getApiBase()
  PREPROCESSING_BASE = getPreprocessingBase()
  AI_BASE = getAiBase()
}

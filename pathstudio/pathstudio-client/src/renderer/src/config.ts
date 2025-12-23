/**
 * API Configuration for PathStudio Client
 *
 * Supports both static configuration (via environment variables) and
 * dynamic port discovery (via Electron IPC).
 */

// Electron API interface for backend discovery
interface ElectronBackendApi {
  getGatewayPort: () => Promise<number | null>
  onGatewayPort: (callback: (port: number) => void) => () => void
}

interface ElectronApi {
  backend?: ElectronBackendApi
}

// Get hostname safely
function getHostname(): string {
  try {
    return window.location?.hostname || '127.0.0.1'
  } catch {
    return '127.0.0.1'
  }
}

// Get window.api safely
function getElectronApi(): ElectronApi | undefined {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (window as any).api as ElectronApi | undefined
  } catch {
    return undefined
  }
}

const hostname = getHostname()

// Mutable API configuration object
// This allows dynamic updates when port is discovered
const apiConfig = {
  gatewayPort: null as number | null,
  initialized: false
}

/**
 * Initialize dynamic port discovery from Electron
 * Call this early in the app lifecycle
 */
export async function initializeApiConfig(): Promise<void> {
  if (apiConfig.initialized) return

  const electronApi = getElectronApi()
  if (electronApi?.backend) {
    // Get initial port
    const port = await electronApi.backend.getGatewayPort()
    if (port) {
      apiConfig.gatewayPort = port
      console.log('[Config] Gateway port initialized:', port)
    }

    // Listen for port updates
    electronApi.backend.onGatewayPort((port) => {
      apiConfig.gatewayPort = port
      console.log('[Config] Gateway port updated:', port)
    })
  }

  apiConfig.initialized = true
}

/**
 * Get the current API base URL
 * Priority: Environment variable > Dynamic port > Default
 */
export function getApiBase(): string {
  // Environment variable takes precedence (for production/custom deployments)
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE
  }

  // Dynamic port from Electron
  if (apiConfig.gatewayPort) {
    return `http://127.0.0.1:${apiConfig.gatewayPort}`
  }

  // Default fallback
  return `http://${hostname}:6100`
}

// Getter property for backward compatibility
// Uses Object.defineProperty to make it dynamic
export let API_BASE = import.meta.env.VITE_API_BASE || `http://${hostname}:6100`

// Update API_BASE when port is discovered
// This is a workaround since we can't use Object.defineProperty on module exports
export function updateApiBase(): void {
  API_BASE = getApiBase()
}

// These are less critical as Gateway proxies most requests
export const AI_BASE = import.meta.env.VITE_AI_BASE || `http://${hostname}:6102/api/ai`
export const PREPROCESSING_BASE = import.meta.env.VITE_PREPROCESSING_BASE || `http://${hostname}:6101`

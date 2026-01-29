/**
 * API Configuration for PathLab Client
 *
 * Supports both static configuration (via environment variables) and
 * dynamic port discovery (via Electron IPC).
 *
 * Modes:
 * - Debug mode (VITE_DEBUG=true): Use fixed ports 6100, 6101, 6102
 * - Electron mode: Discover ports via IPC from main process
 * - Browser mode: Use default ports or environment variables
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

// Check if we're in debug mode
const isDebugMode = import.meta.env.VITE_DEBUG === 'true' || import.meta.env.DEV

// Default fixed ports for debug mode
const DEFAULT_GATEWAY_PORT = 6100
const DEFAULT_PREPROCESSING_PORT = 6101
const DEFAULT_AI_PORT = 6102

// Mutable API configuration object
// This allows dynamic updates when ports are discovered
const apiConfig = {
  gatewayPort: null as number | null,
  preprocessingPort: null as number | null,
  aiPort: null as number | null,
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
      // Update exports
      updateApiBase()
    })
  }

  apiConfig.initialized = true
}

/**
 * Get the current API base URL
 * Priority: Environment variable > Dynamic port > Default
 */
export function getApiBase(): string {
  // Environment variable takes precedence
  if (import.meta.env.VITE_API_BASE) {
    return import.meta.env.VITE_API_BASE
  }

  // Dynamic port from Electron
  if (apiConfig.gatewayPort) {
    return `http://127.0.0.1:${apiConfig.gatewayPort}`
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

  if (apiConfig.preprocessingPort) {
    return `http://127.0.0.1:${apiConfig.preprocessingPort}`
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

  if (apiConfig.aiPort) {
    return `http://127.0.0.1:${apiConfig.aiPort}/api/ai`
  }

  return `http://${hostname}:${DEFAULT_AI_PORT}/api/ai`
}

// Export mutable URLs - updated when ports are discovered
export let API_BASE = import.meta.env.VITE_API_BASE || `http://${hostname}:${DEFAULT_GATEWAY_PORT}`
export let PREPROCESSING_BASE = import.meta.env.VITE_PREPROCESSING_BASE || `http://${hostname}:${DEFAULT_PREPROCESSING_PORT}`
export let AI_BASE = import.meta.env.VITE_AI_BASE || `http://${hostname}:${DEFAULT_AI_PORT}/api/ai`

/**
 * Update all API base URLs when ports are discovered
 */
export function updateApiBase(): void {
  API_BASE = getApiBase()
  PREPROCESSING_BASE = getPreprocessingBase()
  AI_BASE = getAiBase()
}

// Log configuration in debug mode
// if (isDebugMode) {
//   console.log('[Config] Debug mode enabled - using fixed ports')
//   console.log('[Config] Gateway:', API_BASE)
//   console.log('[Config] Preprocessing:', PREPROCESSING_BASE)
//   console.log('[Config] AI:', AI_BASE)
// }

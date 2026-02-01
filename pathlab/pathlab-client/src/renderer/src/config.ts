/**
 * API Configuration for PathLab Client
 *
 * Supports both static configuration (via environment variables) and
 * dynamic port discovery (via Electron IPC).
 *
 * Modes:
 * - Debug mode (VITE_DEBUG=true): Use fixed ports 5100, 5101, 5102
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
// Note: These should match the ports set in start_all_yihui.sh
const DEFAULT_GATEWAY_PORT = 5100
const DEFAULT_PREPROCESSING_PORT = 5101
const DEFAULT_AI_PORT = 5102

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
    try {
      // Get initial port
      const port = await electronApi.backend.getGatewayPort()
      if (port) {
        apiConfig.gatewayPort = port
        console.log('[Config] Gateway port initialized:', port)
      } else {
        // If port discovery failed, use default port
        console.log('[Config] Port discovery returned null, using default port:', DEFAULT_GATEWAY_PORT)
        apiConfig.gatewayPort = DEFAULT_GATEWAY_PORT
      }

      // Listen for port updates
      electronApi.backend.onGatewayPort((port) => {
        apiConfig.gatewayPort = port
        console.log('[Config] Gateway port updated:', port)
        // Update exports
        updateApiBase()
      })
    } catch (error) {
      console.warn('[Config] Failed to get gateway port from Electron, using default:', error)
      apiConfig.gatewayPort = DEFAULT_GATEWAY_PORT
    }
  } else {
    // Not in Electron or backend API not available, use default
    console.log('[Config] Not in Electron mode, using default port:', DEFAULT_GATEWAY_PORT)
    apiConfig.gatewayPort = DEFAULT_GATEWAY_PORT
  }

  // Update API base URLs after initialization
  updateApiBase()
  apiConfig.initialized = true
  
  // Log final configuration
  console.log('[Config] Final API_BASE:', getApiBase())
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

  // Default fallback: Use 127.0.0.1 in Electron, hostname in browser
  // In Electron, hostname might be empty or incorrect, so always use 127.0.0.1
  const isElectron = typeof window !== 'undefined' && (window as any).api !== undefined
  const defaultHost = isElectron ? '127.0.0.1' : (hostname || '127.0.0.1')
  return `http://${defaultHost}:${DEFAULT_GATEWAY_PORT}`
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

  const isElectron = typeof window !== 'undefined' && (window as any).api !== undefined
  const defaultHost = isElectron ? '127.0.0.1' : (hostname || '127.0.0.1')
  return `http://${defaultHost}:${DEFAULT_PREPROCESSING_PORT}`
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

  const isElectron = typeof window !== 'undefined' && (window as any).api !== undefined
  const defaultHost = isElectron ? '127.0.0.1' : (hostname || '127.0.0.1')
  return `http://${defaultHost}:${DEFAULT_AI_PORT}/api/ai`
}

// Export mutable URLs - updated when ports are discovered
// Initialize with safe defaults (use 127.0.0.1 in Electron)
const isElectron = typeof window !== 'undefined' && (window as any).api !== undefined
const defaultHost = isElectron ? '127.0.0.1' : (hostname || '127.0.0.1')
export let API_BASE = import.meta.env.VITE_API_BASE || `http://${defaultHost}:${DEFAULT_GATEWAY_PORT}`
export let PREPROCESSING_BASE = import.meta.env.VITE_PREPROCESSING_BASE || `http://${defaultHost}:${DEFAULT_PREPROCESSING_PORT}`
export let AI_BASE = import.meta.env.VITE_AI_BASE || `http://${defaultHost}:${DEFAULT_AI_PORT}/api/ai`

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

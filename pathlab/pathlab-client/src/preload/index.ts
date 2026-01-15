import { contextBridge, ipcRenderer } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

// Custom APIs for renderer
const api = {
  // Authentication
  auth: {
    /**
     * Open external URL in system browser (for OAuth login)
     */
    openLoginUrl: (url: string): Promise<void> => {
      return ipcRenderer.invoke('open-external-url', url)
    },

    /**
     * Listen for OAuth callback from deep link
     * Returns cleanup function
     */
    onAuthCallback: (callback: (data: { code: string; state?: string }) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, data: { code: string; state?: string }): void => {
        callback(data)
      }
      ipcRenderer.on('auth-callback', handler)

      // Return cleanup function
      return (): void => {
        ipcRenderer.removeListener('auth-callback', handler)
      }
    }
  },

  // Backend service discovery
  backend: {
    /**
     * Get the gateway port (dynamically discovered)
     */
    getGatewayPort: (): Promise<number | null> => {
      return ipcRenderer.invoke('get-gateway-port')
    },

    /**
     * Listen for gateway port updates
     * Returns cleanup function
     */
    onGatewayPort: (callback: (port: number) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, port: number): void => {
        callback(port)
      }
      ipcRenderer.on('gateway-port', handler)

      // Return cleanup function
      return (): void => {
        ipcRenderer.removeListener('gateway-port', handler)
      }
    }
  },

  // File system helpers
  files: {
    /**
     * Open file picker to select local files
     */
    selectFiles: (options?: { title?: string; filters?: { name: string; extensions: string[] }[] }): Promise<string[] | null> => {
      return ipcRenderer.invoke('select-files', options)
    },

    /**
     * Open directory picker to select storage location
     */
    selectDirectory: (options?: { title?: string }): Promise<string | null> => {
      return ipcRenderer.invoke('select-directory', options)
    }
  }
}

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', electronAPI)
    contextBridge.exposeInMainWorld('api', api)
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = electronAPI
  // @ts-ignore (define in dts)
  window.api = api
}

// Type declarations for renderer
export type API = typeof api

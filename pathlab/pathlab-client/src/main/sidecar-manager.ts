import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import { existsSync } from 'fs'
import { app, BrowserWindow } from 'electron'

let pythonProcess: ChildProcess | null = null
let gatewayPort: number | null = null

/**
 * Parse PORT=<number> from process output
 */
function parsePort(data: string): number | null {
  const match = data.toString().match(/PORT=(\d+)/)
  if (match) {
    return parseInt(match[1], 10)
  }
  return null
}

/**
 * Get the discovered gateway port
 */
export function getGatewayPort(): number | null {
  return gatewayPort
}

/**
 * Check if backend is already running on the expected port
 */
async function checkBackendRunning(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const http = require('http')
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port: port,
        path: '/health',
        method: 'GET',
        timeout: 1000
      },
      (res: any) => {
        resolve(res.statusCode === 200)
      }
    )
    req.on('error', () => resolve(false))
    req.on('timeout', () => {
      req.destroy()
      resolve(false)
    })
    req.end()
  })
}

/**
 * Start the Python sidecar process
 * Returns a promise that resolves when the port is discovered
 */
export function startPythonSidecar(): Promise<number> {
  return new Promise(async (resolve, reject) => {
    const isDev = !app.isPackaged

    // In development mode, check if backend is already started externally
    if (isDev && process.env.PATHLAB_BACKEND_STARTED === '1') {
      const expectedPort = parseInt(process.env.GATEWAY_PORT || '5100', 10)
      console.log(`[Sidecar] Backend started externally, checking port ${expectedPort}...`)
      
      // Check if backend is running
      const isRunning = await checkBackendRunning(expectedPort)
      if (isRunning) {
        gatewayPort = expectedPort
        console.log(`[Sidecar] Using existing backend on port ${expectedPort}`)
        
        // Notify all renderer windows about the port (if any exist)
        BrowserWindow.getAllWindows().forEach((win) => {
          win.webContents.send('gateway-port', expectedPort)
        })
        
        resolve(expectedPort)
        return
      } else {
        console.log(`[Sidecar] Backend not found on port ${expectedPort}, will start sidecar...`)
      }
    }

    let pythonPath = 'python3'
    let scriptPath = ''

    if (isDev) {
      // Development: use virtual environment Python if available
      const venvPython = join(process.cwd(), 'server', '.venv', 'bin', 'python')
      if (existsSync(venvPython)) {
        pythonPath = venvPython
        console.log('[Sidecar] Using virtual environment Python')
      } else {
        pythonPath = 'python3'
        console.log('[Sidecar] Using system Python (no venv found)')
      }
      scriptPath = join(process.cwd(), 'server/main.py')
      // Set dev mode environment variable
      process.env.PATHLAB_DEV = '0' // Disable reload in sidecar mode
      process.env.PATHLAB_ENV = 'development' // Mark as development environment
    } else {
      // Production: use the bundled executable
      pythonPath = join(process.resourcesPath, 'server/main')
      scriptPath = '' // No script path needed for executable
      process.env.PATHLAB_ENV = 'production' // Mark as production environment
    }

    console.log(`Starting Python sidecar: ${pythonPath} ${scriptPath}`)

    // Spawn Python process
    if (isDev) {
      // Ensure debug mode and fixed ports are set for development
      const env = {
        ...process.env,
        PATHLAB_DEBUG: process.env.PATHLAB_DEBUG || '1',
        GATEWAY_PORT: process.env.GATEWAY_PORT || '5100',
        PREPROCESSING_PORT: process.env.PREPROCESSING_PORT || '5101',
        AI_PORT: process.env.AI_PORT || '5102',
      }
      pythonProcess = spawn(pythonPath, [scriptPath], {
        env,
        stdio: ['pipe', 'pipe', 'pipe']
      })
    } else {
      pythonProcess = spawn(pythonPath, [], {
        env: { ...process.env },
        stdio: ['pipe', 'pipe', 'pipe']
      })
    }

    let portResolved = false
    const timeout = setTimeout(() => {
      if (!portResolved) {
        reject(new Error('Timeout waiting for Python sidecar to start'))
      }
    }, 30000) // 30 second timeout

    pythonProcess.stdout?.on('data', (data) => {
      const output = data.toString()
      console.log(`[Python]: ${output}`)

      // Try to parse port from output
      if (!portResolved) {
        const port = parsePort(output)
        if (port) {
          gatewayPort = port
          portResolved = true
          clearTimeout(timeout)
          console.log(`[Sidecar] Gateway port discovered: ${port}`)

          // Notify all renderer windows about the port
          BrowserWindow.getAllWindows().forEach((win) => {
            win.webContents.send('gateway-port', port)
          })

          resolve(port)
        }
      }
    })

    pythonProcess.stderr?.on('data', (data) => {
      // uvicorn logs to stderr, so this is normal output
      console.log(`[Python]: ${data}`)
    })

    pythonProcess.on('error', (error) => {
      console.error(`[Python Error]: Failed to start process:`, error)
      if (!portResolved) {
        clearTimeout(timeout)
        reject(error)
      }
    })

    pythonProcess.on('close', (code) => {
      console.log(`Python process exited with code ${code}`)
      pythonProcess = null
      gatewayPort = null
    })
  })
}

export function stopPythonSidecar(): void {
  if (pythonProcess) {
    console.log('Stopping Python sidecar...')
    pythonProcess.kill()
    pythonProcess = null
    gatewayPort = null
  }
}

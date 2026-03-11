import { spawn, ChildProcess } from 'child_process'
import { join } from 'path'
import { existsSync } from 'fs'
import { app, BrowserWindow } from 'electron'

let pythonProcess: ChildProcess | null = null

export interface BackendServicePorts {
  gateway: number | null
  preprocessing: number | null
  ai: number | null
}

let servicePorts: BackendServicePorts = {
  gateway: null,
  preprocessing: null,
  ai: null
}

/**
 * Parse PORT=<number> from process output
 */
function parseGatewayPort(line: string): number | null {
  const match = line.match(/PORT=(\d+)/)
  if (match) {
    return parseInt(match[1], 10)
  }
  return null
}

/**
 * Parse [Services] Gateway: <port>, Preprocessing: <port>, AI: <port>
 */
function parseServicePorts(line: string): BackendServicePorts | null {
  const match = line.match(/\[Services\]\s*Gateway:\s*(\d+),\s*Preprocessing:\s*(\d+),\s*AI:\s*(\d+)/)
  if (!match) {
    return null
  }

  return {
    gateway: parseInt(match[1], 10),
    preprocessing: parseInt(match[2], 10),
    ai: parseInt(match[3], 10)
  }
}

function notifyRendererWindows(): void {
  BrowserWindow.getAllWindows().forEach((win) => {
    win.webContents.send('backend-service-ports', { ...servicePorts })
    if (servicePorts.gateway) {
      win.webContents.send('gateway-port', servicePorts.gateway)
    }
  })
}

function updateServicePorts(nextPorts: Partial<BackendServicePorts>): void {
  let changed = false

  for (const [key, value] of Object.entries(nextPorts) as Array<[keyof BackendServicePorts, number | null]>) {
    if (value !== null && servicePorts[key] !== value) {
      servicePorts = {
        ...servicePorts,
        [key]: value
      }
      changed = true
    }
  }

  if (changed) {
    notifyRendererWindows()
  }
}

/**
 * Get the discovered gateway port
 */
export function getGatewayPort(): number | null {
  return servicePorts.gateway
}

/**
 * Get all discovered backend service ports
 */
export function getServicePorts(): BackendServicePorts {
  return { ...servicePorts }
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

    servicePorts = {
      gateway: null,
      preprocessing: null,
      ai: null
    }

    let portResolved = false
    let stdoutBuffer = ''
    const timeout = setTimeout(() => {
      if (!portResolved) {
        reject(new Error('Timeout waiting for Python sidecar to start'))
      }
    }, 30000) // 30 second timeout

    const resolveGatewayPort = (port: number): void => {
      updateServicePorts({ gateway: port })

      if (!portResolved) {
        portResolved = true
        clearTimeout(timeout)
        console.log(`[Sidecar] Gateway port discovered: ${port}`)
        resolve(port)
      }
    }

    const handleOutputLine = (line: string): void => {
      const services = parseServicePorts(line)
      if (services) {
        updateServicePorts(services)
        if (services.gateway) {
          resolveGatewayPort(services.gateway)
        }
      }

      const gatewayPort = parseGatewayPort(line)
      if (gatewayPort) {
        resolveGatewayPort(gatewayPort)
      }
    }

    pythonProcess.stdout?.on('data', (data) => {
      const output = data.toString()
      console.log(`[Python]: ${output}`)

      stdoutBuffer += output
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() || ''

      for (const line of lines) {
        handleOutputLine(line)
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
      servicePorts = {
        gateway: null,
        preprocessing: null,
        ai: null
      }
    })
  })
}

export function stopPythonSidecar(): void {
  if (pythonProcess) {
    console.log('Stopping Python sidecar...')
    pythonProcess.kill()
    pythonProcess = null
    servicePorts = {
      gateway: null,
      preprocessing: null,
      ai: null
    }
  }
}
